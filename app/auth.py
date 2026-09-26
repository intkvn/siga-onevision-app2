"""Autenticación y autorización por roles para la aplicación."""
from datetime import datetime

from fastapi import HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import APP_PASSWORD, APP_USERNAME
from app.models import UsuarioAplicacion


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ROL_ADMINISTRADOR = "Administrador"
ROL_INVENTARIADOR = "Inventariador"


def normalizar_username(username: str) -> str:
    return str(username or "").strip().casefold()


def crear_hash_password(password: str) -> str:
    return pwd_context.hash(password)


def asegurar_usuario_administrador(db: Session) -> UsuarioAplicacion:
    """Crea una sola vez el administrador configurado en el entorno."""
    username = normalizar_username(APP_USERNAME)
    usuario = db.query(UsuarioAplicacion).filter(
        UsuarioAplicacion.username == username
    ).first()
    if usuario is None:
        usuario = UsuarioAplicacion(
            username=username,
            nombre_completo="Administrador",
            password_hash=crear_hash_password(APP_PASSWORD),
            rol=ROL_ADMINISTRADOR,
            activo=1,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
    return usuario


def verificar_credenciales(
    db: Session, username: str, password: str,
) -> UsuarioAplicacion | None:
    usuario = db.query(UsuarioAplicacion).filter(
        UsuarioAplicacion.username == normalizar_username(username),
        UsuarioAplicacion.activo == 1,
    ).first()
    if usuario is None or not pwd_context.verify(password, usuario.password_hash):
        return None
    return usuario


def guardar_sesion(request: Request, usuario: UsuarioAplicacion) -> None:
    request.session.clear()
    request.session.update({
        "logueado": True,
        "usuario_id": usuario.id,
        "usuario": usuario.username,
        "nombre_usuario": usuario.nombre_completo,
        "rol": usuario.rol,
    })


def requiere_login(request: Request):
    if not request.session.get("logueado"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if not request.session.get("usuario_id") or not request.session.get("rol"):
        request.session.clear()
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    if (
        request.session.get("rol") == ROL_INVENTARIADOR
        and not request.url.path.startswith("/inventariador")
    ):
        raise HTTPException(
            status_code=303, headers={"Location": "/inventariador"}
        )
    return request.session


def requiere_administrador(request: Request):
    sesion = requiere_login(request)
    if sesion.get("rol") != ROL_ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Acceso solo para administradores.")
    return sesion


def actualizar_password(usuario: UsuarioAplicacion, password: str) -> None:
    usuario.password_hash = crear_hash_password(password)
    usuario.actualizado_en = datetime.utcnow()
