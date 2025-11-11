"""App configuration and constants

Responsibilities:
- Resolve storage paths (base, PDFs, database)
- Provide simple helpers for request validation
"""

import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STORAGE_DIR = os.environ.get('STORAGE_DIR', os.path.join(BASE_DIR, 'storage'))
PDF_DIR: str = os.path.join(STORAGE_DIR, 'pdfs')
DB_PATH: str = os.path.join(STORAGE_DIR, 'app.db')

# Ensure storage dirs exist at import time
os.makedirs(PDF_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.pdf'}

def allowed_file(filename: str) -> bool:
    """Return True if filename has an allowed extension.

    Currently only .pdf files are accepted.
    """
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS
