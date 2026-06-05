from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from forms import ChangePasswordForm, LoginForm
from services.auth_service import AuthService


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if AuthService.login_disabled():
        return redirect(url_for("dashboard.index"))
    form = LoginForm()
    next_url = _safe_next_url(request.args.get("next")) or url_for("dashboard.index")
    if form.validate_on_submit():
        user = AuthService.authenticate(form.username.data, form.password.data)
        if user:
            AuthService.login_user(user)
            flash("已登录系统。", "success")
            return redirect(next_url)
        flash("账号或密码不正确。", "danger")
    return render_template("auth/login.html", form=form, next_url=next_url, title="登录系统")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    AuthService.logout_user()
    flash("已退出登录。", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/account/password", methods=["GET", "POST"])
def change_password():
    if AuthService.login_disabled():
        return redirect(url_for("dashboard.index"))
    user = AuthService.current_user()
    if not user:
        return redirect(url_for("auth.login", next=request.path))

    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not check_password_hash(user.password_hash, str(form.current_password.data or "")):
            flash("当前密码不正确。", "danger")
        elif str(form.current_password.data or "") == str(form.new_password.data or ""):
            flash("新密码不能与当前密码相同。", "warning")
        else:
            AuthService.update_password(user, form.new_password.data)
            flash("密码已更新，请使用新密码继续管理系统。", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/change_password.html", form=form, title="修改密码")


def _safe_next_url(value):
    text = str(value or "").strip()
    if not text or not text.startswith("/") or text.startswith("//"):
        return ""
    return text
