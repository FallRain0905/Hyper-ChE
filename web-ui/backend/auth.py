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
import tempfile
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
    # Kept under the legacy column name for database compatibility. The value
    # now represents the next daily quota reset time.
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

# Unified API channel registry. A channel is one upstream endpoint plus its
# encrypted secret; the models served by it live in model_profiles.
# scope="platform" rows are managed by admins and have no owner; scope="user"
# rows belong to a single account and follow the same encryption as
# user_api_keys.
channels = Table(
    "channels",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("scope", String(16), nullable=False, default="platform"),
    Column("owner_user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("provider_name", String(128), nullable=False, default=""),
    Column("protocol", String(32), nullable=False, default="openai"),
    Column("base_url", Text, nullable=False, default=""),
    Column("secret_encrypted", Text, nullable=False, default=""),
    Column("status", String(16), nullable=False, default="active"),
    Column("migrated_from", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# One model served by a channel, tagged with the role it fills. Roles are
# extraction, answer, judge, embedding and reranker. embedding_dim is required
# for the embedding role so vector stores can be validated on load.
model_profiles = Table(
    "model_profiles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("channel_id", String(36), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("role", String(32), nullable=False, default="answer"),
    Column("model_name", String(255), nullable=False, default=""),
    Column("embedding_dim", Integer, nullable=True),
    Column("context_window", Integer, nullable=True),
    Column("max_concurrency", Integer, nullable=False, default=4),
    Column("per_key_max_concurrency", Integer, nullable=True),
    Column("timeout_seconds", Integer, nullable=False, default=600),
    Column("priority", Integer, nullable=False, default=100),
    Column("extra_json", Text, nullable=False, default="{}"),
    Column("enabled", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# A prompt pack is a versioned bundle of domain configuration plus prompt
# templates. Built-in hyperrag/domains directories are imported as read-only
# seed packs with scope="system".
prompt_packs = Table(
    "prompt_packs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("domain_id", String(64), nullable=False, default="default", index=True),
    Column("name", String(255), nullable=False, default=""),
    Column("description", Text, nullable=False, default=""),
    Column("scope", String(16), nullable=False, default="user"),
    Column("owner_user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("status", String(16), nullable=False, default="draft"),
    Column("published_version_id", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

# Published versions are immutable. Editing forks a new draft row; rollback
# copies an old published version forward as a new draft rather than mutating
# history.
prompt_versions = Table(
    "prompt_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("pack_id", String(36), ForeignKey("prompt_packs.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("version_no", Integer, nullable=False, default=1),
    Column("status", String(16), nullable=False, default="draft"),
    Column("config_json", Text, nullable=False, default="{}"),
    Column("prompts_json", Text, nullable=False, default="{}"),
    Column("changelog", Text, nullable=False, default=""),
    Column("created_by", String(36), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("content_hash", String(64), nullable=True),
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
    configured = os.getenv("HYPERCHE_SQLITE_PATH")
    if configured:
        path = configured
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return f"sqlite:///{path}"

    candidates = [
        os.path.join(os.getenv("LOCALAPPDATA") or "", "HyperChE", "hyperche_app.db"),
        os.path.join(tempfile.gettempdir(), "HyperChE", "hyperche_app.db"),
    ]
    for path in candidates:
        if not path or path.startswith(os.sep + "HyperChE"):
            continue
        try:
            directory = os.path.dirname(os.path.abspath(path))
            os.makedirs(directory, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="sqlite_write_test_", dir=directory, delete=True):
                pass
            return f"sqlite:///{path}"
        except Exception:
            continue

    fallback = os.path.join(tempfile.gettempdir(), "hyperche_app.db")
    return f"sqlite:///{fallback}"


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

    def get_user_runtime_settings(self, user_id: str) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "hyperrag_domain": "default",
            # Binding to a published prompt pack; None means use the plain domain.
            "prompt_pack_id": None,
            "prompt_version_id": None,
            "experimentMode": "hyper_final",
            "promptProfile": "chemistry",
            "indexProfile": "dual_concat",
            "enableEntityNormalization": True,
            "enableMeasurementInstances": True,
            "enableEfuRepair": True,
            "enableHybridRerank": True,
        }
        raw = self.get_config(f"user_runtime_settings:{user_id}")
        if not raw:
            return defaults
        try:
            saved = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return defaults
        if not isinstance(saved, dict):
            return defaults
        return {**defaults, **{key: saved[key] for key in defaults if key in saved}}

    def set_user_runtime_settings(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_user_runtime_settings(user_id)
        allowed = set(current)
        merged = {**current, **{key: payload[key] for key in allowed if key in payload}}
        self.set_config(
            f"user_runtime_settings:{user_id}",
            json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
        )
        return merged

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
        email = (os.getenv("HYPERCHE_ADMIN_EMAIL") or "").strip().lower()
        password = os.getenv("HYPERCHE_ADMIN_PASSWORD") or ""
        if not email or not password:
            return
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
        now = utcnow()
        # Reset at the next UTC midnight. Keeping one global boundary makes
        # the daily public allowance predictable for every account.
        return datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)

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

        now = utcnow()
        reset_at = _as_aware_utc(row["monthly_reset_at"])
        expected_reset_at = self._quota_reset_at()
        # The existing column name is kept for database compatibility, but its
        # value must always point to the next UTC midnight. Any other future
        # boundary is a legacy monthly row and is migrated on first access.
        if not reset_at or reset_at <= now or reset_at != expected_reset_at:
            conn.execute(
                update(user_quotas)
                .where(user_quotas.c.user_id == user_id)
                .values(
                    trial_embedding_calls_used=0,
                    trial_llm_calls_used=0,
                    trial_docs_used=0,
                    monthly_reset_at=expected_reset_at,
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

    def list_users(self) -> list[dict[str, Any]]:
        """Return users with quota usage for the administrator console."""
        limits = self.get_quota_limits()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    users.c.id,
                    users.c.email,
                    users.c.display_name,
                    users.c.role,
                    users.c.created_at,
                    users.c.last_login_at,
                ).order_by(users.c.created_at.desc())
            ).mappings().all()

            result = []
            for row in rows:
                self._ensure_quota(conn, row["id"])
                quota = conn.execute(
                    select(user_quotas).where(user_quotas.c.user_id == row["id"])
                ).mappings().one()
                is_admin = row["role"] == "admin"
                result.append(
                    {
                        "id": row["id"],
                        "email": row["email"],
                        "display_name": row["display_name"],
                        "role": row["role"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
                        "quota": {
                            "trial_docs_used": 0 if is_admin else quota["trial_docs_used"],
                            "trial_docs_limit": 999999 if is_admin else limits["trial_docs_limit"],
                            "trial_llm_calls_used": 0 if is_admin else quota["trial_llm_calls_used"],
                            "trial_llm_calls_limit": 999999 if is_admin else limits["trial_llm_calls_limit"],
                            "trial_embedding_calls_used": 0 if is_admin else quota["trial_embedding_calls_used"],
                            "trial_embedding_calls_limit": 999999 if is_admin else limits["trial_embedding_calls_limit"],
                            "daily_reset_at": quota["monthly_reset_at"].isoformat() if quota["monthly_reset_at"] else None,
                            "unlimited": is_admin,
                        },
                    }
                )
            return result

    def reset_user_quota(self, user_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            user_exists = conn.execute(select(users.c.id).where(users.c.id == user_id)).first()
            if not user_exists:
                raise ValueError("User not found")
            self._ensure_quota(conn, user_id)
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
        return self.get_quota(user_id)

    def reset_all_user_quotas(self) -> int:
        """Reset all non-admin usage after public daily limits change."""
        with self.engine.begin() as conn:
            user_ids = conn.execute(select(users.c.id).where(users.c.role != "admin")).scalars().all()
            reset_at = self._quota_reset_at()
            for user_id in user_ids:
                self._ensure_quota(conn, user_id)
                conn.execute(
                    update(user_quotas)
                    .where(user_quotas.c.user_id == user_id)
                    .values(
                        trial_embedding_calls_used=0,
                        trial_llm_calls_used=0,
                        trial_docs_used=0,
                        monthly_reset_at=reset_at,
                    )
                )
            return len(user_ids)

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
                "daily_reset_at": None,
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
                "daily_reset_at": row["monthly_reset_at"].isoformat() if row["monthly_reset_at"] else None,
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

    # ---------- Channels and model profiles ----------

    @staticmethod
    def _channel_metadata(row: Any) -> dict[str, Any]:
        """Serialize a channel row for API output. Never includes the secret."""
        return {
            "id": row["id"],
            "scope": row["scope"],
            "owner_user_id": row["owner_user_id"],
            "provider_name": row["provider_name"],
            "protocol": row["protocol"],
            "base_url": row["base_url"],
            "status": row["status"],
            "migrated_from": row["migrated_from"],
            "has_secret": bool(row["secret_encrypted"]),
            "secret": "***" if row["secret_encrypted"] else "",
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    @staticmethod
    def _model_profile_dict(row: Any) -> dict[str, Any]:
        extra: Any = {}
        try:
            extra = json.loads(row["extra_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            extra = {}
        return {
            "id": row["id"],
            "channel_id": row["channel_id"],
            "role": row["role"],
            "model_name": row["model_name"],
            "embedding_dim": row["embedding_dim"],
            "context_window": row["context_window"],
            "max_concurrency": row["max_concurrency"],
            "per_key_max_concurrency": row["per_key_max_concurrency"],
            "timeout_seconds": row["timeout_seconds"],
            "priority": row["priority"],
            "extra": extra,
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    def count_channels(self, scope: str | None = None) -> int:
        stmt = select(channels.c.id)
        if scope:
            stmt = stmt.where(channels.c.scope == scope)
        with self.engine.begin() as conn:
            return len(conn.execute(stmt).scalars().all())

    def create_channel(
        self,
        *,
        scope: str,
        owner_user_id: str | None,
        provider_name: str,
        protocol: str = "openai",
        base_url: str = "",
        secret: str = "",
        status: str = "active",
        migrated_from: str | None = None,
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        scope = (scope or "platform").strip().lower()
        if scope not in {"platform", "user"}:
            raise ValueError("scope must be platform or user")
        if scope == "user" and not owner_user_id:
            raise ValueError("user-scoped channels require an owner")
        now = utcnow()
        new_id = channel_id or secrets.token_hex(16)
        encrypted = _fernet().encrypt(secret.strip().encode("utf-8")).decode("utf-8") if secret.strip() else ""
        with self.engine.begin() as conn:
            conn.execute(
                insert(channels).values(
                    id=new_id,
                    scope=scope,
                    owner_user_id=owner_user_id if scope == "user" else None,
                    provider_name=provider_name.strip(),
                    protocol=(protocol or "openai").strip().lower(),
                    base_url=base_url.strip(),
                    secret_encrypted=encrypted,
                    status=status,
                    migrated_from=migrated_from,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_channel(new_id) or {}

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(channels).where(channels.c.id == channel_id)).mappings().first()
            if not row:
                return None
            item = self._channel_metadata(row)
            item["models"] = [
                self._model_profile_dict(model)
                for model in conn.execute(
                    select(model_profiles)
                    .where(model_profiles.c.channel_id == channel_id)
                    .order_by(model_profiles.c.priority, model_profiles.c.created_at)
                ).mappings().all()
            ]
            return item

    def list_channels(self, scope: str | None = None, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        stmt = select(channels)
        if scope:
            stmt = stmt.where(channels.c.scope == scope)
        if owner_user_id is not None:
            stmt = stmt.where(channels.c.owner_user_id == owner_user_id)
        stmt = stmt.order_by(channels.c.scope, channels.c.created_at)
        with self.engine.begin() as conn:
            rows = conn.execute(stmt).mappings().all()
            result = []
            for row in rows:
                item = self._channel_metadata(row)
                item["models"] = [
                    self._model_profile_dict(model)
                    for model in conn.execute(
                        select(model_profiles)
                        .where(model_profiles.c.channel_id == row["id"])
                        .order_by(model_profiles.c.priority, model_profiles.c.created_at)
                    ).mappings().all()
                ]
                result.append(item)
            return result

    def update_channel(
        self,
        channel_id: str,
        *,
        provider_name: str | None = None,
        protocol: str | None = None,
        base_url: str | None = None,
        secret: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        if provider_name is not None:
            values["provider_name"] = provider_name.strip()
        if protocol is not None:
            values["protocol"] = protocol.strip().lower()
        if base_url is not None:
            values["base_url"] = base_url.strip()
        if status is not None:
            values["status"] = status
        # An empty or masked secret keeps the stored value untouched.
        if secret is not None and secret.strip() and secret.strip() != "***":
            values["secret_encrypted"] = _fernet().encrypt(secret.strip().encode("utf-8")).decode("utf-8")
        with self.engine.begin() as conn:
            conn.execute(update(channels).where(channels.c.id == channel_id).values(**values))
        return self.get_channel(channel_id)

    def delete_channel(self, channel_id: str) -> bool:
        with self.engine.begin() as conn:
            conn.execute(delete(model_profiles).where(model_profiles.c.channel_id == channel_id))
            result = conn.execute(delete(channels).where(channels.c.id == channel_id))
            return bool(result.rowcount)

    def get_channel_secret(self, channel_id: str) -> str:
        with self.engine.begin() as conn:
            encrypted = conn.execute(
                select(channels.c.secret_encrypted).where(channels.c.id == channel_id)
            ).scalar_one_or_none()
        if not encrypted:
            return ""
        return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")

    def create_model_profile(
        self,
        *,
        channel_id: str,
        role: str,
        model_name: str,
        embedding_dim: int | None = None,
        context_window: int | None = None,
        max_concurrency: int = 4,
        per_key_max_concurrency: int | None = None,
        timeout_seconds: int = 600,
        priority: int = 100,
        extra: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        now = utcnow()
        profile_id = secrets.token_hex(16)
        with self.engine.begin() as conn:
            conn.execute(
                insert(model_profiles).values(
                    id=profile_id,
                    channel_id=channel_id,
                    role=(role or "answer").strip().lower(),
                    model_name=model_name.strip(),
                    embedding_dim=embedding_dim,
                    context_window=context_window,
                    max_concurrency=max(1, int(max_concurrency)),
                    per_key_max_concurrency=per_key_max_concurrency,
                    timeout_seconds=max(1, int(timeout_seconds)),
                    priority=int(priority),
                    extra_json=json.dumps(extra or {}, ensure_ascii=False),
                    enabled=enabled,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_model_profile(profile_id) or {}

    def get_model_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(model_profiles).where(model_profiles.c.id == profile_id)).mappings().first()
            return self._model_profile_dict(row) if row else None

    def update_model_profile(self, profile_id: str, **patch: Any) -> dict[str, Any] | None:
        allowed = {
            "role",
            "model_name",
            "embedding_dim",
            "context_window",
            "max_concurrency",
            "per_key_max_concurrency",
            "timeout_seconds",
            "priority",
            "enabled",
        }
        values: dict[str, Any] = {"updated_at": utcnow()}
        for key in allowed:
            if key in patch and patch[key] is not None:
                values[key] = patch[key]
        if "extra" in patch and patch["extra"] is not None:
            values["extra_json"] = json.dumps(patch["extra"], ensure_ascii=False)
        with self.engine.begin() as conn:
            conn.execute(update(model_profiles).where(model_profiles.c.id == profile_id).values(**values))
        return self.get_model_profile(profile_id)

    def delete_model_profile(self, profile_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(delete(model_profiles).where(model_profiles.c.id == profile_id))
            return bool(result.rowcount)

    def list_model_profiles_for_role(
        self,
        role: str,
        *,
        include_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return enabled profiles for a role, optionally including one user's own channels.

        Platform channels are always eligible; a user's private channels are
        added only for that user so personal keys take precedence at resolve time.
        """
        with self.engine.begin() as conn:
            stmt = (
                select(
                    model_profiles,
                    channels.c.id.label("channel_pk"),
                    channels.c.scope.label("channel_scope"),
                    channels.c.owner_user_id.label("channel_owner"),
                    channels.c.provider_name.label("channel_provider_name"),
                    channels.c.protocol.label("channel_protocol"),
                    channels.c.base_url.label("channel_base_url"),
                    channels.c.status.label("channel_status"),
                )
                .join(channels, model_profiles.c.channel_id == channels.c.id)
                .where(
                    model_profiles.c.role == role,
                    model_profiles.c.enabled == True,  # noqa: E712
                    channels.c.status == "active",
                )
            )
            rows = conn.execute(stmt).mappings().all()
        result = []
        for row in rows:
            scope = row["channel_scope"]
            if scope == "user" and not (include_user_id and row["channel_owner"] == include_user_id):
                continue
            item = self._model_profile_dict(row)
            item["channel"] = {
                "id": row["channel_pk"],
                "scope": scope,
                "owner_user_id": row["channel_owner"],
                "provider_name": row["channel_provider_name"],
                "protocol": row["channel_protocol"],
                "base_url": row["channel_base_url"],
                "status": row["channel_status"],
            }
            result.append(item)
        result.sort(key=lambda item: (item["priority"], item["created_at"] or ""))
        return result

    # ---------- Prompt packs and versions ----------

    @staticmethod
    def _pack_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "domain_id": row["domain_id"],
            "name": row["name"],
            "description": row["description"],
            "scope": row["scope"],
            "owner_user_id": row["owner_user_id"],
            "status": row["status"],
            "published_version_id": row["published_version_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    @staticmethod
    def _version_dict(row: Any, include_body: bool = False) -> dict[str, Any]:
        item = {
            "id": row["id"],
            "pack_id": row["pack_id"],
            "version_no": row["version_no"],
            "status": row["status"],
            "changelog": row["changelog"],
            "created_by": row["created_by"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
            "content_hash": row["content_hash"],
        }
        if include_body:
            try:
                item["config"] = json.loads(row["config_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                item["config"] = {}
            try:
                item["prompts"] = json.loads(row["prompts_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                item["prompts"] = {}
        else:
            item["config_json_len"] = len(row["config_json"] or "")
            item["prompts_json_len"] = len(row["prompts_json"] or "")
        return item

    def create_prompt_pack(
        self,
        *,
        domain_id: str,
        name: str,
        description: str = "",
        scope: str = "user",
        owner_user_id: str | None = None,
        status: str = "draft",
        pack_id: str | None = None,
    ) -> dict[str, Any]:
        scope = (scope or "user").strip().lower()
        if scope not in {"system", "user"}:
            raise ValueError("scope must be system or user")
        if scope == "user" and not owner_user_id:
            raise ValueError("user-scoped packs require an owner")
        now = utcnow()
        new_id = pack_id or secrets.token_hex(16)
        with self.engine.begin() as conn:
            conn.execute(
                insert(prompt_packs).values(
                    id=new_id,
                    domain_id=domain_id.strip(),
                    name=name.strip(),
                    description=description or "",
                    scope=scope,
                    owner_user_id=owner_user_id if scope == "user" else None,
                    status=status,
                    published_version_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_prompt_pack(new_id) or {}

    def get_prompt_pack(self, pack_id: str, *, include_versions: bool = False) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(select(prompt_packs).where(prompt_packs.c.id == pack_id)).mappings().first()
            if not row:
                return None
            item = self._pack_dict(row)
            if include_versions:
                item["versions"] = [
                    self._version_dict(version)
                    for version in conn.execute(
                        select(prompt_versions)
                        .where(prompt_versions.c.pack_id == pack_id)
                        .order_by(prompt_versions.c.version_no.desc())
                    ).mappings().all()
                ]
            return item

    def list_prompt_packs(
        self,
        *,
        owner_user_id: str | None = None,
        include_system: bool = True,
        domain_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(prompt_packs).order_by(prompt_packs.c.scope, prompt_packs.c.name)
            ).mappings().all()
            result = []
            for row in rows:
                if row["scope"] == "system":
                    if not include_system:
                        continue
                elif not (owner_user_id and row["owner_user_id"] == owner_user_id):
                    continue
                if domain_id and row["domain_id"] != domain_id:
                    continue
                item = self._pack_dict(row)
                count = conn.execute(
                    select(prompt_versions.c.id).where(prompt_versions.c.pack_id == row["id"])
                ).scalars().all()
                item["version_count"] = len(count)
                result.append(item)
            return result

    def update_prompt_pack(
        self,
        pack_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        published_version_id: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            values["name"] = name.strip()
        if description is not None:
            values["description"] = description
        if status is not None:
            values["status"] = status
        if published_version_id is not None:
            values["published_version_id"] = published_version_id
        with self.engine.begin() as conn:
            conn.execute(update(prompt_packs).where(prompt_packs.c.id == pack_id).values(**values))
        return self.get_prompt_pack(pack_id)

    def delete_prompt_pack(self, pack_id: str) -> bool:
        with self.engine.begin() as conn:
            conn.execute(delete(prompt_versions).where(prompt_versions.c.pack_id == pack_id))
            result = conn.execute(delete(prompt_packs).where(prompt_packs.c.id == pack_id))
            return bool(result.rowcount)

    def next_version_no(self, pack_id: str) -> int:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(prompt_versions.c.version_no).where(prompt_versions.c.pack_id == pack_id)
            ).scalars().all()
        return (max(rows) + 1) if rows else 1

    def create_prompt_version(
        self,
        *,
        pack_id: str,
        config: dict[str, Any],
        prompts: dict[str, Any],
        changelog: str = "",
        created_by: str | None = None,
        status: str = "draft",
        version_no: int | None = None,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        new_id = version_id or secrets.token_hex(16)
        number = version_no if version_no is not None else self.next_version_no(pack_id)
        config_text = json.dumps(config or {}, ensure_ascii=False, sort_keys=True)
        prompts_text = json.dumps(prompts or {}, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(f"{config_text}\n{prompts_text}".encode("utf-8")).hexdigest()
        with self.engine.begin() as conn:
            conn.execute(
                insert(prompt_versions).values(
                    id=new_id,
                    pack_id=pack_id,
                    version_no=number,
                    status=status,
                    config_json=config_text,
                    prompts_json=prompts_text,
                    changelog=changelog or "",
                    created_by=created_by,
                    created_at=now,
                    published_at=now if status == "published" else None,
                    content_hash=content_hash,
                )
            )
        return self.get_prompt_version(new_id, include_body=True) or {}

    def get_prompt_version(self, version_id: str, *, include_body: bool = False) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(prompt_versions).where(prompt_versions.c.id == version_id)
            ).mappings().first()
            return self._version_dict(row, include_body=include_body) if row else None

    def get_published_version(self, pack_id: str, *, include_body: bool = False) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            pack = conn.execute(
                select(prompt_packs.c.published_version_id).where(prompt_packs.c.id == pack_id)
            ).scalar_one_or_none()
            if not pack:
                return None
            row = conn.execute(
                select(prompt_versions).where(prompt_versions.c.id == pack)
            ).mappings().first()
            return self._version_dict(row, include_body=include_body) if row else None

    def list_prompt_versions(self, pack_id: str, *, include_body: bool = False) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(prompt_versions)
                .where(prompt_versions.c.pack_id == pack_id)
                .order_by(prompt_versions.c.version_no.desc())
            ).mappings().all()
            return [self._version_dict(row, include_body=include_body) for row in rows]

    def get_draft_version(self, pack_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(prompt_versions)
                .where(prompt_versions.c.pack_id == pack_id, prompt_versions.c.status == "draft")
                .order_by(prompt_versions.c.version_no.desc())
            ).mappings().first()
            return self._version_dict(row, include_body=True) if row else None

    def update_prompt_version_body(
        self,
        version_id: str,
        *,
        config: dict[str, Any] | None = None,
        prompts: dict[str, Any] | None = None,
        changelog: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {}
        if config is not None:
            values["config_json"] = json.dumps(config, ensure_ascii=False, sort_keys=True)
        if prompts is not None:
            values["prompts_json"] = json.dumps(prompts, ensure_ascii=False, sort_keys=True)
        if changelog is not None:
            values["changelog"] = changelog
        if values:
            with self.engine.begin() as conn:
                conn.execute(update(prompt_versions).where(prompt_versions.c.id == version_id).values(**values))
                row = conn.execute(
                    select(prompt_versions).where(prompt_versions.c.id == version_id)
                ).mappings().first()
                if row:
                    content_hash = hashlib.sha256(
                        f"{row['config_json']}\n{row['prompts_json']}".encode("utf-8")
                    ).hexdigest()
                    conn.execute(
                        update(prompt_versions).where(prompt_versions.c.id == version_id).values(content_hash=content_hash)
                    )
        return self.get_prompt_version(version_id, include_body=True)

    def publish_prompt_version(self, pack_id: str, version_id: str) -> dict[str, Any] | None:
        """Promote a draft to published and point the pack at it."""
        now = utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                update(prompt_versions)
                .where(prompt_versions.c.id == version_id, prompt_versions.c.pack_id == pack_id)
                .values(status="published", published_at=now)
            )
            conn.execute(
                update(prompt_packs)
                .where(prompt_packs.c.id == pack_id)
                .values(published_version_id=version_id, status="published", updated_at=now)
            )
        return self.get_prompt_version(version_id, include_body=True)

    def delete_prompt_version(self, version_id: str) -> bool:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(prompt_versions.c.status, prompt_versions.c.pack_id, prompt_versions.c.id).where(
                    prompt_versions.c.id == version_id
                )
            ).mappings().first()
            if not row or row["status"] == "published":
                return False
            pack = conn.execute(
                select(prompt_packs.c.published_version_id).where(prompt_packs.c.id == row["pack_id"])
            ).scalar_one_or_none()
            if pack == version_id:
                return False
            result = conn.execute(delete(prompt_versions).where(prompt_versions.c.id == version_id))
            return bool(result.rowcount)


auth_store = AuthStore()
