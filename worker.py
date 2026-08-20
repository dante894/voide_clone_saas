"""
Cola simple de generación de audio en segundo plano.

La generación en sí NO corre acá — se le pide por HTTP a un servicio
externo (ver carpeta cloud_run/, pensado para Google Cloud Run) que tiene
la RAM necesaria para cargar XTTS-v2. Esto le permite a la app principal
(en Render) quedarse liviana y funcionar en el plan Free, sin cargar
PyTorch ni el modelo en este proceso.

Se sigue usando una cola con un solo worker (no por límite de RAM local,
sino para no mandar varias peticiones pesadas en simultáneo al servicio
externo, que también tiene recursos limitados).
"""

import queue
import threading
import traceback
import uuid
import os
from datetime import datetime
from pathlib import Path

import requests

import config

_job_queue: "queue.Queue[int]" = queue.Queue()

# Generar un audio puede tardar varios minutos si el servicio estaba
# "dormido" (Cloud Run con min-instances=0 tarda unos segundos en levantar
# el contenedor) además del tiempo de inferencia.
GENERATE_TIMEOUT_SECONDS = 600


def enqueue_job(job_id: int) -> None:
    print(f"[DEBUG] enqueue_job llamado con job_id={job_id} queue_id={id(_job_queue)}", flush=True)
    _job_queue.put(job_id)


def _call_remote_generate(text: str, language: str, speaker_wav_path: Path) -> bytes:
    if not config.VOICE_ENGINE_URL:
        raise RuntimeError(
            "Falta configurar VOICE_ENGINE_URL: la app no sabe a qué servidor "
            "pedirle la generación de audio."
        )

    url = config.VOICE_ENGINE_URL.rstrip("/") + "/generate"
    headers = {
        # Si el motor está detrás de un túnel gratis de ngrok, este header
        # evita que ngrok devuelva su página de aviso interstitial en vez
        # de pasar la petición real. No afecta a Cloud Run ni a otros hosts.
        "ngrok-skip-browser-warning": "true",
    }
    if config.VOICE_ENGINE_SECRET:
        headers["Authorization"] = f"Bearer {config.VOICE_ENGINE_SECRET}"

    with open(speaker_wav_path, "rb") as f:
        files = {"speaker_wav": (speaker_wav_path.name, f, "audio/wav")}
        data = {"text": text, "language": language}
        resp = requests.post(
            url, data=data, files=files, headers=headers, timeout=GENERATE_TIMEOUT_SECONDS
        )

    if resp.status_code != 200:
        # El servicio devuelve errores en JSON ({"detail": "..."})
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        raise RuntimeError(f"El servidor de generación devolvió un error: {detail}")

    return resp.content


def _process_job(app, job_id: int, voices_dir: Path, output_dir: Path) -> None:
    print(f"[DEBUG] _process_job arrancó para job_id={job_id}", flush=True)
    from models import Job, db

    with app.app_context():
        job = Job.query.get(job_id)
        if job is None:
            return
        job.status = "processing"
        db.session.commit()

        try:
            speaker_wav = voices_dir / job.voice_filename
            if not speaker_wav.exists():
                raise FileNotFoundError("El archivo de voz de referencia ya no existe.")

            audio_bytes = _call_remote_generate(job.text, job.language, speaker_wav)

            out_filename = f"{uuid.uuid4().hex}.wav"
            out_path = output_dir / out_filename
            out_path.write_bytes(audio_bytes)

            job.status = "done"
            job.output_filename = out_filename
            job.output_size_bytes = out_path.stat().st_size
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            job.status = "error"
            job.error_message = str(exc)
        finally:
            job.finished_at = datetime.utcnow()
            db.session.commit()


def start_worker(app, voices_dir: Path, output_dir: Path) -> None:
    """Arranca el hilo que va tomando trabajos de la cola, uno por vez."""
    print(f"[DEBUG] start_worker() llamado, queue_id={id(_job_queue)} pid={os.getpid()}", flush=True)

    def _loop():
        print(f"[DEBUG] _loop() arrancó dentro del hilo, queue_id={id(_job_queue)} pid={os.getpid()}", flush=True)
        while True:
            job_id = _job_queue.get()
            print(f"[DEBUG] _loop sacó job_id={job_id} de la cola", flush=True)
            try:
                _process_job(app, job_id, voices_dir, output_dir)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                _job_queue.task_done()

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    print(f"[DEBUG] thread.start() ejecutado, thread.is_alive()={thread.is_alive()}", flush=True)


def requeue_pending_jobs(app) -> None:
    """Al arrancar la app, vuelve a encolar trabajos que quedaron a medias
    (por ejemplo si el servicio se reinició en Render)."""
    from models import Job

    with app.app_context():
        pending = Job.query.filter(Job.status.in_(["pending", "processing"])).all()
        for job in pending:
            job.status = "pending"
        from models import db

        db.session.commit()
        for job in pending:
            enqueue_job(job.id)