"""
Flask-based mini-Spotify clone
• Local /songs folder for audio
• Song metadata stored in Firebase Firestore
• Audio streamed via <audio> tag
"""

import os
import json,requests
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_from_directory, flash
)
from werkzeug.utils import secure_filename


import firebase_admin
from firebase_admin import credentials, firestore, auth

# ───────────────────────────────────────────────
# 1. Load .env when running locally
# ───────────────────────────────────────────────
      # Render ignores this; it’s only for local dev

# ───────────────────────────────────────────────
# 2. Initialise Firebase credentials
#    • First look for Render secret file
#    • Fallback to FIREBASE_CONFIG env-var
# ───────────────────────────────────────────────
CRED_FILE_PATH = "/etc/secrets/firebase_config.json"  # Render secret-file mount point
JAMENDO_API_KEY = "97c3c1fb"  # Leave as-is per your request
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

def search_jamendo_tracks(query, limit=10):
    url = "https://api.jamendo.com/v3.0/tracks"
    params = {
        "client_id": JAMENDO_API_KEY,
        "format": "json",
        "limit": limit,
        "namesearch": query,
        "audioformat": "mp31",
        "include": "musicinfo+stats",
        "order": "popularity_total"
    }
    response = requests.get(url, params=params)
    if response.ok:
        raw_results = response.json().get("results", [])
        normalized = []
        for r in raw_results:
            normalized.append({
                "id": r.get("id"),  # For linking to detailed page
                "title": r.get("name"),
                "artist": r.get("artist_name"),
                "audio": r.get("audio"),
                "album_image": r.get("album_image"),
                "duration": r.get("duration"),
                "source": "jamendo"
            })
        return normalized
    else:
        return []

@app.route("/songs")
def songs():
    query = request.args.get("q", "").strip().lower()
    local_results = []
    jamendo_results = []

    # Get local songs
    for doc in db.collection("songs").stream():
        data = doc.to_dict()
        if not query or query in data["title"].lower() or query in data["artist"].lower():
            data["source"] = "local"
            local_results.append(data)

    # Get Jamendo songs
    if query:
        jamendo_results = search_jamendo_tracks(query)
        for song in jamendo_results:
            song["source"] = "jamendo"

    all_results = local_results + jamendo_results

    return render_template(
        "player.html",
        songs=all_results,
        query=query,
        user=current_user_email()
    )


@app.route("/songs/<path:filename>")
def serve_song(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        conditional=True,
    )


@app.route("/song/<path:filename>")
def song_page(filename):
    doc_ref = db.collection("songs").where("filename", "==", filename).stream()
    song_data = next(doc_ref, None)

    if not song_data:
        return "Song not found", 404

    song = song_data.to_dict()
    return render_template("song.html", song=song)


@app.route("/jamendo/<track_id>")
def jamendo_song_page(track_id):
    url = "https://api.jamendo.com/v3.0/tracks"
    params = {
        "client_id": JAMENDO_API_KEY,
        "format": "json",
        "id": track_id,
        "audioformat": "mp31",
        "include": "musicinfo+stats"
    }

    response = requests.get(url, params=params)
    if response.ok:
        results = response.json().get("results", [])
        if results:
            song = results[0]
            song_data = {
                "title": song["name"],
                "artist": song["artist_name"],
                "uploader": "Jamendo",
                "filename": "",
                "audio": song["audio"],
                "album_image": song.get("album_image", ""),
                "duration": song.get("duration")
            }
            return render_template("song.html", song=song_data)
    
    return "Jamendo song not found", 404

# ───────────────────────────────────────────────
# Run
# ───────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
