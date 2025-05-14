from flask import render_template, request, redirect, url_for, jsonify, abort, flash, current_app
from tinydb import TinyDB, Query
import json
import os
from datetime import datetime
import shutil


from . import voting_bp, socketio
from .utils import (
    load_options, load_vote_options, calculate_ranked_choice, 
    calculate_awards, get_file_path, load_lock_state
)

# Initialize the database - use an absolute path to ensure it's found
db_path = get_file_path('db.json')
db = TinyDB(db_path)
User = Query()
votes_locked = False

@voting_bp.route('/')
def index():
    options = load_options()
    vo = load_vote_options()
    return render_template('index.html', options=options, votes=vo, votes_locked=load_lock_state())

@voting_bp.route('/results')
def results():
    # Retrieve all votes from the database
    votes = [vote['rank'] for vote in db.all()]
    vo = load_vote_options()
    ranked_results = calculate_ranked_choice(votes, vo)
    return render_template('results.html', ranked_results=ranked_results)

@voting_bp.route('/api/awards')
def get_awards():
    """API endpoint that calculates and returns award winners."""
    try:
        # Load options data with explicit UTF-8 encoding
        with open('pizzavision/options.json', 'r', encoding='utf-8') as json_file:
            options_data = json.load(json_file)
        
        # Calculate awards based on the database and options
        calculated_awards = calculate_awards(db, options_data)
        
        # Check if custom award details are provided
        if 'award_details' in options_data:
            # Update awards with custom subtexts and image URLs if provided
            for award in calculated_awards:
                award_name = award["award"]
                if award_name in options_data['award_details']:
                    details = options_data['award_details'][award_name]
                    if 'subtext' in details:
                        award["subtext"] = details['subtext']
                    if 'image_url' in details:
                        award["image_url"] = details['image_url']
        
        return jsonify(calculated_awards)
    except Exception as e:
        print(f"Error loading or processing options.json: {str(e)}")
        # Return a simple error response
        return jsonify({"error": str(e)}), 500

@voting_bp.route('/awards')
def awards():
    try:
        # Load options data with explicit UTF-8 encoding
        with open('pizzavision/options.json', 'r', encoding='utf-8') as json_file:
            options_data = json.load(json_file)
            
        # Calculate awards dynamically
        calculated_awards = calculate_awards(db, options_data)
        
        # Check if custom award details are provided
        if 'award_details' in options_data:
            # Update awards with custom subtexts and image URLs if provided
            for award in calculated_awards:
                award_name = award["award"]
                if award_name in options_data['award_details']:
                    details = options_data['award_details'][award_name]
                    if 'subtext' in details:
                        award["subtext"] = details['subtext']
                    if 'image_url' in details:
                        award["image_url"] = details['image_url']
        
        return render_template('awards_presentation.html', awards=calculated_awards)
    except Exception as e:
        print(f"Error loading or processing options.json: {str(e)}")
        # Return a simple error page
        return f"Error loading awards: {str(e)}", 500
    

OPTIONS_FILE = os.path.join("pizzavision", "options.json")  # adjust if different
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")     # set in env
OPTIONS_FILE = os.path.join("pizzavision", "options.json")
BACKUP_FILE  = os.path.join("pizzavision", "options_bak.json")
DB_FILE      = os.path.join("pizzavision", "db.json")       # adjust if different


# -------- helpers --------------------------------------------------
def _load_options():
    with open(OPTIONS_FILE, "r", encoding="utf‑8") as fh:
        return json.load(fh)

def _save_options(data):
    with open(OPTIONS_FILE, "w", encoding="utf‑8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)


# ------------------------------------------------------------------
@voting_bp.route("/admin", methods=["GET", "POST"])
def admin_panel():
    """
    Single admin page with three actions:
      save_options   – reorder / delete items
      clear_db       – wipe TinyDB
      restore_options – copy options_bak.json -> options.json
    """
    # -------- POST (AJAX) ------------------------------------------
    if request.method == "POST":
        if request.form.get("password") != ADMIN_PASSWORD:
            abort(403, "wrong password")

        action = request.form.get("action")

        # 1) Save new ordering / deletions
        if action == "save_options":
            labels = request.form.getlist("labels[]")
            data   = _load_options()
            by_lbl = {opt["label"]: opt for opt in data["options"]}
            data["options"] = [by_lbl[lbl] for lbl in labels if lbl in by_lbl]
            _save_options(data)
            db.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="ok")

        # 2) Clear TinyDB
        if action == "clear_db":
            db.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="cleared")
        
        if action == "unlock_votes":
            data   = _load_options()
            data["locked"] = False
            _save_options(data)
            current_app.extensions["socketio"].emit("refresh")
            return jsonify(status="unlocked")

        # 3) Restore from backup
        if action == "restore_options":
            if not os.path.exists(BACKUP_FILE):
                abort(500, "options_bak.json not found")
            with open(BACKUP_FILE, "r", encoding="utf‑8") as fh:
                backup = json.load(fh)
            _save_options(backup)
            db.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="restored")
        
        # 4) Lock votes
        if action == "lock_votes":
            # Create a timestamp-named backup of the current vote DB
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"votes_finalized_{timestamp}.json"
            backup_path = os.path.join("pizzavision", backup_filename)
            
            # Copy the current DB to the backup file
            shutil.copy2(DB_FILE, backup_path)
            
            # Broadcast the votes_finalized message to all clients
            current_app.extensions["socketio"].emit("votes_finalized", {"timestamp": timestamp})
            data   = _load_options()
            data["locked"] = True
            _save_options(data)
            
            return jsonify(status="votes_locked", timestamp=timestamp)

        abort(400, "unknown action")

    # -------- GET ---------------------------------------------------
    data = _load_options()
    return render_template("admin.html", options=data["options"])



# Define SocketIO event handlers
def register_socketio_handlers(socket_io):
    """Register SocketIO event handlers"""
    
    @socket_io.on('nameChanged')
    def on_namechange(data):
        old_name = data['old_name']
        new_name = data['new_name']
        
        # Update the user's name in the database
        search_result = db.search(User.user == old_name)
        if search_result:
            # If the user already has entries, update their name
            db.update({'user': new_name}, User.user == old_name)
            print(f"Username changed from '{old_name}' to '{new_name}'")
        else:
            # If this is a new user (no previous rankings), just log it
            print(f"New user registered: '{new_name}'")
        
        # Emit an event to all clients to notify of the name change
        socket_io.emit('userRenamed', {'old_name': old_name, 'new_name': new_name}, broadcast=True)

    @socket_io.on('rankchanged')
    def on_rankchange(data):
        user = data['user']
        rank = data['rank']
        # Check if user already has an entry, update if they do, add if they don't
        search_result = db.search(User.user == user)
        if search_result:
            db.update({'rank': rank}, User.user == user)
        else:
            db.insert({'user': user, 'rank': rank})
        print(f"{user}'s new ranking: {rank}")