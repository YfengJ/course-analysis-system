from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from forms import AnalysisFilterForm
from models import Course, Student
from services.analysis_revision_service import AnalysisRevisionService
from services.analysis_run_service import AnalysisRunService
from services.attainment_service import AttainmentService
from services.chart_service import ChartService
from services.course_insight_service import CourseInsightService
from services.seed_service import DEFAULT_SEMESTER


analysis_bp = Blueprint("analysis", __name__, url_prefix="/courses/<int:course_id>/analysis")


@analysis_bp.route("/", methods=["GET", "POST"])
def index(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    semesters = sorted({item.semester for item in Student.query.filter_by(course_id=course.id).all()}) or [DEFAULT_SEMESTER]
    semester = request.values.get("semester") or request.args.get("semester") or semesters[-1]
    classes = sorted({item.class_name for item in Student.query.filter_by(course_id=course.id, semester=semester).all()})
    class_scope = request.values.get("class_scope") or request.args.get("class_scope") or "全部班级"

    form = AnalysisFilterForm()
    form.semester.choices = [(item, item) for item in semesters]
    form.class_scope.choices = [("全部班级", "全部班级")] + [(item, item) for item in classes]
    form.semester.data = semester
    form.class_scope.data = class_scope

    score_student_count = Student.query.filter_by(course_id=course.id, semester=semester).count() if class_scope == "全部班级" else Student.query.filter_by(course_id=course.id, semester=semester, class_name=class_scope).count()
    has_score_data = score_student_count > 0
    analysis_record = AnalysisRunService.get_record(course.id, semester, class_scope)

    if request.method == "POST":
        if not has_score_data:
            flash("当前统计范围下还没有可用于计算的成绩数据，请先完成成绩导入。", "warning")
        else:
            summary = AttainmentService.calculate(course, semester, class_scope)
            action = request.form.get("action") or "recalculate"
            if action == "save_revision":
                qualitative_overrides = {}
                for item in summary["objective_results"]:
                    objective_id = str(item["objective_id"])
                    qualitative_overrides[objective_id] = {
                        "excellent_count": request.form.get(f"excellent_count_{objective_id}", 0),
                        "good_count": request.form.get(f"good_count_{objective_id}", 0),
                        "medium_count": request.form.get(f"medium_count_{objective_id}", 0),
                        "poor_count": request.form.get(f"poor_count_{objective_id}", 0),
                    }
                AnalysisRevisionService.save_revision(
                    course.id,
                    semester,
                    class_scope,
                    qualitative_overrides=qualitative_overrides,
                    analysis_note=request.form.get("analysis_note", ""),
                    improvement_note=request.form.get("improvement_note", ""),
                )
                summary, _ = AnalysisRevisionService.apply_active_revision(summary, course.id, semester, class_scope)
                change_note = "教师人工修订"
                flash("人工修订已保存，报告预览和 Word 导出会同步使用这版数据。", "success")
            else:
                summary, _ = AnalysisRevisionService.apply_active_revision(summary, course.id, semester, class_scope)
                change_note = "系统重新计算"
                flash("第四章数据已重新计算，可继续编辑第五章并查看报告预览。", "success")
            AttainmentService.save_qualitative_records(summary)
            AnalysisRunService.mark_complete(
                course.id,
                semester,
                class_scope,
                summary["student_count"],
                summary=summary,
                change_note=change_note,
            )
        return redirect(url_for("analysis.index", course_id=course.id, semester=semester, class_scope=class_scope))

    has_analysis_result = AnalysisRunService.is_ready(course.id, semester, class_scope)
    if has_analysis_result:
        summary = AttainmentService.calculate(course, semester, class_scope)
        summary, analysis_revision = AnalysisRevisionService.apply_active_revision(summary, course.id, semester, class_scope)
        charts = ChartService.build_summary_charts(summary)
        insight_payload = CourseInsightService.get_payload(course.id, semester, class_scope)
        weakest_objective = min(summary["objective_results"], key=lambda item: item["quantitative_attainment"]) if summary["objective_results"] else None
        strongest_objective = max(summary["objective_results"], key=lambda item: item["quantitative_attainment"]) if summary["objective_results"] else None
        weakest_assessment = min(summary["assessment_performance"], key=lambda item: item["score_rate"]) if summary["assessment_performance"] else None
    else:
        analysis_revision = None
        summary = {
            "semester": semester,
            "class_scope": class_scope,
            "student_count": score_student_count,
            "total_status": "待计算",
            "total_quantitative_attainment": 0.0,
            "total_qualitative_attainment": 0.0,
            "total_quantitative_attainment_percent": 0.0,
            "total_qualitative_score_percent": 0.0,
            "objective_results": [],
            "assessment_performance": [],
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
        charts = {"objective_bar": {}, "distribution_chart": {}, "assessment_bar": {}}
        insight_payload = None
        weakest_objective = None
        strongest_objective = None
        weakest_assessment = None

    return render_template(
        "analysis/index.html",
        course=course,
        summary=summary,
        charts=charts,
        form=form,
        insight_payload=insight_payload,
        weakest_objective=weakest_objective,
        strongest_objective=strongest_objective,
        weakest_assessment=weakest_assessment,
        has_score_data=has_score_data,
        has_analysis_result=has_analysis_result,
        analysis_record=analysis_record,
        analysis_revision=analysis_revision,
        analysis_snapshots=AnalysisRunService.list_snapshots(course.id, semester, class_scope),
        title=f"{course.name} - 达成度分析",
    )
