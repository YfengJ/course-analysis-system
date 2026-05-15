from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from forms import AnalysisFilterForm
from models import Course, Student
from services.analysis_run_service import AnalysisRunService
from services.attainment_service import AttainmentService
from services.chart_service import ChartService
from services.course_insight_service import CourseInsightService
from services.llm_service import LLMService
from services.seed_service import DEFAULT_SEMESTER


insight_bp = Blueprint("insight", __name__, url_prefix="/courses/<int:course_id>/insights")


@insight_bp.route("/", methods=["GET", "POST"])
def show(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)

    semesters = sorted({item.semester for item in Student.query.filter_by(course_id=course.id).all()}) or [DEFAULT_SEMESTER]
    selected_semester = (request.values.get("semester") or semesters[-1]).strip()
    classes = sorted({item.class_name for item in Student.query.filter_by(course_id=course.id, semester=selected_semester).all()})
    class_scope = (request.values.get("class_scope") or "全部班级").strip()
    analysis_ready = AnalysisRunService.is_ready(course.id, selected_semester, class_scope)

    if request.method == "POST":
        if not analysis_ready:
            flash("请先完成第四章计算，再生成第五章 AI 分析内容。", "warning")
        else:
            try:
                CourseInsightService.generate_for_scope(course, selected_semester, class_scope)
                flash("已生成并保存当前统计范围的评价结果分析与持续改进措施。", "success")
            except RuntimeError as exc:
                flash(str(exc), "warning")
            except Exception as exc:  # noqa: BLE001
                flash(f"生成失败：{exc}", "danger")
        return redirect(url_for("insight.show", course_id=course.id, semester=selected_semester, class_scope=class_scope))

    form = AnalysisFilterForm()
    form.semester.choices = [(item, item) for item in semesters]
    form.class_scope.choices = [("全部班级", "全部班级")] + [(item, item) for item in classes]
    form.semester.data = selected_semester
    form.class_scope.data = class_scope

    if analysis_ready:
        summary = AttainmentService.calculate(course, selected_semester, class_scope)
        charts = ChartService.build_summary_charts(summary)
        insight_payload = CourseInsightService.get_payload(course.id, selected_semester, class_scope)
    else:
        student_count = Student.query.filter_by(course_id=course.id, semester=selected_semester).count() if class_scope == "全部班级" else Student.query.filter_by(course_id=course.id, semester=selected_semester, class_name=class_scope).count()
        summary = {
            "semester": selected_semester,
            "class_scope": class_scope,
            "student_count": student_count,
            "total_quantitative_attainment": 0.0,
            "total_qualitative_attainment": 0.0,
            "assessment_performance": [],
            "objective_results": [],
        }
        charts = {"objective_bar": {}, "assessment_bar": {}}
        insight_payload = None

    return render_template(
        "insights/show.html",
        course=course,
        form=form,
        summary=summary,
        charts=charts,
        class_scope=class_scope,
        semester=selected_semester,
        has_analysis_data=summary["student_count"] > 0,
        analysis_ready=analysis_ready,
        insight_payload=insight_payload,
        llm_ready=LLMService.is_configured(),
        title=f"{course.name} - AI评价与改进",
    )
