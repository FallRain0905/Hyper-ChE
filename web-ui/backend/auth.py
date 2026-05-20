# -*- coding: utf-8 -*-
"""Authentication, quota, and per-user API key storage for HyperChE."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine


AUTH_COOKIE_NAME = "hyperche_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MSG_INVALID_EMAIL = "\u8bf7\u8f93\u5165\u6709\u6548\u90ae\u7bb1"
MSG_WEAK_PASSWORD = "\u5bc6\u7801\u81f3\u5c11\u9700\u8981 8 \u4f4d"
MSG_DUPLICATE_EMAIL = "\u8be5\u90ae\u7bb1\u5df2\u6ce8\u518c"
MSG_QUOTA_EXHAUSTED = "\u8bd5\u7528\u989d\u5ea6\u4e0d\u8db3"


def _split_api_keys(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[\n,;]+", value) if item.strip()]


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("email", String(255), unique=True, nullable=False, index=True),
    Column("password_hash", Text, nullable=False),
    Column("display_name", String(255), nullable=False, default=""),
    Column("role", String(64), nullable=False, default="user"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
)

user_quotas = Table(
    "user_quotas",
    metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("trial_embedding_calls_used", Integer, nullable=False, default=0),
    Column("trial_llm_calls_used", Integer, nullable=False, default=0),
    Column("trial_docs_used", Integer, nullable=False, default=0),
    Column("monthly_reset_at", DateTime(timezone=True), nullable=False),
)

user_api_keys = Table(
    "user_api_keys",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("provider_type", String(32), nullable=False),
    Column("base_url", Text, nullable=False),
    Column("model_name", Text, nullable=False),
    Column("api_key_encrypted", Text, nullable=False),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

app_config = Table(
    "app_config",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sqlite_url() -> str:
    path = os.getenv("HYPERCHE_SQLITE_PATH", os.path.join(os.path.dirname(__file__), "hyperche_app.db"))
    return f"sqlite:///{path}"


def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or _sqlite_url()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def make_engine() -> Engine:
    connect_args = {}
    url = _database_url()
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


def _secret() -> str:
    return os.getenv("JWT_SECRET") or os.getenv("APP_SECRET_KEY") or "hyperche-dev-secret-change-me"


def _fernet() -> Fernet:
    digest = hashlib.sha256((os.getenv("APP_SECRET_KEY") or _secret()).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n = 2**14
    r = 8
    p = 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt_sha256${n}${r}${p}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split("$")
        algorithm = parts[0]
        if algorithm == "scrypt_sha256":
            _, n, r, p, salt_b64, digest = parts
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=_b64url_decode(salt_b64),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=32,
            )
            return hmac.compare_digest(_b64url(candidate), digest)
        if algorithm == "pbkdf2_sha256":
            _, iterations, salt, digest = parts
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            )
            return hmac.compare_digest(_b64url(candidate), digest)
        return False
    except Exception:
        return False


def needs_password_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith("scrypt_sha256$")


def create_token(user_id: str, role: str, expires_hours: int = 24 * 14) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time() + expires_hours * 3600),
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def verify_token(token: str) -> dict[str, Any] | None:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), signature_b64):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


class AuthStore:
    def __init__(self) -> None:
        self.engine = make_engine()
        metadata.create_all(self.engine)
        self.ensure_admin_user()

    def get_config(self, key: str, default: str | None = None) -> str | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(app_config.c.value).where(app_config.c.key == key)).first()
            return row[0] if row else default

    def set_config(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            existing = conn.execute(select(app_config.c.key).where(app_config.c.key == key)).first()
            if existing:
                conn.execute(update(app_config).where(app_config.c.key == key).values(value=str(value)))
            else:
                conn.execute(insert(app_config).values(key=key, value=str(value)))

    def get_quota_limits(self) -> dict[str, int]:
        return {
            "trial_docs_limit": int(self.get_config("trial_docs_limit", os.getenv("TRIAL_DOC_LIMIT", "3")) or 3),
            "trial_llm_calls_limit": int(self.get_config("trial_llm_calls_limit", os.getenv("TRIAL_LLM_CALL_LIMIT", "50")) or 50),
            "trial_embedding_calls_limit": int(self.get_config("trial_embedding_calls_limit", os.getenv("TRIAL_EMBEDDING_CALL_LIMIT", "200")) or 200),
        }

    def set_quota_limits(self, docs: int, llm: int, embedding: int) -> dict[str, int]:
        docs = max(0, int(docs))
        llm = max(0, int(llm))
        embedding = max(0, int(embedding))
        self.set_config("trial_docs_limit", str(docs))
        self.set_config("trial_llm_calls_limit", str(llm))
        self.set_config("trial_embedding_calls_limit", str(embedding))
        return self.get_quota_limits()

    def ensure_admin_user(self) -> None:
        email = (os.getenv("HYPERCHE_ADMIN_EMAIL") or "admin@123.com").strip().lower()
        password = os.getenv("HYPERCHE_ADMIN_PASSWORD") or "admin123"
        display_name = os.getenv("HYPERCHE_ADMIN_NAME") or "HyperChE Admin"
        now = utcnow()
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.email == email)).mappings().first()
            if row:
                conn.execute(
                    update(users)
                    .where(users.c.id == row["id"])
                    .values(
                        password_hash=hash_password(password),
                        display_name=display_name,
                        role="admin",
                    )
                )
                self._ensure_quota(conn, row["id"])
                return
            user_id = secrets.token_hex(16)
            conn.execute(
                insert(users).values(
                    id=user_id,
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    role="admin",
                    created_at=now,
                    last_login_at=None,
                )
            )
            self._ensure_quota(conn, user_id)

    @property
    def trial_docs_limit(self) -> int:
        return self.get_quota_limits()["trial_docs_limit"]

    @property
    def trial_llm_limit(self) -> int:
        return self.get_quota_limits()["trial_llm_calls_limit"]

    @property
    def trial_embedding_limit(self) -> int:
        return self.get_quota_limits()["trial_embedding_calls_limit"]

    def _quota_reset_at(self) -> datetime:
        return utcnow() + timedelta(days=30)

    def _ensure_quota(self, conn, user_id: str) -> None:
        row = conn.execute(select(user_quotas).where(user_quotas.c.user_id == user_id)).mappings().first()
        if not row:
            conn.execute(
                insert(user_quotas).values(
                    user_id=user_id,
                    trial_embedding_calls_used=0,
                    trial_llm_calls_used=0,
                    trial_docs_used=0,
                    monthly_reset_at=self._quota_reset_at(),
                )
            )
            return

        reset_at = _as_aware_utc(row["monthly_reset_at"])
        if reset_at and reset_at <= utcnow():
            conn.execute(
                update(user_quotas)
                .where(user_quotas.c.user_id == user_id)
                .values(
                    trial_embedding_calls_used=0,
                    trial_llm_calls_used=0,
                    trial_docs_used=0,
                    monthly_reset_at=self._quota_reset_at(),
                )
            )

    def create_user(self, email: str, password: str, display_name: str = "") -> dict[str, Any]:
        email = email.strip().lower()
        display_name = (display_name.strip() or email.split("@")[0])[:255]
        if not email or not EMAIL_RE.match(email):
            raise ValueError(MSG_INVALID_EMAIL)
        if len(password) < 8:
            raise ValueError(MSG_WEAK_PASSWORD)

        user_id = secrets.token_hex(16)
        now = utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(select(users.c.id).where(users.c.email == email)).first()
            if existing:
                raise ValueError(MSG_DUPLICATE_EMAIL)
            conn.execute(
                insert(users).values(
                    id=user_id,
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    role="user",
                    created_at=now,
                    last_login_at=now,
                )
            )
            self._ensure_quota(conn, user_id)
        return self.get_user(user_id) or {}

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        email = email.strip().lower()
        with self.engine.begin() as conn:
            row = conn.execute(select(users).where(users.c.email == email)).mappings().first()
            if not row or not verify_password(password, row["password_hash"]):
                return None
            values = {"last_login_at": utcnow()}
            if needs_password_rehash(row["password_hash"]):
                values["password_hash"] = hash_password(password)
            conn.execute(update(users).where(users.c.id == row["id"]).values(**values))
        return self.get_user(row["id"])

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(
                    users.c.id,
                    users.c.email,
                    users.c.display_name,
                    users.c.role,
                    users.c.created_at,
                    users.c.last_login_at,
                ).where(users.c.id == user_id)
            ).mappings().first()
            if not row:
                return None
            self._ensure_quota(conn, user_id)
            return dict(row)

    def user_from_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        payload = verify_token(token)
        if not payload:
            return None
        return self.get_user(payload.get("sub", ""))

    def get_quota(self, user_id: str) -> dict[str, Any]:
        user = self.get_user(user_id)
        if user and user.get("role") == "admin":
            return {
                "trial_docs_used": 0,
                "trial_docs_limit": 999999,
                "trial_llm_calls_used": 0,
                "trial_llm_calls_limit": 999999,
                "trial_embedding_calls_used": 0,
                "trial_embedding_calls_limit": 999999,
                "monthly_reset_at": None,
                "unlimited": True,
            }
        with self.engine.begin() as conn:
            self._ensure_quota(conn, user_id)
            row = conn.execute(select(user_quotas).where(user_quotas.c.user_id == user_id)).mappings().one()
            return {
                "trial_docs_used": row["trial_docs_used"],
                "trial_docs_limit": self.trial_docs_limit,
                "trial_llm_calls_used": row["trial_llm_calls_used"],
                "trial_llm_calls_limit": self.trial_llm_limit,
                "trial_embedding_calls_used": row["trial_embedding_calls_used"],
                "trial_embedding_calls_limit": self.trial_embedding_limit,
                "monthly_reset_at": row["monthly_reset_at"].isoformat() if row["monthly_reset_at"] else None,
            }

    def consume_quota(self, user_id: str, quota_type: str, amount: int = 1) -> None:
        user = self.get_user(user_id)
        if user and user.get("role") == "admin":
            return
        column_map = {
            "docs": user_quotas.c.trial_docs_used,
            "llm": user_quotas.c.trial_llm_calls_used,
            "embedding": user_quotas.c.trial_embedding_calls_used,
        }
        limit_map = {
            "docs": self.trial_docs_limit,
            "llm": self.trial_llm_limit,
            "embedding": self.trial_embedding_limit,
        }
        if quota_type not in column_map:
            raise ValueError("Unknown quota type")
        column = column_map[quota_type]
        limit = limit_map[quota_type]
        with self.engine.begin() as conn:
            self._ensure_quota(conn, user_id)
            row = conn.execute(select(user_quotas).where(user_quotas.c.user_id == user_id)).mappings().one()
            used = int(row[column.name] or 0)
            if used + amount > limit:
                raise PermissionError(f"{MSG_QUOTA_EXHAUSTED}: {quota_type} {used}/{limit}")
            conn.execute(update(user_quotas).where(user_quotas.c.user_id == user_id).values({column.name: used + amount}))

    def add_api_key(
        self,
        user_id: str,
        provider_type: str,
        base_url: str,
        model_name: str,
        api_key: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        provider_type = provider_type.strip().lower()
        if provider_type not in {"llm", "embedding"}:
            raise ValueError("provider_type must be llm or embedding")
        if not base_url.strip() or not model_name.strip() or not api_key.strip():
            raise ValueError("base_url, model_name and api_key are required")
        key_id = secrets.token_hex(16)
        encrypted = _fernet().encrypt(api_key.strip().encode("utf-8")).decode("utf-8")
        with self.engine.begin() as conn:
            conn.execute(
                insert(user_api_keys).values(
                    id=key_id,
                    user_id=user_id,
                    provider_type=provider_type,
                    base_url=base_url.strip(),
                    model_name=model_name.strip(),
                    api_key_encrypted=encrypted,
                    enabled=enabled,
                    created_at=utcnow(),
                )
            )
        return self.get_api_key_metadata(user_id, key_id) or {}

    def get_api_key_metadata(self, user_id: str, key_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(
                    user_api_keys.c.id,
                    user_api_keys.c.provider_type,
                    user_api_keys.c.base_url,
                    user_api_keys.c.model_name,
                    user_api_keys.c.enabled,
                    user_api_keys.c.created_at,
                ).where(user_api_keys.c.id == key_id, user_api_keys.c.user_id == user_id)
            ).mappings().first()
            if not row:
                return None
            item = dict(row)
            encrypted_key = conn.execute(
                select(user_api_keys.c.api_key_encrypted).where(
                    user_api_keys.c.id == key_id,
                    user_api_keys.c.user_id == user_id,
                )
            ).scalar_one_or_none()
            if encrypted_key:
                decrypted = _fernet().decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
                item["api_key_count"] = len(_split_api_keys(decrypted))
            else:
                item["api_key_count"] = 0
            item["api_key"] = "***"
            item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
            return item

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    user_api_keys.c.id,
                    user_api_keys.c.provider_type,
                    user_api_keys.c.base_url,
                    user_api_keys.c.model_name,
                    user_api_keys.c.enabled,
                    user_api_keys.c.created_at,
                )
                .where(user_api_keys.c.user_id == user_id)
                .order_by(user_api_keys.c.created_at.desc())
            ).mappings().all()
            result = []
            for row in rows:
                item = dict(row)
                encrypted_key = conn.execute(
                    select(user_api_keys.c.api_key_encrypted).where(user_api_keys.c.id == row["id"])
                ).scalar_one_or_none()
                if encrypted_key:
                    decrypted = _fernet().decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
                    item["api_key_count"] = len(_split_api_keys(decrypted))
                else:
                    item["api_key_count"] = 0
                item["api_key"] = "***"
                item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
                result.append(item)
            return result

    def delete_api_key(self, user_id: str, key_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(delete(user_api_keys).where(user_api_keys.c.id == key_id, user_api_keys.c.user_id == user_id))
            return bool(result.rowcount)

    def get_enabled_provider(self, user_id: str | None, provider_type: str) -> dict[str, str] | None:
        if not user_id:
            return None
        with self.engine.begin() as conn:
            row = conn.execute(
                select(user_api_keys)
                .where(
                    user_api_keys.c.user_id == user_id,
                    user_api_keys.c.provider_type == provider_type,
                    user_api_keys.c.enabled == True,  # noqa: E712
                )
                .order_by(user_api_keys.c.created_at.desc())
            ).mappings().first()
            if not row:
                return None
            return {
                "baseUrl": row["base_url"],
                "modelName": row["model_name"],
                "apiKey": _fernet().decrypt(row["api_key_encrypted"].encode("utf-8")).decode("utf-8"),
            }

    def get_enabled_providers(self, user_id: str | None, provider_type: str) -> list[dict[str, Any]]:
        if not user_id:
            return []
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(user_api_keys)
                .where(
                    user_api_keys.c.user_id == user_id,
                    user_api_keys.c.provider_type == provider_type,
                    user_api_keys.c.enabled == True,  # noqa: E712
                )
                .order_by(user_api_keys.c.created_at.desc())
            ).mappings().all()
            providers = []
            for row in rows:
                api_key_text = _fernet().decrypt(row["api_key_encrypted"].encode("utf-8")).decode("utf-8")
                api_keys = _split_api_keys(api_key_text)
                if not api_keys:
                    continue
                providers.append(
                    {
                        "id": row["id"],
                        "baseUrl": row["base_url"],
                        "modelName": row["model_name"],
                        "apiKey": "\n".join(api_keys),
                        "apiKeys": api_keys,
                    }
                )
            return providers


auth_store = AuthStore()
