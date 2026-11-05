"""Viewer session and portable-project API routes."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import HTTPException
from ..session import (
    import_project,
    list_sessions,
    load_session,
    project_from_dict,
    project_to_dict,
    save_session,
    session_to_project,
)


def register_session_routes(app, *, settings):
    @app.get("/api/session")
    def sessions():
        return {
            "sessions": [
                asdict(session) for session in list_sessions(settings.session_dir)
            ]
        }

    @app.post("/api/session/{session_id}")
    def save_viewer_session(session_id: str, request: dict[str, object]):
        state = request.get("state")
        if not isinstance(state, dict):
            raise HTTPException(
                status_code=400,
                detail="session request requires an object-valued 'state'",
            )
        title = request.get("title")
        try:
            session = save_session(
                settings.session_dir,
                session_id,
                state,
                title=title if isinstance(title, str) else "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(session)

    @app.get("/api/session/{session_id}")
    def session(session_id: str):
        try:
            saved = load_session(settings.session_dir, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if saved is None:
            raise HTTPException(status_code=404, detail="session not found")
        return asdict(saved)

    @app.get("/api/session/{session_id}/project")
    def session_project(session_id: str):
        try:
            saved = load_session(settings.session_dir, session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if saved is None:
            raise HTTPException(status_code=404, detail="session not found")
        return project_to_dict(session_to_project(saved))

    @app.post("/api/session/{session_id}/project")
    def import_viewer_project(session_id: str, request: dict[str, object]):
        payload = request.get("project", request)
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400, detail="project import requires an object payload"
            )
        try:
            project = project_from_dict(payload)
            saved = import_project(settings.session_dir, project, session_id=session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(saved)
