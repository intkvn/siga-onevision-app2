"""Operaciones masivas portables para evitar un UPDATE por cada registro."""
from __future__ import annotations

from sqlalchemy import case, update
from sqlalchemy.orm import Session


def actualizar_mapeos_por_id(
    db: Session,
    modelo,
    mapeos: list[dict],
    tamano_lote: int = 500,
) -> None:
    """Actualiza varios registros con una sentencia SQL por bloque.

    ``bulk_update_mappings`` usa ``executemany`` para UPDATE y puede provocar un
    viaje de red por fila según el controlador. Los CASE concentran el bloque
    en una sola sentencia y mantienen la misma transacción.
    """
    if not mapeos:
        return
    for inicio in range(0, len(mapeos), tamano_lote):
        lote = mapeos[inicio:inicio + tamano_lote]
        ids = [fila["id"] for fila in lote]
        campos = [campo for campo in lote[0] if campo != "id"]
        valores = {
            campo: case(
                {fila["id"]: fila[campo] for fila in lote},
                value=modelo.id,
                else_=getattr(modelo, campo),
            )
            for campo in campos
        }
        db.execute(
            update(modelo).where(modelo.id.in_(ids)).values(valores)
        )
