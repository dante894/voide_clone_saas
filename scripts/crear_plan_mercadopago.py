"""
Ejecutá esto UNA SOLA VEZ para crear el "plan" de suscripción en Mercado Pago
(el molde que define precio y frecuencia). El ID que te devuelve se pega en
la variable de entorno MP_PLAN_ID en Render.

Uso:
    export MP_ACCESS_TOKEN="APP_USR-..."     (tu access token de PRODUCCIÓN)
    export APP_BASE_URL="https://tu-app.onrender.com"
    export MP_PRO_PRICE_ARS="9999"           (precio mensual en pesos)
    python scripts/crear_plan_mercadopago.py

Referencia del endpoint:
https://www.mercadopago.com/developers/en/reference/subscriptions/_preapproval_plan/post
"""

import os
import sys

import requests

ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000")
PRICE = float(os.environ.get("MP_PRO_PRICE_ARS", "9999"))

if not ACCESS_TOKEN:
    print("Falta MP_ACCESS_TOKEN en el entorno.")
    sys.exit(1)

plan_data = {
    "reason": "Estudio de Voz — Plan Pro",
    "auto_recurring": {
        "frequency": 1,
        "frequency_type": "months",
        "transaction_amount": PRICE,
        "currency_id": "ARS",
    },
    "back_url": BASE_URL,
}

resp = requests.post(
    "https://api.mercadopago.com/preapproval_plan",
    json=plan_data,
    headers={
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    },
    timeout=15,
)

data = resp.json() if resp.content else {}

if resp.status_code not in (200, 201):
    print(f"Error creando el plan (HTTP {resp.status_code}):", data)
    sys.exit(1)

print("Plan creado correctamente.")
print("MP_PLAN_ID =", data.get("id"))
print("\nCopiá ese valor y pegalo como variable de entorno MP_PLAN_ID en Render.")
