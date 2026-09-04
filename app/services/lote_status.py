"""Utilidades compartidas entre Normalización e Impresión para calcular
el estado de un lote y a qué expedientes corresponde, sin tener que
guardar esa información aparte (se calcula a partir de lo que ya hay
en la base de datos)."""
from app.models import Pecosa, Expediente


def _numeros_solicitados(lote) -> list[str]:
    if not lote.pecosas_solicitadas:
        return []
    return [numero for numero in lote.pecosas_solicitadas.split(",") if numero]


def expedientes_de_lotes(db, lotes) -> dict[int, list[str]]:
    """Obtiene los expedientes de varios lotes con una sola consulta.

    Normalización e Impresión muestran muchos lotes a la vez. Consultar cada
    lote de forma independiente se vuelve lento cuando la base está remota.
    """
    numeros_por_lote = {
        lote.id: _numeros_solicitados(lote)
        for lote in lotes
    }
    numeros = {
        numero
        for solicitadas in numeros_por_lote.values()
        for numero in solicitadas
    }
    if not numeros:
        return {lote_id: [] for lote_id in numeros_por_lote}

    filas = (
        db.query(Pecosa.numero, Expediente.numero)
        .join(Pecosa, Pecosa.expediente_id == Expediente.id)
        .filter(Pecosa.numero.in_(numeros))
        .all()
    )
    expedientes_por_pecosa = {}
    for numero_pecosa, numero_expediente in filas:
        expedientes_por_pecosa.setdefault(numero_pecosa, set()).add(numero_expediente)

    return {
        lote_id: sorted({
            expediente
            for numero in solicitadas
            for expediente in expedientes_por_pecosa.get(numero, set())
        })
        for lote_id, solicitadas in numeros_por_lote.items()
    }


def expedientes_de_lote(db, lote) -> list[str]:
    """Devuelve los expedientes correspondientes a un lote."""
    return expedientes_de_lotes(db, [lote]).get(lote.id, [])
