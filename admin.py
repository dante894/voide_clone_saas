"""
Panel de administración simple: estadísticas de usuarios (email vs Google),
suscripciones Pro, y visitas al sitio. Solo accesible para usuarios con
is_admin=True (ver config.ADMIN_EMAILS).
"""

from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from models import LoginEvent, PageView, User, db

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

DAYS_WINDOW = 14


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(404)  # no revelamos que existe un panel de admin
        return view(*args, **kwargs)
    return wrapped


def _daily_counts(model, date_column, since):
    rows = (
        db.session.query(func.date(date_column).label("day"), func.count(model.id))
        .filter(date_column >= since)
        .group_by("day")
        .order_by("day")
        .all()
    )
    return {str(day): count for day, count in rows}


def _fill_series(counts_by_day: dict, days: int):
    today = datetime.utcnow().date()
    series = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        series.append({"day": d.isoformat(), "count": counts_by_day.get(d.isoformat(), 0)})
    return series


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    since = datetime.utcnow() - timedelta(days=DAYS_WINDOW)

    total_users = User.query.count()
    pro_users = User.query.filter_by(plan="pro", mp_status="authorized").count()
    google_users = User.query.filter_by(oauth_provider="google").count()
    password_users = total_users - google_users

    signups_series = _fill_series(_daily_counts(User, User.created_at, since), DAYS_WINDOW)

    # Logins por proveedor, por día (dos series separadas)
    login_rows = (
        db.session.query(
            func.date(LoginEvent.created_at).label("day"),
            LoginEvent.provider,
            func.count(LoginEvent.id),
        )
        .filter(LoginEvent.created_at >= since)
        .group_by("day", LoginEvent.provider)
        .all()
    )
    google_by_day, password_by_day = {}, {}
    for day, provider, count in login_rows:
        target = google_by_day if provider == "google" else password_by_day
        target[str(day)] = count
    logins_google_series = _fill_series(google_by_day, DAYS_WINDOW)
    logins_password_series = _fill_series(password_by_day, DAYS_WINDOW)

    total_logins_window = sum(r["count"] for r in logins_google_series) + sum(
        r["count"] for r in logins_password_series
    )

    pageviews_series = _fill_series(_daily_counts(PageView, PageView.created_at, since), DAYS_WINDOW)
    total_pageviews_window = sum(r["count"] for r in pageviews_series)

    signups_max = max((r["count"] for r in signups_series), default=0) or 1
    pageviews_max = max((r["count"] for r in pageviews_series), default=0) or 1
    logins_max = max(
        [r["count"] for r in logins_google_series] + [r["count"] for r in logins_password_series],
        default=0,
    ) or 1

    top_paths = (
        db.session.query(PageView.path, func.count(PageView.id).label("n"))
        .filter(PageView.created_at >= since)
        .group_by(PageView.path)
        .order_by(func.count(PageView.id).desc())
        .limit(10)
        .all()
    )

    recent_signups = User.query.order_by(User.created_at.desc()).limit(15).all()
    recent_logins = (
        LoginEvent.query.order_by(LoginEvent.created_at.desc()).limit(15).all()
    )

    return render_template(
        "admin/dashboard.html",
        days_window=DAYS_WINDOW,
        total_users=total_users,
        pro_users=pro_users,
        google_users=google_users,
        password_users=password_users,
        signups_series=signups_series,
        logins_google_series=logins_google_series,
        logins_password_series=logins_password_series,
        total_logins_window=total_logins_window,
        pageviews_series=pageviews_series,
        total_pageviews_window=total_pageviews_window,
        signups_max=signups_max,
        pageviews_max=pageviews_max,
        logins_max=logins_max,
        top_paths=top_paths,
        recent_signups=recent_signups,
        recent_logins=recent_logins,
    )
