"""Add backend root to sys.path so tests can import services, routes, etc."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
