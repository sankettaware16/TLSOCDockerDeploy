# Base Python image
FROM python:3.11-slim

# Install system dependencies needed for compilation and GeoIP support
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libmaxminddb0 \
        libmaxminddb-dev \
        libsnappy-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root user for security
RUN groupadd --gid 1001 appuser \
    && useradd --uid 1001 --gid appuser --shell /bin/bash --create-home appuser

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy engine source code
COPY main.py        .
COPY config.yaml    .
COPY core/          ./core/
COPY utils/         ./utils/
COPY rules/         ./rules/

# Create required runtime directories and set ownership
RUN mkdir -p logs database \
    && mkdir -p /var/log/soc_output \
    && chown -R appuser:appuser /app \
    && chown appuser:appuser /var/log/soc_output

# Download GeoIP database if license key is provided
ARG MAXMIND_LICENSE_KEY=""
RUN if [ -n "$MAXMIND_LICENSE_KEY" ]; then \
      echo "[+] Downloading GeoIP database..." && \
      curl -L \
        "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" \
        -o /tmp/geo.tar.gz && \
      tar -xzf /tmp/geo.tar.gz -C /tmp && \
      mv /tmp/GeoLite2-City_*/GeoLite2-City.mmdb /app/database/ && \
      rm -rf /tmp/geo* && \
      echo "[+] GeoIP database installed successfully" ; \
    else \
      echo "[!] No MaxMind key provided — GeoIP enrichment will be disabled" ; \
    fi

# Switch to non-root and set Environment Variables
USER appuser

# Disable output buffering for real-time container logs
ENV PYTHONUNBUFFERED=1
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379

# Start the engine
ENTRYPOINT ["python3", "main.py"]
