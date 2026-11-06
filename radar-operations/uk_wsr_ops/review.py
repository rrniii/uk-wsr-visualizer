from __future__ import annotations

import io
import json
import sqlite3
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import h5py
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw

from .core import (
    PROCESSORS,
    audit_case,
    digest,
    fields,
    manifest,
    output_path,
    read,
    safe_id,
    sha,
    sweeps,
)
from .policies import POLICIES, decide, diagnostic
from .scoring import polygon_mask, score


@contextmanager
def connect(state):
    db = sqlite3.connect(Path(state) / "review.sqlite", timeout=30)
    db.execute(
        "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created REAL, reviewer TEXT, case_id TEXT, kind TEXT, payload TEXT)"
    )
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def create_app(config):
    app = FastAPI(title="Radar processing decision workspace")
    doc = manifest(config["manifest"])
    cases = {c["case_id"]: c for c in doc["cases"]}
    state = Path(config["state_root"])
    state.mkdir(parents=True, exist_ok=True)
    with connect(state):
        pass

    @app.middleware("http")
    async def local_writes(request: Request, call_next):
        if request.method == "POST" and request.headers.get("x-radar-review") != "1":
            return Response("Review header required", status_code=403)
        return await call_next(request)

    def case(case_id):
        if case_id not in cases:
            raise HTTPException(404, "Unknown case")
        return cases[case_id]

    def event(reviewer, case_id, kind, payload):
        safe_id(reviewer)
        with connect(state) as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "annotation":
                payload["source_first"] = (
                    db.execute(
                        "SELECT 1 FROM events WHERE reviewer=? AND case_id=? AND kind='reveal' LIMIT 1",
                        (reviewer, case_id),
                    ).fetchone()
                    is None
                )
            db.execute(
                "INSERT INTO events(created,reviewer,case_id,kind,payload) VALUES(?,?,?,?,?)",
                (
                    time.time(),
                    reviewer,
                    case_id,
                    kind,
                    json.dumps(payload, allow_nan=False),
                ),
            )

    def exposed(reviewer, case_id):
        with connect(state) as db:
            return (
                db.execute(
                    "SELECT 1 FROM events WHERE reviewer=? AND case_id=? AND kind='reveal' LIMIT 1",
                    (reviewer, case_id),
                ).fetchone()
                is not None
            )

    @lru_cache(maxsize=16)
    def verified(case_id, processor, signature):
        row = audit_case(config, case(case_id), processor)
        if row["status"] != "integrity_verified":
            raise HTTPException(409, {"status": row["status"], "errors": row["errors"]})
        return row

    def product(case_id, processor):
        if processor not in PROCESSORS:
            raise HTTPException(404, "Unknown processor")
        p = output_path(config, case(case_id), processor)
        source = Path(case(case_id)["source_path"])
        sidecar = (
            p.with_suffix(".provenance.json")
            if processor == "rack"
            else Path(
                str(p)
                + {
                    "pyrad": ".pyrad.json",
                    "lrose": ".json",
                    "baltrad": ".provenance.json",
                }[processor]
            )
        )
        signature = tuple(
            (q.stat().st_size, q.stat().st_mtime_ns) if q.exists() else None
            for q in (source, p, sidecar)
        )
        verified(case_id, processor, signature)
        return p

    @app.get("/", response_class=HTMLResponse)
    def home():
        return Path(__file__).with_name("review.html").read_text()

    @app.get("/api/cases")
    def list_cases():
        inventory = (
            read(state / "inventory.json")
            if (state / "inventory.json").exists()
            else {"rows": []}
        )
        return {
            "manifest_sha256": doc["manifest_sha256"],
            "cases": [
                {k: c.get(k) for k in ("case_id", "radar", "pulse", "season")}
                for c in cases.values()
            ],
            "inventory": [
                {k: r.get(k) for k in ("case_id", "processor", "status", "errors")}
                for r in inventory["rows"]
            ],
            "policies": POLICIES,
        }

    @app.get("/api/operational/{case_id}")
    def operational(case_id: str):
        from .batch import selected_product

        case(case_id)
        try:
            return selected_product(
                config.get("releases_root", str(state / "releases")), case_id
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/pack")
    def pack():
        path = state / "decision-pack.json"
        if not path.exists():
            return {"cards": [], "complete": False}
        entry = read(path)
        if entry.get("policy_hashes") != {p: digest(v) for p, v in POLICIES.items()}:
            raise HTTPException(
                409, "Decision pack requires recomputation for current policies"
            )
        return entry

    @app.get("/api/operations")
    def operations_status():
        from .monitor import status

        return status(config)

    @app.get("/api/cases/{case_id}")
    def metadata(case_id: str):
        c = case(case_id)
        source = c["source_path"]
        if sha(source) != c["source_sha256"]:
            raise HTTPException(409, "Source checksum mismatch")
        with h5py.File(source, "r") as h:
            result = [
                {
                    "name": n,
                    "elevation": float(h[n]["where"].attrs["elangle"]),
                    "shape": list(fields(h[n])["DBZH"]["data"].shape),
                    "fields": sorted(fields(h[n])),
                }
                for n in sweeps(h)
                if "DBZH" in fields(h[n])
            ]
        return {"sweeps": result}

    @app.post("/api/cases/{case_id}/reveal")
    def reveal(case_id: str, payload: dict):
        case(case_id)
        reviewer = safe_id(payload["reviewer"])
        event(reviewer, case_id, "reveal", {"manifest_sha256": doc["manifest_sha256"]})
        order = sorted(
            PROCESSORS, key=lambda p: digest([case_id, p, doc["manifest_sha256"]])
        )
        metrics_path = state / "metrics" / (case_id + ".json")
        selected = {}
        if metrics_path.exists():
            entry = read(metrics_path)
            if entry.get("policy_hashes") != {
                p: digest(v) for p, v in POLICIES.items()
            }:
                raise HTTPException(
                    409, "Candidate metrics require recomputation for current policies"
                )
            for row in entry["sweeps"]:
                if row["sweep"] == payload.get("sweep"):
                    selected = row["metrics"]
        return {
            "candidates": [
                {
                    "alias": chr(65 + i),
                    "processor": p if payload.get("named") else None,
                    "coverage": selected.get(p),
                }
                for i, p in enumerate(order)
            ]
        }

    def resolve_alias(case_id, alias):
        if alias not in "ABCD" or len(alias) != 1:
            raise HTTPException(404, "Unknown alias")
        return sorted(
            PROCESSORS, key=lambda p: digest([case_id, p, doc["manifest_sha256"]])
        )[ord(alias) - 65]

    @app.get("/api/cases/{case_id}/image")
    def render(
        case_id: str,
        sweep: str,
        quantity: str = "DBZH",
        candidate: str = "source",
        view: str = "cleaned",
        reviewer: str = "reviewer",
        projection: str = "gate",
    ):
        c = case(case_id)
        if candidate == "source":
            path = Path(c["source_path"])
            if sha(path) != c["source_sha256"]:
                raise HTTPException(409, "Source checksum mismatch")
        else:
            if not exposed(reviewer, case_id):
                raise HTTPException(403, "Reveal candidates first")
            path = product(case_id, resolve_alias(case_id, candidate))
        with h5py.File(path, "r") as h:
            if sweep not in sweeps(h) or quantity not in fields(h[sweep]):
                raise HTTPException(404, "Field/sweep unavailable")
            data = diagnostic(fields(h[sweep])[quantity])
            geometry = dict(h[sweep]["where"].attrs)
            azimuth = dict(h[sweep]["how"].attrs) if "how" in h[sweep] else {}
            if candidate != "source":
                decision = decide(h[sweep], resolve_alias(case_id, candidate))
                if data.shape != decision["remove"].shape:
                    raise HTTPException(409, "Field geometry incompatible with mask")
                if view == "cleaned":
                    data[decision["remove"]] = np.nan
                elif view == "removed":
                    data[~decision["remove"]] = np.nan
                elif view == "decision":
                    data = np.where(
                        decision["supported"],
                        np.where(
                            decision["remove"], 1, np.where(decision["uncertain"], 2, 0)
                        ),
                        3,
                    ).astype(float)
        lo, hi = {
            "DBZH": (-32, 75),
            "ZDR": (-5, 8),
            "RHOHV": (0, 1),
            "VRADH": (-30, 30),
            "PHIDP": (-180, 180),
            "WRADH": (0, 10),
        }.get(quantity, (-32, 75))
        if candidate != "source" and view == "decision":
            palette = np.array(
                [[50, 120, 180], [235, 75, 45], [245, 190, 60], [90, 90, 90]],
                dtype=np.uint8,
            )
            rgb = palette[np.nan_to_num(data).astype(int)]
        else:
            t = np.clip(np.nan_to_num((data - lo) / (hi - lo)), 0, 1)
            rgb = (
                np.stack(
                    [
                        np.clip(2 * t - 0.2, 0, 1),
                        np.sin(t * np.pi),
                        np.clip(1.2 - 2 * t, 0, 1),
                    ],
                    axis=-1,
                )
                * 255
            ).astype(np.uint8)
            rgb[~np.isfinite(data)] = [15, 23, 35]
        if projection == "polar":
            if "startazA" not in azimuth or "stopazA" not in azimuth:
                raise HTTPException(
                    409, "Measured ray azimuths unavailable; use native gate view"
                )
            start, stop = (
                np.asarray(azimuth["startazA"]),
                np.asarray(azimuth["stopazA"]),
            )
            if start.shape != (data.shape[0],) or stop.shape != start.shape:
                raise HTTPException(409, "Ray azimuth geometry differs")
            widths = (stop - start) % 360
            centres = (start + widths / 2) % 360
            order = np.argsort(centres)
            yy, xx = np.indices((720, 720), dtype=float)
            xx -= 359.5
            yy = 359.5 - yy
            angle = np.degrees(np.arctan2(xx, yy)) % 360
            right = np.searchsorted(centres[order], angle) % len(order)
            left = (right - 1) % len(order)
            delta_right = np.abs((angle - centres[order[right]] + 180) % 360 - 180)
            delta_left = np.abs((angle - centres[order[left]] + 180) % 360 - 180)
            rays = order[np.where(delta_right <= delta_left, right, left)]
            range_start = float(geometry["rstart"]) * 1000
            spacing = float(geometry["rscale"])
            outer = range_start + data.shape[1] * spacing
            distance = np.hypot(xx, yy) / 350 * outer
            gates = np.floor((distance - range_start) / spacing).astype(int)
            valid = (
                (gates >= 0)
                & (gates < data.shape[1])
                & (np.minimum(delta_left, delta_right) <= widths[rays] / 2 + 0.001)
            )
            projected = rgb[rays, np.clip(gates, 0, data.shape[1] - 1)].copy()
            projected[~valid] = [15, 23, 35]
            image = Image.fromarray(projected)
            overlay = ImageDraw.Draw(image)
            for fraction in (0.25, 0.5, 0.75, 1):
                radius = 350 * fraction
                overlay.ellipse(
                    (359.5 - radius, 359.5 - radius, 359.5 + radius, 359.5 + radius),
                    outline=(140, 150, 160),
                    width=1,
                )
            overlay.text((356, 1), "N", fill="white")
            overlay.text((704, 355), "E", fill="white")
            overlay.text((8, 702), f"{outer / 1000:.1f} km slant range", fill="white")
        elif projection == "gate":
            image = Image.fromarray(rgb).resize((720, 480), Image.Resampling.NEAREST)
        else:
            raise HTTPException(422, "Unknown projection")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return Response(
            stream.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/cases/{case_id}/annotations")
    def annotate(case_id: str, payload: dict):
        c = case(case_id)
        reviewer = safe_id(payload["reviewer"])
        if payload.get("label") not in (
            "weather",
            "biology",
            "mixed",
            "ground_clutter",
            "sea_clutter",
            "interference",
            "speckle",
            "receiver_background",
            "uncertain",
        ):
            raise HTTPException(422, "Unknown label")
        action = (
            "ignore"
            if payload["label"] == "uncertain"
            else "retain"
            if payload["label"] in ("weather", "biology", "mixed")
            else "remove"
        )
        with h5py.File(c["source_path"], "r") as h:
            if sha(c["source_path"]) != c["source_sha256"]:
                raise HTTPException(409, "Source changed before annotation")
            if payload["sweep"] not in sweeps(h):
                raise HTTPException(422, "Invalid sweep")
            shape = fields(h[payload["sweep"]])["DBZH"]["data"].shape
        try:
            polygon_mask(shape, payload["vertices"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        record = {
            "sweep": payload["sweep"],
            "label": payload["label"],
            "action": action,
            "vertices": payload["vertices"],
            "notes": str(payload.get("notes", ""))[:4000],
            "source_first": not exposed(reviewer, case_id),
            "manifest_sha256": doc["manifest_sha256"],
            "source_sha256": c["source_sha256"],
            "shape": list(shape),
        }
        if payload.get("supersedes") is not None:
            with connect(state) as db:
                old = db.execute(
                    "SELECT reviewer,case_id,kind FROM events WHERE id=?",
                    (int(payload["supersedes"]),),
                ).fetchone()
            if old != (reviewer, case_id, "annotation"):
                raise HTTPException(
                    422,
                    "Revision may replace only this reviewer's annotation on this case",
                )
            record["supersedes"] = int(payload["supersedes"])
        event(reviewer, case_id, "annotation", record)
        return record

    @app.get("/api/export")
    def export(strict: bool = True, include_ignored: bool = False):
        with connect(state) as db:
            rows = db.execute(
                "SELECT id,reviewer,case_id,payload FROM events WHERE kind='annotation' ORDER BY id"
            ).fetchall()
        superseded = {
            json.loads(payload).get("supersedes") for _, _, _, payload in rows
        }
        return [
            {"revision": i, "reviewer": reviewer, "case_id": cid, **readout}
            for i, reviewer, cid, payload in rows
            for readout in [json.loads(payload)]
            if not strict
            or (
                i not in superseded
                and readout["source_first"]
                and (include_ignored or readout["action"] != "ignore")
            )
        ]

    @app.get("/api/scores")
    def scores():
        labels = export(True, True)
        result = []
        for cid, sweep, reviewer in sorted(
            {(r["case_id"], r["sweep"], r["reviewer"]) for r in labels}
        ):
            regions = [
                r
                for r in labels
                if (r["case_id"], r["sweep"], r["reviewer"]) == (cid, sweep, reviewer)
            ]
            for p in PROCESSORS:
                try:
                    with h5py.File(product(cid, p), "r") as h:
                        result.append(
                            {
                                "case_id": cid,
                                "sweep": sweep,
                                "reviewer": reviewer,
                                "processor": p,
                                **score(decide(h[sweep], p), regions),
                            }
                        )
                except (HTTPException, ValueError) as exc:
                    result.append(
                        {
                            "case_id": cid,
                            "processor": p,
                            "status": "unavailable",
                            "error": str(exc),
                        }
                    )
        return {
            "labelled_regions": len(labels),
            "scores": result,
            "interpretation": "Only source-first confident labels; no labels means no scientific scores.",
        }

    return app
