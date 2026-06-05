import json
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, session, url_for

from forms import ScoreUploadForm
from models import Assessment, Course, ImportBatch
from services.import_service import ImportService
from services.score_template_service import ScoreTemplateService
from services.seed_service import DEFAULT_SEMESTER


import_bp = Blueprint("importer", __name__, url_prefix="/courses/<int:course_id>/imports")


@import_bp.route("/score-template")
def download_score_template(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)

    template_dir = Path(current_app.config["EXPORT_FOLDER"]) / "templates"
    output_path = template_dir / f"course_{course.id}_score_template.xlsx"
    try:
        ScoreTemplateService.build_course_template(course, output_path)
    except ValueError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("importer.import_scores", course_id=course.id))

    download_name = f"{course.name}成绩导入模板.xlsx"
    return send_file(
        output_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@import_bp.route("/", methods=["GET", "POST"])
def import_scores(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        abort(404)
    form = ScoreUploadForm()
    form.semester.data = form.semester.data or DEFAULT_SEMESTER
    preview_result = None
    pending_import = session.get("pending_score_import")

    if request.method == "POST" and request.form.get("action") == "confirm_pending":
        pending_import = session.get("pending_score_import") or {}
        if pending_import.get("course_id") != course.id:
            flash("没有找到可确认的成绩预检结果，请重新上传并预检。", "warning")
            return redirect(url_for("importer.import_scores", course_id=course.id))
        file_paths = [Path(item) for item in pending_import.get("file_paths", [])]
        semester = pending_import.get("semester") or DEFAULT_SEMESTER
        try:
            result = ImportService.import_score_files(file_paths, course, semester)
        except Exception as exc:
            current_app.logger.exception("成绩确认导入失败：%s", ", ".join(str(item) for item in file_paths))
            flash(f"成绩导入失败：{exc}", "danger")
            return redirect(url_for("importer.import_scores", course_id=course.id))
        session.pop("pending_score_import", None)
        if result["success"]:
            flash(f"成绩导入成功，共处理 {result['imported']} 条学生记录。下一步请进入“达成度分析”页面手动执行第四章计算。", "success")
        else:
            for issue in result["issues"][:8]:
                flash(issue, "danger")
        return redirect(url_for("importer.import_scores", course_id=course.id))

    if form.validate_on_submit():
        uploaded_files = [item for item in request.files.getlist(form.file.name) if item and item.filename]
        if not uploaded_files:
            flash("请至少选择一个成绩文件。", "danger")
            return redirect(url_for("importer.import_scores", course_id=course.id))
        file_paths = [ImportService.save_upload(item, current_app.config["UPLOAD_FOLDER"]) for item in uploaded_files]
        try:
            preview_result = ImportService.preview_score_files(file_paths, course, form.semester.data.strip())
        except Exception as exc:
            current_app.logger.exception("成绩预检失败：%s", ", ".join(str(item) for item in file_paths))
            flash(f"成绩预检失败：{exc}", "danger")
            return redirect(url_for("importer.import_scores", course_id=course.id))

        if preview_result["success"]:
            session["pending_score_import"] = {
                "course_id": course.id,
                "semester": form.semester.data.strip(),
                "file_paths": [str(item) for item in file_paths],
            }
            pending_import = session["pending_score_import"]
            flash("成绩文件预检通过，请确认后再写入系统。", "success")
        else:
            session.pop("pending_score_import", None)
            pending_import = None
            for issue in preview_result["issues"][:8]:
                flash(issue, "danger")
    recent_imports = ImportBatch.query.filter_by(course_id=course.id).order_by(ImportBatch.created_at.desc()).limit(5).all()
    latest_import_detail = None
    if recent_imports:
        latest = recent_imports[0]
        latest_import_detail = {
            "filename": latest.filename,
            "sheet": latest.source_sheet or "-",
            "mapping": json.loads(latest.column_mapping_json or "{}"),
            "issues": json.loads(latest.issues_json or "[]"),
            "issue_count": latest.issue_count,
            "imported_count": latest.imported_count,
            "import_version": latest.import_version or 1,
            "file_hash": latest.file_hash or "",
            "pre_student_count": latest.pre_student_count or 0,
            "post_student_count": latest.post_student_count or 0,
            "cleanup_count": latest.cleanup_count or 0,
            "status": latest.status or "已完成",
        }
    assessments = Assessment.query.filter_by(course_id=course.id).order_by(Assessment.sequence.asc()).all()
    return render_template(
        "import/index.html",
        course=course,
        form=form,
        recent_imports=recent_imports,
        latest_import_detail=latest_import_detail,
        preview_result=preview_result,
        pending_import=pending_import,
        assessments=assessments,
        title=f"{course.name} - 成绩导入",
    )
