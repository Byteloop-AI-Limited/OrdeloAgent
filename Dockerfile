FROM python:3.13-slim

# Install system packages in one go and clean up
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /app

# Set PYTHONPATH to /app for all processes
ENV PYTHONPATH=/app

# Install UV package manager using official installer
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/app/.venv/bin:$PATH"

# Install dependencies from lockfile first (better layer caching)
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

# Copy your application code (including start.sh) into /app
COPY . /app

# Install the project itself from lockfile
RUN uv sync --frozen --no-dev

# Copy your startup script and make it executable
RUN chmod +x /app/start.sh

# Expose the port App Runner will bind to ($PORT, default 80)
EXPOSE 80

# Let start.sh handle everything else (env-files, gunicorn conf, etc.)
ENTRYPOINT ["/app/start.sh"]
