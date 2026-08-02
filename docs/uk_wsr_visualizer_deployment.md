# Service Deployment

> **Maintainer page.** Desktop packages run a private local service and do not
> require this deployment. These instructions describe an optional
> NCAS/JASMIN-managed web service.

## Architecture

The web host serves the FastAPI application and static viewer behind a reverse
proxy. Catalogue production, bulk HDF5 processing, and large object-store jobs
remain on JASMIN/GWS or batch workers.

~~~text
public HTTPS
  -> Nginx or equivalent
  -> 127.0.0.1:8000 FastAPI
  -> public PVOL catalogue and local service cache
~~~

Do not hard-code an old workstation address in public documentation. Set the
hostname, TLS certificate, CORS origin, and service account for the actual
deployment. Keep deployment-specific `ncas` host aliases in the protected
service configuration rather than in public user instructions.

## Filesystem layout

~~~text
/opt/uk-wsr-visualizer/
  repo/
  venv/
  data/
/etc/uk-wsr-visualizer/
  uk-wsr-visualizer.env
  object_store.toml
~~~

Repository templates are under `deploy/`. Review them before installation;
they contain example names and paths, not credentials.

## Install

Create a dedicated service identity, clone both required repositories, and
install into an isolated environment:

~~~bash
python3 -m venv /opt/uk-wsr-visualizer/venv
/opt/uk-wsr-visualizer/venv/bin/python -m pip install -e /opt/uk-wsr-qc
/opt/uk-wsr-visualizer/venv/bin/python -m pip install \
  -e "/opt/uk-wsr-visualizer/repo[export,video,object-store]"
~~~

Install a protected environment file from
`deploy/env/uk-wsr-visualizer.env.example`. The service should use the public
PVOL root unless a local catalogue is deliberately configured.

## Start and verify

Run the API on loopback:

~~~bash
/opt/uk-wsr-visualizer/venv/bin/uk-wsr-visualizer api \
  --host 127.0.0.1 \
  --port 8000
~~~

Verify lightweight readiness before remote catalogue access:

~~~bash
curl --fail http://127.0.0.1:8000/api/ready
curl --fail http://127.0.0.1:8000/api/status
curl --fail http://127.0.0.1:8000/api/startup-diagnostics
~~~

Then test catalogue summary, one day, one HDF5 render, identify, animation,
export, manifest, and cache clear. Readiness must remain independent of a
temporary remote catalogue failure.

## systemd and reverse proxy

The repository contains API and timer units plus an Nginx template. Enable only
the API and monitoring units required by the deployment. Object-store
publication timers require a separate approval and credential review.

Before exposing the service:

- use HTTPS;
- bind FastAPI to loopback;
- set request and download limits;
- confirm public cache and log paths;
- test CORS from the final origin;
- verify logs contain no secrets or private source paths;
- run the repository smoke test against both loopback and the public URL.

## Rollback

Keep the previous application commit and environment available. A rollback must
restore code, static assets, and schema-compatible cache behavior together.
Never roll back the public root catalogue to a state that references missing
objects.
