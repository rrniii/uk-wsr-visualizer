# Deployment Assets

This directory contains example systemd, Nginx, environment, and smoke-test
assets for an optional hosted UK WSR Visualizer service. Desktop users do not
need these files.

The templates are deployment-specific starting points. Replace hostnames,
origins, service users, paths, and certificates with reviewed local values.
Never commit credentials.

## Suggested layout

~~~text
/opt/uk-wsr-visualizer/
  repo/
  venv/
  data/
/etc/uk-wsr-visualizer/
  uk-wsr-visualizer.env
  object_store.toml
~~~

## Installation sequence

1. Create a non-login `ukwsr` service identity.
2. Clone the visualizer and standalone QC repositories under `/opt`.
3. Create an isolated virtual environment.
4. Install the QC package, then the visualizer with the required extras.
5. Copy and review the environment template.
6. Install the API unit and start it on loopback.
7. Verify `/api/ready`, `/api/status`, and
   `/api/startup-diagnostics`.
8. Configure HTTPS reverse proxying.
9. Run a real catalogue/source/render/export smoke test.

## Timers

The repository includes timers for catalogue refresh, preview build, freshness
checks, and object-store publication. Enable only tasks owned by this host.
Bulk PVOL production and upload remain JASMIN pipeline responsibilities.

Do not enable the object-store publication timer until permissions, credentials,
CORS, data policy, dry-run plan, checksums, reconciliation, and rollback have
all been reviewed.

## Smoke tests

~~~bash
bash deploy/bin/uk-wsr-visualizer-remote-smoke-test.sh \
  http://127.0.0.1:8000
~~~

Run the same test through the final HTTPS origin. The release smoke script also
checks configured manifests and publication state; review its required
environment before use.

For the complete operational boundary, see
`docs/uk_wsr_visualizer_deployment.md` and
`docs/jasmin_object_store_setup.md`.
