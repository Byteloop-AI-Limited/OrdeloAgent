# FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11
# FROM tiangolo/uvicorn-gunicorn-fastapi:python3.12
FROM python:3.12-slim

# Install system packages in one go and clean up
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Create and set working directory
WORKDIR /app

# Install UV package manager
RUN pip install uv
COPY requirements.txt /tmp/requirements.txt
RUN uv pip install --system -r /tmp/requirements.txt

# Copy your application code (including start.sh) into /app
COPY . /app

# Simpler copy, try at a later stage
# COPY start.sh gunicorn_conf.py aws_setting.py config ordelo ordelo_datamodels utils_common watomation /app/

# Copy your startup script and make it executable
RUN chmod +x /app/start.sh

# Expose the port App Runner will bind to ($PORT, default 80)
EXPOSE 80

# Let start.sh handle everything else (env-files, gunicorn conf, etc.)
ENTRYPOINT ["/app/start.sh"]

# docker build -t ordelo-local .
# docker run --env-file .env -p 80:80 ordelo-local