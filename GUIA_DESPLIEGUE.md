# Publicación de SIGA One Visión con Render y Neon

Esta guía usa la base local ya preparada, por lo que no tendrás que repetir
la carga inicial ni los registros existentes.

## Antes de comenzar

- La copia de seguridad ya fue creada en la carpeta `backups` de esta computadora.
- La copia y la base local están bloqueadas para que GitHub nunca las publique.
- Solo usa archivos `.xlsx` al importar reportes de Verificación en producción.
- Mantendremos dos espacios separados: esta app local para probar cambios y la
  app en Render para el trabajo real. Un cambio local no llega a producción hasta
  que se publique manualmente.

## Paso 1. Crear el proyecto de Neon

1. Entra a [Neon](https://console.neon.tech/).
2. Pulsa **New Project**.
3. Coloca el nombre `siga-onevision-produccion`.
4. Elige el proveedor y región que Neon te ofrezca más cercanos a la región de
   Render. Render se configurará en Oregon.
5. Deja el nombre de la base que Neon propone por defecto, salvo que quieras usar
   `siga_onevision`.
6. Pulsa **Create Project**.
7. En el proyecto creado pulsa **Connect** y elige **Connection string**.
8. No pegues la cadena de conexión en GitHub ni la envíes por correo. Déjala abierta
   en Neon y avísame cuando el proyecto esté listo. La usaremos una sola vez para
   copiar la base protegida.

## Paso 2. Copiar los datos a Neon

Este paso lo haré yo desde esta computadora cuando tengas el proyecto de Neon listo.
La herramienta preparada para ello:

- crea las tablas necesarias;
- se detiene si encuentra datos previos en Neon, para evitar duplicados;
- compara la cantidad de registros de cada tabla al terminar;
- nunca modifica la base SQLite local ni la copia de seguridad.

Al finalizar revisaremos juntos que existan, como mínimo, los maestros, 382 pecosas,
22 lotes y 582 bienes que contiene la copia preparada hoy.

## Paso 3. Crear el servicio en Render

Haz este paso después de que confirmemos la copia a Neon.

1. Entra a [Render](https://dashboard.render.com/).
2. Pulsa **New** y luego **Blueprint**.
3. Conecta GitHub si Render te lo solicita y elige el repositorio
   `intkvn/siga-onevision-app2`.
4. Render detectará el archivo `render.yaml` que ya está preparado en el repositorio.
5. Verifica estos datos antes de crear:
   - Servicio: `siga-onevision-app`.
   - Tipo: **Web Service**.
   - Entorno: **Python**.
   - Región: **Oregon**.
   - Plan: **Free**.
6. Render te pedirá valores secretos. Completa:

| Variable | Valor |
| --- | --- |
| `DATABASE_URL` | La cadena de conexión de Neon del Paso 1. |
| `APP_USERNAME` | Tu usuario de ingreso. |
| `APP_PASSWORD` | Tu contraseña de ingreso. |

`SECRET_KEY` se genera automáticamente. `EJECUTORA`, `ANIO_INVENTARIO` y la versión
de Python ya vienen definidos en la configuración.

7. Pulsa **Apply** o **Create Blueprint**.
8. Espera a que el despliegue termine con estado **Live**.
9. Abre la dirección que Render muestra y agrega `/health` al final. Debe mostrar
   `{"status":"ok"}`. Luego abre la misma dirección sin `/health` e ingresa a la app.

## Verificación posterior a la publicación

1. Comprueba que veas los maestros, las pecosas, los lotes y los bienes ya existentes.
2. Registra una pecosa de prueba solo si tienes un caso real pendiente.
3. Genera un archivo de Normalización y verifica que descargue correctamente.
4. Revisa Control General y Verificación.
5. Si aparece un error, copia el texto de la sección **Logs** de Render y envíamelo.

## Trabajo futuro sin arriesgar producción

La recomendación para esta etapa es trabajar primero en la copia local, como hemos
hecho hasta ahora. Cuando un cambio esté comprobado localmente, se publica en GitHub.
El despliegue automático está desactivado, así que la versión de producción solo
cambiará cuando pulses **Manual Deploy** en Render y elijas la última versión.

Antes de publicar cambios que afecten datos, haremos una copia de Neon y revisaremos
la actualización en local. Evita utilizar la base SQLite de Render: en el plan Free,
los archivos locales se pierden cuando el servicio se reinicia o se suspende. La base
de datos persistente es Neon.

## Qué esperar del plan gratuito

Render puede suspender un servicio Free después de 15 minutos sin solicitudes; la
primera visita posterior puede tardar alrededor de un minuto. Esto no afecta la base
de Neon. Si en el futuro necesitas que la app responda siempre sin espera inicial,
será necesario evaluar un plan de pago.
