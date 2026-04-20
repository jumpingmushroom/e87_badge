"""Root conftest.py — ensures the project root is on sys.path for pytest."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
