# Requerimientos pendientes

Este documento conserva requerimientos funcionales acordados que todavía no han sido implementados. Deben volver a revisarse antes de modificar el código o la base de datos.

## Carga Inventario 2026 y posterior

**Estado:** análisis pausado, pendiente de implementación.

**Nombre de referencia:** `Carga Inventario 2026 y posterior`.

Cuando el usuario solicite retomar este requerimiento, continuar el análisis desde las reglas registradas aquí y contrastarlas nuevamente con el código, la base de datos y el estado vigente de producción.

### Base confirmada

- La carga #1 actual contiene 39,225 activos fijos.
- Esta carga representa el inventario inicial completo de 2026.
- Los 39,225 bienes de esa carga deben quedar identificados de forma persistente como pertenecientes a `Inventario 2026`.

### Clasificación de cargas posteriores

- Un bien del inventario inicial que vuelva a aparecer en una carga posterior conserva su clasificación `Inventario 2026`, aunque se actualicen sus datos.
- Un bien que aparezca por primera vez después de la carga #1 debe clasificarse como `Posterior`.
- Los sobrantes mantienen además su clasificación existente `tipo_bien = Sobrante`.
- Para auditar el origen, el diseño propuesto debe registrar la carga en la que apareció cada bien por primera vez.

### Estados por establecimiento

1. Si quedan bienes del `Inventario 2026` sin imprimir, el estado es `Pendiente`.
2. Si todos los bienes del `Inventario 2026` están impresos y no hay bienes posteriores, el estado es `Completo Inventario 2026`.
3. Si todos los bienes del `Inventario 2026` están impresos y existen bienes posteriores pendientes, el estado sigue siendo `Completo Inventario 2026` y debe mostrarse adicionalmente la cantidad de `nuevos pendientes`.
4. Si están impresos tanto los bienes del `Inventario 2026` como todos los bienes posteriores activos, el estado es `Completo Total`.
5. Si un establecimiento no tiene bienes de la carga inicial y tiene bienes posteriores pendientes, debe mostrarse `Pendiente`, igual que los demás establecimientos.
6. Un bien bloqueado cuenta como no completado.
7. Una reimpresión no cambia por sí sola la clasificación de origen del bien.

### Información que debe mostrar el resumen

El resumen por establecimiento debe permitir distinguir al menos:

- avance del `Inventario 2026`;
- avance del universo total vigente;
- cantidad de bienes posteriores pendientes;
- estado resultante;
- fecha en que se completó el inventario inicial;
- fecha en que se completó el total, cuando corresponda.

Ejemplo:

```text
Inventario 2026: 500/500
Total actual: 500/503
Estado: Completo Inventario 2026
3 nuevos pendientes
```

Después de imprimir los tres bienes posteriores:

```text
Inventario 2026: 500/500
Total actual: 503/503
Estado: Completo Total
```

### Persistencia propuesta para revisar

La implementación debe evaluar campos equivalentes a:

- `carga_origen_id`: carga en la que el bien apareció por primera vez;
- `cohorte_impresion`: `Inventario 2026` o `Posterior`;
- identificación persistente de la carga base del inventario.

Los nombres definitivos y la migración deben revisarse antes de implementarlos.

### Consideraciones técnicas ya detectadas

- El modelo actual no guarda la carga de origen ni la cohorte de cada bien.
- Las actualizaciones actuales conservan el estado de impresión de un bien ya impreso.
- El resumen actual calcula los estados sobre la consulta filtrada. La implementación debe calcular el estado del establecimiento usando todos sus bienes activos, para que un filtro visual no produzca un estado completo incorrecto.
- Debe prepararse una migración para asociar los 39,225 bienes actuales con la carga #1 y la cohorte `Inventario 2026`.

### Pruebas pendientes

- migración de la carga #1 como inventario inicial;
- actualización posterior de un bien inicial sin cambiar su cohorte;
- incorporación de un activo fijo posterior;
- incorporación de un sobrante posterior;
- transición de `Pendiente` a `Completo Inventario 2026`;
- visualización de nuevos pendientes sin perder el estado `Completo Inventario 2026`;
- transición a `Completo Total`;
- establecimiento con solo bienes posteriores;
- bloqueo de un bien y efecto sobre el estado;
- orden por fecha de finalización;
- independencia entre los filtros visuales y el estado real del establecimiento.

