"""Initialize only the isolated Windows development database."""

import importlib
import os
from pathlib import Path
import pkgutil
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
os.chdir(root / "backend")
from dotenv import dotenv_values

os.environ.update(
    {k: v for k, v in dotenv_values(root / ".env.local").items() if v is not None}
)
from sqlalchemy import inspect, text
from app.core.database import Base, SessionLocal, engine
from app.core.security import get_password_hash
import app.models
from app.models.user import User

if engine.url.host != "127.0.0.1" or engine.url.database != "okk_quant_dev":
    raise RuntimeError("This initializer only accepts the local okk_quant_dev database")
for module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{module.name}")
Base.metadata.create_all(engine)
with SessionLocal() as db:
    if not db.query(User).filter(User.username == "admin").first():
        db.add(
            User(
                username="admin",
                hashed_password=get_password_hash(os.environ["DEV_ADMIN_PASSWORD"]),
                is_active=True,
                is_superuser=True,
            )
        )
        db.commit()
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
print(
    f"Local database ready: {len(inspect(engine).get_table_names())} tables; admin account ready"
)
