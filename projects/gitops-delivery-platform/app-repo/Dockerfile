# orders-api: stdlib Python, no dependencies, runs as a fixed non-root UID.
# The base is pinned by digest (Renovate/Dependabot bumps it); the tag is for humans.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# UID/GID 10001 matches runAsUser/runAsGroup in the Helm chart.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /srv
COPY --chown=root:root --chmod=0444 app/orders_api.py /srv/orders_api.py

# CI passes the immutable git SHA; /version reports it.
ARG APP_VERSION=unset
ENV APP_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.source="https://github.com/example-org/orders-api" \
      org.opencontainers.image.revision="${APP_VERSION}"

USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python3", "/srv/orders_api.py"]
