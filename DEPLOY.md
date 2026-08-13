# Desplegar Estudio de Voz en Render con planes Free / Pro (Mercado Pago)

Esta guía asume que ya tenés cuenta en Render y credenciales de Mercado Pago
de **producción** (Access Token y Public Key), como indicaste.

---

## 0. Qué cambió respecto a la versión local

La app original corría sola en tu PC, sin usuarios. Esta versión agrega:

- Cuentas de usuario (`/registro`, `/login`).
- Un plan **Free** y un plan **Pro** (pago mensual, vía suscripción de
  Mercado Pago), con límites distintos definidos en `config.py`:

  | | Free | Pro |
  |---|---|---|
  | Caracteres por audio | 300 | 5000 |
  | Voces guardadas | 1 | 10 |
  | Audios por día | 5 | 100 |

  Cambiá estos números en `config.py` (`PLAN_LIMITS`) cuando quieras.

- La generación de audio ahora corre **en segundo plano** (una cola simple
  con un solo "worker"), porque en un servidor sin GPU, XTTS-v2 puede tardar
  1–3 minutos por frase, y una petición HTTP normal no puede esperar tanto
  sin cortarse.

---

## 1. Preparar el repositorio

1. Subí esta carpeta a un repositorio de GitHub (Render despliega desde Git).
2. Revisá `config.py` si querés ajustar los límites de cada plan.

---

## 2. Crear el plan de suscripción en Mercado Pago (una sola vez)

Mercado Pago necesita un "plan" (molde con precio y frecuencia) antes de
poder suscribir usuarios.

```bash
pip install requests
export MP_ACCESS_TOKEN="APP_USR-tu-access-token-de-produccion"
export APP_BASE_URL="https://TU-APP.onrender.com"   # podés ponerlo provisorio y corregirlo después
export MP_PRO_PRICE_ARS="9999"                       # precio mensual del plan Pro
python scripts/crear_plan_mercadopago.py
```

Va a imprimir algo como:

```
MP_PLAN_ID = 2c938084726fca480172750000000000
```

Guardá ese valor, lo vas a necesitar en el paso 4.

---

## 3. Motor de generación de audio en Hugging Face (recomendado, gratis)

XTTS-v2 necesita varios GB de RAM para cargarse — más de lo que da el plan
Free de Render. En vez de pagar un plan más caro, se puede correr el modelo
en un Hugging Face Space gratuito (2 vCPU / 16 GB RAM) y que la app en
Render le pida el audio por HTTP. El código de ese Space ya está armado en
la carpeta `hf_space/` de este proyecto.

