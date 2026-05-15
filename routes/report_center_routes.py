from pathlib import Path

from flask import Blueprint, render_template, request

from models import Report


report_center_bp = Blueprint("report_center", __name__, url_prefix="/reports")


@report_center_bp.route("/")
def index():
    keyword = (request.args.get("keyword") or "").strip()
    status_filter = request.args.get("status", "all")

    reports = Report.query.order_by(Report.created_at.desc()).all()
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

        report_rows.append(
            {
                "report": report,
                "course": course,
                "course_name": course_name,
                "course_code": course_code,
                "download_ready": bool(report.word_path),
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
