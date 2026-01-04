#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

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
  [ -f "$venv_path/bin/activate" ] && \
  "$venv_path/bin/python" -c "import pip" 2>/dev/null
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
  echo "INFO: Creating new virtual environment in $VENV_DIR..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# envAct: Activate virtual environment
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Upgrade pip and install dependencies
python -m pip install --upgrade pip --quiet

if [ -f "requirements.txt" ]; then
  echo "INFO: Installing requirements.txt..."
  python -m pip install -r requirements.txt --quiet
fi

if [ -f "requirements-dev.txt" ]; then
  echo "INFO: Installing requirements-dev.txt..."
  python -m pip install -r requirements-dev.txt --quiet
fi

# setPyPath: Set Python path to project root and persist in venv activate
export PYTHONPATH="$ROOT_DIR"

# Add PYTHONPATH to venv activate script if not already present
ACTIVATE_SCRIPT="$VENV_DIR/bin/activate"
if ! grep -q "PYTHONPATH=" "$ACTIVATE_SCRIPT" 2>/dev/null; then
  echo "" >> "$ACTIVATE_SCRIPT"
  echo "# Added by run_setup.sh - set PYTHONPATH to project root" >> "$ACTIVATE_SCRIPT"
  echo "export PYTHONPATH=\"$ROOT_DIR\"" >> "$ACTIVATE_SCRIPT"
  echo "INFO: PYTHONPATH added to $ACTIVATE_SCRIPT"
else
  echo "INFO: PYTHONPATH already in $ACTIVATE_SCRIPT"
fi
echo "INFO: PYTHONPATH set to $ROOT_DIR"

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
