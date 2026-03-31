#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

# Check uv is available
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found on PATH." >&2
  echo "Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

# Check Python is available
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN not found on PATH." >&2
  exit 1
fi

# Function to check if venv is functional
is_venv_functional() {
  local venv_path="$1"
  [ -d "$venv_path" ] && \
  [ -f "$venv_path/bin/python" ] && \
  [ -f "$venv_path/bin/activate" ]
}

# Determine venv directory - prefer .venv, fallback to venv
if is_venv_functional ".venv"; then
  VENV_DIR=".venv"
  echo "INFO: Using existing .venv directory."
elif is_venv_functional "venv"; then
  VENV_DIR="venv"
  echo "INFO: Using existing venv directory."
else
  # Create new venv (prefer .venv, remove broken one if exists)
  VENV_DIR=".venv"
  if [ -d "$VENV_DIR" ]; then
    echo "INFO: Removing broken $VENV_DIR..."
    rm -rf "$VENV_DIR"
  fi
  echo "INFO: Creating new virtual environment in $VENV_DIR with uv..."
  uv venv "$VENV_DIR" --python "$PYTHON_BIN"
fi

# envAct: Activate virtual environment
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install dependencies using uv sync with pyproject.toml
echo "INFO: Syncing dependencies from pyproject.toml..."
if [ "${INSTALL_DEV:-}" = "1" ]; then
  echo "INFO: Including dev dependency group (INSTALL_DEV=1)..."
  uv sync --group dev
else
  echo "INFO: Installing production dependencies only (set INSTALL_DEV=1 for dev group)."
  uv sync --no-group dev
fi

# setPyPath: Set Python path to project root and persist in venv activate
export PYTHONPATH="$ROOT_DIR"

# Add PYTHONPATH and envLoad to venv activate script if not already present
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
if ! grep -q "PYTHONPATH=" "$ACTIVATE_SCRIPT" 2>/dev/null; then
  echo "" >> "$ACTIVATE_SCRIPT"
  echo "# Added by run_setup.sh - set PYTHONPATH to project root" >> "$ACTIVATE_SCRIPT"
  echo "export PYTHONPATH=\"$ROOT_DIR\"" >> "$ACTIVATE_SCRIPT"
  echo "INFO: PYTHONPATH added to $ACTIVATE_SCRIPT"
else
  echo "INFO: PYTHONPATH already in $ACTIVATE_SCRIPT"
fi

# Add envLoad to activate script
if ! grep -q "envLoad" "$ACTIVATE_SCRIPT" 2>/dev/null; then
  cat >> "$ACTIVATE_SCRIPT" << 'ENVLOAD'

# envLoad: Load .env file from project root
if [ -f "$PYTHONPATH/.env" ]; then
  set -a
  source "$PYTHONPATH/.env"
  set +a
fi
ENVLOAD
  echo "INFO: envLoad added to $ACTIVATE_SCRIPT"
else
  echo "INFO: envLoad already in $ACTIVATE_SCRIPT"
fi
echo "INFO: PYTHONPATH set to $ROOT_DIR"

# envLoad: Load environment variables from .env file if present
if [ -f "$ROOT_DIR/.env" ]; then
  echo "INFO: Loading environment variables from .env..."
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
  echo "INFO: Environment variables loaded from .env"
else
  echo "INFO: No .env file found, skipping envLoad."
fi

# Check for required AWS_SETTINGS_* variables (used by aws_setting.py)
REQUIRED_VARS=(
  "AWS_SETTINGS_KEY_ID"
  "AWS_SETTINGS_ACCESS_KEY"
  "AWS_SETTINGS_REGION"
  "AWS_SETTINGS_SECRET_NAME"
)

missing_vars=()
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    missing_vars+=("$var")
  fi
done

if [ "${#missing_vars[@]}" -eq 0 ]; then
  echo "SUCCESS: All AWS_SETTINGS_* variables are set."
  echo "SUCCESS: Environment ready for aws_setting.py to fetch secrets from SSM."
else
  echo "ERROR: Missing required AWS_SETTINGS_* variables:"
  for var in "${missing_vars[@]}"; do
    echo "  - $var"
  done
  exit 1
fi

echo "SUCCESS: Setup complete."