1. Creá una cuenta en [huggingface.co](https://huggingface.co) si no tenés.
2. Andá a **New Space** (huggingface.co/new-space). Nombre: por ejemplo
   `estudio-de-voz`. **SDK: Docker**. Visibilidad: Public o Private (con
   Private necesitás un token para el health check, con Public alcanza con
   el secreto del endpoint `/generate`). Hardware: CPU Basic (gratis).
3. Subí el contenido de la carpeta `hf_space/` (Dockerfile, app.py,
   requirements.txt, README.md) a la raíz del repositorio del Space —
   podés arrastrarlos desde la interfaz web de Hugging Face, o clonar el
   repo del Space con git y hacer push:
   ```bash
   git clone https://huggingface.co/spaces/TU-USUARIO/estudio-de-voz
   cp hf_space/* estudio-de-voz/
   cd estudio-de-voz
   git add . && git commit -m "Motor de generación" && git push
   ```
4. En el Space → **Settings → Variables and secrets**, agregá un secreto:
   ```
   SPACE_API_SECRET = <una clave larga y random que vos elijas>
   ```
5. Esperá a que el Space termine de construir (el ícono pasa a verde
   "Running"). Entrá a `https://TU-USUARIO-estudio-de-voz.hf.space/health`
   y confirmá que responda `{"status":"ok",...}`.
6. En Render, agregá estas variables de entorno al servicio web:
   ```
   HF_SPACE_URL=https://TU-USUARIO-estudio-de-voz.hf.space
   HF_SPACE_SECRET=<la misma clave que pusiste en el paso 4>
   ```
7. Con esto, el servicio web de Render puede quedarse en el plan **Free**
   sin problema — ya no carga PyTorch ni el modelo, solo le pide el audio
   al Space.

**Nota sobre la primera generación después de inactividad**: en el plan
gratis, el Space se pausa tras un tiempo sin uso y tarda unos segundos (o
más, la primera vez que carga el modelo) en despertar. Es esperable, no un
error — el trabajo va a decir "en cola" un poco más esa primera vez.

## 4. Crear el servicio en Render (Blueprint)

1. En el dashboard de Render: **New → Blueprint**.
2. Conectá el repositorio. Render va a detectar `render.yaml` y proponer:
   - Un **Web Service** (`estudio-de-voz`) en plan **Free** — alcanza de
     sobra porque el modelo XTTS-v2 ya NO corre acá (corre en el Hugging
     Face Space del paso anterior).
   - Una base de datos **Postgres** (`estudio-de-voz-db`).
3. Cuando te pida las variables marcadas `sync: false`, cargá:
   - `MP_ACCESS_TOKEN`, `MP_PUBLIC_KEY`, `MP_PLAN_ID` (el que obtuviste en
     el paso 2)
   - `HF_SPACE_URL` y `HF_SPACE_SECRET` (los del paso 3)
4. Confirmá la creación. El primer deploy debería ser rápido — ya no
   instala PyTorch acá.

> ⚠️ No cambies el número de instancias a más de 1. La cola de generación
> vive en memoria dentro de un solo proceso; con más instancias, cada una
> tendría su propia cola y el comportamiento sería inconsistente.

> 💡 Sin disco persistente, las voces guardadas se pierden en cada
> redeploy (aceptable mientras estás probando). Si más adelante querés que
> sobrevivan, subí este servicio a un plan pago (Starter o superior) y
> agregá un disco en `/var/data` con `DATA_DIR=/var/data` — no hace falta
> volver a subir a Standard, con Starter alcanza porque el modelo no corre
> acá.

### Si preferís crearlo a mano en vez de con Blueprint

Creá un Web Service normal apuntando a este repo, con:
- Runtime: Python 3 (no Docker)
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 4 --timeout 300 --bind 0.0.0.0:$PORT`
- Las variables de entorno de `.env.example`.
- Agregá una base de datos Postgres y copiá su "Internal Connection String"
  en `DATABASE_URL`.

---

## 5. Actualizar `APP_BASE_URL` con la URL real

Una vez que Render te asigna la URL definitiva (por ejemplo
`https://estudio-de-voz.onrender.com`), actualizá la variable de entorno
`APP_BASE_URL` en el Dashboard de Render con esa URL exacta (se usa para
armar el link de retorno de Mercado Pago).

---

## 6. Configurar el webhook de Mercado Pago

En el [panel de Mercado Pago](https://www.mercadopago.com/developers/panel) →
tu aplicación → **Webhooks**, agregá esta URL:

```
https://TU-APP.onrender.com/webhooks/mercadopago
```

Suscribí (como mínimo) el evento **preapproval** (suscripciones). Así, cada
vez que un pago mensual se acredita o alguien cancela, tu app se entera y
activa/desactiva el plan Pro automáticamente — sin que dependa de que el
usuario vuelva a tu sitio.

---

## 7. Probar el flujo completo

1. Entrá a tu app → `/registro` → creá una cuenta.
2. Andá a `/planes` → "Pasarme a Pro con Mercado Pago" → te redirige al
   checkout de Mercado Pago.
3. Completá el pago (en producción, con una tarjeta real; Mercado Pago no
   tiene "modo sandbox" para suscripciones tan simple como para pagos
   sueltos — si querés probar sin cobrar de verdad, se recomienda armar
   usuarios de prueba desde el panel de Mercado Pago antes de ir a
   producción).
4. Mercado Pago te redirige de vuelta y, en paralelo, manda el webhook.
   Recargá `/cuenta` en unos segundos: debería decir **PRO**.

---

## 8. Login con Google (opcional)

1. En la [consola de Google Cloud](https://console.cloud.google.com/apis/credentials),
   creá credenciales tipo **"ID de cliente de OAuth"** → Aplicación web.
2. En "URI de redirección autorizados" agregá:
   `https://TU-APP.onrender.com/auth/google/callback`
3. Copiá el **Client ID** y **Client Secret** a las variables de entorno
   `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` en Render.
4. Listo — en `/login` y `/registro` va a aparecer automáticamente el botón
   "Continuar con Google". Si dejás esas variables vacías, el botón
   simplemente no se muestra y el login por email/contraseña sigue
   funcionando igual.

Si un email ya tenía cuenta creada con contraseña y esa persona después
entra con Google usando el mismo email, la app une ambas cuentas (no crea
una duplicada).

## 9. Panel de administración

1. Definí la variable de entorno `ADMIN_EMAILS` en Render con tu email (o
   varios, separados por coma): `ADMIN_EMAILS=vos@tuemail.com`.
2. Iniciá sesión (o registrate) con ese email — se te promueve a admin
   automáticamente en cuanto entrás.
3. Entrá a `https://TU-APP.onrender.com/admin` para ver:
   - Usuarios totales, suscripciones Pro activas, y el desglose Google vs
     email/contraseña.
   - Registros, logins (por proveedor) y visitas al sitio, día por día.
   - Las páginas más visitadas y las últimas cuentas/logins.
   Cualquier persona que no sea admin recibe un 404 al entrar ahí (no se
   revela que existe el panel).

> Si ya tenías la app desplegada ANTES de agregar login con Google/admin,
> corré una vez `python scripts/migrate_db.py` (con la misma `DATABASE_URL`
> de producción) para agregar las columnas nuevas a la tabla de usuarios sin
> perder los datos existentes. Las tablas nuevas (`login_events`,
> `page_views`) las crea solo `db.create_all()` al arrancar la app.

## 10. Costos a tener en cuenta

- Con este esquema (Render Free + Hugging Face Space CPU Basic), **la app
  no tiene costo fijo mensual**. Vas a pagar solo si más adelante subís
  Render a un plan pago (para tener disco persistente) o si el Space
  necesita más recursos que el free tier de Hugging Face.
- El Space de Hugging Face gratis se pausa tras un tiempo sin uso — la
  primera generación después de una pausa tarda más (tiene que despertar y
  cargar el modelo de nuevo).
- Mercado Pago cobra una comisión por transacción sobre cada cobro de la
  suscripción (revisá el porcentaje vigente en tu panel).
- Generar audio con XTTS-v2 en CPU sigue siendo lento (minutos por frase,
  sin GPU). Si el volumen crece mucho, vas a necesitar un Space con GPU de
  pago en Hugging Face, o mover la inferencia a un servicio de GPU por uso
  (Replicate, Modal).

---

## 11. Recordatorio de uso responsable

El README original ya lo advertía y sigue aplicando: usá esto solo con voces
de personas que dieron su consentimiento, o con tu propia voz. Como ahora es
un servicio con usuarios, es buena idea agregar términos de uso que dejen
esto explícito y responsabilicen a cada usuario por el contenido que genera.
