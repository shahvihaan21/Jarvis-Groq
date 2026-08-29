"""
Vercel Serverless Function entry point for Jarvis AI Django backend.
Exposes the WSGI application to @vercel/python runtime.
"""

import os
import sys
from pathlib import Path

# Add project root and backend folder to sys.path so modules resolve anywhere in Lambda
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai.settings")

from ai.wsgi import application

# Vercel looks for 'app' or 'application'
app = application
