# Estado del proyecto

Fecha de corte: 27 de septiembre de 2026.

Commit base documentado: `4614ffba8103a7cf6c68cc50d81d49f03648c87f` (`Compact inventor request history on mobile`).

## 1. Resumen ejecutivo

El proyecto está funcional como aplicación web monolítica y cubre el ciclo de pecosas, normalización, QR, impresión, solicitudes móviles, control general, verificación y maestro patrimonial. El código actual pasa 71 pruebas locales.

La producción en Render con PostgreSQL de Neon fue puesta en funcionamiento y el usuario confirmó que el Web Service nuevo respondía correctamente. Se realizaron cargas reales de aproximadamente 39 mil bienes, se detectó y corrigió el problema de lentitud por actualizaciones fila por fila y se crearon respaldos de producción.

El último conjunto de cambios de Control Impresión e interfaz móvil fue enviado a `origin/main`. El propietario confirmó que el servicio productivo desplegó el commit `4614ffb`.

## 2. Completado en código

### Autenticación y usuarios

- Inicio y cierre de sesión con bcrypt.
- Roles Administrador e Inventariador.
- Restricción del Inventariador a su portal.
- Creación, edición, cambio de contraseña y activación de usuarios.
- Protección contra desactivar o degradar al último administrador.

### Pecosas y normalización

- Registro individual y masivo sin duplicados.
- Firma individual y agrupada con expediente de firma.
- Maestros importables y exportables.
- Cruce exacto persona/DNI y dependencia/IPRESS.
- Lotes parciales, completado posterior y diferimiento de pecosas faltantes.
- Regularización de Carga Inicial histórica.
- Generación del formato One Vision `.xls`.

### Impresión histórica

- Lectura incremental del reporte QR.
- Corrección del código patrimonial alterado por el reporte.
- PDF de dos etiquetas por página para Argox.
- Perfil de impresión configurable.
- Excel para BarTender.
- Validaciones de ruta, legibilidad y espacio.

### Control General y Verificación

- Importación acumulada de Relación de Pecosas con reemplazo de la foto anterior.
- Estados por cantidad esperada, ingresada y firma.
- Observación y restitución por año y pecosa.
- Reasignación auditada de bienes de más.
- Exportación de control.
- Comparación de pecosa y año contra el último SIGA.

### Control Impresión

- Universo anual acumulativo.
- Historial de cada reporte con nuevas, actualizadas, sin cambios, duplicadas y omitidas.
- Actualizaciones masivas y lectura incremental.
- Normalización de patrimonios de 11 dígitos.
- Clasificación de códigos cortos como sobrantes.
- Conservación de lotes y confirmaciones previas.
- Filtros por red, establecimiento, área, estado, tipo y búsqueda.
- Resumen por establecimiento.
- Lotes de hasta 1000 bienes con división automática de selecciones mayores.
- Bloqueo de QR duplicados y lotes abiertos duplicados.
- Reimpresión con confirmación explícita.
- PDF, Excel BarTender y hoja de control.
- Impresión parcial sin volver a incluir items ya impresos.

### Solicitudes de inventariadores

- Cuentas separadas por inventariador.
- Solicitudes de hasta 500 QR.
- Validación previa en tarjetas responsivas.
- Omisión de QR que ya pertenecen a solicitudes activas.
- Creación parcial para listas mixtas.
- Solicitud anticipada de QR todavía no sincronizado.
- Reconciliación automática después de una carga.
- Vínculo automático con lotes abiertos.
- Estados de lista para recojo y recogido.
- Confirmación de recojo mediante modal centrado.
- Historial móvil compacto, con fecha dentro del detalle.

### Regla DIRESA

- Área obligatoria solo para establecimiento normalizado `DIRESA - CAJAMARCA`.
- Solicitud en espera si falta área.
- Mensaje `QR sin area, actualiza en One Vision`.
- Bloqueo de PDF y confirmación mientras falte área.
- Sticker de Control Impresión muestra área en DIRESA y establecimiento fuera de DIRESA.
- Módulo histórico Impresión QR conservado sin esa modificación.

### Maestro Patrimonial

- Cargas completas y parciales.
- Validación estricta de 41 columnas.
- Clasificación Nuevo, Actualizado, Sin cambios y No incluido.
- QR repetido como alerta no bloqueante.
- Procesamiento por bloques y reanudación.
- Historial, versiones y cambios por campo.
- Ediciones manuales con motivo.
- Conflictos entre SIGA y correcciones manuales.
- Resolución conservando manual o aceptando SIGA.
- Panel de calidad entre tres orígenes.
- Exportación personalizada y SIGA completo.
- Ficha patrimonial PDF.

## 3. Verificación automática actual

Comando ejecutado:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Resultado verificado:

```text
Ran 71 tests in 1.088s
OK
```

Cobertura funcional incluida:

