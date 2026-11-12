from pathlib import Path

import pytest
from commerce_core.checkpoints import (
    checkpoint_dsn,
    open_checkpointer,
    prepare_checkpoint_storage,
)
from commerce_core.db import sqlite_file_path
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def test_checkpoint_dsn_strips_sqlalchemy_driver() -> None:
    dsn = checkpoint_dsn("postgresql+psycopg://u:p@host:5432/buyer_checkpoints")
    assert dsn == "postgresql://u:p@host:5432/buyer_checkpoints"


def test_checkpoint_dsn_rejects_sqlite() -> None:
    with pytest.raises(ValueError):
        checkpoint_dsn("sqlite+aiosqlite:///./data/checkpoints.db")


def test_sqlite_file_path_returns_path_for_sqlite_url() -> None:
    path = sqlite_file_path("sqlite+aiosqlite:////app/data/orchestrator.db")
    assert path == Path("/app/data/orchestrator.db")


def test_sqlite_file_path_returns_none_for_postgres() -> None:
    assert sqlite_file_path("postgresql+psycopg://u:p@host:5432/orchestrator") is None


def test_prepare_checkpoint_storage_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "checkpoints.db"
    prepare_checkpoint_storage(str(target))
    assert target.parent.is_dir()


def test_prepare_checkpoint_storage_is_a_noop_for_postgres(tmp_path: Path) -> None:
    prepare_checkpoint_storage("postgresql+psycopg://u:p@host:5432/db")
    # Nothing to assert beyond "does not raise"; PostgreSQL has no local storage.
    assert not list(tmp_path.iterdir())


async def test_open_checkpointer_selects_sqlite_for_a_path(tmp_path: Path) -> None:
    target = tmp_path / "checkpoints.db"
    async with open_checkpointer(str(target)) as saver:
        assert isinstance(saver, AsyncSqliteSaver)
    assert target.exists()
