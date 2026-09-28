# Reglas de negocio

## 1. Acceso y usuarios

### 1.1 Inicio de sesión

1. El nombre de usuario se normaliza con recorte y `casefold`.
2. Solo una cuenta con `activo = 1` puede iniciar sesión.
3. La contraseña se verifica contra bcrypt.
4. La sesión guarda `usuario_id`, username, nombre y rol.
5. Un Administrador entra al inicio general y es redirigido a `/pecosas`.
6. Un Inventariador entra a `/inventariador`.
7. Si un Inventariador intenta acceder a otra ruta, se redirige a `/inventariador`.
8. El cierre de sesión borra todo el contenido de la sesión.

### 1.2 Cuenta administrativa inicial

1. En el arranque se busca `APP_USERNAME` ya normalizado.
2. Si no existe, se crea una cuenta Administrador con `APP_PASSWORD`.
3. Si existe, cambiar las variables no cambia automáticamente su contraseña.

### 1.3 Administración de cuentas

- Roles válidos: `Administrador`, `Inventariador`.
- La contraseña nueva debe tener al menos ocho caracteres.
- Username no puede repetirse.
- Un administrador no puede quitarse a sí mismo el rol Administrador.
- Un usuario no puede desactivar su propia cuenta activa.
- Debe quedar al menos un administrador activo.

## 2. Pecosas y expedientes

### 2.1 Registro individual

1. Se recortan pecosa y expediente.
2. Si el número de pecosa ya existe, no se crea otro registro.
3. Si el expediente no existe, se crea con la fecha local actual.
4. Se crea la pecosa en estado `Recibida` y con fecha de recepción actual.

### 2.2 Registro múltiple

1. Un formulario acepta números separados por comas o líneas.
2. Se quitan repeticiones dentro del propio formulario sin alterar el orden.
3. Se consultan pecosas existentes.
4. Si todas ya existen, no se crea un expediente vacío.
5. Si hay nuevas, se reutiliza o crea el expediente y solo se insertan las nuevas.
6. El resultado informa cuáles ya existían.

### 2.3 Estados de pecosa

Estados visibles en la interfaz actual:

| Estado | Significado |
| --- | --- |
| `Recibida` | Pendiente de normalización. |
| `Normalizada` | Tiene bienes incorporados a un lote. |
| `StickerGenerado` | Tiene al menos un QR cargado o llegó así desde Carga Inicial. |
| `Firmada` | Se registraron firmante, fecha y expediente de firma. |

El comentario heredado del modelo menciona `IngresadaSIGA` y `CargadaOneVision`, pero esos estados no aparecen en la lista visible ni en las transiciones actuales. No deben introducirse sin definir antes su uso.

### 2.4 Firma

- La firma registra `firmante`, `expediente_firma`, fecha actual y estado `Firmada`.
- Control General permite asignar un mismo expediente de firma a varias pecosas y luego confirmar firmantes individualmente o en grupo.
- Una pecosa ya firmada se devuelve como tal y no se sobrescribe en la asignación masiva previa.

## 3. Maestros de personas y centros de costo

### 3.1 Personas

- El nombre nuevo se guarda en mayúsculas, sin espacios exteriores.
- El nombre es único.
- La importación detecta variantes de nombre y documento.
- Si el nombre no existe, se inserta.
- Si existe con DNI vacío, se completa.
- Si existe con DNI no vacío, la importación no lo sobrescribe.

### 3.2 Centros de costo

- La dependencia nueva se guarda en mayúsculas.
- El nombre de dependencia es único.
- La importación detecta variantes de dependencia, centro de costo, IPRESS u One Vision.
- Si no existe, se inserta.
- Si existe con IPRESS vacío, se completa.
- Si existe con IPRESS no vacío, la importación no lo sobrescribe.

### 3.3 Cruce SIGA

1. Nombre de persona y dependencia se convierten a mayúsculas.
2. Se recortan y compactan espacios.
3. La coincidencia debe ser exacta después de normalizar.
4. No hay coincidencia difusa ni elección automática aproximada.
5. Si falta persona o centro, el bien queda pendiente y debe corregirse desde la interfaz o el maestro.
6. También se considera pendiente si existe la relación pero DNI o IPRESS están vacíos.

## 4. Normalización de Altas SIGA a One Vision

### 4.1 Crear lote

