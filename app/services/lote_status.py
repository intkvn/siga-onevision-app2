"""Utilidades compartidas entre Normalización e Impresión para calcular
el estado de un lote y a qué expedientes corresponde, sin tener que
guardar esa información aparte (se calcula a partir de lo que ya hay
en la base de datos)."""
from app.models import Pecosa, Expediente


def expedientes_de_lote(db, lote) -> list[str]:
    """Devuelve los números de expediente que corresponden a las pecosas
    que se marcaron para este lote (aunque algunas no se hayan encontrado
    todavía en el reporte)."""
    if not lote.pecosas_solicitadas:
        return []
    numeros = [p for p in lote.pecosas_solicitadas.split(",") if p]
    if not numeros:
        return []
    filas = (
        db.query(Expediente.numero)
        .join(Pecosa, Pecosa.expediente_id == Expediente.id)
        .filter(Pecosa.numero.in_(numeros))
        .distinct()
        .all()
    )
    return sorted({f[0] for f in filas})
