# Gestión QR: SIGA MP, One Vision y control patrimonial

Aplicación web interna para administrar el ciclo de altas patrimoniales, normalizar reportes de SIGA MP al formato de One Vision, cruzar códigos QR, generar stickers, controlar el avance de pecosas y mantener un maestro patrimonial auditable.

El sistema también incorpora un flujo operativo de solicitudes de stickers. Los inventariadores envían códigos QR desde el celular, Patrimonio prepara e imprime lotes y el inventariador confirma el recojo.

## Problema que resuelve

El proceso combina archivos producidos por SIGA MP y One Vision que no comparten exactamente las mismas claves, nombres ni formatos. Sin una herramienta central aparecen problemas recurrentes:

- pecosas duplicadas o incompletas;
- cruces manuales entre responsable, DNI, dependencia e IPRESS;
- códigos patrimoniales alterados por Excel o por el reporte de One Vision;
- QR duplicados, faltantes o todavía no sincronizados;
- lotes impresos sin trazabilidad;
- dificultad para distinguir bienes nuevos, actualizados y sin cambios;
- pérdida del historial cuando se corrigen datos manualmente;
- solicitudes repetidas del mismo sticker por distintos inventariadores.

La aplicación conserva esas relaciones en una base de datos, valida los archivos antes de aplicarlos y registra el historial de cargas, versiones, correcciones, conflictos, lotes y solicitudes.

## Usuarios

### Administrador

Tiene acceso a los módulos de gestión:

- Pecosas
- Normalización
- Maestros
- Impresión QR
- Control Impresión
- Maestro Patrimonial
- Control General
- Verificación
- Carga Inicial
- Usuarios

### Inventariador

Solo puede entrar al portal `/inventariador`. Desde allí puede:

- validar uno o varios QR;
- enviar una solicitud de stickers;
- confirmar explícitamente una reimpresión;
- revisar hasta las 100 solicitudes más recientes propias;
- consultar QR observados, pendientes de sincronización o pendientes de área;
- confirmar el recojo de stickers listos.

## Alcance funcional

### El sistema sí hace

1. Registra expedientes y pecosas sin duplicar el número de pecosa.
2. Importa y mantiene maestros de personas y centros de costo.
3. Lee el reporte de Altas Institucionales de SIGA, filtra las pecosas seleccionadas y cruza responsable y dependencia por coincidencia exacta normalizada.
4. Genera el archivo `.xls` de 16 columnas requerido por One Vision.
5. Lee el reporte QR de One Vision, cruza por código patrimonial y genera PDF o Excel para impresión.
6. Mantiene un universo anual acumulativo para Control Impresión.
7. Clasifica activos fijos y sobrantes, conserva el historial de impresión y evita lotes duplicados abiertos.
8. Administra solicitudes de stickers y sincroniza solicitudes anticipadas cuando se vuelve a cargar el reporte.
9. Aplica la regla especial de área obligatoria para `DIRESA - CAJAMARCA` solo en Control Impresión.
10. Compara el universo esperado de pecosas con los bienes ingresados y permite observar o corregir asignaciones.
11. Mantiene un Maestro Patrimonial con cargas completas o parciales, trazabilidad por versión, correcciones manuales y resolución de conflictos.
12. Genera exportaciones Excel y fichas patrimoniales PDF.
13. Usa SQLite en desarrollo y PostgreSQL de Neon en producción.

### El sistema no hace

- No se conecta directamente a SIGA MP ni a One Vision. Los intercambios se realizan mediante archivos Excel.
- No modifica datos dentro de SIGA MP ni de One Vision.
- No descarga automáticamente nuevos reportes de One Vision.
- No envía notificaciones por correo, SMS, WhatsApp ni notificaciones móviles.
- No controla físicamente la impresora. Genera PDF o Excel para el proceso de impresión.
- No reemplaza el respaldo administrado de PostgreSQL.
- No ofrece una API pública documentada para integraciones externas.
- No implementa permisos por módulo. Existen dos roles globales: `Administrador` e `Inventariador`.
- No muestra progreso real durante la carga síncrona de Control Impresión. Se decidió conservar el mensaje de procesamiento porque esa importación ya es rápida y una barra basada en consultas adicionales no aportaba progreso fiable.

## Módulos y rutas principales

