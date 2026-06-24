"""Persisted WCT-style viewer sessions."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .compat import UTC

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
PROJECT_TYPE = "avocet-wct-project"
PROJECT_VERSION = 1


@dataclass
class ViewerSession:
    session_id: str
    state: dict[str, Any]
    created_at: str
    updated_at: str
    title: str = ""
    version: int = 1
    notes: list[str] = field(default_factory=list)


@dataclass
class ViewerProject:
    type: str
    version: int
    exported_at: str
    session: ViewerSession
    application: str = "avocet-radar-toolkit"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def validate_session_id(session_id: str) -> None:
    if not SESSION_ID_RE.match(session_id):
        raise ValueError("session_id must be 1-80 chars using letters, numbers, dot, dash, or underscore")


def session_path(session_dir: Path, session_id: str) -> Path:
    validate_session_id(session_id)
    return session_dir / f"{session_id}.json"


def save_session(session_dir: Path, session_id: str, state: dict[str, Any], title: str = "") -> ViewerSession:
    path = session_path(session_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_session(session_dir, session_id)
    created_at = existing.created_at if existing else _now()
    session = ViewerSession(
        session_id=session_id,
        state=state,
        title=title,
        created_at=created_at,
        updated_at=_now(),
    )
    path.write_text(json.dumps(asdict(session), indent=2, sort_keys=True), encoding="utf-8")
    return session


def load_session(session_dir: Path, session_id: str) -> ViewerSession | None:
    path = session_path(session_dir, session_id)
    if not path.exists():
        return None
    return ViewerSession(**json.loads(path.read_text(encoding="utf-8")))


def list_sessions(session_dir: Path) -> list[ViewerSession]:
    if not session_dir.exists():
        return []
    sessions = []
    for path in sorted(session_dir.glob("*.json")):
        try:
            sessions.append(ViewerSession(**json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return sessions


def session_to_project(session: ViewerSession) -> ViewerProject:
    return ViewerProject(
        type=PROJECT_TYPE,
        version=PROJECT_VERSION,
        exported_at=_now(),
        session=session,
    )


def project_to_dict(project: ViewerProject) -> dict[str, Any]:
    return {
        "type": project.type,
        "version": project.version,
        "exported_at": project.exported_at,
        "application": project.application,
        "session": asdict(project.session),
    }


def project_from_dict(payload: dict[str, Any]) -> ViewerProject:
    if payload.get("type") != PROJECT_TYPE:
        raise ValueError(f"project type must be {PROJECT_TYPE!r}")
    version = int(payload.get("version", 0))
    if version != PROJECT_VERSION:
        raise ValueError(f"unsupported project version: {version}")
    raw_session = payload.get("session")
    if not isinstance(raw_session, dict):
        raise ValueError("project requires an object-valued session")
    raw_session.setdefault("notes", [])
    raw_session.setdefault("version", 1)
    session = ViewerSession(**raw_session)
    validate_session_id(session.session_id)
    if not isinstance(session.state, dict):
        raise ValueError("project session state must be an object")
    return ViewerProject(
        type=PROJECT_TYPE,
        version=PROJECT_VERSION,
        exported_at=str(payload.get("exported_at") or _now()),
        application=str(payload.get("application", "avocet-radar-toolkit")),
        session=session,
    )


def write_project_file(path: Path, session: ViewerSession) -> ViewerProject:
    project = session_to_project(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project_to_dict(project), indent=2, sort_keys=True), encoding="utf-8")
    return project


def read_project_file(path: Path) -> ViewerProject:
    return project_from_dict(json.loads(path.read_text(encoding="utf-8")))


def import_project(session_dir: Path, project: ViewerProject, session_id: str | None = None) -> ViewerSession:
    target_session_id = session_id or project.session.session_id
    validate_session_id(target_session_id)
    return save_session(
        session_dir,
        target_session_id,
        project.session.state,
        title=project.session.title or target_session_id,
    )
