"""
Pytest configuration for backend_py tests.

Sets up the Python path to ensure backend_py is importable.
"""

import sys
from pathlib import Path

# Ensure the parent directory is in the path so 'backend_py' is importable
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
