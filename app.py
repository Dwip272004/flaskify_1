"""
Flask-based mini-Spotify clone
• Stores audio files *locally* in a /songs folder
• Saves only song metadata (title, artist, filename) to Firebase Firestore
• Plays songs via <audio> served by Flask
"""

import os
import json
from datetime import timedelta

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_from_directory, flash
)
from werkzeug.utils import secure_filename

import firebase_admin
from firebase_admin import credentials, firestore, auth

# ───────────────────────────────────────────
#  App & Firebase initialisation
# ───────────────────────────────────────────

# ----------- Firebase credentials ----------
#
#  1) File-based (development):
#        cred = credentials.Certificate("firebase_config.json")
#
#  2) Env-var-based (production / Render):
#        firebase_json = json.loads(os.getenv("FIREBASE_CONFIG"))
#        cred = credentials.Certificate(firebase_json)
#
cred = credentials.Certificate("firebase_config.json")      # ← choose option 1 or 2
firebase_admin.initialize_app(cred)

db = firestore.client()

# -------------- Flask app ------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-change-me")

# Local upload directory
UPLOAD_FOLDER = os.path.join(app.root_path, "songs")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg"}

# ───────────────────────────────────────────
#  Helper utilities
# ───────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def current_user_email() -> str | None:
    return session.get("email")

# ───────────────────────────────────────────
#  Routes
# ───────────────────────────────────────────
@app.route("/")
def index():
    """Landing page."""
    return render_template("index.html", user=current_user_email())


# ---------- Authentication (very basic demo) -----------
@app.route("/register", methods=["GET", "POST"])
def register():
    """Create a Firebase Auth user (email / password)."""
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        try:
            auth.create_user(email=email, password=password)
            flash("Registration successful – please sign in.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Error: {e}", "danger")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    *Demo* login: we simply create a session after verifying
    that the email exists in Firebase Auth.
    """
    if request.method == "POST":
        email = request.form["email"].strip()
        try:
            auth.get_user_by_email(email)   # raises error if not found
            session["email"] = email
            flash("Logged in!", "success")
            return redirect(url_for("songs"))
        except Exception as e:
            flash(f"Login failed: {e}", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("email", None)
    flash("You’ve been logged out.", "info")
    return redirect(url_for("index"))


# ------------------ Song upload -------------------------
@app.route("/upload", methods=["GET", "POST"])
def upload():
    """
    Upload an audio file to /songs and store metadata in Firestore.
    Any logged-in user can upload; add role checks if needed.
    """
    if not current_user_email():
        return redirect(url_for("login"))

    if request.method == "POST":
        song_file = request.files.get("song")
        title = request.form["title"].strip()
        artist = request.form["artist"].strip()

        # Validation
        if not (song_file and allowed_file(song_file.filename)):
            flash("Unsupported file type; allowed: mp3 / wav / ogg", "warning")
            return redirect(request.url)

        filename = secure_filename(song_file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # Avoid overwrite; add suffix if necessary
        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(file_path):
            filename = f"{base}_{counter}{ext}"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            counter += 1

        song_file.save(file_path)

        # Store metadata in Firestore
        db.collection("songs").add({
            "title": title,
            "artist": artist,
            "filename": filename,
            "uploader": current_user_email(),
        })

        flash("Song uploaded successfully!", "success")
        return redirect(url_for("upload"))

    return render_template("upload.html")


# ------------------ Song search & player ---------------
@app.route("/songs")
def songs():
    """Search and list songs. Empty query ⇒ show all."""
    query = request.args.get("q", "").strip().lower()
    results = []

    for doc in db.collection("songs").stream():
        data = doc.to_dict()
        if not query or \
           query in data["title"].lower() or \
           query in data["artist"].lower():
            results.append(data)

    # Sort alphabetically for consistency
    results.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))
    return render_template("player.html", songs=results, query=query, user=current_user_email())


# ------------------ Serve audio files ------------------
@app.route("/songs/<path:filename>")
def serve_song(filename):
    """
    Streams audio from the local songs folder.
    Setting conditional=True enables HTTP range requests
    so the browser can seek within the track.
    """
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        conditional=True,           # still enables range-requests / seeking
    )                                # omit max_age → Flask/Werkzeug sets a default

@app.route("/song/<path:filename>")
def song_page(filename):
    """Dedicated page to play one song."""
    # Find song metadata from Firestore
    doc_ref = db.collection("songs").where("filename", "==", filename).stream()
    song_data = next(doc_ref, None)

    if not song_data:
        return "Song not found", 404

    song = song_data.to_dict()
    return render_template("song.html", song=song)


# ───────────────────────────────────────────
#  Main
# ───────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
