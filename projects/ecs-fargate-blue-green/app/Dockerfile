# syntax=docker/dockerfile:1
#
# Multi-arch base (linux/arm64 and linux/amd64), pinned by exact tag. Pin by
# digest too in a real pipeline; a tag can be re-pointed upstream.
# Build for Graviton:  docker buildx build --platform linux/arm64 -t bluegreen-api:<sha> .
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm

# ---- build stage: compile and smoke-import before anything is tagged -------
FROM ${PYTHON_IMAGE} AS build
WORKDIR /src
COPY server.py healthcheck.py VERSION ./
RUN python -m py_compile server.py healthcheck.py \
 && python -c "import server; server.load_config({})" \
 && rm -rf __pycache__

# ---- runtime stage ----------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG APP_VERSION=0.0.0-dev
ARG IMAGE_TAG=unknown
LABEL org.opencontainers.image.title="bluegreen-api" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${IMAGE_TAG}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_VERSION=${APP_VERSION} \
    IMAGE_TAG=${IMAGE_TAG}

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=build --chown=root:root /src/server.py /src/healthcheck.py /src/VERSION ./

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["python", "/app/server.py"]
