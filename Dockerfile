FROM python:3.12-slim

WORKDIR /app

# Install the package (and its only dependency, aiohttp) from pyproject.toml.
COPY pyproject.toml ./
COPY herdogroco/ ./herdogroco/
RUN pip install --no-cache-dir .

COPY healthcheck.py .

# Build metadata (passed by compose / CI).
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV GIT_SHA=$GIT_SHA BUILD_DATE=$BUILD_DATE

LABEL org.opencontainers.image.source="https://github.com/mirecekd/herdogroco" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.created=$BUILD_DATE

# The container listens on all interfaces by default (the app itself defaults
# to 127.0.0.1). Compose overrides HOST because it uses host networking.
ENV HOST=0.0.0.0 \
    PORT=8130 \
    DATA_DIR=/app/data

# Run as an unprivileged user. The data directory holds the OAuth state
# (clients, token hashes, pairing code), so it must be writable by this user;
# for a bind mount, chown the host directory to uid 1000.
RUN useradd --create-home --uid 1000 herdogroco && \
    mkdir -p /app/data && \
    chown herdogroco:herdogroco /app/data
USER herdogroco

VOLUME /app/data

EXPOSE 8130

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "healthcheck.py"]

CMD ["python", "-m", "herdogroco"]