1. Solo se muestran pecosas en estado `Recibida`.
2. El usuario selecciona una o varias pecosas y carga el reporte de Altas Institucionales.
3. Antes de crear el lote se verifica que todas sigan existiendo y en estado `Recibida`.
4. El reporte debe contener las columnas esperadas.
5. El número de pecosa se extrae de `observaciones` por el primer grupo de dígitos.
6. Se filtran las filas correspondientes a las pecosas seleccionadas, ignorando ceros iniciales para la comparación.
7. Se crea un `LoteCarga` con `ANIO_INVENTARIO`, `EJECUTORA` y la lista CSV de pecosas solicitadas.
8. Cada fila con código patrimonial crea un `BienAlta` si la pareja pecosa y código todavía no existe dentro del lote.
9. Filas sin código patrimonial se omiten y contabilizan.
10. Repeticiones dentro del reporte o reintentos sobre el mismo lote se omiten.
11. La pecosa pasa a `Normalizada` al crear al menos un bien.

### 4.2 Pecosas sin filas

- Una pecosa seleccionada que no aparece en el reporte permanece listada como no encontrada.
- Un lote no se puede generar mientras existan pecosas no encontradas.
- El usuario puede completar el mismo lote con un reporte corregido.
- El usuario puede diferir una pecosa faltante a un lote posterior.
- No se permite diferir si el lote quedaría sin ninguna pecosa procesada.
- Si la pecosa diferida no tiene ningún bien, vuelve a `Recibida`.

### 4.3 Completar un lote

1. Se reutiliza el mismo lote y las pecosas registradas en `pecosas_solicitadas`.
2. Solo se agregan bienes no existentes por pecosa y código patrimonial.
3. No se cambia el expediente de la pecosa.
4. No se reemplazan bienes existentes.
5. Si se agrega al menos un bien, se invalida `archivo_generado` para obligar a regenerar el archivo.

### 4.4 Regularización histórica

Los lotes de Carga Inicial se reconocen porque año o ejecutora están vacíos.

1. Se cruza todo bien histórico por código patrimonial contra un reporte completo de Altas SIGA.
2. Un código duplicado en el reporte es ambiguo y no actualiza ningún bien con ese código.
3. Se completan dependencia y persona fuente, fecha de alta y estado de conservación.
4. Una asignación manual existente solo se reemplaza si SIGA encuentra coincidencia exacta en el maestro.
5. Año y ejecutora del lote se completan si todas sus filas encontradas coinciden en un único par.
6. Si un lote obtiene pares diferentes se reporta como inconsistente.

### 4.5 Generación del formato One Vision

Se puede generar solo si:

- el lote contiene al menos un bien;
- no falta ninguna pecosa seleccionada;
- todos los bienes tienen persona con DNI;
- todos los bienes tienen centro de costo con IPRESS.

El `.xls` contiene 16 columnas. El número de pecosa se escribe en `Observaciones`.

Existe una equivalencia configurada para mostrar estados de conservación:

| Código | Texto visible |
| --- | --- |
| `1` | Bueno |
| `2` | Regular |
| `3` | Malo |
| `4` | Muy Malo |
| `5` | Nuevo |
| `6` | Chatarra |
| `7` | RAEE |

El `.xls` para One Vision debe conservar el código numérico almacenado en `estado_conservacion`, no el texto visible. Por ejemplo, debe escribir `1`, cuyo significado es `Bueno`. La tabla de equivalencias se usa para mostrar el texto en la interfaz.

## 5. Carga Inicial histórica

1. Exige al menos una persona y un centro de costo cargados.
2. Acepta uno o varios consolidados `.xlsx`.
3. Requiere código patrimonial, bien, pecosa, expediente y lote.
4. Un código patrimonial ya presente en `bienes_alta` se omite globalmente.
5. Una pecosa nueva se crea con estado `StickerGenerado`.
6. Una pecosa existente solo se sube a `StickerGenerado` si estaba `Recibida` o `Normalizada`.
7. No se degrada una pecosa más avanzada.
8. Si el lote del Excel es numérico se usa directamente como PK de `lotes_carga`.
9. Si no es numérico se crea un ID automático y se alerta.
10. En PostgreSQL se reajusta la secuencia después de insertar IDs manuales.
11. El establecimiento se cruza por nombre normalizado exacto contra centros de costo.
12. Un establecimiento sin coincidencia deja `centro_costo_id` nulo y se reporta.
13. Se actualiza `pecosas_solicitadas` con las pecosas efectivamente presentes en cada lote.

## 6. Impresión QR del flujo histórico

Este módulo trabaja con `BienAlta` y `LoteCarga`. No usa las reglas particulares de Control Impresión.

