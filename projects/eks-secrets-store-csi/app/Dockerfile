# syntax=docker/dockerfile:1
#
# secure-frontend stand-in. The image contains code only: no secret is
# copied in, passed as a build arg, or set with ENV. Secrets arrive at run
# time as files on the CSI volume (/mnt/secrets), mounted read-only.
#
# Base pinned by exact tag. Pin by digest as well in a real pipeline
# (python:3.12.12-slim-bookworm@sha256:<digest>) and let Renovate bump it.
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY server.py ./
RUN python -m py_compile server.py && rm -rf __pycache__

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    SECRETS_DIR=/mnt/secrets \
    SECRETS_POLL_SECONDS=10

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
# Owned by root, so the app user can't modify its own code.
COPY --from=build --chown=root:root /src/server.py ./

USER 10001:10001
EXPOSE 8080

ENTRYPOINT ["python", "/app/server.py"]
