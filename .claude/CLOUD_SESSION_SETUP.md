# Cloud Session Setup

This document provides setup instructions for working with the Ordelo Agent project in cloud sessions (e.g., Claude Code on the web).

## Python Virtual Environment Setup

When starting a new cloud session, the Python virtual environment needs to be activated to ensure all dependencies are available and the project is configured correctly.

### Quick Setup

Run the setup script to automatically create and configure the virtual environment:

```bash
source run_setup.sh
```

This script will:
1. Create a `.venv` directory (if it doesn't exist)
2. Activate the virtual environment
3. Upgrade pip to the latest version
4. Install all dependencies from `requirements.txt`
5. Set `PYTHONPATH` to the project root (`/home/user/OrdeloAgent`)
6. Verify AWS environment variables are configured

### Manual Setup (Alternative)

If you prefer to set up the environment manually:

```bash
# Create the virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Set PYTHONPATH
export PYTHONPATH="/home/user/OrdeloAgent"
```

### Activating Existing Virtual Environment

If the `.venv` directory already exists from a previous session:

```bash
source .venv/bin/activate
```

### Verifying Setup

After running the setup, verify everything is configured correctly:

```bash
# Check virtual environment is activated
echo $VIRTUAL_ENV
# Expected: /home/user/OrdeloAgent/.venv

# Check Python location
which python
# Expected: /home/user/OrdeloAgent/.venv/bin/python

# Check PYTHONPATH
echo $PYTHONPATH
# Expected: /home/user/OrdeloAgent

# Verify dependencies are installed
pip list
```

### Requirements

The setup script requires the following AWS environment variables to be set (these should be available in the runtime):

- `AWS_SETTINGS_KEY_ID`
- `AWS_SETTINGS_ACCESS_KEY`
- `AWS_SETTINGS_REGION`
- `AWS_SETTINGS_SECRET_NAME`

These variables are used by `aws_setting.py` to fetch secrets from AWS Systems Manager (SSM).

### Optional: Install Development Dependencies

To install development dependencies (e.g., testing tools, linters):

```bash
INSTALL_DEV=1 source run_setup.sh
```

## Notes for Claude Code Sessions

- The virtual environment activation doesn't persist across separate tool invocations in Claude Code
- When running Python commands, prefix them with `source .venv/bin/activate &&` to ensure the venv is active
- The `run_setup.sh` script is idempotent and can be run multiple times safely
- The script prefers `.venv` over `venv` directory naming convention

## Created

2026-01-04
