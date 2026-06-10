"""Shared pytest fixtures.

`temp_db` points the ORM at a throwaway SQLite file (so DB tests never touch the
real idea_machine.db), runs the migration, and resets the cached engine/session
factory around each test.
"""
import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import config
    from db import models

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{db_file}")
    # Force a fresh engine bound to the temp URL (the globals are cached).
    models._engine = None
    models._SessionFactory = None
    models.init_db()
    yield models
    models._engine = None
    models._SessionFactory = None
