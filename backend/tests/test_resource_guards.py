from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import BoundedSemaphore, Event, Lock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db as database, main


def test_connections_are_bounded_and_slots_recover(monkeypatch):
    monkeypatch.setattr(database, "connection_slots", BoundedSemaphore(2))
    monkeypatch.setenv("DB_ACQUIRE_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setenv("DATABASE_URL", "test-only-private-dsn")
    release, occupied = Event(), Event()
    lock = Lock()
    counts = {"current": 0, "peak": 0}

    @contextmanager
    def connect(dsn, **kwargs):
        assert kwargs["connect_timeout"] == 5 and "statement_timeout=30000" in kwargs["options"]
        with lock:
            counts["current"] += 1
            counts["peak"] = max(counts["peak"], counts["current"])
            if counts["current"] == 2:
                occupied.set()
        try:
            yield object()
        finally:
            with lock:
                counts["current"] -= 1

    monkeypatch.setattr(database.psycopg, "connect", connect)

    def hold():
        with database.db():
            assert release.wait(2)

    with ThreadPoolExecutor(max_workers=2) as threads:
        pending = [threads.submit(hold) for _ in range(2)]
        try:
            assert occupied.wait(2)
            with pytest.raises(database.DatabaseBusy):
                with database.db():
                    pass
        finally:
            release.set()
        for future in pending:
            future.result()
    with database.db():
        pass
    assert counts == {"current": 0, "peak": 2}


def test_connect_failure_does_not_leak_a_slot(monkeypatch):
    monkeypatch.setattr(database, "connection_slots", BoundedSemaphore(1))
    monkeypatch.setenv("DATABASE_URL", "test-only-private-dsn")

    def failed(*args, **kwargs):
        raise psycopg.OperationalError("private-dsn")

    monkeypatch.setattr(database.psycopg, "connect", failed)
    for _ in range(2):
        with pytest.raises(psycopg.OperationalError):
            with database.db():
                pass


@pytest.mark.parametrize("error", [database.DatabaseBusy, psycopg.OperationalError,
                                  psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable])
def test_db_overload_is_retryable_and_redacted(monkeypatch, error):
    @contextmanager
    def failed():
        raise error("private-dsn-and-query")
        yield

    monkeypatch.setattr(main, "db", failed)
    response = TestClient(main.app).get("/api/health")
    assert response.status_code == 503 and response.headers["Retry-After"] == "2"
    assert response.headers["Cache-Control"] == "no-store" and "private" not in response.text


def test_real_statement_deadline_and_release(monkeypatch):
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "50")
    with pytest.raises(psycopg.errors.QueryCanceled):
        with database.db() as conn:
            conn.execute("SELECT pg_sleep(0.2)")
    with database.db() as conn:
        assert conn.execute("SELECT 1 AS n").fetchone()["n"] == 1
