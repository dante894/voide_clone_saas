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

# Los Spaces de Hugging Face esperan que el contenedor escuche en el puerto 7860
EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
