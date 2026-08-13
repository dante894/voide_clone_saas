"""
Servidor de generación de audio (XTTS-v2) para correr en un Hugging Face
Space con Docker (CPU Basic: 2 vCPU / 16 GB RAM, gratis).

Este servicio NO tiene usuarios, planes, ni base de datos — es solo un
"motor" de texto-a-voz que la app principal (en Render) llama por HTTP.
Así, la parte pesada (PyTorch + XTTS-v2) corre acá, donde sí hay RAM de
sobra, y Render se queda liviano.

Endpoint:
    POST /generate
    Headers: Authorization: Bearer <SPACE_API_SECRET>
    Form-data:
        text: str
        language: str (es, en, fr, ...)
        speaker_wav: archivo de audio (la voz de referencia)
    Devuelve: audio/wav (los bytes del audio generado) o JSON de error.

    GET /health
    Devuelve {"status": "ok", "model_loaded": true|false} — no exige el
    secreto, sirve para verificar que el Space está despierto.
"""

import os
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

API_SECRET = os.environ.get("SPACE_API_SECRET", "")

app = FastAPI(title="Estudio de Voz — motor XTTS-v2")

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            import torch
            from TTS.api import TTS

            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[hf-space] Cargando modelo XTTS-v2 en: {device} ...")
            _model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
            print("[hf-space] Modelo listo.")
        return _model


def _check_auth(authorization: str | None) -> None:
    if not API_SECRET:
        # Si no configuraste el secreto, el Space queda abierto a cualquiera
        # que tenga la URL. No recomendado, pero no bloqueamos el arranque.
        return
    expected = f"Bearer {API_SECRET}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="No autorizado")


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/generate")
async def generate(
    text: str = Form(...),
    language: str = Form(...),
    speaker_wav: UploadFile = None,
    authorization: str | None = Header(default=None),
):
    _check_auth(authorization)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Falta el texto")
    if speaker_wav is None:
        raise HTTPException(status_code=400, detail="Falta el audio de referencia (speaker_wav)")

    try:
        model = get_model()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudo cargar el modelo: {exc}") from exc

    with tempfile.TemporaryDirectory() as tmp:
        speaker_path = Path(tmp) / "speaker.wav"
        speaker_path.write_bytes(await speaker_wav.read())

        out_path = Path(tmp) / "output.wav"
        try:
            model.tts_to_file(
                text=text,
                speaker_wav=str(speaker_path),
                language=language,
                file_path=str(out_path),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Error generando el audio: {exc}") from exc

        # FileResponse necesita que el archivo siga existiendo al momento de
        # enviarse; lo copiamos fuera del TemporaryDirectory antes de que se
        # borre al salir del "with".
        final_path = Path(tempfile.gettempdir()) / f"out_{os.getpid()}_{threading.get_ident()}.wav"
        final_path.write_bytes(out_path.read_bytes())

    return FileResponse(
        final_path,
        media_type="audio/wav",
        filename="output.wav",
        background=BackgroundTask(lambda: final_path.unlink(missing_ok=True)),
    )
