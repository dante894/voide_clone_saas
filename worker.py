"""
Cola simple de generación de audio en segundo plano.

XTTS-v2 en CPU (Render sin GPU) puede tardar 1-3 minutos por frase, así que
no conviene generar el audio dentro de la misma petición HTTP (se pasaría el
timeout de gunicorn). En cambio: se crea un "Job" en la base de datos, se
encola acá, y el frontend consulta el estado con /api/jobs/<id>.

Se usa un solo worker en paralelo (max_workers=1) a propósito: correr más de
una generación de XTTS-v2 a la vez en un servidor sin GPU y con RAM limitada
puede tirar el proceso por falta de memoria.
"""

import queue
import threading
import traceback
from datetime import datetime
from pathlib import Path

_job_queue: "queue.Queue[int]" = queue.Queue()
_tts_model = None
_model_lock = threading.Lock()


def get_model():
    """Carga el modelo XTTS-v2 una sola vez (perezoso, hilo-seguro)."""
    global _tts_model
    with _model_lock:
        if _tts_model is None:
            import torch
            from TTS.api import TTS

            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[worker] Cargando modelo XTTS-v2 en: {device} ...")
            _tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
            print("[worker] Modelo listo.")
        return _tts_model


def enqueue_job(job_id: int) -> None:
    _job_queue.put(job_id)


def _process_job(app, job_id: int, voices_dir: Path, output_dir: Path) -> None:
    from models import Job, db

    with app.app_context():
        job = Job.query.get(job_id)
        if job is None:
            return
        job.status = "processing"
        db.session.commit()

        try:
            model = get_model()
            speaker_wav = voices_dir / job.voice_filename
            if not speaker_wav.exists():
                raise FileNotFoundError("El archivo de voz de referencia ya no existe.")

            import uuid

            out_filename = f"{uuid.uuid4().hex}.wav"
            out_path = output_dir / out_filename
            model.tts_to_file(
                text=job.text,
                speaker_wav=str(speaker_wav),
                language=job.language,
                file_path=str(out_path),
            )
            job.status = "done"
            job.output_filename = out_filename
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            job.status = "error"
            job.error_message = str(exc)
        finally:
            job.finished_at = datetime.utcnow()
            db.session.commit()


def start_worker(app, voices_dir: Path, output_dir: Path) -> None:
    """Arranca el hilo que va tomando trabajos de la cola, uno por vez."""

    def _loop():
        while True:
            job_id = _job_queue.get()
            try:
                _process_job(app, job_id, voices_dir, output_dir)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                _job_queue.task_done()

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()


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