| Módulo | Ruta | Función |
| --- | --- | --- |
| Inicio de sesión | `/login` | Autenticación con sesión y contraseña bcrypt. |
| Pecosas | `/pecosas` | Registro, búsqueda y firma de pecosas. |
| Normalización | `/normalizacion` | Cruce de Altas SIGA y generación del formato One Vision. |
| Maestros | `/maestros` | Personas, DNI, centros de costo e IPRESS. |
| Impresión QR | `/impresion` | Cruce por lote, PDF de stickers y Excel BarTender. |
| Control Impresión | `/control-impresion` | Universo anual, filtros, lotes, impresión e historial de cargas. |
| Solicitudes administrativas | `/control-impresion/solicitudes` | Cola de solicitudes de inventariadores. |
| Portal inventariador | `/inventariador` | Validación, envío, seguimiento y recojo de stickers. |
| Maestro Patrimonial | `/maestro-patrimonial` | Consulta, cargas, auditoría, calidad y exportación. |
| Control General | `/control` | Comparación de pecosas esperadas e ingresadas. |
| Verificación | `/verificacion` | Comparación de pecosa y año contra el último reporte SIGA. |
| Carga Inicial | `/carga-inicial` | Migración de un consolidado histórico. |
| Usuarios | `/usuarios` | Administración de cuentas y roles. |
| Salud | `/health` | Respuesta pública `{"status":"ok"}`. |

## Estructura del repositorio

```text
app/
  main.py                 Arranque, routers y adecuaciones de esquema
  config.py               Variables de entorno
  database.py             Motor y sesiones SQLAlchemy
  models.py               Modelo ORM de 27 tablas
  auth.py                 Autenticación, sesiones y roles
  routers/                Endpoints y composición de cada módulo
  services/               Lectura Excel, reglas, PDF y actualizaciones masivas
  templates/              Interfaz Jinja2
  static/style.css        Estilos generales y vista móvil del inventariador
scripts/
  migrar_sqlite_a_neon.py Migración inicial de SQLite a una base Neon vacía
sql/
  vista_bartender.sql     Vista heredada para BarTender
tests/
  test_importaciones.py   Suite unitaria e integración local
render.yaml               Blueprint de Render incluido en el repositorio
Procfile                  Comando web alternativo
runtime.txt               Versión de Python
requirements.txt          Dependencias fijadas
```

## Requisitos locales

- Python 3.12.10
- `venv` o equivalente
- SQLite, incluido con Python, para el modo local predeterminado
- Acceso a Internet durante la instalación de dependencias y para cargar Bootstrap desde CDN en la interfaz

## Instalación local

```bash
git clone <URL_DEL_REPOSITORIO>
cd siga-onevision-app2

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Editar `.env` antes de iniciar. Para desarrollo local se puede conservar SQLite:

```dotenv
DATABASE_URL=sqlite:///./local_dev.db
APP_USERNAME=admin
APP_PASSWORD=elige_una_contrasena_segura
SECRET_KEY=elige_un_texto_largo_y_aleatorio
EJECUTORA=785
ANIO_INVENTARIO=2026
```

Iniciar la aplicación:

```bash
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000`. En el primer arranque se crean las tablas y, si no existe, la cuenta administrativa indicada por `APP_USERNAME` y `APP_PASSWORD`.

## Variables de entorno

| Variable | Obligatoria en producción | Uso |
| --- | --- | --- |
| `DATABASE_URL` | Sí | URL de PostgreSQL. También acepta el prefijo heredado `postgres://` y lo transforma a `postgresql://`. |
| `APP_USERNAME` | Sí | Usuario administrativo que se crea solo si todavía no existe. |
| `APP_PASSWORD` | Sí | Contraseña inicial de ese administrador. Cambiar el valor no modifica una cuenta ya creada. |
| `SECRET_KEY` | Sí | Firma de la cookie de sesión. Debe ser larga, aleatoria y estable entre despliegues. |
| `EJECUTORA` | Sí | Código usado en el formato One Vision. Valor actual de ejemplo: `785`. |
| `ANIO_INVENTARIO` | Sí | Año predeterminado de normalización e inventario. Valor actual de ejemplo: `2026`. |
| `PORT` | Lo aporta Render | Puerto del proceso web. |
| `PYTHON_VERSION` | Recomendable | Debe coincidir con `3.12.10`. |

No publicar `.env`, `.env.production.local`, bases `.db`, archivos Excel, reportes ni respaldos. El `.gitignore` ya excluye esos elementos.

## Pruebas

Ejecutar:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Estado verificado el 27 de septiembre de 2026:

