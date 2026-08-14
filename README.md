# Estudio de Voz — SaaS de texto a voz con clonación de voz

Convierte texto en audio usando una voz clonada a partir de una muestra de
audio (modelo **XTTS-v2** de Coqui, español + 16 idiomas más). Esta versión
es multiusuario, pensada para desplegarse en Render con:

- **Plan Free**: 300 caracteres por audio, 1 voz guardada, 5 audios por día.
- **Plan Pro** (pago mensual vía Mercado Pago): 5000 caracteres por audio,
  10 voces guardadas, 100 audios por día.
- **Login con Google** (opcional) además de email/contraseña.
- **Panel de administración** (`/admin`) con estadísticas de usuarios,
  logins por proveedor y visitas al sitio.

> ⚠️ **Importante**: usá esto solo con voces de personas que te hayan dado
> su permiso (o tu propia voz). Generar audio con la voz de alguien sin su
> consentimiento puede ser ilegal y, en cualquier caso, es una mala idea.

La generación de audio (XTTS-v2) corre en un **servicio aparte en Google
Cloud Run** (gratis dentro de la cuota mensual), no en Render — así la app
web puede vivir en el plan Free de Render sin problemas de memoria. Ver
`DEPLOY.md`, sección 3, para configurarlo.

Para desplegarlo en Render con cobros por Mercado Pago, seguí **`DEPLOY.md`**
— tiene la guía completa paso a paso.

---

## Estructura del proyecto

```
app.py               # App Flask principal (rutas, sesión, lógica de límites)
config.py            # Variables de entorno y límites de cada plan
models.py            # Modelos de base de datos (User, Voice, Job)
auth.py              # Registro / login / logout / login con Google
billing.py           # Integración con Mercado Pago (suscripciones + webhook)
worker.py            # Cola de generación: le pide el audio al servicio de Cloud Run
admin.py              # Panel de administración (/admin)
templates/           # HTML (index, login, registro, planes, cuenta, admin)
static/style.css      # Estilos compartidos
cloud_run/              # Código para el servicio de Cloud Run (motor XTTS-v2)
  app.py                # Servidor FastAPI con el endpoint /generate
  Dockerfile
  requirements.txt
  README.md
scripts/
  crear_plan_mercadopago.py   # Se corre UNA vez para crear el plan Pro en MP
  migrate_db.py                # Migración liviana para bases ya desplegadas
render.yaml           # Blueprint de despliegue en Render
Procfile               # Alternativa manual (sin Blueprint)
.env.example           # Variables de entorno de ejemplo
DEPLOY.md               # Guía de despliegue completa
```

---

## Correr en local

Requisitos: Python 3.10, 3.11 o 3.12. Esta app YA NO corre el modelo
XTTS-v2 localmente — se lo pide por HTTP al servicio de Cloud Run (ver
`cloud_run/`), así que no hace falta instalar PyTorch para levantar la app
principal.

```bash
python -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Editá .env: como mínimo poné un SECRET_KEY propio.
# Si todavía no tenés VOICE_ENGINE_URL/VOICE_ENGINE_SECRET, la generación de audio
# va a fallar con un error claro hasta que configures el Space (ver
# DEPLOY.md sección 3), pero el resto de la app funciona igual.
# Si todavía no tenés MP_PLAN_ID, el botón "Pasarme a Pro" va a mostrar un
# error hasta que lo configures (ver más abajo), pero el resto de la app
# funciona igual.
export $(cat .env | xargs)      # o usá python-dotenv si preferís
python app.py
```

Abrí `http://127.0.0.1:5000`. Te va a pedir crear una cuenta (`/registro`).
Sin `DATABASE_URL` configurado, se usa un SQLite local (`local.db`) que se
crea solo la primera vez.

---

## Habilitar los pagos de Mercado Pago en local (opcional)

1. Corré `scripts/crear_plan_mercadopago.py` una vez (ver `DEPLOY.md`,
   sección 2) para obtener `MP_PLAN_ID`.
2. Completá `MP_ACCESS_TOKEN`, `MP_PUBLIC_KEY` y `MP_PLAN_ID` en tu `.env`.
3. Para que el webhook te llegue en local necesitás exponer tu servidor a
   internet (por ejemplo con `ngrok`) y cargar esa URL pública + `/webhooks/mercadopago`
   en el panel de Mercado Pago.

En producción (Render) esto ya viene resuelto en `DEPLOY.md`.

---

## Cómo usar la app (una vez logueado)

1. **Voces de referencia**: grabá (pide permiso de micrófono) o subí un
   archivo de audio de 10–15 segundos o más, con una sola persona hablando,
   sin música ni ruido de fondo. Dale un nombre y guardala.
2. **Guion**: escribí el texto (respetando el límite de caracteres de tu
   plan) y elegí el idioma.
3. **Generar audio**: se encola el trabajo; la página va mostrando el
   estado ("en cola" → "generando" → "listo") y te deja escuchar el
   resultado. **Al tocar "Descargar", el archivo se borra del servidor** en
   cuanto termina de bajarse a tu dispositivo — no queda guardado ahí, así
   que asegurate de guardarlo bien en tu computadora/teléfono antes de
   cerrar la página (no se puede volver a descargar después).

---

## Consejos para mejores resultados

- Usá audio limpio: sin música, eco ni varias personas hablando a la vez.
- 15–30 segundos de muestra suelen dar mejores resultados que 5 segundos.
- Frases muy largas pueden tardar más; si el resultado suena raro al final,
  probá generar el texto en partes más cortas.

---

## Dónde se guarda todo

- Con `DATA_DIR` configurado (recomendado en Render, con disco persistente):
  las voces, audios generados y la caché del modelo se guardan ahí y
  sobreviven a los redeploys.
- Sin `DATA_DIR`: se guardan junto al código (`voices/`, `outputs/`), lo cual
  está bien para correr en local pero se pierde en cada redeploy si lo usás
  así en un hosting con filesystem efímero.
- Los datos de usuarios y suscripciones viven en la base de datos
  (`DATABASE_URL`), no en archivos.
