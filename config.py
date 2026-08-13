"""
Configuración central de la app: variables de entorno y límites de planes.
"""

import os

# --- Básico / seguridad ---
SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esto-en-produccion")

# --- Base de datos ---
# En Render, definí DATABASE_URL apuntando a tu Postgres (Render lo genera solo
# si agregás una base de datos y la vinculás al servicio).
# En local, si no hay DATABASE_URL, se usa un SQLite en disco.
_raw_db_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")
# Render/Heroku a veces entregan "postgres://" y SQLAlchemy 2.x requiere "postgresql://"
if _raw_db_url.startswith("postgres://"):
    _raw_db_url = _raw_db_url.replace("postgres://", "postgresql://", 1)
SQLALCHEMY_DATABASE_URI = _raw_db_url

# --- URL pública de la app (para back_urls de Mercado Pago) ---
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")

# --- Mercado Pago ---
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_PUBLIC_KEY = os.environ.get("MP_PUBLIC_KEY", "")
# ID del plan de suscripción (preapproval_plan) del plan Pro.
# Se genera una sola vez con scripts/crear_plan_mercadopago.py y se pega acá.
MP_PLAN_ID = os.environ.get("MP_PLAN_ID", "")
# Secreto para validar la firma de los webhooks de Mercado Pago (recomendado).
MP_WEBHOOK_SECRET = os.environ.get("MP_WEBHOOK_SECRET", "")
MP_PRO_PRICE_ARS = os.environ.get("MP_PRO_PRICE_ARS", "9999")

# --- Motor de generación de audio (Hugging Face Space) ---
# En vez de cargar XTTS-v2 en este mismo servidor (pesa demasiada RAM para
# el plan Free de Render), la generación se delega a un Space de Hugging
# Face. Ver carpeta hf_space/ para el código de ese servidor.
HF_SPACE_URL = os.environ.get("HF_SPACE_URL", "")  # ej: https://tuusuario-estudio-de-voz.hf.space
HF_SPACE_SECRET = os.environ.get("HF_SPACE_SECRET", "")

# --- Almacenamiento de voces / audios ---
# En Render, si querés que sobrevivan a los redeploys, montá un Persistent Disk
# y apuntá esta variable a esa carpeta (por ejemplo /var/data).
DATA_DIR = os.environ.get("DATA_DIR", "")

# --- Login con Google (OAuth 2.0) ---
# Se crean en https://console.cloud.google.com/apis/credentials
# (tipo "ID de cliente de OAuth" -> Aplicación web).
# Como URI de redirección autorizado, agregá:
#   {APP_BASE_URL}/auth/google/callback
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# --- Panel de administración ---
# Emails (separados por coma) que se promueven automáticamente a admin la
# primera vez que inician sesión (por email/contraseña o con Google).
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# --- Límites por plan ---
PLAN_LIMITS = {
    "free": {
        "max_chars": 300,           # caracteres máximos por generación
        "max_voices": 1,            # voces de referencia guardadas
        "max_generations_per_day": 5,
        "max_storage_mb": 50,        # espacio total (voces + audios generados)
    },
    "pro": {
        "max_chars": 5000,
        "max_voices": 10,
        "max_generations_per_day": 100,
        "max_storage_mb": 1000,
    },
}
