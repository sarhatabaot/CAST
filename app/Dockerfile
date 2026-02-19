FROM astral/uv:python3.12-bookworm-slim

# Set work directory
WORKDIR /app

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Move lock files into a non-runtime directory for better caching
COPY pyproject.toml uv.lock /_lock/

# Sync dependencies (cached until lock files change)
RUN --mount=type=cache,target=/root/.cache \
    cd /_lock && \
    uv sync \
        --frozen \
        --no-install-project

# Copy application code
COPY .. .
