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
1. Verify `uv` is installed and available
2. Create a `.venv` directory using `uv venv` (if it doesn't exist)
3. Activate the virtual environment
4. Install all dependencies from `requirements.txt` using `uv pip`
5. Set `PYTHONPATH` to the project root (`/home/user/OrdeloAgent`)
6. Verify AWS environment variables are configured

### Manual Setup (Alternative)

If you prefer to set up the environment manually:

```bash
# Create the virtual environment with uv
uv venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies using uv
uv pip install -r requirements.txt

# Set PYTHONPATH
export PYTHONPATH="/home/user/OrdeloAgent"
```

**Note:** `uv` must be installed. If not available, install it with:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Activating Existing Virtual Environment

If the `.venv` directory already exists from a previous session:

```bash
source .venv/bin/activate
```

### Verifying Setup

After running the setup, verify everything is configured correctly:

```bash
# Check uv is installed
uv --version

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
uv pip list
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

- **UV Package Manager:** This project uses `uv` for faster and more reliable package management instead of `pip`
- The virtual environment activation doesn't persist across separate tool invocations in Claude Code
- When running Python commands, prefix them with `source .venv/bin/activate &&` to ensure the venv is active
- The `run_setup.sh` script is idempotent and can be run multiple times safely
- The script prefers `.venv` over `venv` directory naming convention
- `uv` is typically pre-installed in cloud environments; if not, the setup script will fail with installation instructions

## Why UV?

`uv` is a modern Python package manager written in Rust that provides:
- **10-100x faster** installation than pip
- Better dependency resolution
- Built-in virtual environment management
- Compatible with pip and requirements.txt
- Drop-in replacement for pip commands

## Created

2026-01-04
