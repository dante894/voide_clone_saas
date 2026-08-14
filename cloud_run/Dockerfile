FROM python:3.11-slim

WORKDIR /app

# ffmpeg y libsndfile son dependencias de audio que usa Coqui TTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Acepta la licencia no comercial de Coqui de forma no interactiva
ENV COQUI_TOS_AGREED=1

# Cloud Run inyecta el puerto real en la variable de entorno PORT (por
# defecto 8080) — NO se puede fijar un puerto fijo como en otros hosts.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT}
