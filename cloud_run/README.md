# Motor de generación de audio (XTTS-v2) — Google Cloud Run

Servicio HTTP simple para generar audio con voz clonada, pensado para que lo
llame la app principal de "Estudio de Voz" (alojada en Render) en vez de
cargar el modelo XTTS-v2 ahí (necesita demasiada RAM para el plan Free).

## Endpoints

- `GET /health` — chequeo simple, no requiere autenticación.
- `POST /generate` — genera el audio. Requiere el header
  `Authorization: Bearer <VOICE_ENGINE_SECRET>` y recibe `text`, `language`
  y `speaker_wav` (archivo) como form-data. Devuelve el audio en `.wav`.

## Cómo desplegarlo

Ver `DEPLOY.md` en la raíz del proyecto, sección 3, para la guía paso a
paso completa (crear el proyecto de Google Cloud, instalar `gcloud`, y
desplegar con un solo comando).

Resumen rápido, si ya tenés `gcloud` configurado:

```bash
cd cloud_run
gcloud run deploy estudio-de-voz-engine \
  --source . \
  --region us-central1 \
  --memory 8Gi \
  --cpu 4 \
  --timeout 600 \
  --concurrency 1 \
  --max-instances 1 \
  --min-instances 0 \
  --set-env-vars VOICE_ENGINE_SECRET=<tu-clave-secreta> \
  --allow-unauthenticated
```

`--allow-unauthenticated` deja la URL pública (pero protegida por el
secreto de `VOICE_ENGINE_SECRET`, que valida el propio código en
`app.py`) — es lo más simple para que la app de Render pueda llamarlo sin
tener que manejar credenciales de Google Cloud.
