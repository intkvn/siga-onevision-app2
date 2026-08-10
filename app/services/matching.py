"""
Cruza cada fila del reporte SIGA ya filtrado contra los maestros de
Persona (por nombre_completo) y CentroCosto (por nombre_depend),
para obtener el DNI y el IPRESS que exige el Formato de Importación.

Cuando no encuentra coincidencia exacta, NO inventa nada: marca la
fila como "sin cruce" para que la corrijas manualmente desde la app
(sección 6.3 de los requerimientos: corregir manualmente o registrar
un nuevo trabajador / centro de costo).
"""
from sqlalchemy.orm import Session
from app.models import Persona, CentroCosto


def _normalizar(texto: str) -> str:
    return " ".join(str(texto).strip().upper().split()) if texto else ""


def buscar_persona(db: Session, nombre_completo: str) -> Persona | None:
    objetivo = _normalizar(nombre_completo)
    for persona in db.query(Persona).all():
        if _normalizar(persona.nombre_completo) == objetivo:
            return persona
    return None


def buscar_centro_costo(db: Session, nombre_depend: str) -> CentroCosto | None:
    objetivo = _normalizar(nombre_depend)
    for centro in db.query(CentroCosto).all():
        if _normalizar(centro.nombre_depend) == objetivo:
            return centro
    return None


def cruzar_fila(db: Session, nombre_completo: str, nombre_depend: str) -> dict:
    """Devuelve el resultado del cruce para una fila del reporte SIGA."""
    persona = buscar_persona(db, nombre_completo)
    centro = buscar_centro_costo(db, nombre_depend)
    return {
        "persona": persona,
        "centro_costo": centro,
        "cruce_completo": persona is not None and centro is not None,
    }