### 6.1 Carga del reporte QR

1. Se selecciona un lote existente.
2. El lector recorre el `.xlsx` en modo `read_only`.
3. Corrige el código patrimonial tomando sus últimos 12 dígitos cuando corresponde.
4. Solo cruza contra bienes del lote elegido.
5. Un valor QR no vacío actualiza `codigo_qr`.
6. Una ruta no vacía actualiza `ruta_qr`.
7. Filas de otros lotes se ignoran.
8. Si un bien queda con QR, su pecosa pasa a `StickerGenerado`.

### 6.2 Etiquetas

- El módulo genera dos etiquetas por página para el perfil Argox.
- El sticker histórico muestra la dependencia del centro de costo.
- La regla especial que muestra área para `DIRESA - CAJAMARCA` no aplica aquí.
- También puede generar Excel compatible con BarTender.

## 7. Validación física de stickers

Un bien queda excluido del PDF si ocurre cualquiera de estos casos:

- falta Ruta QR;
- la ruta tiene espacios al inicio o final;
- contiene caracteres de control;
- no usa `http` o `https`, o no tiene host;
- falta código QR;
- la ruta es demasiado larga para mantener el módulo QR mínimo;
- el código visible no cabe con la escala mínima;
- descripción y ubicación no caben completas en la etiqueta.

Para sobrantes, el código visible puede ser solo QR. Para activos, se muestra `QR-CódigoPatrimonial`.

## 8. Control General de pecosas

### 8.1 Importación

- La Relación de Pecosas es acumulativa y reemplaza por completo la tabla anterior.
- La cantidad esperada es la suma de `cant_aprobada` por año y número de pecosa.
- Valores de cantidad no válidos se convierten en cero.

### 8.2 Cálculo de estado

Orden de prioridad:

1. Observación activa: `Observada`.
2. Pecosa inexistente en la aplicación: `Pendiente envío almacén`.
3. Cantidad ingresada mayor que esperada: `Inconsistencia: bienes de más`.
4. Cantidad ingresada menor que esperada: `Ingresada parcial en SIGA`.
5. Cantidad completa pero pecosa no firmada: `Ingresado a SIGA y OVC (falta firma)`.
6. Cantidad completa y firmada: `Firmada/Completa`.

### 8.3 Observaciones

Causales permitidas:

- `No corresponde a activo fijo`
- `Transferencia a otra RIS/unidad ejecutora`
- `Otra`

Solo puede observarse una fila en `Pendiente envío almacén`. El sustento es obligatorio. La observación se identifica por año y número. Restituirla cambia `activa` a 0 y la fila vuelve a calcularse normalmente.

### 8.4 Corrección de bienes de más

1. Solo se habilita si la cantidad ingresada supera la esperada.
2. El bien se mueve a una pecosa destino ya registrada.
3. La pecosa destino debe ser distinta.
4. El motivo es obligatorio.
5. Se conserva el lote del bien.
6. La pecosa destino se agrega a `pecosas_solicitadas` del lote.
7. Si el bien ya tiene QR, la pecosa destino puede pasar a `StickerGenerado`.
8. Si tiene lote pero no QR, la pecosa destino puede pasar a `Normalizada`.
9. Se registra origen, destino, motivo y fecha en auditoría.

## 9. Verificación de pecosa y año

1. Cada nueva importación reemplaza la tabla de verificación anterior.
2. Códigos patrimoniales repetidos rechazan el reporte.
3. Para cada `BienAlta`, se busca el mismo código en el último reporte.
4. Se compara pecosa asignada con `nro_pecosa` real.
5. Se compara año del lote con el año extraído de `fecha_alta`.

Estados:

| Estado | Condición |
| --- | --- |
| `SIN VERIFICAR` | Código ausente del reporte. |
| `REPORTE SIGA INCOMPLETO` | Falta pecosa real o año. |
| `PECOSA INCORRECTA` | Pecosa, año o ambos difieren. |
| `PECOSA CORRECTA` | Pecosa y año coinciden. |

## 10. Importación acumulativa de Control Impresión

### 10.1 Identidad y clasificación

1. Un código numérico de 11 dígitos se completa a 12 con un cero inicial.
2. Un código de 12 o más caracteres se clasifica `Activo fijo`.
3. Un código menor de 12 que no sea el caso numérico de 11 se clasifica `Sobrante`.
4. Para sobrantes, el código patrimonial no se almacena como identidad; queda nulo.
5. Un QR numérico pierde ceros iniciales. Un QR alfanumérico se conserva.
6. Una fila sin código patrimonial y sin QR se omite.

