"""
Pytest configuration file

Adds the parent directory to sys.path so that tests can import
modules from the project root.
"""
import sys
from pathlib import Path

# Add the parent directory to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
