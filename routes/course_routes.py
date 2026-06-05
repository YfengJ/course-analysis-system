import json
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from forms import CourseCreateForm, CourseForm, ObjectiveForm, OutlineUploadForm
from models import (
    AnalysisRun,
    AnalysisRevision,
    AnalysisSnapshot,
    Assessment,
    Course,
    CourseInsight,
    CourseObjective,
    ImportBatch,
    ObjectiveAssessmentWeight,
    ObjectiveRequirementMap,
    ObjectiveScore,
    QualitativeRecord,
    Report,
    Score,
    Student,
    TeachingOutline,
    db,
)
from services.course_progress_service import CourseProgressService
from services.auth_service import AuthService
from services.import_service import ImportService
from services.seed_service import create_generic_course_structure
from services.template_adapters.outline_template_adapter import OutlineTemplateAdapter


course_bp = Blueprint("course", __name__, url_prefix="/courses")


def get_course_or_404(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    return course


def _safe_int(value, default=32):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=1.5):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _build_course_from_outline_payload(parsed):
    parsed_code = (parsed.get("course_code") or "").strip()
    code = parsed_code or f"AUTO{datetime.now().strftime('%Y%m%d%H%M%S')}"
    name = (parsed.get("course_name") or "").strip() or "未命名课程"
    hours = parsed.get("hours")
    credits = parsed.get("credits")
    if not hours and parsed.get("hours_credits") and "/" in parsed["hours_credits"]:
        hours = parsed["hours_credits"].split("/", 1)[0]
    if not credits and parsed.get("hours_credits") and "/" in parsed["hours_credits"]:
        credits = parsed["hours_credits"].split("/", 1)[1]
    return Course(
        code=code,
        name=name,
        english_name=(parsed.get("english_name") or "").strip(),
        nature=(parsed.get("nature") or "").strip(),
        category=(parsed.get("category") or "").strip(),
        hours=_safe_int(hours),
        credits=_safe_float(credits),
        assessment_method=(parsed.get("assessment_method") or "考查").strip(),
        semester=(parsed.get("semester_hint") or "").strip(),
        class_names=(parsed.get("class_names") or "").strip(),
        department=(parsed.get("department") or "").strip(),
        major=(parsed.get("major") or "").strip(),
        course_owner=(parsed.get("course_owner") or "待完善").strip(),
        prerequisites=(parsed.get("prerequisites") or "").strip(),
        textbook=(parsed.get("textbook") or "").strip(),
        description=(parsed.get("description") or "").strip(),
        expected_value=current_app.config["DEFAULT_EXPECTED_VALUE"],
        template_name="教学大纲驱动课程模板",
        template_source=(parsed.get("source_template") or "").strip(),
    )


@course_bp.route("/new", methods=["GET", "POST"])
def create_course():
    form = CourseCreateForm()
    outline_form = OutlineUploadForm()
    if form.validate_on_submit():
        course = Course()
        form.populate_obj(course)
        current_user = AuthService.current_user()
        if current_user:
            course.owner_user_id = current_user.id
        db.session.add(course)
        db.session.flush()
        create_generic_course_structure(course)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("课程保存失败，请检查课程编号、学期和班级信息后重试。", "danger")
            return render_template("courses/new.html", form=form, outline_form=outline_form, title="新建课程")
        flash("课程已创建，请继续配置课程目标和导入数据。", "success")
        return redirect(url_for("course.detail", course_id=course.id))
    return render_template("courses/new.html", form=form, outline_form=outline_form, title="新建课程")


@course_bp.route("/new/from-outline", methods=["POST"])
def create_course_from_outline():
    form = OutlineUploadForm()
    if not form.validate_on_submit():
        flash("请上传 docx 格式的教学大纲。", "danger")
        return redirect(url_for("course.create_course"))

    file_path = ImportService.save_upload(form.file.data, current_app.config["UPLOAD_FOLDER"])
    parsed = OutlineTemplateAdapter.extract(file_path)["payload"]

    course = _build_course_from_outline_payload(parsed)
    current_user = AuthService.current_user()
    if current_user:
        course.owner_user_id = current_user.id
    db.session.add(course)
    db.session.flush()
    create_generic_course_structure(course)
    try:
        ImportService.import_outline(file_path, course)
    except IntegrityError:
        db.session.rollback()
        flash("教学大纲建课失败，请检查课程编号、学期和班级信息后重试。", "danger")
        return redirect(url_for("course.create_course"))

    flash("已根据教学大纲创建课程，并同步课程基础信息、课程目标和考核权重。", "success")
    return redirect(url_for("course.show_outline", course_id=course.id))


