"""Administración de las cuentas internas de la aplicación."""
from datetime import datetime
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    ROL_ADMINISTRADOR,
    ROL_INVENTARIADOR,
    actualizar_password,
    crear_hash_password,
    normalizar_username,
    requiere_administrador,
)
from app.database import get_db
from app.models import UsuarioAplicacion


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
ROLES = (ROL_ADMINISTRADOR, ROL_INVENTARIADOR)


def _volver(mensaje: str, tipo: str = "info") -> RedirectResponse:
    return RedirectResponse(
        url=f"/usuarios?{tipo}={quote_plus(mensaje)}", status_code=303
    )


@router.get("/usuarios", response_class=HTMLResponse)
def listar_usuarios(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    usuarios = db.query(UsuarioAplicacion).order_by(
        UsuarioAplicacion.rol, UsuarioAplicacion.nombre_completo
    ).all()
    return templates.TemplateResponse(
        "usuarios.html",
        {"request": request, "usuarios": usuarios, "roles": ROLES},
    )


@router.post("/usuarios")
def crear_usuario(
    nombre_completo: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    rol: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    username = normalizar_username(username)
    nombre_completo = " ".join(nombre_completo.strip().split())
    if not username or not nombre_completo:
        return _volver("Completa el nombre y el usuario.", "error")
    if rol not in ROLES:
        raise HTTPException(status_code=400, detail="Rol no válido.")
    if len(password) < 8:
        return _volver("La contraseña debe tener al menos 8 caracteres.", "error")
    if db.query(UsuarioAplicacion).filter_by(username=username).first():
        return _volver("Ese nombre de usuario ya existe.", "error")
    db.add(UsuarioAplicacion(
        nombre_completo=nombre_completo,
        username=username,
        password_hash=crear_hash_password(password),
        rol=rol,
        activo=1,
    ))
    db.commit()
    return _volver("Usuario creado correctamente.")


@router.post("/usuarios/{usuario_id}/editar")
def editar_usuario(
    usuario_id: int,
    request: Request,
    nombre_completo: str = Form(...),
    rol: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    usuario = db.get(UsuarioAplicacion, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    nombre_completo = " ".join(nombre_completo.strip().split())
    if not nombre_completo or rol not in ROLES:
        return _volver("Nombre o rol no válido.", "error")
    if (
        usuario.id == request.session.get("usuario_id")
        and rol != ROL_ADMINISTRADOR
    ):
        return _volver("No puedes retirar tu propio rol de administrador.", "error")
    usuario.nombre_completo = nombre_completo
    usuario.rol = rol
    usuario.actualizado_en = datetime.utcnow()
    db.commit()
    return _volver("Usuario actualizado.")


@router.post("/usuarios/{usuario_id}/password")
def cambiar_password_usuario(
    usuario_id: int,
    password: str = Form(...),
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    usuario = db.get(UsuarioAplicacion, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if len(password) < 8:
        return _volver("La contraseña debe tener al menos 8 caracteres.", "error")
    actualizar_password(usuario, password)
    db.commit()
    return _volver(f"Contraseña de {usuario.username} actualizada.")


@router.post("/usuarios/{usuario_id}/estado")
def cambiar_estado_usuario(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(requiere_administrador),
):
    usuario = db.get(UsuarioAplicacion, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    if usuario.id == request.session.get("usuario_id") and usuario.activo:
        return _volver("No puedes desactivar tu propia cuenta.", "error")
    if usuario.rol == ROL_ADMINISTRADOR and usuario.activo:
        administradores = db.query(UsuarioAplicacion).filter_by(
            rol=ROL_ADMINISTRADOR, activo=1
        ).count()
        if administradores <= 1:
            return _volver("Debe quedar al menos un administrador activo.", "error")
    usuario.activo = 0 if usuario.activo else 1
    usuario.actualizado_en = datetime.utcnow()
    db.commit()
    return _volver("Estado del usuario actualizado.")
