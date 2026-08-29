"""
WSGI config for Jarvis AI project.
Exposes the WSGI callable as a module-level variable named `application` (and `app` for Vercel).
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ai.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application  # Alias for serverless platforms like Vercel
