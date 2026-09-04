#!/usr/bin/env python3
"""Copia la base local SQLite a una base PostgreSQL vacía de Neon.

Uso:
    NEON_DATABASE_URL='postgresql://...' \
        .venv/bin/python scripts/migrar_sqlite_a_neon.py --source /ruta/respaldo.db

La herramienta se niega a escribir si la base de destino ya contiene datos.
No elimina ni altera la base SQLite de origen.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Permite ejecutar este archivo directamente desde la carpeta scripts.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

# Importar los modelos registra todas las tablas en Base.metadata.
from app.database import Base
import app.models  # noqa: F401


def normalizar_url_postgres(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def contar_tablas(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            tabla.name: conn.execute(select(func.count()).select_from(tabla)).scalar_one()
            for tabla in Base.metadata.sorted_tables
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migra una copia SQLite de SIGA One Visión a una base Neon vacía."
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="Ruta absoluta de la copia .db que se migrará.",
    )
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"No existe la copia SQLite indicada: {args.source}")

    target_url = os.getenv("NEON_DATABASE_URL")
    if not target_url:
        raise SystemExit(
            "Falta NEON_DATABASE_URL. Defínela solo en esta sesión antes de ejecutar la migración."
        )

    source_engine = create_engine(f"sqlite:///{args.source.resolve()}")
    target_engine = create_engine(
        normalizar_url_postgres(target_url), pool_pre_ping=True
    )

    try:
        Base.metadata.create_all(target_engine)
        counts_before = contar_tablas(target_engine)
        existing_rows = sum(counts_before.values())
        if existing_rows:
            detalle = ", ".join(
                f"{nombre}: {cantidad}"
                for nombre, cantidad in counts_before.items()
                if cantidad
            )
            raise SystemExit(
                "La base de Neon ya contiene datos. La migración se cancela para no "
                f"duplicarlos. Filas existentes: {detalle}"
            )

        with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
            for table in Base.metadata.sorted_tables:
                rows = source_conn.execute(select(table)).mappings().all()
                if rows:
                    target_conn.execute(table.insert(), [dict(row) for row in rows])

            # Ajusta las secuencias de identificadores para los próximos registros.
            for table in Base.metadata.sorted_tables:
                if "id" in table.c:
                    target_conn.execute(text(
                        "SELECT setval("
                        f"pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), true)"
                    ))

        source_counts = contar_tablas(source_engine)
        target_counts = contar_tablas(target_engine)
        if source_counts != target_counts:
            raise SystemExit(
                "La comprobación de cantidades no coincide. No inicies Render y "
                "revísalo antes de continuar."
            )

        print("Migración terminada y comprobada.")
        for table_name, count in source_counts.items():
            print(f"- {table_name}: {count}")
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