@course_bp.route("/")
def index():
    keyword = (request.args.get("keyword") or "").strip()
    status_filter = request.args.get("status", "all")

    course_query = Course.query
    current_user = AuthService.current_user()
    if current_user and current_user.role != "admin":
        course_query = course_query.filter(
            or_(Course.owner_user_id.is_(None), Course.owner_user_id == current_user.id)
        )
    courses = course_query.order_by(Course.updated_at.desc()).all()
    course_rows = []
    summary = {
        "all": 0,
        "pending": 0,
        "completed": 0,
    }
    for course in courses:
        snapshot = CourseProgressService.build_snapshot(course)
        outline_count = TeachingOutline.query.filter_by(course_id=course.id).count()
        student_count = snapshot["student_count"]
        latest_report = snapshot["latest_report"]

        is_completed = snapshot["status_group"] == "completed"
        summary["all"] += 1
        summary["completed" if is_completed else "pending"] += 1
        if keyword and keyword not in course.name and keyword not in course.code:
            continue
        if status_filter == "completed" and not is_completed:
            continue
        if status_filter == "pending" and is_completed:
            continue

        course_rows.append(
            {
                "course": course,
                "outline_count": outline_count,
                "student_count": student_count,
                "objective_count": len(course.objectives),
                "assessment_count": len(course.assessments),
                "report_count": len(course.reports),
                "latest_report": latest_report,
                "latest_analysis": snapshot["latest_analysis"],
                "status": snapshot["display_status"],
                "status_group": snapshot["status_group"],
                "next_action": snapshot["next_action"],
                "stages": snapshot["stages"],
                "report_preview_ready": snapshot["report_preview_ready"],
                "report_ready": snapshot["report_ready"],
            }
        )

    return render_template(
        "courses/index.html",
        course_rows=course_rows,
        keyword=keyword,
        status_filter=status_filter,
        summary=summary,
        title="课程列表",
    )


@course_bp.route("/<int:course_id>/delete", methods=["POST"])
def delete_course(course_id: int):
    course = get_course_or_404(course_id)
    if not AuthService.can_manage_course(course):
        abort(403)
    course_name = course.name

    student_ids = [item.id for item in Student.query.with_entities(Student.id).filter_by(course_id=course.id)]
    objective_ids = [item.id for item in CourseObjective.query.with_entities(CourseObjective.id).filter_by(course_id=course.id)]
    assessment_ids = [item.id for item in Assessment.query.with_entities(Assessment.id).filter_by(course_id=course.id)]
    objective_weight_ids = []
    if objective_ids or assessment_ids:
        conditions = []
        if objective_ids:
            conditions.append(ObjectiveAssessmentWeight.objective_id.in_(objective_ids))
        if assessment_ids:
            conditions.append(ObjectiveAssessmentWeight.assessment_id.in_(assessment_ids))
        query = ObjectiveAssessmentWeight.query.with_entities(ObjectiveAssessmentWeight.id).filter(or_(*conditions))
        objective_weight_ids = [item.id for item in query]

    if student_ids:
        ObjectiveScore.query.filter(ObjectiveScore.student_id.in_(student_ids)).delete(synchronize_session=False)
        Score.query.filter(Score.student_id.in_(student_ids)).delete(synchronize_session=False)
    if objective_weight_ids:
        ObjectiveScore.query.filter(ObjectiveScore.objective_weight_id.in_(objective_weight_ids)).delete(synchronize_session=False)
    if assessment_ids:
        Score.query.filter(Score.assessment_id.in_(assessment_ids)).delete(synchronize_session=False)
    if objective_ids:
        QualitativeRecord.query.filter(QualitativeRecord.objective_id.in_(objective_ids)).delete(synchronize_session=False)
        ObjectiveRequirementMap.query.filter(ObjectiveRequirementMap.objective_id.in_(objective_ids)).delete(synchronize_session=False)
        ObjectiveAssessmentWeight.query.filter(ObjectiveAssessmentWeight.objective_id.in_(objective_ids)).delete(synchronize_session=False)
    if assessment_ids:
        ObjectiveAssessmentWeight.query.filter(ObjectiveAssessmentWeight.assessment_id.in_(assessment_ids)).delete(synchronize_session=False)

    QualitativeRecord.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Student.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Assessment.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    CourseObjective.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    CourseInsight.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    Report.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    AnalysisRun.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    AnalysisSnapshot.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    AnalysisRevision.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    ImportBatch.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    TeachingOutline.query.filter_by(course_id=course.id).delete(synchronize_session=False)
    db.session.delete(course)
    db.session.commit()

    flash(f"课程“{course_name}”及其成绩、分析和报告记录已删除。", "success")
    return redirect(url_for("course.index"))


