"""
Database setup and persistence. Uses asyncpg directly — no ORM.
"""

import os
import asyncpg


async def get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(os.environ["DATABASE_URL"])


async def init_db(conn: asyncpg.Connection) -> None:
    """Create tables if they don't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          BIGSERIAL       PRIMARY KEY,
            hash        VARCHAR(80)     NOT NULL UNIQUE,
            source_url  TEXT            NOT NULL UNIQUE,
            headline    TEXT            NOT NULL,
            reporters   TEXT[]          NOT NULL DEFAULT '{}',
            body_text   TEXT            NOT NULL,
            media_urls  JSONB           NOT NULL DEFAULT '[]'
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_hash
        ON articles USING hash (hash)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_articles_fts
        ON articles USING GIN(to_tsvector('english', headline || ' ' || body_text))
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS kg_elements (
            id           BIGSERIAL   PRIMARY KEY,
            article_hash VARCHAR(80) NOT NULL REFERENCES articles(hash) ON DELETE CASCADE,
            name         TEXT        NOT NULL,
            entity_type  VARCHAR(30) NOT NULL
                CHECK (entity_type IN ('PERSON','ORGANIZATION','LOCATION','COUNTRY','COMPANY','EVENT')),
            UNIQUE (article_hash, name, entity_type)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_elements_hash ON kg_elements (article_hash)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_elements_type ON kg_elements (entity_type)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_elements_name ON kg_elements (name)")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS kg_relations (
            id           BIGSERIAL   PRIMARY KEY,
            article_hash VARCHAR(80) NOT NULL REFERENCES articles(hash) ON DELETE CASCADE,
            subject_id   BIGINT      NOT NULL REFERENCES kg_elements(id) ON DELETE CASCADE,
            object_id    BIGINT      NOT NULL REFERENCES kg_elements(id) ON DELETE CASCADE,
            relation     VARCHAR(100) NOT NULL,
            UNIQUE (article_hash, subject_id, object_id, relation)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_relations_hash    ON kg_relations (article_hash)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_relations_subject ON kg_relations (subject_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_relations_object  ON kg_relations (object_id)")


async def already_ingested(conn: asyncpg.Connection, url: str) -> str | None:
    """Return the hash if this URL was already ingested, else None."""
    row = await conn.fetchrow("SELECT hash FROM articles WHERE source_url = $1", url)
    return row["hash"] if row else None


async def save_article(
    conn: asyncpg.Connection,
    source_url: str,
    source_name: str,
    publish_dt,
    headline: str,
    body_text: str,
    reporters: list[str],
    media_urls: list[dict],
) -> str:
    """
    Generate a unique hash and insert the article row. Returns the hash.
    Runs inside a transaction with FOR UPDATE to ensure unique sequences.
    """
    import json
    from datetime import datetime

    now = datetime.utcnow()
    effective_dt = publish_dt or now
    date_str = effective_dt.strftime("%d%m%Y")
    time_str = effective_dt.strftime("%H%M%S") if publish_dt else "000000"
    prefix = f"{source_name}-{date_str}-{time_str}"

    async with conn.transaction():
        # Lock matching rows to safely determine next sequence number
        rows = await conn.fetch(
            "SELECT id FROM articles WHERE hash LIKE $1 FOR UPDATE",
            f"{prefix}-%",
        )
        sequence = len(rows) + 1
        hash = f"{prefix}-{sequence:03d}"

        await conn.execute(
            """
            INSERT INTO articles (hash, source_url, headline, reporters, body_text, media_urls)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            hash,
            source_url,
            headline,
            reporters,
            body_text,
            json.dumps(media_urls),
        )

    return hash


async def save_elements_and_relations(
    conn: asyncpg.Connection,
    article_hash: str,
    elements: list[dict],
    relations: list[dict],
) -> None:
    """Upsert elements then relations."""
    name_to_id: dict[str, int] = {}

    for elem in elements:
        name = elem["name"].strip()
        entity_type = elem["entity_type"].upper()
        row = await conn.fetchrow(
            """
            INSERT INTO kg_elements (article_hash, name, entity_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (article_hash, name, entity_type) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            article_hash, name, entity_type,
        )
        if row:
            name_to_id[name] = row["id"]

    for rel in relations:
        subject_id = name_to_id.get(rel["subject"])
        object_id = name_to_id.get(rel["object"])
        relation = rel["relation"].upper()

        if not subject_id or not object_id or not relation:
            continue

        await conn.execute(
            """
            INSERT INTO kg_relations (article_hash, subject_id, object_id, relation)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            """,
            article_hash, subject_id, object_id, relation,
        )
