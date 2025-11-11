import os
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

# Import the Flask app factory from the backend package
from backend.app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = bool(os.environ.get("FLASK_DEBUG"))
    app.run(host="0.0.0.0", port=port, debug=debug)
