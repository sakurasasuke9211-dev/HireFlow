import logging
from datetime import datetime
from typing import Any

from hireflow_api.config import ROOT_DIR, settings

logger = logging.getLogger(__name__)
from hireflow_api.models import RowModel

SQL_DIR = ROOT_DIR / "infra" / "sql"
REQUIRED_TABLE = "orgs"

_client = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def to_row(model: RowModel) -> dict[str, Any]:
    return {key: _jsonable(value) for key, value in model.model_dump().items()}


async def get_client():
    global _client
    if _client is None:
        if not settings.supabase_configured:
            raise RuntimeError(
                "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        from supabase import acreate_client

        _client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


def _apply_filters(query, filters: dict[str, Any]):
    for key, value in filters.items():
        query = query.eq(key, value)
    return query


async def fetch_one(table: str, **filters: Any) -> dict[str, Any] | None:
    client = await get_client()
    query = _apply_filters(client.table(table).select("*"), filters).limit(1)
    result = await query.execute()
    rows = result.data or []
    return rows[0] if rows else None


async def fetch_many(
    table: str,
    *,
    order: str | None = None,
    desc: bool = False,
    limit: int | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    client = await get_client()
    query = _apply_filters(client.table(table).select("*"), filters)
    if order:
        query = query.order(order, desc=desc)
    if limit is not None:
        query = query.limit(limit)
    result = await query.execute()
    return result.data or []


async def fetch_in(
    table: str,
    column: str,
    values: list[Any],
    *,
    order: str | None = None,
    desc: bool = False,
    **filters: Any,
) -> list[dict[str, Any]]:
    if not values:
        return []
    client = await get_client()
    query = _apply_filters(client.table(table).select("*"), filters).in_(column, values)
    if order:
        query = query.order(order, desc=desc)
    result = await query.execute()
    return result.data or []


async def count_rows(table: str, **filters: Any) -> int:
    client = await get_client()
    query = _apply_filters(client.table(table).select("id", count="exact"), filters)
    result = await query.execute()
    return int(result.count or 0)


async def insert_row(table: str, payload: dict[str, Any] | RowModel) -> dict[str, Any]:
    client = await get_client()
    row = to_row(payload) if isinstance(payload, RowModel) else {key: _jsonable(value) for key, value in payload.items()}
    result = await client.table(table).insert(row).execute()
    data = result.data or []
    if not data:
        raise RuntimeError(f"insert into {table} returned no row")
    return data[0]


async def insert_rows(table: str, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not payloads:
        return []
    client = await get_client()
    rows = [{key: _jsonable(value) for key, value in item.items()} for item in payloads]
    result = await client.table(table).insert(rows).execute()
    return result.data or []


async def update_rows(table: str, payload: dict[str, Any], **filters: Any) -> list[dict[str, Any]]:
    if not filters:
        raise ValueError(f"refusing to update {table} without filters")
    client = await get_client()
    row = {key: _jsonable(value) for key, value in payload.items()}
    query = _apply_filters(client.table(table).update(row), filters)
    result = await query.execute()
    return result.data or []


async def delete_rows(table: str, **filters: Any) -> None:
    if not filters:
        raise ValueError(f"refusing to delete {table} without filters")
    client = await get_client()
    await _apply_filters(client.table(table).delete(), filters).execute()


def _sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        buf.append(raw_line)
        if line.endswith(";"):
            statement = "\n".join(buf).strip().rstrip(";")
            if statement:
                statements.append(statement)
            buf = []
    leftover = "\n".join(buf).strip().rstrip(";")
    if leftover:
        statements.append(leftover)
    return statements


async def apply_schema() -> None:
    if not settings.supabase_db_url:
        return
    import asyncpg

    conn = await asyncpg.connect(
        settings.supabase_db_url,
        statement_cache_size=0,
        ssl="require" if "supabase.co" in settings.supabase_db_url else False,
    )
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            for statement in _sql_statements(sql):
                await conn.execute(statement)
    finally:
        await conn.close()


async def init_db() -> None:
    if not settings.supabase_configured:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env."
        )
    await apply_schema()
    from hireflow_api.storage import ensure_bucket

    await ensure_bucket()
    try:
        await fetch_many(REQUIRED_TABLE, limit=1)
    except Exception as exc:
        raise RuntimeError(
            "Supabase tables are missing. Run infra/sql/001_phase0.sql through 009_phase6.sql "
            "in the Supabase SQL editor, or set SUPABASE_DB_URL so the API can apply them."
        ) from exc
    try:
        await fetch_many("match_results", limit=1)
    except Exception as exc:
        raise RuntimeError(
            "Phase 2 tables are missing. Run infra/sql/004_phase2.sql in the Supabase SQL editor."
        ) from exc
    try:
        await fetch_many("interview_plans", limit=1)
    except Exception as exc:
        raise RuntimeError(
            "Phase 3 tables are missing. Run infra/sql/006_phase3.sql in the Supabase SQL editor."
        ) from exc
    try:
        await fetch_many("transcripts", limit=1)
    except Exception as exc:
        raise RuntimeError(
            "Phase 4 tables are missing. Run infra/sql/007_phase4.sql in the Supabase SQL editor."
        ) from exc
    try:
        await fetch_many("decisions", limit=1)
    except Exception as exc:
        raise RuntimeError(
            "Phase 5 tables are missing. Run infra/sql/008_phase5.sql in the Supabase SQL editor."
        ) from exc
    try:
        await fetch_many("file_assistant_requests", limit=1)
    except Exception:
        logger.warning(
            "Phase 6 table file_assistant_requests is missing. "
            "Run infra/sql/009_phase6.sql in the Supabase SQL editor. "
            "File assistant works; request history will not persist until then."
        )
