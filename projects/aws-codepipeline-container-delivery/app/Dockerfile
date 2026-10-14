# syntax=docker/dockerfile:1
#
# Base image pinned by exact tag. For stronger reproducibility pin by digest
# as well (python:3.12.12-slim-bookworm@sha256:<digest>) and let Dependabot or
# Renovate bump it; a tag can be re-pointed upstream, a digest cannot.
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

# ---- build stage: compile and smoke-import the app ---------------------------
# A failing import or syntax error stops the build here, before any image is
# tagged. Only the checked sources are copied into the runtime stage.
FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY server.py healthcheck.py VERSION ./
RUN python -m py_compile server.py healthcheck.py \
 && python -c "import server; server.load_config({})" \
 && rm -rf __pycache__

# ---- runtime stage ----------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown

LABEL org.opencontainers.image.title="container-delivery-demo" \
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
COPY --from=build --chown=root:root /src/server.py /src/healthcheck.py /src/VERSION ./

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["python", "/app/server.py"]
