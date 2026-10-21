"""Migrations must build exactly the schema the models describe.

TEST_POSTGRES_URL, if set, must point at a throwaway database: the test
downgrades it to an empty schema.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from structflow_api.models import Base

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _urls(tmp_path: Path) -> list[str]:
    urls = [f"sqlite+pysqlite:///{tmp_path / 'migrate.db'}"]
    if os.environ.get("TEST_POSTGRES_URL"):
        urls.append(os.environ["TEST_POSTGRES_URL"])
    return urls


@pytest.mark.parametrize("which", ["sqlite", "postgres"])
def test_upgrade_matches_models_and_downgrades(tmp_path, which):
    urls = _urls(tmp_path)
    if which == "postgres" and len(urls) == 1:
        pytest.skip("set TEST_POSTGRES_URL to run against Postgres")
    url = urls[0] if which == "sqlite" else urls[1]

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    command.downgrade(cfg, "base")
    engine.dispose()
