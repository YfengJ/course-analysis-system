import json
import hashlib
from pathlib import Path
import re

from models import ImportBatch, Report, TeachingOutline, db
from services.analysis_run_service import AnalysisRunService
from services.attainment_service import AttainmentService
from services.course_insight_service import CourseInsightService
from services.template_adapters.report_template_adapter import ReportTemplateAdapter


class ReportService:
    @staticmethod
    def _safe_filename_part(value, default="全部班级", max_chars=28):
        text = str(value or "").strip() or default
        parts = [item.strip() for item in re.split(r"[、,，\s]+", text) if item.strip()]
        if len(parts) > 12 and sum(1 for item in parts if item.isdigit()) >= 12:
            text = default
        text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text).strip(" ._")
        if not text:
            text = default
        if len(text) > max_chars:
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
            text = f"{text[:max_chars]}_{digest}"
        return text

    @classmethod
    def _report_filename(cls, course, semester, class_scope):
        class_label = course.class_names if class_scope == "全部班级" else class_scope
        parts = [
            cls._safe_filename_part(getattr(course, "code", ""), "course", 24),
            str(getattr(course, "id", "") or "0"),
            cls._safe_filename_part(semester, "未设置学期", 28),
            cls._safe_filename_part(class_label or class_scope, "全部班级", 28),
            "达成度分析报告",
        ]
        filename = "_".join(parts) + ".docx"
        while len(filename.encode("utf-8")) > 220 and len(parts[3]) > 8:
            parts[3] = parts[3][: max(8, len(parts[3]) - 4)]
            filename = "_".join(parts) + ".docx"
        return filename

    @classmethod
    def build_report_context(cls, course, semester: str, class_scope: str):
        """组装报告预览页与 Word 导出所需的完整上下文数据。"""
        analysis_ready = AnalysisRunService.is_ready(course.id, semester, class_scope)
        if analysis_ready:
            summary = AttainmentService.calculate(course, semester, class_scope)
        else:
            summary = {
                "semester": semester,
                "class_scope": class_scope,
                "student_count": 0,
                "total_quantitative_attainment": 0.0,
                "total_quantitative_attainment_percent": 0.0,
                "total_qualitative_attainment": 0.0,
                "total_qualitative_score_percent": 0.0,
                "total_status": "待计算",
                "objective_results": [],
                "chapter_four": {
                    "quantitative_rows": [],
                    "qualitative_rows": [],
                    "statistics_rows": [],
                    "attainment_rows": [],
                    "distribution_rows": [],
                    "quantitative_formula": "",
                    "qualitative_formula": "",
                },
            }
        insight_payload = CourseInsightService.get_payload(course.id, semester, class_scope)
        latest_outline = TeachingOutline.query.filter_by(course_id=course.id).order_by(TeachingOutline.created_at.desc()).first()
        latest_import = ImportBatch.query.filter_by(course_id=course.id).order_by(ImportBatch.created_at.desc()).first()

        return {
            "summary": summary,
            "analysis_ready": analysis_ready,
            "analysis_text": insight_payload["overview_text"] if insight_payload else "",
            "objective_comments": [item["analysis"] for item in insight_payload["objective_analyses"]] if insight_payload else [],
            "improvement_actions": [item["action"] for item in insight_payload["improvement_actions"]] if insight_payload else [],
            "generated_insight": insight_payload,
            "chapter_five_ready": bool(insight_payload),
            "latest_outline": latest_outline,
            "latest_import": latest_import,
            "template_meta": {
                "course_template": course.template_name or "通用课程模板",
                "course_template_version": course.template_version or "v2",
                "report_template": ReportTemplateAdapter.NAME,
                "report_template_version": ReportTemplateAdapter.VERSION,
            },
        }

    @classmethod
    def generate_word_report(cls, course, semester: str, class_scope: str, report_folder: str, context=None, template_path=None):
        """根据分析结果生成规范化 Word 报告并写入报告记录表。"""
        context = context or cls.build_report_context(course, semester, class_scope)
        summary = context["summary"]
        document = ReportTemplateAdapter.build_document(course, semester, class_scope, context, template_path=template_path)

        report_dir = Path(report_folder)
        report_dir.mkdir(parents=True, exist_ok=True)
        filename = cls._report_filename(course, semester, class_scope)
        output_path = report_dir / filename
        document.save(output_path)

        report = Report(
            course_id=course.id,
            semester=semester,
            class_scope=class_scope,
            quantitative_attainment=summary["total_quantitative_attainment"],
            qualitative_attainment=summary["total_qualitative_attainment"],
            status=summary["total_status"],
            word_path=str(output_path),
            html_snapshot=json.dumps(summary, ensure_ascii=False, default=str),
            summary_text=context["analysis_text"],
            improvement_text="\n".join(context["improvement_actions"]) if context["chapter_five_ready"] else "",
            template_name=ReportTemplateAdapter.NAME,
            template_version=ReportTemplateAdapter.VERSION,
            source_template=str(template_path or context["template_meta"]["course_template"]),
        )
        db.session.add(report)
        db.session.commit()

        return report, context
