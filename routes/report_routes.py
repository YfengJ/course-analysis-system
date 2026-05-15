from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for

from models import Course, ImportBatch, Report, Student
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


@report_bp.route("/download/<int:report_id>")
def download_report(course_id: int, report_id: int):
    report = Report.query.get_or_404(report_id)
    return send_file(report.word_path, as_attachment=True)
