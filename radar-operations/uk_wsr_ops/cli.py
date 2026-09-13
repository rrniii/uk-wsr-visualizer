import argparse
import json
from collections import Counter
from pathlib import Path

from .core import PROCESSORS, atomic, audit_case, manifest, read


def main():
    parser = argparse.ArgumentParser(prog="uk-wsr-ops")
    parser.add_argument("--config", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--index", type=int)
    audit.add_argument("--metrics", action="store_true")
    commands.add_parser("summarize")
    commands.add_parser("pack")
    commands.add_parser("status")
    candidate = commands.add_parser("materialize-candidate")
    candidate.add_argument("--index", type=int, required=True)
    candidate.add_argument("--processor", choices=PROCESSORS, required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8791)
    run = commands.add_parser("run-one")
    run.add_argument("--index", type=int, required=True)
    run.add_argument("--decision", required=True)
    run.add_argument("--releases", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--decision", required=True)
    publish.add_argument("--releases", required=True)
    select = commands.add_parser("activate")
    select.add_argument("--catalogue", required=True)
    select.add_argument("--releases", required=True)
    commands.add_parser("decision-template")
    freeze = commands.add_parser("freeze-archive")
    freeze.add_argument("--cases", required=True)
    freeze.add_argument("--destination", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--decision", required=True)
    submit.add_argument("--releases", required=True)
    submit.add_argument("--interpreter", required=True)
    submit.add_argument("--script", required=True)
    submit.add_argument("--execute", action="store_true")
    selected = commands.add_parser("selected")
    selected.add_argument("--releases", required=True)
    selected.add_argument("--case-id", required=True)
    args = parser.parse_args()
    config = read(args.config)
    if args.command == "freeze-archive":
        from .batch import freeze_archive

        print(json.dumps(freeze_archive(args.cases, args.destination), indent=2))
        return
    doc = manifest(config["manifest"])
    state = Path(config["state_root"])
    if args.command == "audit":
        cases = doc["cases"] if args.index is None else [doc["cases"][args.index]]
        for case in cases:
            rows = [audit_case(config, case, processor) for processor in PROCESSORS]
            atomic(
                state / "audit" / (case["case_id"] + ".json"),
                {"manifest_sha256": doc["manifest_sha256"], "rows": rows},
            )
            if args.metrics:
                from .evaluation import characterize

                atomic(
                    state / "metrics" / (case["case_id"] + ".json"),
                    characterize(config, case, rows),
                )
            print(
                json.dumps(
                    {
                        "case_id": case["case_id"],
                        "states": {r["processor"]: r["status"] for r in rows},
                    }
                ),
                flush=True,
            )
    elif args.command == "summarize":
        rows = []
        for case in doc["cases"]:
            path = state / "audit" / (case["case_id"] + ".json")
            if path.exists():
                entry = read(path)
                if entry["manifest_sha256"] != doc["manifest_sha256"]:
                    raise ValueError("Stale audit manifest")
                rows.extend(entry["rows"])
        summary = {
            "manifest_sha256": doc["manifest_sha256"],
            "expected": len(doc["cases"]) * 4,
            "audited": len(rows),
            "processors": {
                p: dict(Counter(r["status"] for r in rows if r["processor"] == p))
                for p in PROCESSORS
            },
            "rows": rows,
        }
        atomic(state / "inventory.json", summary)
        print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    elif args.command == "serve":
        import uvicorn
        from .review import create_app

        uvicorn.run(create_app(config), host="127.0.0.1", port=args.port)
    elif args.command == "pack":
        from .evaluation import build_pack

        pack = build_pack(config, doc)
        print(json.dumps({k: v for k, v in pack.items() if k != "cards"}, indent=2))
    elif args.command == "status":
        from .monitor import status

        print(json.dumps(status(config), indent=2))
    elif args.command == "materialize-candidate":
        from .operations import clean_product, code_digest
        from .core import sha

        case = doc["cases"][args.index]
        audit = audit_case(config, case, args.processor)
        if audit["status"] != "integrity_verified":
            raise ValueError("Candidate evidence failed integrity checks")
        destination = (
            state
            / "cleaned-candidates"
            / args.processor
            / case["case_id"]
            / "product.h5"
        )
        stats = clean_product(
            case["source_path"], audit["output_path"], destination, args.processor
        )
        record = {
            "status": "awaiting_scientific_review",
            "case_id": case["case_id"],
            "processor": args.processor,
            "source_sha256": case["source_sha256"],
            "evidence_sha256": audit["output_sha256"],
            "output_sha256": sha(destination),
            "code_sha256": code_digest(),
            "sweeps": stats,
        }
        atomic(destination.with_suffix(".json"), record)
        print(json.dumps(record, indent=2))
    elif args.command == "run-one":
        from .operations import run_one

        print(
            json.dumps(
                run_one(
                    config, args.releases, doc["cases"][args.index], read(args.decision)
                )
            )
        )
    elif args.command == "publish":
        from .operations import publish_catalog

        print(publish_catalog(args.releases, doc, read(args.decision)))
    elif args.command == "activate":
        from .operations import activate

        activate(args.releases, args.catalogue)
    elif args.command == "decision-template":
        from .operations import code_digest
        from .policies import POLICIES
        from .core import digest

        print(
            json.dumps(
                {
                    "status": "pending_review",
                    "processor": None,
                    "reviewer": None,
                    "rationale": "",
                    "blocking_failures": ["Scientific decision session outstanding"],
                    "coherent_echo_loss_accepted": False,
                    "supported_groups": [],
                    "review_evidence_sha256": None,
                    "code_sha256": code_digest(),
                    "review_evidence_path": None,
                    "runtime_identity_sha256": None,
                    "available_policy_hashes": {
                        p: digest(v) for p, v in POLICIES.items()
                    },
                },
                indent=2,
            )
        )
    elif args.command == "submit":
        from .batch import submit

        print(
            json.dumps(
                submit(
                    args.config,
                    doc,
                    args.decision,
                    args.releases,
                    args.interpreter,
                    args.script,
                    args.execute,
                ),
                indent=2,
            )
        )
    elif args.command == "selected":
        from .batch import selected_product

        print(json.dumps(selected_product(args.releases, args.case_id), indent=2))


if __name__ == "__main__":
    main()
