from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    """Create tables. Called on startup; safe to call repeatedly."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    _upgrade_schema()


def _upgrade_schema() -> None:
    """
    Add columns that create_all() will not: it only creates missing tables, so a
    persistent database made before a column existed would break every query.
    Nullable additions are safe to apply as plain ADD COLUMN on SQLite/PostgreSQL.
    """
    added = {"photo_url": "VARCHAR(2000)"}

    existing = {column["name"] for column in inspect(engine).get_columns("contacts")}
    _migrate_flat_addresses(existing)
    for name, ddl_type in added.items():
        if name in existing:
            continue
        try:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE contacts ADD COLUMN {name} {ddl_type}"))
        except DatabaseError:
            # Another worker added the column between our check and the ALTER;
            # verify that is what happened rather than swallowing a real failure.
            still_missing = name not in {
                column["name"] for column in inspect(engine).get_columns("contacts")
            }
            if still_missing:
                raise


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_LEGACY_ADDRESS_COLUMNS = ("address", "city", "state", "postal_code", "country")


def _migrate_flat_addresses(contact_columns: set[str]) -> None:
    """
    Move pre-normalization flat address columns into the addresses table.

    Runs per contact and is idempotent: a contact's flat values are copied only
    while that contact has no address rows, and copied values are cleared in the
    same transaction, so re-running at every startup is a no-op and an
    explicitly emptied address list is never resurrected from stale columns.
    """
    if not all(column in contact_columns for column in _LEGACY_ADDRESS_COLUMNS):
        return

    has_flat_values = (
        "COALESCE(address, '') != '' OR COALESCE(city, '') != '' "
        "OR COALESCE(state, '') != '' OR COALESCE(postal_code, '') != '' "
        "OR COALESCE(country, '') != ''"
    )

    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            # Serialize concurrent workers; SQLite already serializes writers.
            connection.execute(text("LOCK TABLE addresses IN EXCLUSIVE MODE"))
        connection.execute(
            text(
                "INSERT INTO addresses (contact_id, type, address, city, state, postal_code, country) "
                f"SELECT id, 'home', address, city, state, postal_code, country FROM contacts "
                f"WHERE ({has_flat_values}) "
                "AND NOT EXISTS (SELECT 1 FROM addresses WHERE addresses.contact_id = contacts.id)"
            )
        )
        connection.execute(
            text(
                "UPDATE contacts SET address = NULL, city = NULL, state = NULL, "
                "postal_code = NULL, country = NULL "
                f"WHERE ({has_flat_values}) AND EXISTS ("
                "SELECT 1 FROM addresses WHERE addresses.contact_id = contacts.id "
                "AND addresses.type = 'home' "
                "AND COALESCE(addresses.address, '') = COALESCE(contacts.address, '') "
                "AND COALESCE(addresses.city, '') = COALESCE(contacts.city, '') "
                "AND COALESCE(addresses.state, '') = COALESCE(contacts.state, '') "
                "AND COALESCE(addresses.postal_code, '') = COALESCE(contacts.postal_code, '') "
                "AND COALESCE(addresses.country, '') = COALESCE(contacts.country, ''))"
            )
        )
