from flask import Blueprint, render_template


guide_bp = Blueprint("guide", __name__, url_prefix="/guide")


@guide_bp.route("/")
def index():
    return render_template("guide/index.html", title="系统使用说明")
