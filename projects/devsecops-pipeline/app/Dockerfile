# syntax=docker/dockerfile:1
#
# Base image pinned by tag AND by the multi-arch index digest (resolved with
# `docker pull` + `docker inspect` on 2026-10-14). The tag documents intent;
# the digest is what is actually pulled, so an upstream re-tag cannot change
# the build. Let Dependabot/Renovate bump both together.
#
# Debian trixie, not bookworm: on 2026-10-14 the bookworm-based
# python:3.12.12-slim-bookworm carried 37 fixable CRITICAL/HIGH OS findings
# and failed the image gate; this base passes it (see README).
ARG PYTHON_IMAGE=python:3.13.16-slim-trixie@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f

FROM ${PYTHON_IMAGE}

ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown

LABEL org.opencontainers.image.title="devsecops-demo" \
      org.opencontainers.image.description="Synthetic service scanned by the DevSecOps supply-chain pipeline" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
# requirements.txt is intentionally empty (stdlib only); installing it keeps
# the Dockerfile honest if a dependency is ever added. pip itself is then
# removed: the running service never needs it, and on 2026-10-14 the only
# fixable HIGH findings in this image were in pip's vendored urllib3,
# msgpack and setuptools (Trivy reads pip's bundled SBOM).
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --no-input -r requirements.txt \
 && python -m pip uninstall --yes --no-input pip \
 && rm -rf /root/.cache
COPY --chown=root:root server.py healthcheck.py ./

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["python", "/app/server.py"]
