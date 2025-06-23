"""
Flask-based mini-Spotify clone
• Stores audio files locally in a /songs folder
• Saves only song metadata (title, artist, filename) to Firebase Firestore
• Plays songs via <audio> served by Flask
"""

import os
import json
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_from_directory, flash
)
from werkzeug.utils import secure_filename


import firebase_admin
from firebase_admin import credentials, firestore, auth

# ───────────────────────────────────────────────
# Load env vars (used for local development)
# ───────────────────────────────────────────────


# ───────────────────────────────────────────────
# Firebase Initialization from FIREBASE_CONFIG
# ───────────────────────────────────────────────
firebase_json = os.getenv("FIREBASE_CONFIG")
if not firebase_json:
    raise RuntimeError("Missing FIREBASE_CONFIG environment variable")

cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()

# ───────────────────────────────────────────────
# Flask App Setup
# ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-in-production")

# File upload config
UPLOAD_FOLDER = os.path.join(app.root_path, "songs")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"mp3", "wav", "ogg"}

# ───────────────────────────────────────────────
# Utility Functions
# ───────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def current_user_email() -> str | None:
    return session.get("email")

# ───────────────────────────────────────────────
# Routes
# ───────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", user=current_user_email())

@app.route("/register", methods=["GET", "POST"])
def register():
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
    flash("You’ve been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if not current_user_email():
        return redirect(url_for("login"))

    if request.method == "POST":
        song_file = request.files.get("song")
        title = request.form["title"].strip()
        artist = request.form["artist"].strip()

        if not (song_file and allowed_file(song_file.filename)):
            flash("Unsupported file type; allowed: mp3 / wav / ogg", "warning")
            return redirect(request.url)

        filename = secure_filename(song_file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        counter = 1
        base, ext = os.path.splitext(filename)
        while os.path.exists(file_path):
            filename = f"{base}_{counter}{ext}"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            counter += 1

        song_file.save(file_path)

        db.collection("songs").add({
            "title": title,
            "artist": artist,
            "filename": filename,
            "uploader": current_user_email(),
        })

        flash("Song uploaded successfully!", "success")
        return redirect(url_for("upload"))

    return render_template("upload.html")

@app.route("/songs")
def songs():
    query = request.args.get("q", "").strip().lower()
    results = []

    for doc in db.collection("songs").stream():
        data = doc.to_dict()
        if not query or \
           query in data["title"].lower() or \
           query in data["artist"].lower():
            results.append(data)

    results.sort(key=lambda x: (x["artist"].lower(), x["title"].lower()))
    return render_template("player.html", songs=results, query=query, user=current_user_email())

@app.route("/songs/<path:filename>")
def serve_song(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        conditional=True
    )

@app.route("/song/<path:filename>")
def song_page(filename):
    doc_ref = db.collection("songs").where("filename", "==", filename).stream()
    song_data = next(doc_ref, None)

    if not song_data:
        return "Song not found", 404

    song = song_data.to_dict()
    return render_template("song.html", song=song)

# ───────────────────────────────────────────────
# Run
# ───────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
