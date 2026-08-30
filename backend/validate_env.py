"""Validate required deployment environment variables.

Usage: python backend/validate_env.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
required = ("GROQ_API_KEY", "SECRET_KEY")
missing = [name for name in required if not os.getenv(name) or os.getenv(name).startswith("your_")]
if missing:
    print("Missing or placeholder environment variables: " + ", ".join(missing))
    sys.exit(1)
print("Environment configuration is valid.")
