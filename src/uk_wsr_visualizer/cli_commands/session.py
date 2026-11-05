"""Viewer session and portable-project commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from ..config import Settings
from ..session import (
    import_project,
    list_sessions,
    load_session,
    read_project_file,
    save_session,
    write_project_file,
)
from .common import _settings


def cmd_session_list(args: argparse.Namespace) -> int:
    settings = _settings(args)
    payload = [session.__dict__ for session in list_sessions(settings.session_dir)]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_session_get(args: argparse.Namespace) -> int:
    settings = _settings(args)
    session = load_session(settings.session_dir, args.session_id)
    if session is None:
        raise SystemExit("session not found")
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_session_save(args: argparse.Namespace) -> int:
    settings = _settings(args)
    state = json.loads(Path(args.state_json).read_text(encoding="utf-8"))
    session = save_session(
        settings.session_dir, args.session_id, state, title=args.title or ""
    )
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_session_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    session = load_session(settings.session_dir, args.session_id)
    if session is None:
        raise SystemExit("session not found")
    project = write_project_file(Path(args.output), session)
    print(
        json.dumps(
            {"wrote": str(args.output), "session_id": project.session.session_id},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_session_import(args: argparse.Namespace) -> int:
    settings = _settings(args)
    project = read_project_file(Path(args.project_json))
    session = import_project(settings.session_dir, project, session_id=args.session_id)
    print(json.dumps(session.__dict__, indent=2, sort_keys=True))
    return 0


def register_session_commands(subparsers):
    session_parser = subparsers.add_parser("session")
    session_parser.add_argument(
        "--session-dir", type=Path, default=Settings.from_env().session_dir
    )
    session_sub = session_parser.add_subparsers(required=True)
    session_list = session_sub.add_parser("list")
    session_list.set_defaults(func=cmd_session_list)
    session_get = session_sub.add_parser("get")
    session_get.add_argument("session_id")
    session_get.set_defaults(func=cmd_session_get)
    session_save = session_sub.add_parser("save")
    session_save.add_argument("session_id")
    session_save.add_argument("--state-json", required=True)
    session_save.add_argument("--title")
    session_save.set_defaults(func=cmd_session_save)
    session_export = session_sub.add_parser("export")
    session_export.add_argument("session_id")
    session_export.add_argument("--output", required=True)
    session_export.set_defaults(func=cmd_session_export)
    session_import = session_sub.add_parser("import")
    session_import.add_argument("--project-json", required=True)
    session_import.add_argument("--session-id")
    session_import.set_defaults(func=cmd_session_import)