- importación inicial y maestros;
- conexiones SQLite y PostgreSQL;
- lector QR incremental;
- PDF y perfil de impresión;
- paginación;
- pecosas, filtros y firma;
- Control General y reasignación;
- lectura `.xls` de SIGA;
- lotes parciales y regularización;
- Control Impresión por varios bloques;
- sobrantes y patrimonios de 11 dígitos;
- solicitudes, duplicados, reimpresión y lote abierto;
- área DIRESA;
- Maestro Patrimonial, auditoría, exportación y conflictos.

## 4. Evidencia y estado de producción

### Confirmado durante el trabajo

- Se configuró Render con Neon y el usuario confirmó que el Web Service nuevo funcionaba.
- Se realizó una carga de Maestro Patrimonial de 39,225 filas en producción.
- La primera implementación de esa carga mostró una espera excesiva y polling repetido.
- Se canceló el proceso problemático, se optimizaron actualizaciones masivas y se publicó la corrección.
- El usuario informó que la carga optimizada terminó en pocos minutos.
- Control Impresión mostró una velocidad de carga aceptable con el reporte completo.
- La interfaz móvil fue probada desde el dominio de Render y se corrigieron ancho, navegación, validación e historial.
- Se generaron varios dumps de producción.

### Último respaldo visible

```text
backups/production/siga_onevision_produccion_20260927_121731.dump
backups/production/siga_onevision_produccion_20260927_121731.dump.sha256
```

SHA-256 verificado en esta revisión:

```text
d9f3c7fe1304634edd3a57ef7258094e5659bb332f06e2a4f41e3f909787426a
```

El modelo ORM actual contiene 27 tablas.

`PENDIENTE`: todavía no se ha probado la restauración. Debe restaurarse ese dump en una base aislada y comprobar las 27 tablas, cantidades y operaciones principales. En esta revisión no se pudo listar ni restaurar el dump porque `pg_restore` no está instalado.

### Despliegue exacto del último commit

- `main` local estaba sincronizado con `origin/main` antes de crear esta documentación.
- Último commit funcional enviado: `4614ffb`.
- El propietario confirmó que Render desplegó ese SHA.
- El servicio productivo confirmado es `gestion-ovc-siga`, con URL `https://gestion-ovc-siga.onrender.com`.
- El despliegue se ejecuta manualmente desde Render.

## 5. En progreso

### Documentación técnica

En este cambio local se crearon o actualizaron:

- `README.md`
- `ARCHITECTURE.md`
- `DATA_MODEL.md`
- `BUSINESS_RULES.md`
- `STATUS.md`

Al momento de escribir este estado, esos documentos todavía no forman parte de un commit.

### Consolidación de infraestructura

La infraestructura productiva confirmada por el propietario es:

- Web Service: `gestion-ovc-siga`;
- URL: `https://gestion-ovc-siga.onrender.com`;
- Render: Ohio (US East);
- política de despliegue: Manual Deploy;
- Neon: AWS US East 2 (Ohio), PostgreSQL 18;
- Web Service anterior: suspendido.

El repositorio todavía conserva `render.yaml` y `GUIA_DESPLIEGUE.md` con el nombre y la región del servicio anterior.

## 6. Backlog priorizado

### P0: operación y recuperación

1. Ejecutar y registrar un smoke test productivo de cada despliegue manual.
2. Hacer una restauración de prueba del último dump en una base aislada.
3. Documentar RPO, RTO, comandos de respaldo y restauración, propietarios y rotación.
4. Reconciliar `render.yaml` y `GUIA_DESPLIEGUE.md` con el servicio `gestion-ovc-siga` de Ohio.
5. Mantener suspendido el Web Service anterior mientras se define si debe eliminarse.

### P1: integridad y despliegue

1. Incorporar Alembic y sacar los cambios de esquema del arranque.
2. Crear pruebas automatizadas contra PostgreSQL, al menos para migraciones, cargas masivas y concurrencia de solicitudes.
3. Implementar ejecución exclusiva de tareas patrimoniales al escalar a más de una instancia.
4. Evaluar un Background Worker o cola durable para validación, confirmación y exportación patrimonial.
5. Automatizar respaldos y verificación de checksum.
6. Agregar un procedimiento de despliegue que incluya respaldo, migración, smoke test y reversión.

### P1: seguridad

1. Configurar explícitamente cookies seguras para producción: `https_only`, política `same_site` y duración.
2. Evaluar protección CSRF para formularios que modifican datos.
3. Agregar política de cambio o recuperación de contraseña.
4. Evaluar segundo factor o identidad institucional si la aplicación se expone fuera de una red controlada.
5. Verificar que `APP_PASSWORD` y `SECRET_KEY` de producción no sean valores predeterminados.

### P2: rendimiento

