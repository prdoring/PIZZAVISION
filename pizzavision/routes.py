from flask import render_template, request, jsonify, abort, current_app
from flask_socketio import join_room
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import shutil


# Windows ships without the IANA tz database; the `tzdata` pip package fills
# that in. If it's not installed, fall back to UTC rather than crashing the
# whole app at import time.
try:
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
    _PACIFIC_LABEL = "PT"
except Exception:
    PACIFIC_TZ = timezone.utc
    _PACIFIC_LABEL = "UTC"


# sid -> client_id, populated on 'joined', drained on 'disconnect'.
# Single-process only (in-memory) — that matches our SocketIO setup; if we
# ever scale out across instances we'd need a redis adapter for both this
# and the per-client rooms below.
_connected_sids: dict[str, str] = {}


def _client_room(client_id: str) -> str:
    return f"client:{client_id}"


def _fmt_pacific(iso_str):
    """Render an ISO-8601 UTC timestamp as a short Pacific-time string, or '—' if missing."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(PACIFIC_TZ).strftime(f"%Y-%m-%d %H:%M {_PACIFIC_LABEL}")
    except (ValueError, TypeError):
        return iso_str


from . import voting_bp
from .utils import (
    load_options, load_vote_options, calculate_ranked_choice,
    calculate_awards, get_file_path, load_lock_state
)
from .vote_store import get_vote_store
from . import openai_client

# Single shared vote store. Firestore in prod (GOOGLE_CLOUD_PROJECT set),
# TinyDB locally. See vote_store.py.
vote_store = get_vote_store()


@voting_bp.route('/')
def index():
    options = load_options()
    vo = load_vote_options()
    return render_template('index.html', options=options, votes=vo, votes_locked=load_lock_state())


@voting_bp.route('/api/generate-names', methods=['POST'])
def generate_names():
    """Onboarding name generation. Falls back client-side if this returns non-200."""
    body = request.get_json(silent=True) or {}
    try:
        names = openai_client.generate_band_names(
            body.get('song_title', ''),
            body.get('song_vibe', ''),
            body.get('personal_vibe', ''),
            body.get('extra', ''),
        )
        return jsonify(names=names, source='openai')
    except ModuleNotFoundError as e:
        current_app.logger.exception("generate_names: openai package not installed")
        return jsonify(error=str(e), error_code='no_openai_package'), 503
    except RuntimeError as e:
        # raised when OPENAI_API_KEY is missing
        current_app.logger.warning(f"generate_names: {e}")
        return jsonify(error=str(e), error_code='no_api_key'), 503
    except Exception as e:
        current_app.logger.exception("generate_names: unexpected failure")
        return jsonify(error=str(e), error_code='api_error', error_type=type(e).__name__), 503


@voting_bp.route('/api/suggest-answer', methods=['POST'])
def suggest_answer():
    """Per-field 'Surprise me' suggestion for the onboarding dice button.

    Payload: {field: 'song_title'|'song_vibe'|'personal_vibe'|'extra',
              context: {<other field answers>},
              anchor: <user's current text iff they typed/modified it>}
    Returns: {answer: str}
    """
    body = request.get_json(silent=True) or {}
    field = body.get('field', '')
    context = body.get('context') or {}
    anchor = body.get('anchor') or ''
    try:
        answer = openai_client.suggest_answer(field, context, anchor)
        return jsonify(answer=answer)
    except ValueError as e:
        # Bad field name OR empty model output.
        current_app.logger.warning(f"suggest_answer: {e}")
        return jsonify(error=str(e), error_code='bad_input'), 400
    except ModuleNotFoundError as e:
        current_app.logger.exception("suggest_answer: openai package not installed")
        return jsonify(error=str(e), error_code='no_openai_package'), 503
    except RuntimeError as e:
        current_app.logger.warning(f"suggest_answer: {e}")
        return jsonify(error=str(e), error_code='no_api_key'), 503
    except Exception as e:
        current_app.logger.exception("suggest_answer: unexpected failure")
        return jsonify(error=str(e), error_code='api_error', error_type=type(e).__name__), 503


@voting_bp.route('/results')
def results():
    votes = [row['rank'] for row in vote_store.all() if row.get('rank')]
    vo = load_vote_options()
    ranked_results, breakdown = calculate_ranked_choice(votes, vo)
    print(breakdown)
    return render_template('results.html', ranked_results=ranked_results, breakdown=breakdown)


def _load_awards():
    """Shared award-loading logic used by both the JSON API and the HTML view."""
    with open('pizzavision/options.json', 'r', encoding='utf-8') as json_file:
        options_data = json.load(json_file)

    calculated_awards = calculate_awards(vote_store, options_data)

    if 'award_details' in options_data:
        for award in calculated_awards:
            details = options_data['award_details'].get(award["award"])
            if details:
                if 'subtext' in details:
                    award["subtext"] = details['subtext']
                if 'image_url' in details:
                    award["image_url"] = details['image_url']
    return calculated_awards


@voting_bp.route('/api/awards')
def get_awards():
    """API endpoint that calculates and returns award winners."""
    try:
        return jsonify(_load_awards())
    except Exception as e:
        print(f"Error loading or processing options.json: {str(e)}")
        return jsonify({"error": str(e)}), 500


@voting_bp.route('/awards')
def awards():
    try:
        return render_template('awards_presentation.html', awards=_load_awards())
    except Exception as e:
        print(f"Error loading or processing options.json: {str(e)}")
        return f"Error loading awards: {str(e)}", 500


OPTIONS_FILE = os.path.join("pizzavision", "options.json")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
BACKUP_FILE = os.path.join("pizzavision", "options_bak.json")
DB_FILE = os.path.join("pizzavision", "db.json")


def _load_options():
    with open(OPTIONS_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_options(data):
    with open(OPTIONS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)


@voting_bp.route("/admin", methods=["GET", "POST"])
def admin_panel():
    """
    Single admin page with these actions:
      save_options    – reorder / delete items (also clears votes)
      clear_db        – wipe the vote store
      restore_options – copy options_bak.json -> options.json (also clears votes)
      lock_votes      – snapshot current votes and lock the song list
      unlock_votes    – unlock the song list
    """
    if request.method == "POST":
        if request.form.get("password") != ADMIN_PASSWORD:
            abort(403, "wrong password")

        action = request.form.get("action")

        if action == "save_options":
            labels = request.form.getlist("labels[]")
            data = _load_options()
            by_lbl = {opt["label"]: opt for opt in data["options"]}
            data["options"] = [by_lbl[lbl] for lbl in labels if lbl in by_lbl]
            _save_options(data)
            vote_store.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="ok")

        if action == "clear_db":
            vote_store.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="cleared")

        if action == "delete_user":
            client_id = request.form.get("client_id", "").strip()
            if not client_id:
                abort(400, "client_id required")
            removed = vote_store.delete_by_client(client_id)
            if not removed:
                abort(404, "user not found")
            # Targeted: only the affected client (if online) gets wiped and
            # bounced back to onboarding. Other voters are not disturbed.
            current_app.extensions["socketio"].emit(
                "you_were_cleared", to=_client_room(client_id)
            )
            return jsonify(status="deleted")

        if action == "clear_user_rank":
            client_id = request.form.get("client_id", "").strip()
            if not client_id:
                abort(400, "client_id required")
            if not vote_store.clear_rank_by_client(client_id):
                abort(404, "user not found")
            # Targeted: only the affected client (if online) clears its local
            # rank and reloads. Their band name + onboarding answers stay.
            current_app.extensions["socketio"].emit(
                "your_rank_cleared", to=_client_room(client_id)
            )
            return jsonify(status="rank_cleared")

        if action == "unlock_votes":
            data = _load_options()
            data["locked"] = False
            _save_options(data)
            current_app.extensions["socketio"].emit("refresh")
            return jsonify(status="unlocked")

        if action == "restore_options":
            if not os.path.exists(BACKUP_FILE):
                abort(500, "options_bak.json not found")
            with open(BACKUP_FILE, "r", encoding="utf-8") as fh:
                backup = json.load(fh)
            _save_options(backup)
            vote_store.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="restored")

        if action == "lock_votes":
            # Snapshot current votes to a timestamped JSON file before locking.
            # On Cloud Run this writes to the ephemeral container fs — only useful
            # for local dev. Firestore retains the live data either way.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if os.path.exists(DB_FILE):
                backup_filename = f"votes_finalized_{timestamp}.json"
                backup_path = os.path.join("pizzavision", backup_filename)
                try:
                    shutil.copy2(DB_FILE, backup_path)
                except OSError as exc:
                    print(f"lock_votes: snapshot write skipped ({exc})")

            current_app.extensions["socketio"].emit("votes_finalized", {"timestamp": timestamp})
            data = _load_options()
            data["locked"] = True
            _save_options(data)

            return jsonify(status="votes_locked", timestamp=timestamp)

        abort(400, "unknown action")

    data = _load_options()
    online_ids = set(_connected_sids.values())
    users = []
    for row in vote_store.all():
        cid = row.get("client_id", "")
        users.append({
            "client_id": cid,
            "user": row.get("user", "") or "(unnamed)",
            "rank_count": len(row.get("rank") or []),
            "created_at": _fmt_pacific(row.get("created_at")),
            "rank_updated_at": _fmt_pacific(row.get("rank_updated_at")),
            "online": cid in online_ids,
        })
    users.sort(key=lambda u: (u["user"] or "").lower())
    return render_template("admin.html", options=data["options"], users=users)


# ------------------------------------------------------------------
# SocketIO event handlers
# ------------------------------------------------------------------
def register_socketio_handlers(socket_io):
    """Register SocketIO event handlers. Called from pizzavision.py at startup."""

    @socket_io.on('joined')
    def on_joined(data):
        """Client just connected (or refreshed). Return its persisted state.

        Payload: {clientId: str, userName: str}
        Reply  : {user: str, rank: list[str]}

        Side effects:
        - Tracks this sid as belonging to client_id (powers the admin online dot).
        - Joins the client_id-keyed SocketIO room so admin actions can target
          just this user.

        - If we already have a doc for this clientId, return what we have (server
          wins on the band name — the client should sync to it).
        - Otherwise, create a fresh row with the client's userName and an empty
          rank, so subsequent rankchanged events upsert by an existing client_id.
        """
        client_id = data.get('clientId')
        user_name = data.get('userName', '')
        if not client_id:
            return {'user': user_name, 'rank': []}

        _connected_sids[request.sid] = client_id
        join_room(_client_room(client_id))

        existing = vote_store.get_by_client(client_id)
        if existing:
            return {
                'user': existing.get('user', user_name),
                'rank': existing.get('rank', []),
            }

        # First time we've seen this client — seed an empty doc.
        vote_store.update_name(client_id, user_name)
        return {'user': user_name, 'rank': []}

    @socket_io.on('disconnect')
    def on_disconnect():
        _connected_sids.pop(request.sid, None)

    @socket_io.on('rankchanged')
    def on_rankchange(data):
        """Payload: {clientId: str, user: str, rank: list[str]}"""
        client_id = data.get('clientId')
        user = data.get('user', '')
        rank = data.get('rank', [])
        if not client_id:
            print("rankchanged: missing clientId, ignoring")
            return
        vote_store.upsert_rank(client_id, user, rank)
        print(f"{user} ({client_id[:8]}) updated rank: {rank}")

    @socket_io.on('nameChanged')
    def on_namechange(data):
        """Payload: {clientId: str, newName: str}"""
        client_id = data.get('clientId')
        new_name = data.get('newName', '')
        if not client_id:
            print("nameChanged: missing clientId, ignoring")
            return
        vote_store.update_name(client_id, new_name)
        socket_io.emit('userRenamed', {'clientId': client_id, 'new_name': new_name}, broadcast=True)
        print(f"{client_id[:8]} renamed to '{new_name}'")

    @socket_io.on('onboarding_complete')
    def on_onboarding_complete(data):
        """Payload: {clientId, userName, answers: {song_title, song_vibe, personal_vibe, extra}}"""
        client_id = data.get('clientId')
        if not client_id:
            print("onboarding_complete: missing clientId, ignoring")
            return
        answers = data.get('answers') or {}
        vote_store.upsert_user_profile(client_id, {
            'user':          data.get('userName', ''),
            'song_title':    answers.get('song_title', ''),
            'song_vibe':     answers.get('song_vibe', ''),
            'personal_vibe': answers.get('personal_vibe', ''),
            'extra':         answers.get('extra', ''),
        })
        print(f"{client_id[:8]} onboarded as '{data.get('userName', '')}'")
