# Add the project root to the Python path so that imports work correctly.
# This startup file is run whenever IPython is started.
# To use, create a directory at ~/.ipython/profile_default/startup and save
# this file there.

import sys
import os
import subprocess

def configure_pythonpath():
    """
    Configures the Python module search path by getting the Git project root
    and adding it to both PYTHONPATH environment variable and sys.path.
    """
    try:
        # Get the project root using Git
        project_root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], 
                                            universal_newlines=True).strip()
        
        # Set the PYTHONPATH environment variable
        os.environ['PYTHONPATH'] = project_root
        
        # Add to sys.path if not already present
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
            
    except subprocess.CalledProcessError:
        raise RuntimeError("Failed to find Git root. Make sure you're in a Git repository.")

# Configure the Python path when this startup script is run
configure_pythonpath()