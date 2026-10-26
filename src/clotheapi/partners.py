"""店家憑證存在網站資料庫的 partnerapiclient。金鑰只存 SHA-256。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class PartnerStoreError(Exception):
    """資料庫連不上或資料表还不在。"""


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def normalize_database_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return f"postgresql+psycopg://{url[len(prefix):]}"
    return url


class PartnerDirectory:
    def __init__(self, database_url: str) -> None:
        self.engine = _engine(database_url)
        if self.engine.dialect.name == "sqlite":
            self.ensure_table()

    def ensure_table(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS partnerapiclient (
                        id VARCHAR NOT NULL PRIMARY KEY,
                        name VARCHAR NOT NULL,
                        key_hash VARCHAR NOT NULL,
                        revoked_at DATETIME,
                        created_at DATETIME NOT NULL,
                        UNIQUE (key_hash)
                    )
                    """
                )
            )

    def issue(self, name: str) -> tuple[str, str]:
        store_name = name.strip()
        if not store_name:
            raise PartnerStoreError("店家名稱不可空白")
        store_id = uuid.uuid4().hex
        api_key = secrets.token_urlsafe(32)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO partnerapiclient (id, name, key_hash, created_at)
                        VALUES (:id, :name, :key_hash, :created_at)
                        """
                    ),
                    {
                        "id": store_id,
                        "name": store_name,
                        "key_hash": hash_key(api_key),
                        "created_at": datetime.now(timezone.utc),
                    },
                )
        except PartnerStoreError:
            raise
        except Exception as exc:
            raise PartnerStoreError("無法寫入店家憑證，請先完成資料庫遷移") from exc
        return store_id, api_key

    def verify(self, store_id: str, store_name: str, api_key: str) -> bool:
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT name, key_hash, revoked_at
                        FROM partnerapiclient
                        WHERE id = :id
                        """
                    ),
                    {"id": store_id},
                ).first()
        except Exception as exc:
            raise PartnerStoreError("無法驗證店家金鑰") from exc
        if row is None or row.revoked_at is not None:
            return False
        if row.name != store_name:
            return False
        return hmac.compare_digest(row.key_hash, hash_key(api_key))


def _engine(database_url: str) -> Engine:
    url = normalize_database_url(database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)
