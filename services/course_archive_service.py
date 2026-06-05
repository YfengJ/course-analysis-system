import json
import hashlib
import zipfile
from pathlib import Path

from models import AnalysisSnapshot, ImportBatch, Report, TeachingOutline
from services.attainment_service import AttainmentService
from services.report_quality_service import ReportQualityService


class CourseArchiveService:
    @staticmethod
    def _safe_part(value, default="course", max_bytes=44):
        text = str(value or "").strip() or default
        for char in '\\/:*?"<>|\r\n\t':
            text = text.replace(char, "_")
        text = text.strip(" ._") or default
        if len(text.encode("utf-8")) > max_bytes:
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
            while text and len(f"{text}_{digest}".encode("utf-8")) > max_bytes:
                text = text[:-1]
            text = f"{text or default}_{digest}"
        return text

    @classmethod
    def build_archive(cls, course, semester: str, class_scope: str, output_folder: str):
        output_dir = Path(output_folder) / "course_archives"
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = "_".join(
            [
                cls._safe_part(course.code, "course"),
                cls._safe_part(course.name, "课程"),
                cls._safe_part(semester, "学期"),
                cls._safe_part(class_scope, "全部班级"),
                "课程归档包.zip",
            ]
        )
        output_path = output_dir / filename

        summary = AttainmentService.calculate(course, semester, class_scope)
        quality = ReportQualityService.check_course_report(course, semester, class_scope)
        latest_outline = TeachingOutline.query.filter_by(course_id=course.id).order_by(TeachingOutline.created_at.desc()).first()
        imports = ImportBatch.query.filter_by(course_id=course.id, semester=semester).order_by(ImportBatch.created_at.asc()).all()
        snapshots = AnalysisSnapshot.query.filter_by(course_id=course.id, semester=semester, class_scope=class_scope).order_by(AnalysisSnapshot.version_no.asc()).all()
        reports = Report.query.filter_by(course_id=course.id, semester=semester, class_scope=class_scope).order_by(Report.report_version.asc(), Report.created_at.asc()).all()

        manifest = {
            "course": {
                "id": course.id,
                "code": course.code,
                "name": course.name,
                "semester": semester,
                "class_scope": class_scope,
                "owner": course.course_owner,
                "instructors": course.instructors,
            },
            "counts": {
                "objectives": len(course.objectives),
                "assessments": len(course.assessments),
                "students": summary.get("student_count", 0),
                "imports": len(imports),
                "analysis_snapshots": len(snapshots),
                "reports": len(reports),
            },
            "quality": {
                "ready": quality["ready"],
                "blocking_count": quality["blocking_count"],
                "warning_count": quality["warning_count"],
            },
        }

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
            package.writestr("analysis_summary.json", json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            package.writestr("quality_check.json", json.dumps(quality, ensure_ascii=False, indent=2, default=str))
            if latest_outline:
                package.writestr(
                    "teaching_outline/latest_outline.json",
                    json.dumps(
                        {
                            "filename": latest_outline.filename,
                            "summary": latest_outline.summary,
                            "parsed": latest_outline.parsed_json,
                            "created_at": latest_outline.created_at,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                )
            package.writestr(
                "imports/import_batches.json",
                json.dumps(
                    [
                        {
                            "filename": item.filename,
                            "status": item.status,
                            "imported_count": item.imported_count,
                            "issue_count": item.issue_count,
                            "issues": item.issues_json,
                            "file_hash": item.file_hash,
                            "created_at": item.created_at,
                        }
                        for item in imports
                    ],
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            )
            package.writestr(
                "analysis/snapshots.json",
                json.dumps(
                    [
                        {
                            "version_no": item.version_no,
                            "student_count": item.student_count,
                            "quantitative_attainment": item.quantitative_attainment,
                            "qualitative_attainment": item.qualitative_attainment,
                            "status": item.status,
                            "change_note": item.change_note,
                            "created_at": item.created_at,
                        }
                        for item in snapshots
                    ],
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
            )
            for report in reports:
                if report.word_path and Path(report.word_path).exists():
                    package.write(report.word_path, f"reports/{Path(report.word_path).name}")
                package.writestr(
                    f"reports/report_{report.id}_metadata.json",
                    json.dumps(
                        {
                            "id": report.id,
                            "version": report.report_version,
                            "status": report.status,
                            "is_archived": report.is_archived,
                            "quantitative_attainment": report.quantitative_attainment,
                            "qualitative_attainment": report.qualitative_attainment,
                            "created_at": report.created_at,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                )

        return output_path
