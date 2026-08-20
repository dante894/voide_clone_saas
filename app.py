"""
Estudio de Voz — SaaS de texto a voz con clonación de voz (XTTS-v2)

Versión multiusuario pensada para desplegar en Render, con:
- Cuentas de usuario (registro / login)
- Plan Free y Plan Pro (pago mensual vía Mercado Pago)
- Generación de audio en segundo plano (cola de trabajos)

Para correr en local:
    pip install -r requirements.txt
    python app.py
"""

import os
import re
from pathlib import Path

from flask import Flask, after_this_request, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager, current_user, login_required

import config
import worker
from admin import admin_bp
from auth import auth_bp
from billing import billing_bp
from models import Job, PageView, User, Voice, db

BASE_DIR = Path(__file__).resolve().parent

# Si DATA_DIR está configurado (por ejemplo un Persistent Disk de Render),
# las voces y audios generados se guardan ahí para que sobrevivan a los
# redeploys. Si no, se guardan junto al código (se pierden en cada deploy).
# Nota: el modelo XTTS-v2 ya NO se carga en este proceso — corre en un
# servicio aparte (ver cloud_run/ y worker.py), así que esta app no
# necesita cachear ningún modelo pesado.
DATA_ROOT = Path(config.DATA_DIR) if config.DATA_DIR else BASE_DIR
VOICES_DIR = DATA_ROOT / "voices"
OUTPUT_DIR = DATA_ROOT / "outputs"
VOICES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LANGUAGES = {
    "es": "Español", "en": "Inglés", "fr": "Francés", "de": "Alemán",
    "it": "Italiano", "pt": "Portugués", "pl": "Polaco", "tr": "Turco",
    "ru": "Ruso", "nl": "Neerlandés", "cs": "Checo", "ar": "Árabe",
    "zh-cn": "Chino", "ja": "Japonés", "hu": "Húngaro", "ko": "Coreano",
    "hi": "Hindi",
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    # Límite de subida (evita que alguien tire el servidor con archivos gigantes)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()

    register_pageview_tracking(app)
    register_routes(app)
    return app


# Rutas que NO se cuentan como "visita" (APIs, estáticos, webhooks, admin,
# descargas de audio). Solo interesa medir páginas que ve una persona.
_TRACK_EXCLUDE_PREFIXES = ("/static", "/api", "/outputs", "/webhooks", "/admin")


def register_pageview_tracking(app: Flask) -> None:
    @app.after_request
    def _track_pageview(response):
        path = request.path
        if (
            request.method == "GET"
            and response.status_code == 200
            and not any(path.startswith(p) for p in _TRACK_EXCLUDE_PREFIXES)
        ):
            try:
                user_id = current_user.id if current_user.is_authenticated else None
                db.session.add(PageView(path=path, user_id=user_id))
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
        return response


def safe_voice_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^\w\s\-áéíóúñÁÉÍÓÚÑ]", "", name, flags=re.UNICODE)
    name = re.sub(r"\s+", "_", name)
    return name or "voz"