### 10.2 Deduplicación dentro del archivo

- Activos fijos: clave `codigo_patrimonial` normalizado.
- Sobrantes: clave `codigo_qr`.
- La primera aparición se conserva y las posteriores cuentan como duplicadas.

Este fue el motivo por el que una lista visual de 22 filas podía producir menos sobrantes persistidos cuando varios QR o claves se repetían.

### 10.3 Inserción o actualización

1. Se busca o crea el inventario por año y unidad ejecutora.
2. Se reactivan registros existentes con `activo != 1`.
3. Para activos, primero se busca una coincidencia única por código patrimonial.
4. Si no se encuentra, se intenta por QR con compatibilidad de patrimonio.
5. Para sobrantes se busca por QR.
6. Si no existe, se inserta.
7. Si existe, se comparan todos los campos importados y de estado.
8. Si al menos uno cambia, se actualiza.
9. Si nada cambia, solo aumenta `sin_cambios`; no se reescribe la fila.
10. Red, establecimiento y área forman parte de la comparación. Un nuevo reporte puede cambiarlos, incluso dejarlos vacíos.
11. Una actualización no borra lotes, solicitudes ni confirmaciones de impresión.
12. Si el bien ya está `Impreso`, ese estado se conserva aunque cambie el reporte.
13. Si no está impreso y pierde QR o ruta válida, pasa a `Bloqueado`.
14. Si estaba bloqueado y recupera datos válidos, vuelve a `Sticker generado` si ya había generado sticker; de otro modo vuelve a `Pendiente`.
15. Los ausentes del archivo no se desactivan. El universo es acumulativo.

### 10.4 Vínculo con altas

- Una coincidencia única del código con `BienAlta` produce `Vinculado`.
- Más de una coincidencia produce `Ambiguo`.
- Ninguna produce `Sin alta`.

### 10.5 Historial

Cada carga guarda archivo, filas procesadas, nuevas, actualizadas, sin cambios, activos, sobrantes, duplicados, omitidos y totales acumulados.

## 11. Regla de área DIRESA

La regla solo pertenece a Control Impresión.

1. Se normaliza el establecimiento a mayúsculas, espacios compactos y guion rodeado por un espacio.
2. Solo la coincidencia exacta `DIRESA - CAJAMARCA` exige área.
3. Si no tiene área:
   - la validación muestra `Pendiente de actualización de área`;
   - el detalle muestra `QR sin area, actualiza en One Vision`;
   - la solicitud sí se registra, pero queda esperando;
   - no se puede incorporar a un lote nuevo;
   - si ya estaba en un lote, no se puede generar ni confirmar la impresión;
   - una carga posterior con área la devuelve a `Pendiente` o `En lote`, según corresponda.
4. Para ese establecimiento, el sticker de Control Impresión muestra el área.
5. Para otros establecimientos, el área puede estar vacía y el sticker muestra establecimiento.

## 12. Solicitudes de inventariadores

### 12.1 Entrada

- Acepta QR separados por espacios, saltos de línea, comas o punto y coma.
- Normaliza QR numéricos sin ceros iniciales.
- Quita duplicados dentro de la entrada conservando el orden.
- Máximo 500 QR por solicitud.
- Usa el inventario más reciente por año descendente e ID descendente.

### 12.2 Validación de cada QR

Orden:

1. Buscar el mismo QR en un item activo de la misma campaña.
2. Si existe, devolver `Ya solicitado`, indicar número y estado y marcarlo para omitir.
3. Si no existe en el inventario, devolver `Esperando actualización`.
4. Si está asociado a más de un bien, devolver `Observado`.
5. Si pertenece a DIRESA y no tiene área, devolver `Pendiente de actualización de área`.
6. Si el bien no es imprimible, devolver `Observado` con el motivo.
7. Si el bien ya está `Impreso`, devolver `Reimpresión` y exigir confirmación.
8. En otro caso, devolver `Disponible`.

Estados individuales que bloquean otra solicitud del mismo QR:

```text
Pendiente
En lote
Listo para recojo
Pendiente de sincronización
Pendiente de actualización de área
```

`Observado` y `Recogido` no están en esa lista.

### 12.3 Creación

