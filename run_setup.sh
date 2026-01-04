#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=""

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN not found on PATH." >&2
  exit 1
fi

if [ -d ".venv" ]; then
  VENV_DIR=".venv"
elif [ -d "venv" ]; then
  VENV_DIR="venv"
else
  VENV_DIR="venv"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# envAct: Activate virtual environment
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

if [ -f "requirements.txt" ]; then
  python -m pip install -r requirements.txt
fi

if [ -f "requirements-dev.txt" ]; then
  python -m pip install -r requirements-dev.txt
fi

if [ -f ".env" ]; then
  # envLoad: Export environment variables from .env (skip comments)
  export $(grep -v '^#' .env | xargs)
fi

# setPyPath: Set Python path to project root
export PYTHONPATH="$ROOT_DIR"

std_ok=0
if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
  std_ok=1
fi

settings_missing=()
for var in AWS_SETTINGS_KEY_ID AWS_SETTINGS_ACCESS_KEY AWS_SETTINGS_REGION AWS_SETTINGS_SECRET_NAME; do
  if [ -z "${!var:-}" ]; then
    settings_missing+=("$var")
  fi
done

settings_ok=0
if [ "${#settings_missing[@]}" -eq 0 ]; then
  settings_ok=1
fi

if [ "$std_ok" -eq 1 ]; then
  echo "SUCCESS: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are set."
else
  echo "INFO: Missing AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY."
fi

if [ "$settings_ok" -eq 1 ]; then
  echo "SUCCESS: AWS_SETTINGS_* variables are set for aws_setting.py."
else
  echo "INFO: Missing AWS_SETTINGS_* vars: ${settings_missing[*]:-none}"
fi

if [ "$std_ok" -eq 1 ] || [ "$settings_ok" -eq 1 ]; then
  echo "SUCCESS: AWS credentials detected."
else
  echo "WARN: No AWS credentials detected."
  exit 1
fi
