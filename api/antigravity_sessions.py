"""Read-only views of real managed Antigravity conversations, never resumable sessions."""

from __future__ import annotations

from functools import lru_cache
import json
import math
import os
from pathlib import Path
import stat
import uuid

SOURCE = "antigravity"
MAX_RECORD_BYTES = 10 * 1024 * 1024
MAX_FILES = 200  # Match the existing native Claude discovery bound.


def _root(directory=None):
    if directory is not None:
        root = Path(directory)
    elif override := os.getenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR"):
        root = Path(override).expanduser()
    elif os.getenv("HERMES_WEBUI_TEST_STATE_DIR"):
        return None
    else:
        from api.config import _DEFAULT_STATE_HOME

        root = _DEFAULT_STATE_HOME / "review-sessions/antigravity"
    # Resolve operator-selected storage aliases, not record symlinks.
    try:
        return root.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _identity(value):
    if not isinstance(value, str):
        return None
    try:
        return value if value == str(uuid.UUID(value)) else None
    except ValueError:
        return None


def _read(path):
    try:
        if path.suffix != ".json" or _identity(path.stem) is None or path.is_symlink():
            return None
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RECORD_BYTES:
                return None
            data = stream.read(MAX_RECORD_BYTES + 1)
        if len(data) > MAX_RECORD_BYTES:
            return None
        row = json.loads(data)
        if (
            not isinstance(row, dict)
            or row.get("version") != 1
            or row.get("source") != SOURCE
        ):
            return None
        if _identity(row.get("native_conversation_id")) != path.stem:
            return None
        for field in ("created_at", "updated_at"):
            if type(row.get(field)) not in (int, float) or not math.isfinite(
                row[field]
            ):
                return None
        for field, limit in (
            ("workspace", 4096),
            ("model", 256),
            ("role", 40),
            ("status", 64),
        ):
            if not isinstance(row.get(field), str) or len(row[field]) > limit:
                return None
        messages = row.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 1000:
            return None
        if not all(
            isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
            for m in messages
        ):
            return None
        row["messages"] = [
            {"role": m["role"], "content": m["content"]} for m in messages
        ]
        return row
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        RecursionError,
    ):
        return None


def _summary(row):
    return {
        "session_id": SOURCE + "_" + row["native_conversation_id"],
        "title": f"{row['role'].capitalize()}: {Path(row['workspace']).name or 'Antigravity'} · {row['status']}"[
            :120
        ],
        "workspace": row["workspace"],
        "model": row["model"],
        "message_count": len(row["messages"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_message_at": row["updated_at"],
        "pinned": False,
        "archived": False,
        "project_id": None,
        "profile": None,
        "source_tag": SOURCE,
        "raw_source": SOURCE,
        "source_label": "Antigravity",
        "session_source": "external_agent",
        "is_cli_session": True,
        "read_only": True,
        "can_resume": False,
    }


@lru_cache(maxsize=MAX_FILES)
def _cached_summary(path, signature):
    # Cache metadata only: retaining whole reports could consume gigabytes.
    row = _read(path)
    return _summary(row) if row else None


def _metadata(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None
        signature = (info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
        row = _cached_summary(path, signature)
        return dict(row) if row else None
    except OSError:
        return None


def list_sessions(directory=None):
    root = _root(directory)
    if root is None or not root.is_dir():
        return []
    candidates = []
    for path in root.glob("*.json"):
        if _identity(path.stem) is None:
            continue
        try:
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                candidates.append((info.st_mtime_ns, path))
        except OSError:
            continue
    candidates.sort(reverse=True)
    sessions = [row for _, path in candidates[:MAX_FILES] if (row := _metadata(path))]
    sessions.sort(key=lambda row: row["updated_at"], reverse=True)
    return sessions


def _session_path(sid, directory):
    root = _root(directory)
    if root is None or not isinstance(sid, str) or not sid.startswith(SOURCE + "_"):
        return None
    identity = _identity(sid[len(SOURCE) + 1 :])
    return root / (identity + ".json") if identity else None


def session_metadata(sid, directory=None):
    path = _session_path(sid, directory)
    return _metadata(path) if path else None


def session_messages(sid, directory=None):
    path = _session_path(sid, directory)
    row = _read(path) if path else None
    return row["messages"] if row else []
