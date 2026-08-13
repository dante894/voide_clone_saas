---
title: Estudio de Voz - Motor XTTS-v2
emoji: 🎙️
colorFrom: orange
colorTo: red
sdk: docker
app_port: 7860
---

# Motor de generación de audio (XTTS-v2)

Este Space expone un endpoint HTTP simple para generar audio con voz
clonada, pensado para que lo llame la app principal de "Estudio de Voz"
(alojada en Render) en vez de cargar el modelo ahí.

## Endpoints

- `GET /health` — chequeo simple, no requiere autenticación.
- `POST /generate` — genera el audio. Requiere el header
  `Authorization: Bearer <SPACE_API_SECRET>` (configurado como "Secret" en
  la configuración de este Space) y recibe `text`, `language` y
  `speaker_wav` (archivo) como form-data. Devuelve el audio en `.wav`.

## Configuración necesaria

En la pestaña **Settings → Variables and secrets** de este Space, agregá un
secreto:

```
SPACE_API_SECRET = <una clave larga y random que vos elijas>
```

Usá el mismo valor en la variable de entorno `HF_SPACE_SECRET` de la app
principal en Render.

## Nota sobre "dormirse"

En el plan gratis, este Space se pausa después de un tiempo sin uso y tarda
unos segundos en volver a levantar (y a cargar el modelo) en la primera
petición después de la pausa. Es normal — no es un error.
