#!/bin/bash

# Create a virtual environment in the 'venv' directory
uv venv --python 3.12

# Activate the virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies using uv as the package manager, as it is already installed
uv install requirements.txt

echo "Virtual environment setup complete. Dependencies installed using uv."
