from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from models import Course, ImportBatch, Report, Student, db
from services.course_archive_service import CourseArchiveService
from services.report_quality_service import ReportQualityService
from services.report_service import ReportService
from services.seed_service import DEFAULT_SEMESTER


report_bp = Blueprint("report", __name__, url_prefix="/courses/<int:course_id>/reports")


def resolve_report_scope(course: Course):
    """为报告预览与导出选择最合适的学期和班级范围。"""
    requested_semester = (request.args.get("semester") or "").strip()
    requested_class_scope = (request.args.get("class_scope") or "").strip()
    latest_report = Report.query.filter_by(course_id=course.id).order_by(Report.created_at.desc()).first()
    latest_import = ImportBatch.query.filter_by(course_id=course.id).order_by(ImportBatch.created_at.desc()).first()
    latest_student = Student.query.filter_by(course_id=course.id).order_by(Student.created_at.desc()).first()

    semester = (
        requested_semester
        or (latest_report.semester if latest_report else "")
        or (latest_import.semester if latest_import else "")
        or (latest_student.semester if latest_student else "")
        or (course.semester or "")
        or DEFAULT_SEMESTER
    )
    class_scope = (
        requested_class_scope
        or (
            latest_report.class_scope
            if latest_report and latest_report.semester == semester
            else ""
        )
        or (latest_import.class_scope if latest_import and latest_import.semester == semester else "")
        or "全部班级"
    )
    return semester, class_scope


@report_bp.route("/preview")
def preview(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    semester, class_scope = resolve_report_scope(course)
    context = ReportService.build_report_context(course, semester, class_scope)
    recent_reports = Report.query.filter_by(course_id=course.id).order_by(Report.created_at.desc()).limit(10).all()
    return render_template(
        "reports/preview.html",
        course=course,
        semester=semester,
        class_scope=class_scope,
        report_context=context,
        recent_reports=recent_reports,
        title=f"{course.name} - 报告预览",
    )


@report_bp.route("/quality")
def quality_check(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    semester, class_scope = resolve_report_scope(course)
    strict = (request.args.get("strict") or "").lower() in {"1", "true", "yes", "final"}
    result = ReportQualityService.check_course_report(course, semester, class_scope, strict=strict)
    return render_template(
        "reports/quality.html",
        course=course,
        semester=semester,
        class_scope=class_scope,
        quality=result,
        title=f"{course.name} - 报告质量检查",
    )


@report_bp.route("/export-word")
def export_word(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    semester, class_scope = resolve_report_scope(course)
    context = ReportService.build_report_context(course, semester, class_scope)
    if not context["analysis_ready"]:
        flash("请先完成第四章计算，再导出正式报告。", "warning")
        return redirect(url_for("analysis.index", course_id=course.id, semester=semester, class_scope=class_scope))
    if context["summary"]["student_count"] == 0:
        flash("当前统计范围下还没有成绩数据，暂时无法导出报告。", "warning")
        return redirect(url_for("importer.import_scores", course_id=course.id))
    report, _ = ReportService.generate_word_report(
        course,
        semester,
        class_scope,
        current_app.config["REPORT_FOLDER"],
        context=context,
        template_path=current_app.config.get("REPORT_TEMPLATE_DOCX"),
    )
    flash("Word 报告已生成。", "success")
    return redirect(url_for("report.download_report", course_id=course.id, report_id=report.id))


@report_bp.route("/export-archive-package")
def export_archive_package(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    semester, class_scope = resolve_report_scope(course)
    try:
        archive_path = CourseArchiveService.build_archive(course, semester, class_scope, current_app.config["EXPORT_FOLDER"])
    except Exception as exc:
        flash(f"课程归档包生成失败：{exc}", "danger")
        return redirect(url_for("report.preview", course_id=course.id, semester=semester, class_scope=class_scope))
    return send_file(archive_path, as_attachment=True, download_name=Path(archive_path).name)


@report_bp.route("/download/<int:report_id>")
def download_report(course_id: int, report_id: int):
    report = Report.query.get_or_404(report_id)
    if report.course_id != course_id:
        abort(404)
    if not report.word_path or not Path(report.word_path).exists():
        abort(404)
    return send_file(report.word_path, as_attachment=True)


@report_bp.route("/<int:report_id>/archive", methods=["POST"])
def archive_report(course_id: int, report_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    report = Report.query.get_or_404(report_id)
    if report.course_id != course.id:
        abort(404)

    quality = ReportQualityService.check_course_report(course, report.semester, report.class_scope, strict=True)
    if not quality["ready"]:
        flash("质量检查未通过，暂不能归档最终版。请先处理阻断项。", "warning")
        return redirect(url_for("report.quality_check", course_id=course.id, semester=report.semester, class_scope=report.class_scope, strict="1"))

    report.is_archived = True
    report.archived_at = datetime.utcnow()
    report.archive_note = (request.form.get("archive_note") or "教师确认归档").strip()
    db.session.commit()
    flash(f"报告 v{report.report_version or 1} 已归档为最终版。", "success")
    return redirect(url_for("report.preview", course_id=course.id, semester=report.semester, class_scope=report.class_scope))
