from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from auth import login_required, panel_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == panel_password():
            session["auth"] = True
            return redirect(url_for("auth.index"))
        return render_template("login.html", error="密码错误")
    if session.get("auth"):
        return redirect(url_for("auth.index"))
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


@bp.route("/")
@login_required
def index():
    return render_template("index.html")
