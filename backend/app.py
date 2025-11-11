"""Flask application module

Responsibilities:
- Expose the web server with endpoints for PDF upload, retrieval, word CRUD, and LLM generation
- Serve static frontend assets
- Initialize the SQLite database on startup

Public API:
- create_app() -> Flask
"""

import os
import uuid
import logging
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load .env before importing config so env vars (e.g., STORAGE_DIR) take effect
load_dotenv()

from .config import PDF_DIR, allowed_file
from . import db as dbm
from .llm import generate_word_info, generate_batch_word_info
from .pdf_edit import add_highlights_to_pdf, remove_highlights_from_pdf

logger = logging.getLogger(__name__)

def create_app() -> Flask:
    """Application factory that wires routes and initializes the database."""
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'frontend'),
        static_url_path='/static',
    )

    # Initialize database
    dbm.init_db()
    # Log LLM availability for diagnostics
    try:
        has_key = bool(os.environ.get('CEREBRAS_API_KEY'))
        model = os.environ.get('CEREBRAS_MODEL', 'llama3.1-70b')
        logger.info("LLM configured: has_key=%s model=%s", has_key, model)
    except Exception:
        logger.debug("Could not determine LLM config state.")

    @app.get('/')
    def index():
        """Serve the main reader page."""
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/library.html')
    def library_page():
        """Serve the library page."""
        return send_from_directory(app.static_folder, 'library.html')

    @app.get('/words.html')
    def words_page():
        """Serve the all-words page."""
        return send_from_directory(app.static_folder, 'words.html')

    @app.post('/api/upload')
    def upload_pdf():
        """Handle PDF uploads and persist basic metadata in the database."""
        if 'file' not in request.files:
            return jsonify({"error": "Missing file field"}), 400
        f = request.files['file']
        if f.filename == '':
            return jsonify({"error": "Empty filename"}), 400
        if not allowed_file(f.filename):
            return jsonify({"error": "Only PDF files are allowed"}), 400

        original_name = secure_filename(f.filename)
        pdf_id = uuid.uuid4().hex
        filename = f"{pdf_id}.pdf"
        path = os.path.join(PDF_DIR, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f.save(path)
        if not os.path.exists(path):
            return jsonify({"error": "Upload failed to save file"}), 500

        dbm.insert_pdf(pdf_id, original_name, filename)
        return jsonify({"pdf_id": pdf_id, "original_name": original_name})

    @app.get('/api/pdf/<pdf_id>')
    def get_pdf(pdf_id: str):
        """Return the raw PDF bytes for a stored file by ID."""
        rec = dbm.get_pdf(pdf_id)
        if not rec:
            return jsonify({"error": "Not found"}), 404
        path = os.path.join(PDF_DIR, rec['filename'])
        if not os.path.exists(path):
            return jsonify({"error": "File missing"}), 404
        try:
            # On Windows some setups behave better when streaming from file object
            f = open(path, 'rb')
            resp = send_file(f, as_attachment=False, mimetype='application/pdf')
            # Prevent caches from serving stale responses
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            return resp
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to send PDF %s: %s", pdf_id, e)
            return jsonify({"error": "Failed to read PDF"}), 500

    @app.delete('/api/pdf/<pdf_id>')
    def delete_pdf(pdf_id: str):
        """Delete a PDF and all associated data.

        Removes the PDF file from disk and deletes the DB row (cascading to words/info).
        """
        rec = dbm.get_pdf(pdf_id)
        if not rec:
            return jsonify({"deleted": False, "error": "Not found"}), 404
        # Attempt to delete file first (ignore errors if already missing)
        try:
            path = os.path.join(PDF_DIR, rec['filename'])
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:  # noqa: BLE001
            # Log but continue with DB deletion
            logger.warning("Failed to remove file for pdf %s: %s", pdf_id, e)
        ok = dbm.delete_pdf(pdf_id)
        if not ok:
            return jsonify({"deleted": False, "error": "Delete failed"}), 500
        return jsonify({"deleted": True})

    # POST fallback for environments that block DELETE
    @app.post('/api/pdf/<pdf_id>/delete')
    def delete_pdf_post(pdf_id: str):
        rec = dbm.get_pdf(pdf_id)
        if not rec:
            return jsonify({"deleted": False, "error": "Not found"}), 404
        try:
            path = os.path.join(PDF_DIR, rec['filename'])
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to remove file for pdf %s: %s", pdf_id, e)
        ok = dbm.delete_pdf(pdf_id)
        if not ok:
            return jsonify({"deleted": False, "error": "Delete failed"}), 500
        return jsonify({"deleted": True})

    @app.post('/api/add_word')
    def add_word():
        """Add a selected word for a given PDF (idempotent per word)."""
        data = request.get_json(silent=True) or {}
        pdf_id = data.get('pdf_id')
        word = (data.get('word') or '').strip()
        if not pdf_id or not word:
            return jsonify({"error": "pdf_id and word are required"}), 400
        # Normalize word: lower
        word_norm = ''.join(ch for ch in word if ch.isalpha() or ch == "-").lower()
        if not word_norm:
            return jsonify({"error": "Invalid word"}), 400
        rec = dbm.add_word(pdf_id, word_norm)
        return jsonify({"word": rec})

    @app.post('/api/word/ensure')
    def ensure_word():
        """Ensure a word exists and has generated info; return the word record.

        Behavior:
        - If the word doesn't exist for this PDF, insert it.
        - If it already has data, return it as-is.
        - Otherwise, call the LLM to generate, persist, and return the result.
        """
        data = request.get_json(silent=True) or {}
        pdf_id = data.get('pdf_id')
        word = (data.get('word') or '').strip()
        if not pdf_id or not word:
            return jsonify({"error": "pdf_id and word are required"}), 400
        word_norm = ''.join(ch for ch in word if ch.isalpha() or ch == "-").lower()
        if not word_norm:
            return jsonify({"error": "Invalid word"}), 400
        # Ensure word exists
        rec = dbm.add_word(pdf_id, word_norm)
        # Fetch with any existing data
        w = dbm.get_word_with_data(pdf_id, word_norm)
        if w and w.get('data'):
            return jsonify({"word": w, "generated": False})
        # No data yet: generate and persist
        try:
            info = generate_word_info(word_norm)
        except Exception as e:  # noqa: BLE001
            # Detect rate limit and surface 429 even when strict mode raises
            name = type(e).__name__.lower()
            msg = str(e).lower()
            if ('ratelimit' in name) or ('rate limit' in msg) or ('429' in msg):
                logger.warning("Rate limited while ensuring word '%s'", word_norm)
                return jsonify({
                    "error": "Rate limited by LLM provider. Please try again shortly.",
                    "errorType": type(e).__name__,
                }), 429
            logger.exception("LLM generation failed for ensure_word '%s'", word_norm)
            return jsonify({
                "error": "LLM generation failed",
                "errorType": type(e).__name__,
                "errorMessage": str(e),
            }), 502
        # If rate limited, surface a friendly error
        try:
            src = (info or {}).get('_source') if isinstance(info, dict) else None
        except Exception:
            src = None
        if isinstance(src, str) and src.startswith('error:RateLimit'):
            return jsonify({
                "error": "Rate limited by LLM provider. Please try again shortly.",
                "errorType": "RateLimitError",
            }), 429
        # Persist and return
        dbm.upsert_word_info(rec['id'], info)
        w2 = dbm.get_word_with_data(pdf_id, word_norm)
        return jsonify({"word": w2, "generated": True})

    @app.get('/api/words')
    def words():
        """List words for a PDF, including any generated info if present."""
        pdf_id = request.args.get('pdf_id')
        if not pdf_id:
            return jsonify({"error": "pdf_id is required"}), 400
        rows = dbm.list_words(pdf_id)
        return jsonify({"words": rows})

    @app.get('/api/pdfs')
    def list_pdfs():
        """Return all PDFs with word counts for the Library UI."""
        rows = dbm.list_pdfs()
        return jsonify({"pdfs": rows})

    @app.route('/api/generate', methods=['POST', 'GET'])
    def generate():
        """Generate or regenerate vocabulary info for words of a PDF via the LLM."""
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            pdf_id = data.get('pdf_id')
            words_filter = data.get('words')  # optional list of strings
            regenerate = bool(data.get('regenerate', False))
        else:
            pdf_id = request.args.get('pdf_id')
            words_filter = request.args.getlist('words') or None
            regenerate = request.args.get('regenerate', 'false').lower() in {'1','true','yes','on'}
        if not pdf_id:
            return jsonify({"error": "pdf_id is required"}), 400
        rows = dbm.list_words(pdf_id)
        # Map word->row
        targets = []
        for r in rows:
            if words_filter and r['word'] not in words_filter:
                continue
            # If not regenerating, skip any word that already has generated data
            # (regardless of source). Only words with no prior data will be generated.
            if not regenerate and r.get('data'):
                continue
            targets.append(r)
        results = []
        attempted = len(targets)
        logger.info("/api/generate: pdf_id=%s regenerate=%s attempted=%d", pdf_id, regenerate, attempted)
        # Batch in chunks to reduce rate limits
        batch_size = int(os.environ.get('CEREBRAS_BATCH_SIZE', '5'))
        for i in range(0, len(targets), batch_size):
            chunk = targets[i:i+batch_size]
            words = [r['word'] for r in chunk]
            try:
                batch = generate_batch_word_info(words) if len(words) > 1 else {words[0]: generate_word_info(words[0])}
            except Exception as e:
                # If strict mode raised on a rate limit after retries, surface 429
                name = type(e).__name__.lower()
                msg = str(e).lower()
                status = 429 if ('ratelimit' in name) or ('rate limit' in msg) or ('429' in msg) else 502
                if status == 429:
                    logger.warning("Rate limited during batch generation for words %s", words)
                else:
                    logger.exception("LLM batch generation failed for words %s", words)
                return jsonify({
                    "error": "Rate limited by LLM provider. Please wait a moment and try again." if status==429 else "LLM generation failed",
                    "errorType": type(e).__name__,
                    "failed_words": words,
                    "attempted": attempted,
                    "has_api_key": bool(os.environ.get('CEREBRAS_API_KEY')),
                    "model": os.environ.get('CEREBRAS_MODEL', 'gpt-oss-120b'),
                }), status
            # Detect rate-limit fallbacks in the batch
            if any(isinstance(info, dict) and str(info.get('_source','')).startswith('error:RateLimit') for info in batch.values()):
                return jsonify({
                    "error": "Rate limited by LLM provider. Please wait a moment and try again.",
                    "errorType": "RateLimitError",
                    "failed_words": words,
                    "attempted": attempted,
                    "has_api_key": bool(os.environ.get('CEREBRAS_API_KEY')),
                    "model": os.environ.get('CEREBRAS_MODEL', 'gpt-oss-120b'),
                }), 429
            # Persist results
            for r in chunk:
                info = batch.get(r['word'])
                if not info:
                    continue
                dbm.upsert_word_info(r['id'], info)
                results.append({"word": r['word'], "data": info})
        meta = {
            "count": len(results),
            "attempted": attempted,
            "has_api_key": bool(os.environ.get('CEREBRAS_API_KEY')),
            "model": os.environ.get('CEREBRAS_MODEL', 'gpt-oss-120b'),
        }
        return jsonify({"generated": results, **meta})

    @app.get('/api/health')
    def health():
        """Basic app/LLM health info (no external calls)."""
        httpx_version = None
        httpx_ok = None
        try:
            import httpx  # type: ignore
            httpx_version = getattr(httpx, "__version__", None)
            # Consider <0.28 compatible with Cerebras SDK 1.7.0
            def _parse(ver: str):
                parts = ver.split(".")
                return tuple(int(p) for p in parts[:2])
            if httpx_version:
                httpx_ok = _parse(httpx_version) < (0, 28)
        except Exception:
            httpx_version = None
            httpx_ok = None
        return jsonify({
            "ok": True,
            "has_api_key": bool(os.environ.get('CEREBRAS_API_KEY')),
            "model": os.environ.get('CEREBRAS_MODEL', 'gpt-oss-120b'),
            "httpx_version": httpx_version,
            "httpx_compat": httpx_ok,
        })

    @app.get('/api/llm/test')
    def llm_test():
        """Quick test endpoint to validate LLM connectivity and parsing."""
        word = request.args.get('word', 'example')
        force_strict = request.args.get('strict', 'false').lower() in {'1','true','yes','on'}
        try:
            if force_strict:
                prev = os.environ.get('CEREBRAS_STRICT')
                os.environ['CEREBRAS_STRICT'] = '1'
                try:
                    data = generate_word_info(word)
                finally:
                    if prev is None:
                        os.environ.pop('CEREBRAS_STRICT', None)
                    else:
                        os.environ['CEREBRAS_STRICT'] = prev
            else:
                data = generate_word_info(word)
            return jsonify({"ok": True, "word": word, "data": data})
        except Exception as e:  # strict mode errors
            logger.exception("LLM test failed for word '%s'", word)
            return jsonify({
                "ok": False,
                "error": "LLM generation failed",
                "errorType": type(e).__name__,
                "errorMessage": str(e),
                "word": word,
            }), 502

    @app.delete('/api/word/<int:word_id>')
    def delete_word(word_id: int):
        """Delete a word record by ID."""
        ok = dbm.delete_word(word_id)
        if not ok:
            return jsonify({"deleted": False, "error": "Not found"}), 404
        return jsonify({"deleted": True})

    # Fallback for environments where DELETE may be blocked
    @app.post('/api/word/<int:word_id>/delete')
    def delete_word_post(word_id: int):
        """POST fallback for environments blocking DELETE requests."""
        ok = dbm.delete_word(word_id)
        if not ok:
            return jsonify({"deleted": False, "error": "Not found"}), 404
        return jsonify({"deleted": True})

    # Static files are served from /static by Flask's static handler.

    @app.post('/api/pdf/<pdf_id>/highlights')
    def save_highlights(pdf_id: str):
        """Persist highlight annotations into the underlying PDF file.

        Expected JSON body:
        { highlights: [ { page: 1, color: [r,g,b], quads: [[x1,y1,x2,y2,x3,y3,x4,y4], ...] }, ... ] }
        Coordinates are in PDF user space points for the target page (origin bottom-left).
        """
        data = request.get_json(silent=True) or {}
        items = data.get('highlights') or []
        if not isinstance(items, list):
            return jsonify({"error": "highlights must be a list"}), 400
        rec = dbm.get_pdf(pdf_id)
        if not rec:
            return jsonify({"error": "Not found"}), 404
        path = os.path.join(PDF_DIR, rec['filename'])
        try:
            add_highlights_to_pdf(path, items)
            return jsonify({"ok": True, "count": sum(len(i.get('quads', [])) for i in items)})
        except Exception as e:
            logger.exception("Failed to save highlights for %s", pdf_id)
            return jsonify({"error": "Failed to save highlights", "errorType": type(e).__name__, "message": str(e)}), 500

    @app.post('/api/pdf/<pdf_id>/highlights/remove')
    def remove_highlights(pdf_id: str):
        """Remove previously embedded highlight annotations overlapping provided quads."""
        data = request.get_json(silent=True) or {}
        targets = data.get('targets') or []
        if not isinstance(targets, list):
            return jsonify({"error": "targets must be a list"}), 400
        rec = dbm.get_pdf(pdf_id)
        if not rec:
            return jsonify({"error": "Not found"}), 404
        path = os.path.join(PDF_DIR, rec['filename'])
        try:
            result = remove_highlights_from_pdf(path, targets)
            # Support both legacy int and new dict return
            if isinstance(result, dict):
                removed = int(result.get('removed_quads', 0))
                return jsonify({"ok": True, "removed": removed, "detail": result})
            else:
                return jsonify({"ok": True, "removed": int(result)})
        except Exception as e:
            logger.exception("Failed to remove highlights for %s", pdf_id)
            return jsonify({"error": "Failed to remove highlights", "errorType": type(e).__name__, "message": str(e)}), 500

    return app


if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=bool(os.environ.get('FLASK_DEBUG')))
