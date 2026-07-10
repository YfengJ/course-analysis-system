from flask import Blueprint, render_template
from sqlalchemy import or_

from models import Course, Report, TeachingOutline
from services.auth_service import AuthService
from services.course_progress_service import CourseProgressService
from services.seed_service import DEFAULT_COURSE_CODE


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    course_query = Course.query
    current_user = AuthService.current_user()
    if current_user and not AuthService.is_admin(current_user):
        course_query = course_query.filter(
            or_(Course.owner_user_id.is_(None), Course.owner_user_id == current_user.id)
        )
    courses = course_query.order_by(Course.created_at.desc()).all()
    course_cards = []
    for course in courses:
        snapshot = CourseProgressService.build_snapshot(course)
        outline_count = TeachingOutline.query.filter_by(course_id=course.id).count()
        report_count = Report.query.filter_by(course_id=course.id).count()
        latest_import = snapshot["latest_import"]
        course_cards.append(
            {
                "course": course,
                "is_sample": course.code == DEFAULT_COURSE_CODE,
                "outline_count": outline_count,
                "report_count": report_count,
                "student_count": snapshot["student_count"],
                "objective_count": len(course.objectives),
                "assessment_count": len(course.assessments),
                "latest_report": snapshot["latest_report"],
                "latest_import": latest_import,
                "latest_analysis": snapshot["latest_analysis"],
                "stages": snapshot["stages"],
                "completed_stage_count": snapshot["completed_stage_count"],
                "next_action": snapshot["next_action"],
                "analysis_ready": snapshot["analysis_ready"],
                "report_ready": snapshot["report_ready"],
                "report_preview_ready": snapshot["report_preview_ready"],
                "display_status": snapshot["display_status"],
                "template_name": course.template_name or "通用课程模板",
                "template_ready": snapshot["template_ready"],
            }
        )

    featured_course = next((item for item in course_cards if item["is_sample"]), None)
    if not featured_course and course_cards:
        featured_course = course_cards[0]

    visible_course_ids = [course.id for course in courses]
    report_query = Report.query.filter(Report.course_id.in_(visible_course_ids)) if visible_course_ids else None
    recent_reports = report_query.order_by(Report.created_at.desc()).limit(8).all() if report_query is not None else []
    visible_report_count = report_query.count() if report_query is not None else 0
    return render_template(
        "dashboard/index.html",
        title="课程工作台",
        course_cards=course_cards,
        featured_course=featured_course,
        recent_reports=recent_reports,
        course_count=len(course_cards),
        report_count=visible_report_count,
        analyzed_course_count=sum(1 for item in course_cards if item["analysis_ready"]),
        imported_course_count=sum(1 for item in course_cards if item["student_count"] > 0),
        template_ready_count=sum(1 for item in course_cards if item["template_ready"]),
    )
