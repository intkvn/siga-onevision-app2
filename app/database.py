from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

# Algunos proveedores entregan la URL como "postgres://..." y SQLAlchemy
# moderno exige "postgresql://..." — lo corregimos automáticamente.
db_url = DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)



def _opciones_engine(url: str) -> dict:
    """Configura SQLite local y protege PostgreSQL de conexiones vencidas."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    if url.startswith("postgresql"):
        return {
            "connect_args": {},
            "pool_pre_ping": True,
            "pool_recycle": 240,
        }
    return {"connect_args": {}}


engine = create_engine(db_url, **_opciones_engine(db_url))
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
