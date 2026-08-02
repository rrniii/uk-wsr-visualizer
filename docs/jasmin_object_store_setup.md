# JASMIN Object Store Operations

> **Maintainer page.** Normal desktop users do not need object-store
> credentials. Verify live JASMIN policy and configuration before running a
> publication command.

## Current public layout

| Setting | Current value |
|---|---|
| Tenancy | `ncas-radar-o` |
| Public bucket | `uk-wsr-visualizer-public` |
| Public base | `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public` |
| PVOL prefix | `ukmo-nimrod/pvol` |
| Catalogue prefix | `ukmo-nimrod/catalog/pvol` |
| Root catalogue | `ukmo-nimrod/catalog/pvol/catalog.json` |

The final root catalogue generated on 23 July 2026 reports
`upload_complete: true`, 17 sites, 58,427 radar-days, 23,557,040 files, and
132.4 TB represented.

Daily aggregate HDF5 working products remain on GWS. The public desktop path
uses checked per-volume PVOL HDF5 objects; it does not require aggregate files
to be copied into an app-specific layout.

## Endpoints

JASMIN provides separate S3-compatible endpoints:

- internal processing: `http://TENANCY-o.s3.jc.rl.ac.uk`;
- external public reads: `https://TENANCY-o.s3-ext.jc.rl.ac.uk`.

Use the internal endpoint for JASMIN-side jobs and the external endpoint in
public catalogue URLs.

## Credentials

Use a named service identity or an approved user token with the minimum bucket
permissions required. Store credentials in the worker's protected AWS/S3
configuration or service environment, never in this repository.

Before a live operation, confirm:

1. the tenancy role and bucket permissions;
2. source redistribution approval;
3. approved dataset description, licence/access terms, citation, and contact;
4. quota and retention expectations;
5. the exact public origin allowed by CORS;
6. a tested rollback or non-promotion path.

The committed files under `configs/` are examples without secrets. Keep the
real configuration outside version control.

## CORS

Public desktop clients need unauthenticated `GET` and `HEAD` access.
Configure CORS for the actual application/documentation origins and verify it
with a browser request. A wildcard origin can be useful during a controlled
smoke test but should be an explicit policy decision.

Generate the repository's CORS template with:

~~~bash
uk-wsr-visualizer object-store cors-template \
  --config /path/to/object_store.local.toml \
  --output /tmp/uk-wsr-cors.xml
~~~

Apply it with the approved S3 client and credentials for the tenancy.

## Publication gate

The public root catalogue must be the last discovery object promoted. Before
promotion:

1. Build a publication plan.
2. Review object keys, sizes, and redaction of private paths.
3. Sync to staging or the controlled destination.
4. Verify checksums and public readability.
5. Reconcile planned and actual objects.
6. Publish status/manifest records.
7. Promote the root catalogue only when every referenced coverage, day, and
   PVOL object is available.
8. Run a fresh external smoke test.

The object-store CLI is dry-run by default. Inspect `--help` for the installed
version before adding `--execute`:

~~~bash
uk-wsr-visualizer object-store plan --help
uk-wsr-visualizer object-store sync --help
uk-wsr-visualizer object-store verify --help
uk-wsr-visualizer object-store publish --help
uk-wsr-visualizer object-store reconcile --help
~~~

## Production boundary

Aggregate creation, PVOL generation, integrity checks, and bulk upload are
JASMIN data-production operations maintained outside this desktop repository.
This repository provides the client, catalogue parsers, publication helpers,
and verification interfaces; it must not become a second source of truth for
the radar archive.

Relevant service guidance:

- [JASMIN Object Store](https://help.jasmin.ac.uk/docs/short-term-project-storage/object-store/jasmin-object-store/)
- [JASMIN CORS configuration](https://help.jasmin.ac.uk/docs/short-term-project-storage/object-store/configuring-cors-for-object-storage/)
