"""
Generación de audio: le pide el trabajo por HTTP a un servicio externo
(ver carpeta cloud_run/, pensado para Google Cloud Run o para correr en tu
propia PC) que tiene la RAM necesaria para cargar XTTS-v2. Esto le permite a
la app principal (en Render) quedarse liviana, sin cargar PyTorch ni el
modelo en este proceso.

IMPORTANTE — por qué no hay un hilo de fondo:
Al principio esto usaba un hilo en segundo plano (threading.Thread) para
procesar los trabajos sin bloquear las peticiones HTTP. En el plan Free de
Render, ese hilo no llegaba a ejecutarse nunca (se creaba, pero su código
interno jamás corría — algo específico de ese entorno que no vale la pena
perseguir más). En cambio, ahora el trabajo se procesa de forma síncrona,
como efecto colateral de la propia consulta de estado que el navegador ya
hace cada 3 segundos (`GET /api/jobs/<id>`). La primera consulta después de
generar simplemente tarda varios minutos en responder (mientras se genera
el audio), en vez de responder rápido con "en cola". Es menos elegante,
pero funciona de forma confiable en cualquier hosting, sin depender de que
los hilos en segundo plano funcionen bien.
"""

import traceback
import uuid
from datetime import datetime
from pathlib import Path

import requests

import config

# Generar un audio puede tardar varios minutos si el servicio estaba
# "dormido" (Cloud Run con min-instances=0, o si tu PC recién arrancó el
# motor) además del tiempo de inferencia en sí.
GENERATE_TIMEOUT_SECONDS = 600


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


def process_job_sync(job, voices_dir: Path, output_dir: Path) -> None:
    """Procesa un trabajo de punta a punta, EN el mismo request que lo llama
    (bloqueante). Se supone que ya hay un contexto de aplicación/DB activo
    (se llama desde dentro de una vista de Flask), así que no abre uno
    nuevo. Deja al `job` en estado 'done' o 'error' antes de retornar, y
    guarda los cambios en la base."""
    from models import db

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