1. Los QR ya solicitados se omiten, no se vuelven a guardar como observados.
2. Si todos fueron omitidos, no se crea una solicitud vacía.
3. Una lista mixta crea solicitud solo para los QR restantes.
4. Un QR no encontrado se guarda `Pendiente de sincronización`.
5. Un QR DIRESA sin área se guarda `Pendiente de actualización de área`.
6. Una reimpresión no confirmada se guarda `Observado`.
7. Una reimpresión confirmada se guarda `Pendiente` con `es_reimpresion = 1`.
8. Si existe un item de lote abierto para ese bien y todavía no está ligado a otra solicitud, se enlaza y el item pasa a `En lote`.

### 12.4 Reconciliación automática

Se ejecuta después de importar Control Impresión y durante el arranque.

- Si el QR sigue ausente, permanece pendiente de sincronización.
- Si aparece duplicado, pasa a observado.
- Si aparece sin área obligatoria, queda pendiente de área.
- Si no es imprimible, pasa a observado.
- Si ya pertenece a un lote abierto, vuelve a `En lote`.
- Si aparece como impreso, se observa y se pide una nueva solicitud con reimpresión confirmada.
- En otro caso queda `Pendiente`.

### 12.5 Estado resumen de solicitud

Los items observados no se consideran válidos para determinar avance.

| Condición | Estado de solicitud |
| --- | --- |
| No hay items válidos | `Observado` |
| Todos los válidos esperan sincronización o área | `Esperando actualización` |
| Todos recogidos | `Recogido` o `Recogido con observados` |
| Todos listos | `Listo para recojo` o `Listo para recojo con observados` |
| Alguno listo | `Atención parcial` |
| Alguno en lote | `En lote` o `En lote con actualización` |
| Alguno pendiente | `Pendiente` o `Pendiente con actualización` |

### 12.6 Recojo

- El inventariador solo puede marcar sus propias solicitudes.
- Solo se cambian items `Listo para recojo`.
- Si no hay ninguno, la acción se rechaza.
- La interfaz usa una ventana modal centrada antes de confirmar.
- En móvil, el historial muestra resumen compacto sin fecha; la fecha aparece al expandir `Ver QR`.
- Se muestran hasta 100 solicitudes propias, ordenadas por ID descendente.

## 13. Lotes de Control Impresión

### 13.1 Selección directa

- Se puede seleccionar filas visibles o todos los bienes filtrados.
- Máximo 1000 bienes.
- Se excluye un bien si:
  - es DIRESA sin área;
  - su QR está repetido en el inventario;
  - ya está en otro lote sin imprimir;
  - ya está impreso y no se confirmó reimpresión;
  - no supera la validación de etiqueta;
  - tiene más de una solicitud pendiente asociada.
- Si hay exactamente una solicitud pendiente del bien, el item se enlaza al lote.
- Una reimpresión confirmada en la solicitud autoriza la inclusión.

### 13.2 Desde solicitudes

1. Solo se aceptan items todavía `Pendiente`.
2. Todos deben pertenecer al mismo inventario.
3. Se aplican las mismas validaciones de duplicado, lote abierto, área e imprimibilidad.
4. El mismo bien solo puede aparecer una vez en el lote.
5. Items inválidos pasan a `Observado` o a pendiente de área.
6. Items válidos pasan a `En lote`.

### 13.3 PDF, Excel y confirmación

- El PDF solo incluye items que aún no tienen `impreso_en`.
- El Excel `BarTender` solo incluye pendientes.
- La hoja `Control` del Excel conserva todos los items y su estado.
- Generar el PDF marca el lote `Sticker generado` y los bienes `Sticker generado`.
- Si el lote ya tenía items impresos, queda `Impreso parcial`.
- No se puede confirmar impresión antes de generar el PDF.
- La confirmación puede abarcar todo o una selección.
- Confirmar pone fecha al item, marca el bien `Impreso` y el item de solicitud `Listo para recojo`.
- El lote queda `Impreso` si no quedan pendientes; en otro caso `Impreso parcial`.
- Un lote completamente impreso no vuelve a generar PDF.

## 14. Maestro Patrimonial

### 14.1 Preparación

1. Solo acepta `.xlsx`.
2. Tipo válido: `Completa` o `Parcial`.
3. Calcula SHA-256 del archivo.
4. Guarda temporalmente el binario en la base para poder reanudar.
5. Inicia una tarea de validación y redirige al detalle.

### 14.2 Validación

