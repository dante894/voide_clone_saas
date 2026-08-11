"""
Migración liviana para bases de datos que ya estaban desplegadas ANTES de
agregar login con Google, admin y estadísticas de visitas.

`db.create_all()` (lo que corre `app.py` al arrancar) crea tablas nuevas
solas, pero NO modifica una tabla `users` que ya existía. Este script agrega
las columnas que faltan de forma segura (no rompe nada si ya están).

Uso (con la misma DATABASE_URL que usa tu app en Render):
    export DATABASE_URL="postgresql://..."
    python scripts/migrate_db.py

Si tu app es nueva y todavía no tiene usuarios reales, no hace falta correr
esto: alcanza con dejar que `db.create_all()` cree todo desde cero (o, en
local con SQLite, simplemente borrar `local.db` y dejar que se regenere).
"""

import os
import sys

from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("Falta DATABASE_URL en el entorno.")
    sys.exit(1)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
inspector = inspect(engine)

if "users" not in inspector.get_table_names():
    print("La tabla 'users' todavía no existe: no hay nada que migrar "
          "(dejá que create_all() la genere desde cero).")
    sys.exit(0)

existing_columns = {c["name"] for c in inspector.get_columns("users")}
is_sqlite = engine.dialect.name == "sqlite"

statements = []

if "oauth_provider" not in existing_columns:
    statements.append("ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(20)")
if "oauth_id" not in existing_columns:
    statements.append("ALTER TABLE users ADD COLUMN oauth_id VARCHAR(255)")
if "is_admin" not in existing_columns:
    default = "0" if is_sqlite else "FALSE"
    statements.append(f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT {default}")

# password_hash: los usuarios de Google no tienen contraseña, así que la
# columna necesita permitir NULL. SQLite no soporta modificar una columna
# existente con ALTER TABLE; si estás en SQLite local, lo más simple es
# borrar el archivo .db y dejar que se regenere (no hay usuarios reales que
# perder en desarrollo).
if not is_sqlite:
    statements.append("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")

if not statements:
    print("La tabla 'users' ya tiene todas las columnas nuevas. Nada para hacer.")
else:
    with engine.begin() as conn:
        for stmt in statements:
            print("Ejecutando:", stmt)
            conn.execute(text(stmt))
    print(f"Listo: se aplicaron {len(statements)} cambio(s) a la tabla 'users'.")

# --- Columnas de tamaño para el cálculo de almacenamiento usado ---
extra_statements = []

if "voices" in inspector.get_table_names():
    voice_columns = {c["name"] for c in inspector.get_columns("voices")}
    if "size_bytes" not in voice_columns:
        extra_statements.append("ALTER TABLE voices ADD COLUMN size_bytes BIGINT NOT NULL DEFAULT 0")

if "jobs" in inspector.get_table_names():
    job_columns = {c["name"] for c in inspector.get_columns("jobs")}
    if "output_size_bytes" not in job_columns:
        extra_statements.append("ALTER TABLE jobs ADD COLUMN output_size_bytes BIGINT NOT NULL DEFAULT 0")

if extra_statements:
    with engine.begin() as conn:
        for stmt in extra_statements:
            print("Ejecutando:", stmt)
            conn.execute(text(stmt))
    print(f"Listo: se aplicaron {len(extra_statements)} cambio(s) a 'voices'/'jobs'.")
    print("Nota: las voces y audios que ya existían quedan con tamaño 0 hasta que")
    print("se vuelvan a subir/generar (no afecta su funcionamiento, solo el cálculo")
    print("de almacenamiento usado que se muestra en /cuenta).")
else:
    print("'voices' y 'jobs' ya tienen las columnas de tamaño. Nada para hacer.")

print("\nAhora corré tu app normalmente: al arrancar, db.create_all() va a "
      "crear las tablas nuevas (login_events, page_views) si todavía no existen.")
