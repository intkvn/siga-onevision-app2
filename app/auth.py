"""
Login de un solo usuario. No hay tabla de usuarios en la base de datos:
el usuario y la contraseña viven en las variables de entorno
(APP_USERNAME / APP_PASSWORD) y se comparan aquí.
"""
from passlib.context import CryptContext
from fastapi import Request, HTTPException
from app.config import APP_USERNAME, APP_PASSWORD

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Se calcula una sola vez al iniciar la app
_PASSWORD_HASH = pwd_context.hash(APP_PASSWORD)


def verificar_credenciales(username: str, password: str) -> bool:
    if username != APP_USERNAME:
        return False
    return pwd_context.verify(password, _PASSWORD_HASH)


def requiere_login(request: Request):
    """Dependencia de FastAPI: se agrega a cada ruta que necesite
    que el usuario haya iniciado sesión."""
    if not request.session.get("logueado"):
        raise HTTPException(status_code=303, headers={"Location": "/login"})
