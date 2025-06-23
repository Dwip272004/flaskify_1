"""
Flask-based mini-Spotify clone
• Local /songs folder for audio
• Song metadata stored in Firebase Firestore
• Audio streamed via <audio> tag
"""

import os
import json
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_from_directory, flash
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv  # only used in local dev

import firebase_admin
from firebase_admin import credentials, firestore, auth

# ───────────────────────────────────────────────
# 1. Load .env when running locally
# ───────────────────────────────────────────────
load_dotenv()           # Render ignores this; it’s only for local dev

# ───────────────────────────────────────────────
# 2. Initialise Firebase credentials
#    • First look for Render secret file
#    • Fallback to FIREBASE_CONFIG env-var
# ───────────────────────────────────────────────
CRED_FILE_PATH = "/etc/secrets/firebase_config.json"  # Render secret-file mount point

if os.path.exists(CRED_FILE_PATH):
    # ✅ Render Secret File
    cred = credentials.Certificate(CRED_FILE_PATH)
else:
    # ✅ Env-var fallback (for local dev or older setup)
    firebase_json = os.getenv("FIREBASE_CONFIG")
    if not firebase_json:
        raise RuntimeError(
            "Firebase credentials not found. "
            "Either mount a secret file at /etc/secrets/firebase_config.json "
            "or set the FIREBASE_CONFIG environment variable."
        )
    cred_dict = json.loads(firebase_json)
    cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred)
db = firestore.client()

# ───────────────────────────────────────────────
# 3. Flask app configuration
# ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-in-production")

UPLOAD_FOLDER = os.path.join(app.root_path, "songs")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg"}

# ───────────────────────────────────────────────
# 4. Utility helpers
# ───────────────────────────────────────────────
def allowed_file(fname: str) -> bool:
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def current_user_email() -> str | None:
    return session.get("email")

# ───────────────────────────────────────────────
# 5. Routes
# ───────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", user=current_user_email())

# ---------- Auth ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        try:
            auth.create_user(email=email, password=password)
            flash("Registration successful – sign in now.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        try:
            auth.get_user_by_email(email)
            session["email"] = email
            flash("Logged in!", "success")
            return redirect(url_for("songs"))
        except Exception as e:
            flash(f"Login failed: {e}", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("email", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# ---------- Upload ----------
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not current_user_email():
        return redirect(url_for("login"))

    if request.method == "POST":
        song_file = request.files.get("song")
        title = request.form["title"].strip()
        artist = request.form["artist"].strip()

        if not (song_file and allowed_file(song_file.filename)):
            flash("Allowed formats: mp3 / wav / ogg", "warning")
            return redirect(request.url)

        filename = secure_filename(song_file.filename)
        base, ext = os.path.splitext(filename)
        path = os.path.join(UPLOAD_FOLDER, filename)

        counter = 1
        while os.path.exists(path):
            filename = f"{base}_{counter}{ext}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            counter += 1

        song_file.save(path)

        db.collection("songs").add({
            "title": title,
            "artist": artist,
            "filename": filename,
            "uploader": current_user_email(),
        })

        flash("Song uploaded!", "success")
        return redirect(url_for("upload"))

    return render_template("upload.html")

# ---------- Library ----------
@app.route("/songs")
def songs():
    query = request.args.get("q", "").lower().strip()
    results = [
        doc.to_dict()
        for doc in db.collection("songs").stream()
        if not query
        or query in doc.to_dict()["title"].lower()
        or query in doc.to_dict()["artist"].lower()
    ]
    results.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))
    return render_template("player.html", songs=results, query=query, user=current_user_email())

# ---------- Stream file ----------
@app.route("/songs/<path:filename>")
def serve_song(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, conditional=True)

# ---------- Single song page ----------
@app.route("/song/<path:filename>")
def song_page(filename):
    match = next(
        db.collection("songs").where("filename", "==", filename).stream(),
        None
    )
    if not match:
        return "Song not found", 404
    return render_template("song.html", song=match.to_dict())

# ───────────────────────────────────────────────
# 6. Entrypoint
# ───────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