@course_bp.route("/<int:course_id>", methods=["GET", "POST"])
def detail(course_id: int):
    course = get_course_or_404(course_id)
    form = CourseForm(obj=course)
    if form.validate_on_submit():
        form.populate_obj(course)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("课程保存失败，请检查课程编号、学期和班级信息后重试。", "danger")
            return render_template(
                "courses/detail.html",
                course=course,
                form=form,
                title=f"{course.name} - 课程概览",
                latest_outline=TeachingOutline.query.filter_by(course_id=course.id).order_by(TeachingOutline.created_at.desc()).first(),
                latest_report=Report.query.filter_by(course_id=course.id).order_by(Report.created_at.desc()).first(),
            )
        flash("课程基本信息已更新。", "success")
        return redirect(url_for("course.detail", course_id=course.id))

    snapshot = CourseProgressService.build_snapshot(course)
    latest_outline = snapshot["latest_outline"]
    latest_report = snapshot["latest_report"]
    latest_import = snapshot["latest_import"]
    latest_analysis = snapshot["latest_analysis"]
    student_count = snapshot["student_count"]
    progress_items = [
        {"label": "上传教学大纲", "done": latest_outline is not None, "hint": latest_outline.filename if latest_outline else "等待上传"},
        {"label": "导入成绩数据", "done": student_count > 0, "hint": latest_import.filename if latest_import else "等待导入"},
        {
            "label": "计算达成度分析",
            "done": snapshot["analysis_ready"],
            "hint": latest_analysis.updated_at.strftime('%Y-%m-%d %H:%M') if latest_analysis else (latest_report.created_at.strftime('%Y-%m-%d %H:%M') if latest_report else "等待计算"),
        },
        {
            "label": "报告预览/导出",
            "done": latest_report is not None,
            "hint": latest_report.status if latest_report else ("分析完成后即可进入预览" if snapshot["analysis_ready"] else "等待生成"),
        },
    ]
    completed_steps = sum(1 for item in progress_items if item["done"])
    return render_template(
        "courses/detail.html",
        course=course,
        form=form,
        title=f"{course.name} - 课程概览",
        latest_outline=latest_outline,
        latest_report=latest_report,
        latest_import=latest_import,
        progress_items=progress_items,
        completed_steps=completed_steps,
    )


@course_bp.route("/<int:course_id>/objectives", methods=["GET", "POST"])
def manage_objectives(course_id: int):
    course = get_course_or_404(course_id)
    form = ObjectiveForm()
    if form.validate_on_submit():
        sequence = len(course.objectives) + 1
        objective = CourseObjective(
            course_id=course.id,
            sequence=sequence,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            weight=form.weight.data,
        )
        db.session.add(objective)
        db.session.commit()
        flash("课程目标已新增。", "success")
        return redirect(url_for("course.manage_objectives", course_id=course.id))
    objectives = CourseObjective.query.filter_by(course_id=course.id).order_by(CourseObjective.sequence.asc()).all()
    return render_template("courses/objectives.html", course=course, objectives=objectives, form=form, title=f"{course.name} - 课程目标")


@course_bp.route("/<int:course_id>/outline", methods=["GET", "POST"])
def show_outline(course_id: int):
    course = get_course_or_404(course_id)
    form = OutlineUploadForm()
    parsed_outline = None
    pending_outline = session.get("pending_outline_import")

    if request.method == "POST" and request.form.get("action") == "confirm_pending":
        pending_outline = session.get("pending_outline_import") or {}
        if pending_outline.get("course_id") != course.id:
            flash("没有找到可确认的教学大纲预览结果，请重新上传并预览。", "warning")
            return redirect(url_for("course.show_outline", course_id=course.id))
        outline, _ = ImportService.import_outline(Path(pending_outline["file_path"]), course)
        session.pop("pending_outline_import", None)
        flash(f"教学大纲已确认导入并同步：{outline.filename}", "success")
        return redirect(url_for("course.show_outline", course_id=course.id))

    if form.validate_on_submit():
        file_path = ImportService.save_upload(form.file.data, current_app.config["UPLOAD_FOLDER"])
        adapter_result = OutlineTemplateAdapter.extract(file_path)
        parsed_outline = adapter_result["payload"]
        parsed_outline["source_template"] = file_path.name
        session["pending_outline_import"] = {
            "course_id": course.id,
            "file_path": str(file_path),
            "filename": file_path.name,
            "parsed": parsed_outline,
        }
        pending_outline = session["pending_outline_import"]
        flash("教学大纲解析预览已生成，请确认后再写入课程配置。", "success")

    latest_outline = TeachingOutline.query.filter_by(course_id=course.id).order_by(TeachingOutline.created_at.desc()).first()
    if not parsed_outline and pending_outline and pending_outline.get("course_id") == course.id:
        parsed_outline = pending_outline.get("parsed")
    if not parsed_outline and latest_outline and latest_outline.parsed_json:
        parsed_outline = json.loads(latest_outline.parsed_json)
    return render_template(
        "courses/outline.html",
        course=course,
        form=form,
        outline=latest_outline,
        parsed_outline=parsed_outline,
        pending_outline=pending_outline if pending_outline and pending_outline.get("course_id") == course.id else None,
        assessments=Assessment.query.filter_by(course_id=course.id).order_by(Assessment.sequence.asc()).all(),
        title=f"{course.name} - 教学大纲",
    )
