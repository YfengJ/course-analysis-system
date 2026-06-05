from pathlib import Path

from flask import Blueprint, abort, render_template, request

from models import Report
from services.auth_service import AuthService
from services.report_comparison_service import ReportComparisonService


report_center_bp = Blueprint("report_center", __name__, url_prefix="/reports")


@report_center_bp.route("/")
def index():
    keyword = (request.args.get("keyword") or "").strip()
    status_filter = request.args.get("status", "all")

    reports = [
        report
        for report in Report.query.order_by(Report.created_at.desc()).all()
        if not report.course or AuthService.can_manage_course(report.course)
    ]
    report_rows = []
    summary = {
        "all": len(reports),
        "completed": 0,
        "pending": 0,
    }
    for report in reports:
        course = report.course
        course_name = course.name if course else "课程已删除"
        course_code = course.code if course else ""
        searchable_text = " ".join(
            [
                course_name,
                course_code,
                report.semester or "",
                report.class_scope or "",
                Path(report.word_path or "").name,
            ]
        )
        if report.status == "达成":
            summary["completed"] += 1
        else:
            summary["pending"] += 1
        if keyword and keyword not in searchable_text:
            continue
        if status_filter == "completed" and report.status != "达成":
            continue
        if status_filter == "pending" and report.status == "达成":
            continue
        previous_report = None
        if report.comparison_base_report_id:
            previous_report = Report.query.get(report.comparison_base_report_id)
        if previous_report is None and report.report_version and report.report_version > 1:
            previous_report = (
                Report.query.filter_by(course_id=report.course_id, semester=report.semester, class_scope=report.class_scope)
                .filter(Report.report_version < report.report_version)
                .order_by(Report.report_version.desc(), Report.created_at.desc())
                .first()
            )

        report_rows.append(
            {
                "report": report,
                "course": course,
                "course_name": course_name,
                "course_code": course_code,
                "download_ready": bool(report.word_path),
                "previous_report": previous_report,
            }
        )

    return render_template(
        "reports/index.html",
        report_rows=report_rows,
        keyword=keyword,
        status_filter=status_filter,
        summary=summary,
        title="报告中心",
    )


@report_center_bp.route("/compare")
def compare():
    old_report = Report.query.get(request.args.get("old_id", type=int))
    new_report = Report.query.get(request.args.get("new_id", type=int))
    if not old_report or not new_report:
        abort(404)
    if (
        (old_report.course and not AuthService.can_manage_course(old_report.course))
        or (new_report.course and not AuthService.can_manage_course(new_report.course))
    ):
        abort(403)
    comparison = ReportComparisonService.compare_reports(old_report, new_report)
    return render_template(
        "reports/compare.html",
        comparison=comparison,
        title="报告版本对比",
    )
