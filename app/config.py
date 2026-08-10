"""
Configuración central de la app.
Todo lo que puede cambiar entre "tu compu" y "Railway" vive aquí,
leído desde variables de entorno (el archivo .env en local, o las
variables que configures en el panel de Railway en producción).
"""
import os
from dotenv import load_dotenv

load_dotenv()  # en local, lee el archivo .env; en Railway no hace falta (usa sus variables)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_dev.db")
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-cambiar-en-produccion")

# Constantes del Formato de Importación a One Visión
EJECUTORA = os.getenv("EJECUTORA", "785")
ANIO_INVENTARIO = os.getenv("ANIO_INVENTARIO", "2026")

# Tabla de equivalencia de Estado (SIGA estado_conserv -> One Visión Estado)
ESTADOS = {
    "1": "Bueno",
    "2": "Regular",
    "3": "Malo",
    "4": "Muy Malo",
    "5": "Nuevo",
    "6": "Chatarra",
    "7": "RAEE",
}
