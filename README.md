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

Para desplegarlo en Render con cobros por Mercado Pago, seguí **`DEPLOY.md`**
— tiene la guía completa paso a paso.

---

## Estructura del proyecto

```
app.py               # App Flask principal (rutas, sesión, lógica de límites)
config.py            # Variables de entorno y límites de cada plan
models.py            # Modelos de base de datos (User, Voice, Job)
auth.py              # Registro / login / logout
billing.py           # Integración con Mercado Pago (suscripciones + webhook)
worker.py            # Cola de generación de audio en segundo plano
templates/           # HTML (index, login, registro, planes, cuenta)
static/style.css      # Estilos compartidos
scripts/
  crear_plan_mercadopago.py   # Se corre UNA vez para crear el plan Pro en MP
render.yaml           # Blueprint de despliegue en Render
Procfile               # Alternativa manual (sin Blueprint)
.env.example           # Variables de entorno de ejemplo
DEPLOY.md               # Guía de despliegue completa
```

---

## Correr en local

Requisitos: Python 3.10, 3.11 o 3.12. No hace falta GPU (funciona en CPU,
aunque generar audios largos puede tardar uno o varios minutos por frase).

```bash
python -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Editá .env: como mínimo poné un SECRET_KEY propio.
# Si todavía no tenés MP_PLAN_ID, el botón "Pasarme a Pro" va a mostrar un
# error hasta que lo configures (ver más abajo), pero el resto de la app
# funciona igual.
export $(cat .env | xargs)      # o usá python-dotenv si preferís
python app.py
```

Abrí `http://127.0.0.1:5000`. Te va a pedir crear una cuenta (`/registro`).
Sin `DATABASE_URL` configurado, se usa un SQLite local (`local.db`) que se
crea solo la primera vez.

**La primera vez que generes un audio**, se descarga el modelo XTTS-v2
(~1.8 GB), así que necesitás conexión a internet esa primera vez. Después
queda en caché y funciona sin descargar de nuevo.

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
   estado ("en cola" → "generando" → "listo") y te deja escuchar y
   descargar el resultado en `.wav` cuando termina.

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
