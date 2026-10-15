# app-repo (orders-api)

Stands in for the **application repository** of the two-repo GitOps split.
In real use this folder is its own repository; here it sits next to
`config-repo/` so the whole flow can be read in one place.

- `app/orders_api.py`: the service, Python standard library only. `/metrics`
  exposes `http_requests_total{method,path,code}`, the counter behind the
  canary's success-rate analysis.
- `tests/`: `python3 -m unittest discover -s tests -v` from this folder. The
  project-level suite runs them too.
- `Dockerfile`: digest-pinned `python:3.12-slim-bookworm`, UID/GID 10001 (the
  chart's `runAsUser`), read-only friendly (writes nothing but `/tmp`).
- `.github/workflows/ci.yml`: an **example** workflow, never executed in the
  portfolio repo. It tests, builds and pushes
  `ghcr.io/example-org/orders-api:<full git sha>`, then opens a pull request
  on `example-org/orders-config` that changes `envs/dev/values.yaml`
  `image.tag` with `scripts/promote.py --tag <sha> --to dev`. It has no
  cluster credentials; the PR token comes from a GitHub App installed only on
  the config repository.

Run it locally:

```bash
APP_ENV=local python3 app/orders_api.py      # http://127.0.0.1:8080/healthz
```
