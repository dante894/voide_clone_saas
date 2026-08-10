import re
import secrets
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user

import config
from models import LoginEvent, User, db

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _google_redirect_uri() -> str:
    return f"{config.APP_BASE_URL}{url_for('auth.google_callback')}"


def _promote_admin_if_needed(user: User) -> None:
    if user.email in config.ADMIN_EMAILS and not user.is_admin:
        user.is_admin = True
        db.session.commit()


def _log_login(user: User, provider: str) -> None:
    db.session.add(LoginEvent(user_id=user.id, provider=provider))
    db.session.commit()


# ---------- Email / contraseña ----------

@auth_bp.route("/registro", methods=["GET", "POST"])
def register():
    google_enabled = bool(config.GOOGLE_CLIENT_ID)
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not EMAIL_RE.match(email):
            flash("Ingresá un email válido.", "error")
            return render_template("register.html", google_enabled=google_enabled)
        if len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
            return render_template("register.html", google_enabled=google_enabled)
        if User.query.filter_by(email=email).first():
            flash("Ya existe una cuenta con ese email.", "error")
            return render_template("register.html", google_enabled=google_enabled)

        user = User(email=email, plan="free")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        _promote_admin_if_needed(user)
        _log_login(user, "password")
        login_user(user)
        return redirect(url_for("index"))

    return render_template("register.html", google_enabled=google_enabled)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Email o contraseña incorrectos.", "error")
            return render_template("login.html")

        _promote_admin_if_needed(user)
        _log_login(user, "password")
        login_user(user)
        next_url = request.args.get("next")
        return redirect(next_url or url_for("index"))

    return render_template("login.html", google_enabled=bool(config.GOOGLE_CLIENT_ID))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ---------- Google OAuth ----------

@auth_bp.route("/auth/google")
def google_login():
    if not config.GOOGLE_CLIENT_ID:
        flash("El login con Google no está configurado todavía.", "error")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state

    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@auth_bp.route("/auth/google/callback")
def google_callback():
    if not config.GOOGLE_CLIENT_ID:
        flash("El login con Google no está configurado todavía.", "error")
        return redirect(url_for("auth.login"))

    error = request.args.get("error")
    if error:
        flash("No se pudo completar el login con Google.", "error")
        return redirect(url_for("auth.login"))

    state = request.args.get("state")
    expected_state = session.pop("oauth_state", None)
    if not state or not expected_state or state != expected_state:
        flash("La sesión de login con Google expiró o no es válida. Probá de nuevo.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("No se pudo completar el login con Google.", "error")
        return redirect(url_for("auth.login"))

    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_data = token_resp.json() if token_resp.content else {}
        access_token = token_data.get("access_token")
        if token_resp.status_code != 200 or not access_token:
            current_app.logger.error("Error obteniendo token de Google: %s", token_data)
            flash("No se pudo completar el login con Google.", "error")
            return redirect(url_for("auth.login"))

        userinfo_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        userinfo = userinfo_resp.json() if userinfo_resp.content else {}
    except requests.RequestException:
        current_app.logger.exception("Error de red hablando con Google OAuth")
        flash("No se pudo contactar a Google. Probá de nuevo en un rato.", "error")
        return redirect(url_for("auth.login"))

    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    email_verified = userinfo.get("email_verified", False)

    if not google_id or not email or not email_verified:
        flash("Tu cuenta de Google no tiene un email verificado.", "error")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(oauth_provider="google", oauth_id=google_id).first()
    if user is None:
        # ¿Ya existía una cuenta con ese email creada por email/contraseña?
        user = User.query.filter_by(email=email).first()
        if user is None:
            user = User(email=email, plan="free", oauth_provider="google", oauth_id=google_id)
            db.session.add(user)
        else:
            user.oauth_provider = "google"
            user.oauth_id = google_id
        db.session.commit()

    _promote_admin_if_needed(user)
    _log_login(user, "google")
    login_user(user)
    return redirect(url_for("index"))
