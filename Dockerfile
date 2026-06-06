FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by cryptography (google-auth dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for layer caching
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir cffi && pip install --no-cache-dir -e .

# Copy source and config
COPY src/ src/
COPY config/ config/

# logs/state.json must persist across container restarts — mount a volume here
VOLUME ["/app/logs"]

# Default command is a dry run; override with [] for a live run.
# Examples:
#   docker run meo-automation                       # dry run (safe)
#   docker run meo-automation python -m meo.main    # live run
ENTRYPOINT ["python", "-m", "meo.main"]
CMD ["--dry-run"]
