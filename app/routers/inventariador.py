"""Vista única para que el inventariador solicite stickers por código QR."""
from datetime import datetime
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth import ROL_INVENTARIADOR, requiere_login
from app.database import get_db
from app.models import (
    InventarioImpresion,
    ItemSolicitudImpresionInventario,
    SolicitudImpresionInventario,
)
from app.services.solicitudes_impresion import (
    ESTADO_SINCRONIZACION,
    actualizar_estado_solicitud,
    crear_solicitud,
    normalizar_lista_qr,
    validar_qrs_solicitud,
)


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
MAX_QR_SOLICITUD = 500


def _sesion_inventariador(request: Request):
    sesion = requiere_login(request)
    if sesion.get("rol") != ROL_INVENTARIADOR:
        raise HTTPException(status_code=403, detail="Vista exclusiva para inventariadores.")
    return sesion


def _contexto_portal(
    request: Request,
    db: Session,
    resultados=None,
    texto_qr: str = "",
):
    inventario = db.query(InventarioImpresion).order_by(
        InventarioImpresion.anio.desc(), InventarioImpresion.id.desc()
    ).first()
    usuario_id = request.session["usuario_id"]
    solicitudes = []
    if inventario:
        solicitudes = (
            db.query(SolicitudImpresionInventario)
            .options(
                selectinload(SolicitudImpresionInventario.items)
                .joinedload(ItemSolicitudImpresionInventario.bien)
            )
            .filter(
                SolicitudImpresionInventario.inventario_id == inventario.id,
                SolicitudImpresionInventario.usuario_id == usuario_id,
            )
            .order_by(SolicitudImpresionInventario.id.desc())
            .limit(100)
            .all()
        )
    return {
        "request": request,
        "inventario": inventario,
        "solicitudes": solicitudes,
        "resultados": resultados,
        "texto_qr": texto_qr,
        "max_qr": MAX_QR_SOLICITUD,
        "listos": sum(
            1 for solicitud in solicitudes
            if solicitud.estado.startswith("Listo para recojo")
        ),
        "esperando": sum(
            1 for solicitud in solicitudes for item in solicitud.items
            if item.estado == ESTADO_SINCRONIZACION
        ),
    }


@router.get("/inventariador", response_class=HTMLResponse)
def portal_inventariador(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(_sesion_inventariador),
):
    return templates.TemplateResponse(
        "inventariador.html", _contexto_portal(request, db)
    )


@router.post("/inventariador/validar", response_class=HTMLResponse)
def validar_solicitud_inventariador(
    request: Request,
    codigos_qr: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(_sesion_inventariador),
):
    inventario = db.query(InventarioImpresion).order_by(
        InventarioImpresion.anio.desc(), InventarioImpresion.id.desc()
    ).first()
    if inventario is None:
        return RedirectResponse(
            "/inventariador?error=" + quote_plus("Aún no existe un inventario cargado."),
            status_code=303,
        )
    codigos = normalizar_lista_qr(codigos_qr)
    if not codigos:
        return RedirectResponse(
            "/inventariador?error=" + quote_plus("Ingresa al menos un código QR."),
            status_code=303,
        )
    if len(codigos) > MAX_QR_SOLICITUD:
        return RedirectResponse(
            "/inventariador?error=" + quote_plus(
                f"El máximo por solicitud es {MAX_QR_SOLICITUD} códigos QR."
            ), status_code=303,
        )
    resultados = validar_qrs_solicitud(db, inventario.id, codigos)
    return templates.TemplateResponse(
        "inventariador.html",
        _contexto_portal(request, db, resultados=resultados, texto_qr="\n".join(codigos)),
    )


@router.post("/inventariador/solicitudes")
def enviar_solicitud_inventariador(
    request: Request,
    inventario_id: int = Form(...),
    codigos_qr: str = Form(...),
    reimpresiones: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    _=Depends(_sesion_inventariador),
):
    inventario = db.get(InventarioImpresion, inventario_id)
    if inventario is None:
        raise HTTPException(status_code=404, detail="Inventario no encontrado.")
    codigos = normalizar_lista_qr(codigos_qr)
    if not codigos or len(codigos) > MAX_QR_SOLICITUD:
        return RedirectResponse(
            "/inventariador?error=" + quote_plus("La lista de QR no es válida."),
            status_code=303,
        )
    solicitud = crear_solicitud(
        db,
        inventario.id,
        request.session["usuario_id"],
        codigos,
        set(normalizar_lista_qr(" ".join(reimpresiones))),
    )
    return RedirectResponse(
        "/inventariador?info=" + quote_plus(
            f"Solicitud #{solicitud.id} enviada con {len(solicitud.items)} QR."
        ),
        status_code=303,
    )


@router.post("/inventariador/solicitudes/{solicitud_id}/recoger")
def marcar_solicitud_recogida(
    solicitud_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(_sesion_inventariador),
):
    solicitud = (
        db.query(SolicitudImpresionInventario)
        .options(selectinload(SolicitudImpresionInventario.items))
        .filter(
            SolicitudImpresionInventario.id == solicitud_id,
            SolicitudImpresionInventario.usuario_id == request.session["usuario_id"],
        )
        .first()
    )
    if solicitud is None:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    listos = [item for item in solicitud.items if item.estado == "Listo para recojo"]
    if not listos:
        return RedirectResponse(
            "/inventariador?error=" + quote_plus(
                "La solicitud todavía no tiene stickers listos para recoger."
            ), status_code=303,
        )
    ahora = datetime.utcnow()
    for item in listos:
        item.estado = "Recogido"
        item.recogido_en = ahora
    actualizar_estado_solicitud(solicitud)
    db.commit()
    return RedirectResponse(
        "/inventariador?info=" + quote_plus(
            f"Se confirmó el recojo de {len(listos)} sticker(s)."
        ), status_code=303,
    )
