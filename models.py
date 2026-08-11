from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    # Nullable porque los usuarios que entran con Google no tienen contraseña propia.
    password_hash = db.Column(db.String(255), nullable=True)
    plan = db.Column(db.String(20), nullable=False, default="free")  # "free" | "pro"

    # Login social (OAuth). provider: "google" | None (None = email/contraseña)
    oauth_provider = db.Column(db.String(20))
    oauth_id = db.Column(db.String(255))

    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    # Datos de la suscripción de Mercado Pago
    mp_preapproval_id = db.Column(db.String(120))
    mp_status = db.Column(db.String(30))  # authorized | paused | cancelled | pending

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    voices = db.relationship("Voice", backref="owner", lazy=True, cascade="all, delete-orphan")
    jobs = db.relationship("Job", backref="owner", lazy=True, cascade="all, delete-orphan")
    login_events = db.relationship("LoginEvent", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_pro(self) -> bool:
        return self.plan == "pro" and self.mp_status == "authorized"

    def generations_today(self) -> int:
        today_start = datetime.combine(date.today(), datetime.min.time())
        return Job.query.filter(
            Job.user_id == self.id,
            Job.created_at >= today_start,
        ).count()

    def storage_used_bytes(self) -> int:
        """Espacio ocupado por las voces guardadas + audios generados de este usuario."""
        from sqlalchemy import func

        voices_bytes = (
            db.session.query(func.coalesce(func.sum(Voice.size_bytes), 0))
            .filter(Voice.user_id == self.id)
            .scalar()
        )
        outputs_bytes = (
            db.session.query(func.coalesce(func.sum(Job.output_size_bytes), 0))
            .filter(Job.user_id == self.id, Job.status == "done")
            .scalar()
        )
        return int(voices_bytes or 0) + int(outputs_bytes or 0)


class LoginEvent(db.Model):
    """Un registro por cada inicio de sesión, para estadísticas."""

    __tablename__ = "login_events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(20), nullable=False, default="password")  # password | google
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class PageView(db.Model):
    """Contador simple de visitas (una fila por request de página vista)."""

    __tablename__ = "page_views"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class Voice(db.Model):
    __tablename__ = "voices"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)   # nombre real en disco
    display_name = db.Column(db.String(255), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Job(db.Model):
    """Un trabajo de generación de audio (procesado en segundo plano)."""

    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(10), nullable=False)
    voice_filename = db.Column(db.String(255), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="pending")
    # pending | processing | done | error
    output_filename = db.Column(db.String(255))
    output_size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    error_message = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