1. Evaluar tabla temporal PostgreSQL y operaciones de conjunto para los reportes de 39 mil bienes si el volumen o frecuencia aumenta.
2. Evitar que el cruce exacto de maestros recorra todo el catálogo por cada fila; usar índices normalizados o diccionarios precargados.
3. Medir importación de Control Impresión con datos de producción y fijar un objetivo de duración.
4. Optimizar Control General si la relación de pecosas y los bienes crecen de forma significativa.
5. Considerar almacenamiento externo para exportaciones grandes en lugar de BYTEA en PostgreSQL.

### P2: producto y trazabilidad

1. Agregar paginación o archivo histórico para más de 100 solicitudes por inventariador y más de 200 en la vista administrativa.
2. Definir un flujo explícito de baja o inactivación de bienes ausentes del reporte de Control Impresión.
3. Aplicar la restricción única de `inventarios_impresion` por año y unidad ejecutora, decisión de negocio ya confirmada.
4. Definir si un código patrimonial puede pertenecer a pecosas de años distintos, porque `pecosas.numero` es único globalmente.
5. Agregar una prueba que compruebe que el `.xls` de One Vision conserva el código numérico de `Estado`, por ejemplo `1` para `Bueno`.
6. Decidir si la vista SQL de BarTender seguirá utilizándose o debe adaptarse a Control Impresión.

### P3: mantenimiento

1. Reemplazar `datetime.utcnow()` por fechas conscientes de zona horaria.
2. Reemplazar usos heredados de `Query.get()` por `Session.get()`.
3. Dividir `tests/test_importaciones.py` por dominio.
4. Añadir pruebas de navegador para los flujos móvil y administrador.
5. Servir Bootstrap localmente si la aplicación debe funcionar sin acceso al CDN.

## 7. Problemas conocidos y deuda técnica

### Configuración de Render divergente

`render.yaml` indica el nombre `siga-onevision-app`, región Oregon y Auto-Deploy desactivado. Producción usa `gestion-ovc-siga` en Ohio con Manual Deploy. La política manual coincide, pero el nombre y la región declarados están desactualizados.

### Guía de despliegue histórica

`GUIA_DESPLIEGUE.md` todavía habla de Oregon y contiene partes del flujo anterior. Debe actualizarse para documentar `gestion-ovc-siga`, Ohio y Neon AWS US East 2.

### Vista BarTender obsoleta

`sql/vista_bartender.sql` menciona Railway y solo expone `bienes_alta`. Producción usa Neon y el módulo nuevo trabaja con `bienes_inventario_impresion` y lotes propios.

### Migraciones dentro del arranque

Importar `app.main` puede ejecutar DDL y actualizaciones de datos. No hay tabla de versión, downgrade ni bloqueo distribuido.

### Tareas de fondo en proceso web

La persistencia permite reanudar, pero no hay cola externa ni exclusión robusta entre instancias. Un reinicio durante una tarea depende de que el siguiente arranque la detecte.

### Hora sin zona

Las fechas se generan en UTC sin información de zona y se muestran con `strftime` sin conversión a `America/Lima`. La hora visible puede no representar hora local cuando el servidor opera en UTC.

### Contadores de solicitudes en Control Impresión

Los contadores superiores de items `Pendiente`, `Pendiente de sincronización` y `Pendiente de actualización de área` consultan todas las campañas, no filtran por el inventario seleccionado. La vista administrativa detallada también reúne hasta 200 solicitudes globales.

### Ausentes no se desactivan

Control Impresión es acumulativo. Un bien retirado del reporte fuente permanece activo. Esta es la decisión actual, pero requiere un flujo de baja si el negocio necesita reflejar retiros.

### Restricciones implementadas en aplicación

La prevención de QR en solicitudes activas y la creación única del inventario anual se resuelven por consulta previa. Dos solicitudes exactamente concurrentes podrían requerir restricciones adicionales en PostgreSQL.

### Progreso de Control Impresión

No hay barra con porcentaje real. La importación es síncrona y muestra un estado general de procesamiento. Se decidió no simular progreso ni agregar polling porque la carga observada es rápida.

### Advertencias de deprecación

La suite pasa, pero muestra advertencias por `datetime.utcnow()` y API heredada de SQLAlchemy. No son fallos actuales.

## 8. Criterio para considerar estable Control Impresión

Antes de cerrar definitivamente el módulo se recomienda verificar en producción:

1. carga completa con nuevas, actualizadas, sin cambios y sobrantes;
2. QR de 11 dígitos patrimoniales y códigos cortos;
3. lista mixta con QR disponible y QR ya solicitado;
4. QR no sincronizado que se vincula después de una carga;
5. DIRESA sin área y luego con área;
6. generación de PDF y confirmación parcial;
7. reimpresión confirmada;
8. vista móvil en iOS y Android sin zoom manual;
9. respaldo posterior y restauración de prueba.

Las reglas anteriores tienen pruebas automatizadas, salvo la interacción real con navegador, impresora, Render, Neon y restauración del dump.