1. Rechaza la misma huella si otra carga está lista, procesando o completada.
2. Comprueba exactamente las primeras 41 cabeceras y su orden.
3. Omite filas completamente vacías.
4. Convierte fechas, decimales y textos.
5. Normaliza QR numéricos.
6. Un campo obligatorio vacío es error.
7. Un código patrimonial repetido dentro del archivo es error.
8. Un QR repetido entre códigos distintos es alerta, no error.
9. Compara los 22 campos mapeados con `datos_importados`.
10. Clasifica `Nuevo`, `Actualizado` o `Sin cambios`.
11. En carga completa, todo código vigente ausente se agrega como `No incluido`.
12. En carga parcial no se generan `No incluido`.
13. Si existe cualquier error, se borran las filas preparadas y la carga queda `Rechazada`.
14. Sin errores, queda `Lista para confirmar`.
15. El detalle de error se limita a 250 entradas.

### 14.3 Confirmación

1. Solo se confirma una carga `Lista para confirmar` o se reintenta una `Interrumpida`.
2. Pasa a `Procesando`.
3. Procesa bloques de 750.
4. Inserta los nuevos.
5. Ignora `Sin cambios`.
6. Conserva sin cambios un `No incluido`.
7. Para `Actualizado`, compara contra el último dato SIGA importado.
8. Actualiza campos sin corrección manual activa.
9. Si SIGA coincide con el valor manual, cierra la corrección y acepta SIGA.
10. Si SIGA cambia y contradice una corrección activa, conserva el valor manual y crea conflicto.
11. Crea una versión para cada nuevo y actualizado.
12. Crea cambios por campo para actualizados.
13. Relaciona las filas de carga con los bienes.
14. Al terminar marca `Completada` y progreso 100.
15. Si ocurre una excepción, revierte la transacción, marca `Interrumpida` y conserva las filas validadas para reintentar.

### 14.4 Edición manual

- Código patrimonial no es editable.
- El motivo es obligatorio.
- Los campos obligatorios no pueden quedar vacíos.
- Un QR no puede asignarse manualmente si otro bien ya lo tiene.
- Cada campo modificado cierra la corrección activa anterior del mismo campo y crea una nueva.
- Se crea una versión `Edición manual` y sus cambios.

### 14.5 Resolución de conflictos

- `manual`: conserva la corrección y marca `Corrección conservada`.
- `siga`: aplica el valor SIGA, cierra la corrección, marca `SIGA aceptado` y crea versión y cambio.
- Un conflicto no puede resolverse dos veces.

### 14.6 Calidad de datos

El panel compara Maestro Patrimonial, Altas y Control Impresión para identificar:

- bienes del maestro sin QR;
- QR repetidos dentro del maestro;
- un código con QR distintos según el origen;
- un QR asociado a códigos patrimoniales distintos;
- cantidad de valores vacíos en campos opcionales.

Las listas visibles tienen límites de 100 o 200 entradas, pero los totales cuentan el conjunto completo.

### 14.7 Exportación

Tipos:

- `Resumen personalizado`: columnas elegidas, con un conjunto predeterminado si no se elige ninguna.
- `SIGA completo`: reconstruye las 41 columnas usando `datos_fuente` y reemplaza las posiciones mapeadas con valores efectivos.

La exportación respeta filtros, se genera en bloques de 500, guarda el XLSX en base y publica progreso.

## 15. Reglas de recuperación y arranque

Al arrancar:

1. se crean tablas faltantes;
2. se aplican adecuaciones de esquema e índices;
3. se crea el administrador inicial si falta;
4. se reactivan y reclasifican bienes antiguos de Control Impresión;
5. se recalculan totales de inventario;
6. se reconcilian solicitudes de todas las campañas;
7. se reanudan validaciones patrimoniales `Validando` si conservan archivo;
8. se reanudan confirmaciones `Procesando`;
9. se reanudan exportaciones `Pendiente` o `Procesando`.

Si una validación pendiente ya no tiene binario, queda `Interrumpida` con mensaje de archivo temporal no disponible.

## 16. Límites y convenciones que no deben alterarse sin decisión funcional

- La pecosa es única globalmente, no por año.
- El Control Impresión es acumulativo y conserva ausentes.
- El Maestro Patrimonial también conserva los `No incluido`.
- La regla de área DIRESA solo afecta Control Impresión.
- La Impresión QR histórica conserva el establecimiento del centro de costo.
- Solicitudes activas no deben duplicarse entre inventariadores.
- Una reimpresión requiere confirmación explícita.
- QR duplicado en Control Impresión bloquea el lote.
- QR duplicado en Maestro Patrimonial es alerta y permite confirmar.
- Los archivos y credenciales no se suben a Git.