def register_routes(app: Flask) -> None:

    @app.route("/")
    @login_required
    def index():
        limits = config.PLAN_LIMITS["pro" if current_user.is_pro else "free"]
        return render_template(
            "index.html",
            languages=LANGUAGES,
            limits=limits,
            generations_today=current_user.generations_today(),
        )

    # ---------- Voces ----------

    @app.route("/api/voices")
    @login_required
    def api_list_voices():
        voices = Voice.query.filter_by(user_id=current_user.id).order_by(Voice.created_at).all()
        return jsonify([{"filename": v.filename, "name": v.display_name} for v in voices])

    @app.route("/api/voices/<int:voice_id>", methods=["DELETE"])
    @login_required
    def api_delete_voice(voice_id):
        voice = Voice.query.filter_by(id=voice_id, user_id=current_user.id).first()
        if not voice:
            return jsonify({"error": "Voz no encontrada"}), 404
        target = VOICES_DIR / voice.filename
        if target.exists():
            target.unlink()
        db.session.delete(voice)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/upload-voice", methods=["POST"])
    @login_required
    def api_upload_voice():
        plan = "pro" if current_user.is_pro else "free"
        max_voices = config.PLAN_LIMITS[plan]["max_voices"]
        current_count = Voice.query.filter_by(user_id=current_user.id).count()
        if current_count >= max_voices:
            return jsonify({
                "error": f"Tu plan permite hasta {max_voices} voz(ces) guardada(s). "
                         f"Borrá alguna o pasate a Pro para guardar más."
            }), 403

        file = request.files.get("file")
        name = request.form.get("name", "")
        if not file:
            return jsonify({"error": "No se recibió ningún archivo de audio"}), 400

        base_name = safe_voice_name(name) if name else Path(file.filename or "voz").stem
        base_name = safe_voice_name(base_name)

        # Prefijamos con el ID de usuario para que dos usuarios no pisen archivos
        filename = f"u{current_user.id}_{base_name}.wav"
        counter = 1
        while (VOICES_DIR / filename).exists():
            filename = f"u{current_user.id}_{base_name}_{counter}.wav"
            counter += 1

        file.save(VOICES_DIR / filename)
        size_bytes = (VOICES_DIR / filename).stat().st_size
        voice = Voice(user_id=current_user.id, filename=filename, display_name=base_name, size_bytes=size_bytes)
        db.session.add(voice)
        db.session.commit()
        return jsonify({"ok": True, "filename": filename, "id": voice.id})

    # ---------- Generación ----------
    # Nota: no hay cola en segundo plano. El trabajo se crea acá (rápido) y
    # se procesa de forma síncrona la primera vez que se consulta su estado
    # (ver api_job_status más abajo) — ver worker.py para la explicación.

    @app.route("/api/generate", methods=["POST"])
    @login_required
    def api_generate():
        data = request.get_json(force=True) or {}
        text = (data.get("text") or "").strip()
        voice_filename = data.get("voice")
        language = data.get("language", "es")

        plan = "pro" if current_user.is_pro else "free"
        limits = config.PLAN_LIMITS[plan]

        if not text:
            return jsonify({"error": "Escribe algo de texto primero"}), 400
        if not voice_filename:
            return jsonify({"error": "Selecciona una voz de referencia"}), 400
        if language not in LANGUAGES:
            return jsonify({"error": "Idioma no soportado"}), 400
        if len(text) > limits["max_chars"]:
            return jsonify({
                "error": f"Tu plan permite hasta {limits['max_chars']} caracteres por audio "
                         f"(escribiste {len(text)}). Pasate a Pro para generar textos más largos."
            }), 403
        if current_user.generations_today() >= limits["max_generations_per_day"]:
            return jsonify({
                "error": f"Llegaste al límite de {limits['max_generations_per_day']} audios por día "
                         f"de tu plan. Volvé mañana o pasate a Pro."
            }), 403

        voice = Voice.query.filter_by(filename=voice_filename, user_id=current_user.id).first()
        if not voice:
            return jsonify({"error": "No se encontró la voz seleccionada"}), 404

        job = Job(
            user_id=current_user.id,
            text=text,
            language=language,
            voice_filename=voice.filename,
            status="pending",
        )
        db.session.add(job)
        db.session.commit()

        return jsonify({"ok": True, "job_id": job.id})

    @app.route("/api/jobs/<int:job_id>")
    @login_required
    def api_job_status(job_id):
        job = Job.query.filter_by(id=job_id, user_id=current_user.id).first()
        if not job:
            return jsonify({"error": "Trabajo no encontrado"}), 404

        # Si todavía no se procesó, lo hacemos ahora mismo, en esta misma
        # petición (bloqueante). El frontend ya está preparado para esperar
        # varios minutos la respuesta de este endpoint mientras sondea.
        if job.status == "pending":
            worker.process_job_sync(job, VOICES_DIR, OUTPUT_DIR)

        return jsonify({
            "status": job.status,
            "file": job.output_filename,
            "error": job.error_message,
        })

    @app.route("/outputs/<path:filename>")
    @login_required
    def serve_output(filename):
        # Reproducción dentro de la página (el reproductor <audio>). No borra
        # el archivo — para eso está /outputs/<filename>/download.
        job = Job.query.filter_by(output_filename=filename, user_id=current_user.id).first()
        if not job:
            return jsonify({"error": "No autorizado"}), 403
        return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)

    @app.route("/outputs/<path:filename>/download")
    @login_required
    def download_output(filename):
        # Descarga real del archivo. Apenas termina de enviarse, se borra del
        # servidor: así no se va acumulando espacio con audios ya entregados.
        job = Job.query.filter_by(
            output_filename=filename, user_id=current_user.id, status="done"
        ).first()
        if not job:
            return jsonify({"error": "No autorizado o el audio ya fue descargado"}), 404

        file_path = OUTPUT_DIR / filename
        if not file_path.exists():
            return jsonify({"error": "El audio ya no está disponible en el servidor"}), 404

        job_id = job.id

        @after_this_request
        def _delete_after_send(response):
            try:
                if file_path.exists():
                    file_path.unlink()
                j = db.session.get(Job, job_id)
                if j:
                    j.output_filename = None
                    j.output_size_bytes = 0
                    db.session.commit()
            except Exception:  # noqa: BLE001
                app.logger.exception("No se pudo borrar el audio descargado (job %s)", job_id)
            return response

        return send_from_directory(
            OUTPUT_DIR, filename, as_attachment=True, download_name=f"audio_{job_id}.wav"
        )

    @app.route("/cuenta")
    @login_required
    def cuenta():
        plan = "pro" if current_user.is_pro else "free"
        limits = config.PLAN_LIMITS[plan]
        used_bytes = current_user.storage_used_bytes()
        max_bytes = limits["max_storage_mb"] * 1024 * 1024
        storage = {
            "used_mb": used_bytes / (1024 * 1024),
            "max_mb": limits["max_storage_mb"],
            "percent": min(100, round(used_bytes / max_bytes * 100, 1)) if max_bytes else 0,
        }
        return render_template("cuenta.html", user=current_user, storage=storage)


app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    print(f"Estudio de Voz corriendo en http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)