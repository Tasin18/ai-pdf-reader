"""Fetch and vendor PDF.js assets locally.

Downloads a specific version of PDF.js browser assets into frontend/vendor
so the app can run without external CDNs and avoid SRI/CSP issues.
"""

import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
VENDOR_DIR = os.path.join(ROOT, 'frontend', 'vendor')
VERSION = os.environ.get('PDFJS_VERSION', '3.11.174')
CDN_BASE = f'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/{VERSION}'

FILES = {
    'pdf.min.js': f'{CDN_BASE}/pdf.min.js',
    'pdf.worker.min.js': f'{CDN_BASE}/pdf.worker.min.js',
    'pdf_viewer.min.js': f'{CDN_BASE}/pdf_viewer.min.js',
    'pdf_viewer.min.css': f'{CDN_BASE}/pdf_viewer.min.css',
}


def download(url: str, dest: str):
    """Download a URL to the destination file path. Returns True on success."""
    try:
        print(f'Downloading {url} -> {dest}')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as r, open(dest, 'wb') as f:
            f.write(r.read())
    except Exception as e:
        print(f'Failed to download {url}: {e}')
        return False
    return True


def main():
    """Download all declared files if missing."""
    os.makedirs(VENDOR_DIR, exist_ok=True)
    ok = True
    for name, url in FILES.items():
        dest = os.path.join(VENDOR_DIR, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f'Skip existing {name}')
            continue
        if not download(url, dest):
            ok = False
    if not ok:
        print('One or more files failed to download. The app may not be able to render PDFs offline.')
        return 1
    print('PDF.js vendor assets ready.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
