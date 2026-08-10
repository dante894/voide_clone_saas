"""
Integración con Mercado Pago usando "Suscripciones" (preapproval), pensado
para cobros recurrentes mensuales como un plan Pro.

Se usan llamadas HTTP directas a la API REST de Mercado Pago (en vez del SDK
oficial) porque los endpoints de suscripciones están documentados de forma
estable en https://www.mercadopago.com/developers/en/reference/subscriptions
y así evitamos depender de nombres de métodos de un SDK que puede cambiar.

Flujo:
1. Una sola vez, se crea un "plan" (preapproval_plan) con precio y frecuencia
   -> scripts/crear_plan_mercadopago.py. Ese ID se guarda en MP_PLAN_ID.
2. Cuando un usuario quiere pasarse a Pro, /suscribirse crea una
   "suscripción" (preapproval) asociada a ese plan y lo redirige al
   checkout de Mercado Pago (init_point) para que cargue su tarjeta.
3. Mercado Pago le pega a /webhooks/mercadopago cada vez que cambia el
   estado de la suscripción. Ahí volvemos a consultar la API (nunca
   confiamos en el cuerpo del webhook a ciegas) y actualizamos el plan.
"""

import requests
from flask import Blueprint, current_app, jsonify, render_template, request, url_for
from flask_login import current_user, login_required

import config
from models import User, db

billing_bp = Blueprint("billing", __name__)

MP_API_BASE = "https://api.mercadopago.com"


def _headers() -> dict:
    if not config.MP_ACCESS_TOKEN:
        raise RuntimeError("Falta configurar MP_ACCESS_TOKEN en las variables de entorno.")
    return {
        "Authorization": f"Bearer {config.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


@billing_bp.route("/planes")
def planes():
    return render_template(
        "planes.html",
        limits=config.PLAN_LIMITS,
        price=config.MP_PRO_PRICE_ARS,
    )


@billing_bp.route("/suscribirse", methods=["POST"])
@login_required
def suscribirse():
    if not config.MP_PLAN_ID:
        return jsonify({"error": "Todavía no se configuró el plan de Mercado Pago (MP_PLAN_ID)."}), 500

    body = {
        "preapproval_plan_id": config.MP_PLAN_ID,
        "reason": "Estudio de Voz — Plan Pro (mensual)",
        "external_reference": str(current_user.id),
        "payer_email": current_user.email,
        "back_url": f"{config.APP_BASE_URL}{url_for('billing.suscripcion_resultado')}",
    }

    try:
        resp = requests.post(f"{MP_API_BASE}/preapproval", json=body, headers=_headers(), timeout=15)
    except requests.RequestException:
        current_app.logger.exception("Error de red creando preapproval en Mercado Pago")
        return jsonify({"error": "No se pudo contactar a Mercado Pago. Probá de nuevo en un rato."}), 502

    data = resp.json() if resp.content else {}
    if resp.status_code not in (200, 201):
        current_app.logger.error("Error creando preapproval MP (%s): %s", resp.status_code, data)
        return jsonify({"error": "No se pudo iniciar la suscripción con Mercado Pago."}), 502

    # Guardamos el ID para relacionarlo cuando llegue el webhook; el estado
    # real siempre se confirma releyendo la API, no lo que llega acá.
    current_user.mp_preapproval_id = data.get("id")
    current_user.mp_status = data.get("status", "pending")
    db.session.commit()

    init_point = data.get("init_point")
    if not init_point:
        return jsonify({"error": "Mercado Pago no devolvió el link de pago."}), 502

    return jsonify({"init_point": init_point})


@billing_bp.route("/suscripcion/resultado")
@login_required
def suscripcion_resultado():
    return render_template("suscripcion_resultado.html")


@billing_bp.route("/cancelar-suscripcion", methods=["POST"])
@login_required
def cancelar_suscripcion():
    if not current_user.mp_preapproval_id:
        return jsonify({"error": "No tenés una suscripción activa."}), 400

    try:
        resp = requests.put(
            f"{MP_API_BASE}/preapproval/{current_user.mp_preapproval_id}",
            json={"status": "cancelled"},
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException:
        current_app.logger.exception("Error de red cancelando preapproval en Mercado Pago")
        return jsonify({"error": "No se pudo contactar a Mercado Pago. Probá de nuevo en un rato."}), 502

    if resp.status_code not in (200, 201):
        return jsonify({"error": "No se pudo cancelar la suscripción en Mercado Pago."}), 502

    current_user.mp_status = "cancelled"
    current_user.plan = "free"
    db.session.commit()
    return jsonify({"ok": True})


def _get_preapproval(preapproval_id: str):
    try:
        resp = requests.get(
            f"{MP_API_BASE}/preapproval/{preapproval_id}", headers=_headers(), timeout=15
        )
    except requests.RequestException:
        current_app.logger.exception("Error de red consultando preapproval en Mercado Pago")
        return None
    if resp.status_code != 200:
        current_app.logger.error("No se pudo leer preapproval %s: %s", preapproval_id, resp.text)
        return None
    return resp.json()


def _sync_user_from_preapproval(preapproval: dict) -> None:
    """Actualiza el plan de un usuario según el estado real en Mercado Pago."""
    preapproval_id = preapproval.get("id")
    external_reference = preapproval.get("external_reference")

    user = None
    if external_reference:
        try:
            user = User.query.get(int(external_reference))
        except (TypeError, ValueError):
            user = None
    if user is None and preapproval_id:
        user = User.query.filter_by(mp_preapproval_id=preapproval_id).first()
    if user is None:
        current_app.logger.warning("Webhook MP: no se encontró usuario para preapproval %s", preapproval_id)
        return

    status = preapproval.get("status")  # authorized | paused | cancelled | pending
    user.mp_preapproval_id = preapproval_id
    user.mp_status = status
    user.plan = "pro" if status == "authorized" else "free"
    db.session.commit()


@billing_bp.route("/webhooks/mercadopago", methods=["POST"])
def webhook_mercadopago():
    """Mercado Pago manda notificaciones tipo:
    { "type": "preapproval", "data": { "id": "..." } }
    o vía query params ?type=preapproval&data.id=...
    Ante cualquier notificación, volvemos a consultar el recurso en la API
    (nunca confiamos en el cuerpo del webhook a ciegas) y sincronizamos.
    """
    payload = request.get_json(silent=True) or {}
    notif_type = payload.get("type") or request.args.get("type")
    data_id = (payload.get("data") or {}).get("id") or request.args.get("data.id")

    if not notif_type or not data_id:
        return jsonify({"ok": True})  # nada que procesar, respondemos 200 igual

    relevant_types = (
        "preapproval",
        "subscription_preapproval",
        "subscription_authorized_payment",
        "authorized_payment",
    )
    try:
        if notif_type in relevant_types:
            preapproval = _get_preapproval(data_id)
            if preapproval:
                _sync_user_from_preapproval(preapproval)
        # Otros tipos (payment, point_integration_wh, etc.) se ignoran acá.
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Error procesando webhook de Mercado Pago")

    # Mercado Pago espera 200/201 para no reintentar indefinidamente.
    return jsonify({"ok": True})