- 71 pruebas ejecutadas
- 71 pruebas aprobadas
- base de pruebas: SQLite en memoria

La suite cubre importaciones, paginación, cruces, PDF, lotes parciales, Control Impresión, solicitudes, regla DIRESA, Maestro Patrimonial, auditoría y conflictos. No existe todavía una suite automatizada contra PostgreSQL ni pruebas de navegador de extremo a extremo.

## Despliegue a producción

La arquitectura prevista es:

- Render Web Service para FastAPI y Uvicorn
- Neon PostgreSQL para persistencia
- GitHub como origen del código

### Configuración del servicio

1. Crear un Web Service en Render conectado al repositorio.
2. Elegir Python 3.
3. Configurar el comando de construcción:

   ```text
   pip install -r requirements.txt
   ```

4. Configurar el comando de inicio:

   ```text
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

5. Configurar el health check en `/health`.
6. Agregar todas las variables de entorno de la sección anterior.
7. Usar la cadena de conexión de Neon en `DATABASE_URL`.
8. Elegir para Render la misma región geográfica de Neon o la más cercana disponible.
9. Desplegar el commit aprobado de `main`.
10. Verificar `/health`, inicio de sesión y los módulos con una prueba de humo sin modificar datos críticos.

### Estado de la configuración declarativa

Configuración productiva confirmada por el propietario el 27 de septiembre de 2026:

| Elemento | Valor |
| --- | --- |
| Web Service activo | `gestion-ovc-siga` |
| URL | `https://gestion-ovc-siga.onrender.com` |
| Región de Render | Ohio (US East) |
| Despliegue | Manual Deploy |
| Servicio anterior | Suspendido |
| Neon | AWS US East 2 (Ohio), PostgreSQL 18 |

`render.yaml` todavía declara el nombre `siga-onevision-app`, región Oregon y `autoDeployTrigger: off`. La desactivación automática coincide con el flujo manual, pero el nombre y la región no representan al servicio productivo actual. `GUIA_DESPLIEGUE.md` también contiene datos históricos. Cambiar estos archivos no modifica por sí solo el Web Service ya creado en el panel de Render.

### Publicación de cambios

Flujo acordado:

1. Implementar y probar en local.
2. Ejecutar la suite completa.
3. Revisar `git diff` y preparar un commit.
4. Hacer `git push origin main` cuando el usuario autorice la publicación.
5. Abrir el Web Service `gestion-ovc-siga` en Render.
6. Elegir `Manual Deploy` y desplegar el último commit de `main`.
7. Confirmar que el despliegue está `Live`, revisar el SHA publicado y ejecutar una prueba de humo.

### Base de datos y adecuaciones de esquema

La aplicación ejecuta `Base.metadata.create_all()` y varias adecuaciones idempotentes al importar `app.main`. Esto crea tablas nuevas y agrega algunas columnas e índices a bases existentes. No existe Alembic.

Antes de desplegar un cambio que modifique modelos:

1. crear un respaldo de Neon;
2. verificar su checksum;
3. probar el cambio en una copia local cuando sea posible;
4. desplegar una sola instancia durante la modificación del esquema;
5. comprobar tablas, columnas, índices y registros después del arranque.

## Migración inicial de SQLite a Neon

El script incluido solo escribe si la base destino está vacía y compara el número de filas de todas las tablas:

```bash
NEON_DATABASE_URL='postgresql://...' \
  .venv/bin/python scripts/migrar_sqlite_a_neon.py \
  --source /ruta/absoluta/copia.db
```

No usar este script para restaurar sobre una base que ya contiene información.

## Respaldo y recuperación

El repositorio local contiene respaldos excluidos de Git. El respaldo más reciente visible al documentar fue:

```text
backups/production/siga_onevision_produccion_20260927_121731.dump
```

Su archivo `.sha256` coincide con el contenido actual del dump.

`PENDIENTE`: todavía no se ha realizado una restauración de prueba. Debe restaurarse el dump en una base PostgreSQL separada y documentarse los comandos exactos, permisos, propietario y tiempo de recuperación. La presencia del archivo y un checksum correcto no prueba que la restauración complete correctamente.

## Documentación complementaria

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DATA_MODEL.md](DATA_MODEL.md)
- [BUSINESS_RULES.md](BUSINESS_RULES.md)
- [STATUS.md](STATUS.md)
- [GUIA_DESPLIEGUE.md](GUIA_DESPLIEGUE.md), contiene información histórica que debe reconciliarse con el servicio productivo actual.
