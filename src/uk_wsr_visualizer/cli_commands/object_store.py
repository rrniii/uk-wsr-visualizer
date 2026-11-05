"""Object-store planning and publication commands."""

from __future__ import annotations


def register_object_store_commands(subparsers, *, handlers):
    object_store = subparsers.add_parser("object-store")
    object_store_sub = object_store.add_subparsers(required=True)

    object_store_plan = object_store_sub.add_parser("plan")
    object_store_plan.add_argument("--config", required=True)
    object_store_plan.add_argument("--catalog")
    object_store_plan.add_argument("--output", required=True)
    object_store_plan.add_argument("--staging-dir", required=True)
    object_store_plan.add_argument("--preview-dir")
    object_store_plan.add_argument("--tile-dir")
    object_store_plan.add_argument("--export-dir")
    object_store_plan.add_argument("--validation-dir")
    object_store_plan.add_argument("--run-id")
    object_store_plan.add_argument("--sha256-cache")
    object_store_plan.set_defaults(func=handlers["cmd_object_store_plan"])

    object_store_sync = object_store_sub.add_parser("sync")
    object_store_sync.add_argument("--config", required=True)
    object_store_sync.add_argument("--plan", required=True)
    object_store_sync.add_argument("--manifest", required=True)
    object_store_sync.add_argument("--execute", action="store_true")
    object_store_sync.add_argument("--skip-existing", action="store_true")
    object_store_sync.set_defaults(func=handlers["cmd_object_store_sync"])

    object_store_verify = object_store_sub.add_parser("verify")
    object_store_verify.add_argument("--config", required=True)
    object_store_verify.add_argument("--manifest", required=True)
    object_store_verify.add_argument("--output", required=True)
    object_store_verify.add_argument("--execute", action="store_true")
    object_store_verify.set_defaults(func=handlers["cmd_object_store_verify"])

    object_store_publish = object_store_sub.add_parser("publish")
    object_store_publish.add_argument("--config", required=True)
    object_store_publish.add_argument("--manifest", required=True)
    object_store_publish.add_argument("--output")
    object_store_publish.add_argument("--execute", action="store_true")
    object_store_publish.set_defaults(func=handlers["cmd_object_store_publish"])

    object_store_backfill_status = object_store_sub.add_parser("backfill-status")
    object_store_backfill_status.add_argument("--backfill-dir", required=True)
    object_store_backfill_status.add_argument("--sha256-cache")
    object_store_backfill_status.set_defaults(
        func=handlers["cmd_object_store_backfill_status"]
    )

    object_store_reconcile = object_store_sub.add_parser("reconcile")
    object_store_reconcile.add_argument("--config", required=True)
    object_store_reconcile.add_argument("--catalog")
    object_store_reconcile.add_argument("--manifest", required=True)
    object_store_reconcile.add_argument("--output", required=True)
    object_store_reconcile.add_argument("--staging-dir", required=True)
    object_store_reconcile.add_argument("--preview-dir")
    object_store_reconcile.add_argument("--tile-dir")
    object_store_reconcile.add_argument("--export-dir")
    object_store_reconcile.add_argument("--validation-dir")
    object_store_reconcile.add_argument("--run-id")
    object_store_reconcile.set_defaults(func=handlers["cmd_object_store_reconcile"])

    object_store_release = object_store_sub.add_parser("release-candidate")
    object_store_release.add_argument("--config", required=True)
    object_store_release.add_argument("--catalog")
    object_store_release.add_argument("--manifest")
    object_store_release.add_argument("--output", required=True)
    object_store_release.add_argument("--plan-output", required=True)
    object_store_release.add_argument("--staging-dir", required=True)
    object_store_release.add_argument("--preview-dir")
    object_store_release.add_argument("--tile-dir")
    object_store_release.add_argument("--export-dir")
    object_store_release.add_argument("--validation-dir")
    object_store_release.add_argument("--run-id")
    object_store_release.add_argument(
        "--max-catalog-age-hours", type=float, default=24.0
    )
    object_store_release.add_argument(
        "--max-data-latency-days", type=float, default=3.0
    )
    object_store_release.add_argument(
        "--max-manifest-age-hours", type=float, default=30.0
    )
    object_store_release.add_argument("--skip-wct-validation", action="store_true")
    object_store_release.set_defaults(
        func=handlers["cmd_object_store_release_candidate"]
    )

    object_store_cors = object_store_sub.add_parser("cors-template")
    object_store_cors.add_argument("--config", required=True)
    object_store_cors.add_argument("--output", required=True)
    object_store_cors.set_defaults(func=handlers["cmd_object_store_cors_template"])

    object_store_buckets = object_store_sub.add_parser("buckets")
    object_store_buckets.add_argument("--config", required=True)
    object_store_buckets.add_argument(
        "--delete-empty-bucket", action="append", default=[]
    )
    object_store_buckets.add_argument("--create-bucket", action="append", default=[])
    object_store_buckets.add_argument("--execute", action="store_true")
    object_store_buckets.set_defaults(func=handlers["cmd_object_store_buckets"])
