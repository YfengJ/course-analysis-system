from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from services.auth_service import AuthService
from services.data_backup_service import DataBackupService
from services.schema_migration_service import SchemaMigrationService


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _backup_dir():
    folder = current_app.config.get("BACKUP_FOLDER") or str(Path(current_app.config["EXPORT_FOLDER"]) / "backups")
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    return path


@admin_bp.route("/backups")
def backups():
    return render_template(
        "admin/backups.html",
        backups=DataBackupService.list_backups(current_app),
        title="数据备份与恢复",
    )


@admin_bp.route("/backups/create", methods=["POST"])
def create_backup():
    try:
        backup_path = DataBackupService.create_backup(current_app)
        flash(f"备份已创建：{Path(backup_path).name}", "success")
    except Exception as exc:
        flash(f"创建备份失败：{exc}", "danger")
    return redirect(url_for("admin.backups"))


@admin_bp.route("/backups/download/<path:filename>")
def download_backup(filename):
    backup_dir = _backup_dir().resolve()
    backup_path = (backup_dir / filename).resolve()
    if backup_dir not in backup_path.parents or not backup_path.exists() or backup_path.suffix.lower() != ".zip":
        abort(404)
    return send_file(backup_path, as_attachment=True, download_name=backup_path.name)


@admin_bp.route("/backups/restore", methods=["POST"])
def restore_backup():
    if (request.form.get("confirm_restore") or "").strip() != "确认恢复":
        flash("请输入“确认恢复”后再执行恢复操作。", "warning")
        return redirect(url_for("admin.backups"))

    uploaded = request.files.get("backup_file")
    if not uploaded or not uploaded.filename:
        flash("请先选择一个备份 zip 文件。", "warning")
        return redirect(url_for("admin.backups"))

    suffix = Path(uploaded.filename).suffix.lower()
    if suffix != ".zip":
        flash("只支持恢复 zip 格式的系统备份包。", "warning")
        return redirect(url_for("admin.backups"))

    filename = secure_filename(uploaded.filename) or "restore_backup.zip"
    restore_path = _backup_dir() / f"uploaded_{DataBackupService._timestamp()}_{filename}"
    uploaded.save(restore_path)

    try:
        pre_restore_backup = DataBackupService.create_backup(current_app)
        result = DataBackupService.restore_backup(current_app, restore_path)
        SchemaMigrationService.ensure_schema()
        AuthService.ensure_default_user()
        guard = result.get("pre_restore_copy")
        note = (
            f"恢复完成，恢复前已创建完整备份 {Path(pre_restore_backup).name}，"
            f"数据库副本 {Path(guard).name} 已保留。"
            if guard
            else f"恢复完成，恢复前已创建完整备份 {Path(pre_restore_backup).name}。"
        )
        flash(note, "success")
    except Exception as exc:
        flash(f"恢复失败：{exc}", "danger")
    return redirect(url_for("admin.backups"))
