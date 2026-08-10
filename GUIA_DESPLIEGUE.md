# Guía paso a paso — Poner la app en internet (gratis, con Render + Neon)

No necesitas saber programar para seguir esto. Son clics en páginas web.
Tómate tu tiempo, un paso a la vez.

## Por qué dos servicios distintos

- **Render** hospeda la aplicación (gratis, sin tarjeta de crédito). Único detalle:
  si nadie usa la app por 15 minutos, "se duerme", y la primera visita después tarda
  unos 30-60 segundos en responder. Para tu caso (uso personal, no una web pública
  con visitas constantes) esto no es un problema real.
- **Neon** hospeda la base de datos PostgreSQL, con una capa gratuita que **no expira
  nunca** (a diferencia de la base de datos gratis de Render, que se borra a los 90 días).

## Paso 1 — Crear una cuenta en GitHub (donde vivirá tu código)

1. Entra a https://github.com y crea una cuenta gratis (si no tienes una).
2. Arriba a la derecha, haz clic en **"+"** → **"New repository"**.
3. Nómbralo `siga-onevision-app`, márcalo como **Private**, clic en **"Create repository"**.

## Paso 2 — Subir el código a GitHub (sin usar la terminal)

1. En la página de tu repositorio recién creado, busca el enlace **"uploading an existing file"**.
2. Descomprime en tu computadora el archivo `.zip` que te compartí.
3. Arrastra **todos los archivos y carpetas** a esa página de GitHub.
4. Escribe "Primera versión" en "Commit changes" y confirma.

## Paso 3 — Crear tu base de datos gratis en Neon

1. Entra a https://neon.com y crea una cuenta gratis (puedes usar tu cuenta de GitHub).
2. Crea un nuevo proyecto (te va a pedir un nombre — puedes poner `siga-onevision`).
3. Neon te muestra un **Connection string** parecido a:
   `postgresql://usuario:clave@ep-xxxx.neon.tech/neondb?sslmode=require`
4. **Cópialo y guárdalo** — lo vas a necesitar en el Paso 5. (Puedes volver a verlo
   cuando quieras desde el dashboard de Neon, en "Connection Details".)

## Paso 4 — Crear tu app en Render

1. Entra a https://render.com y crea una cuenta gratis (puedes usar tu cuenta de GitHub).
2. Haz clic en **"New"** → **"Web Service"**.
3. Conecta tu cuenta de GitHub y elige el repositorio `siga-onevision-app`.
4. En la configuración:
   - **Name:** `siga-onevision-app` (o el nombre que quieras)
   - **Region:** la más cercana a Perú (Oregon, US West, suele ser la más rápida)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** **Free**
5. Todavía no le des "Create" — antes bajemos a configurar las variables (paso 5).

## Paso 5 — Configurar tus variables de entorno

En la misma pantalla de creación (sección "Environment Variables"), agrega:

| Variable | Valor |
|---|---|
| `DATABASE_URL` | El connection string que copiaste de Neon en el Paso 3 |
| `APP_USERNAME` | El usuario con el que vas a entrar (ej. `admin`) |
| `APP_PASSWORD` | Una contraseña que solo tú conozcas |
| `SECRET_KEY` | Cualquier texto largo y random (ej. escribe cualquier cosa de 40 caracteres) |
| `EJECUTORA` | `785` |
| `ANIO_INVENTARIO` | `2026` |

Ahora sí, haz clic en **"Create Web Service"**. Render va a instalar todo y arrancar
la app — la primera vez tarda unos minutos.

## Paso 6 — Entrar a tu app

1. Cuando el deploy termine (estado "Live"), Render te muestra tu link, algo como
   `https://siga-onevision-app.onrender.com`.
2. Entra a ese link — deberías ver la pantalla de **login**. Usa el usuario y
   contraseña que configuraste en el Paso 5.

¡Listo! Ya tienes la app funcionando en internet, gratis.

## Paso 7 — Primeros pasos dentro de la app

1. Ve a **Maestros** y sube tus archivos `CENTROS_DE_COSTO.xlsx` y `usuarios_responsable.xlsx`
   para cargar los maestros iniciales.
2. Ve a **Pecosas** y registra las pecosas que te lleguen (con su expediente).
3. Ve a **Normalización**, sube el reporte de SIGA y elige las pecosas del lote.
4. Corrige manualmente cualquier bien que no haya cruzado bien (te lo marca en amarillo).
5. Genera el archivo `.xls` y súbelo tú mismo a One Visión (eso sigue siendo manual,
   porque One Visión no tiene una forma automática de recibir datos).
6. Descarga el reporte de QR de One Visión y súbelo en **Impresión QR**, eligiendo el lote
   correspondiente — te devuelve el archivo listo para BarTender y para imprimir en físico.

## Paso 8 (opcional, más adelante) — Conectar BarTender directo a la base de datos

Documentado en `sql/vista_bartender.sql`. Con Neon, la conexión ODBC funciona igual
que con cualquier Postgres — solo asegúrate de incluir `sslmode=require` en la
configuración del driver, porque Neon exige conexión cifrada.

---

## Si algo no funciona

- Si la página no carga o tarda mucho: es normal si nadie la usó en un rato (Render
  "duerme" la app gratis); espera 30-60 segundos y recarga.
- Si dice "usuario o contraseña incorrectos": revisa que `APP_USERNAME` y `APP_PASSWORD`
  en Render sean exactamente lo que estás escribiendo.
- Si el deploy falla: en Render, entra a la pestaña **"Logs"** de tu servicio — ahí
  sale el error en texto. Cópiamelo y seguimos revisando juntos.
- Cualquier error, cópiame el mensaje que te sale y seguimos desde ahí.
