"""Small Flask memory probe; this does not replace the production Node panel."""
from pathlib import Path
from flask import Flask, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
app = Flask(__name__, static_folder=str(PUBLIC), static_url_path="")


@app.get("/api/health")
def health():
    return jsonify(ok=True, runtime="flask")


@app.get("/", defaults={"filename": "index.html"})
@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(PUBLIC, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=17085, debug=False, threaded=True)
