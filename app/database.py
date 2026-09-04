from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

# Algunos proveedores entregan la URL como "postgres://..." y SQLAlchemy
# moderno exige "postgresql://..." — lo corregimos automáticamente.
db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Se usa en cada endpoint para obtener una sesión de base de datos
    y cerrarla automáticamente al terminar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
