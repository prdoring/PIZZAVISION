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

# Shared SocketIO room for any browser viewing the admin page. Joined via the
# `admin_join` event; gets targeted `admin_user_*` pushes so the Users tab
# updates live without polling or page reloads.
ADMIN_ROOM = "admin"


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
    calculate_awards, get_file_path, load_lock_state, load_voting_state,
    VOTING_STATES,
)
from .vote_store import get_vote_store


def _user_admin_payload(row, online_ids):
    """Shape a vote_store row into the dict the admin Users table consumes —
    same fields as the initial server-rendered table, so the JS row-builder
    and the Jinja template stay in lockstep."""
    cid = row.get("client_id", "")
    return {
        "client_id": cid,
        "user": row.get("user", "") or "(unnamed)",
        "first_name": row.get("first_name", "") or "",
        "rank_count": len(row.get("rank") or []),
        "created_at": _fmt_pacific(row.get("created_at")),
        "rank_updated_at": _fmt_pacific(row.get("rank_updated_at")),
        "online": cid in online_ids,
    }


def _emit_admin_user_upsert(socket_io, client_id):
    """Push the canonical row for one user to all admins. Called after any
    mutation that adds or changes a row. No-op if the row is gone."""
    row = vote_store.get_by_client(client_id)
    if not row:
        return
    online_ids = set(_connected_sids.values())
    socket_io.emit(
        "admin_user_upsert",
        _user_admin_payload(row, online_ids),
        to=ADMIN_ROOM,
    )


def _emit_admin_user_online(socket_io, client_id, online):
    socket_io.emit(
        "admin_user_online",
        {"client_id": client_id, "online": online},
        to=ADMIN_ROOM,
    )


def _emit_admin_user_removed(socket_io, client_id):
    socket_io.emit(
        "admin_user_removed",
        {"client_id": client_id},
        to=ADMIN_ROOM,
    )
from . import openai_client
from . import gemini_image_client
from .image_store import get_image_store

# Single shared vote store. Firestore in prod (GOOGLE_CLOUD_PROJECT set),
# TinyDB locally. See vote_store.py.
vote_store = get_vote_store()

# Single shared image store. GCS in prod, local disk in dev. See image_store.py.
image_store = get_image_store()


# ------------------------------------------------------------------
# Background image pipeline — runs after onboarding_complete
# ------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_prompt_then_fan_out(sio, client_id, band_name, answers):
    """Background task: generate the Nano Banana Pro prompt, then fan out
    three parallel image-gen tasks. Each child task emits its own socket
    event as it lands so the client can stream-in the candidates.

    Runs under socketio.start_background_task (greenlet on eventlet, native
    thread otherwise). The client's first_name is intentionally excluded —
    the image is about the fictional act, not the person.
    """
    room = _client_room(client_id)

    vote_store.upsert_user_profile(client_id, {
        'image_status': 'pending',
        'image_candidates': [],
        'image_candidate_errors': {},
    })

    try:
        prompts = openai_client.generate_image_prompts(
            band_name,
            answers.get('first_name', ''),
            answers.get('song_title', ''),
            answers.get('song_vibe', ''),
            answers.get('personal_vibe', ''),
            answers.get('extra', ''),
        )
    except Exception as e:
        print(f"[image] {client_id[:8]} prompt gen failed: {e!r}")
        vote_store.upsert_user_profile(client_id, {
            'image_status': 'failed',
            'image_error': f"{type(e).__name__}: {e}",
        })
        sio.emit('band_images_failed',
                 {'error': str(e), 'error_type': type(e).__name__},
                 to=room)
        return

    vote_store.upsert_user_profile(client_id, {
        'image_prompts': prompts,
        'image_status': 'prompt_ready',
    })
    sio.emit('band_images_starting', {'count': 3}, to=room)
    print(f"[image] {client_id[:8]} 3 prompts ready, fanning out candidates")

    for idx in (0, 1, 2):
        sio.start_background_task(_generate_one_image, sio, client_id, prompts[idx], idx)


def _gemini_call(prompt):
    """Run gemini_image_client.generate_image in a real OS thread when
    running under eventlet.

    Why: the Gemini SDK's HTTP transport doesn't yield cooperatively to
    the eventlet hub. Calling it directly from a greenlet blocks every
    other greenlet (including the sibling image-gen tasks) until it
    returns -- so 3 "parallel" generations serialize and the user sees
    all 3 candidates land at once instead of streaming in. eventlet.tpool
    runs the call in a real OS thread, keeping the hub free for the
    siblings. Falls through to a direct call if eventlet isn't loaded
    (dev / threading async mode), where blocking calls don't share a hub
    anyway.
    """
    try:
        from eventlet import tpool
    except ImportError:
        return gemini_image_client.generate_image(prompt)
    return tpool.execute(gemini_image_client.generate_image, prompt)


def _generate_one_image(sio, client_id, prompt, idx):
    """Background task: generate ONE candidate image and emit its result.

    Each instance runs independently — three of them launch in parallel
    from _generate_prompt_then_fan_out, so total wallclock is ~one slot's
    latency, not three.
    """
    room = _client_room(client_id)
    try:
        image_bytes = _gemini_call(prompt)
        url = image_store.save_candidate(client_id, idx, image_bytes)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[image] {client_id[:8]} candidate {idx} failed: {msg}")
        # Record the failure on the row without disturbing siblings.
        row = vote_store.get_by_client(client_id) or {}
        errors = dict(row.get('image_candidate_errors') or {})
        errors[str(idx)] = msg
        vote_store.upsert_user_profile(client_id, {
            'image_candidate_errors': errors,
        })
        sio.emit('band_image_candidate_failed',
                 {'idx': idx, 'error': msg},
                 to=room)
        return

    # Append this slot to image_candidates. Read-modify-write — at party
    # scale concurrent writes from sibling tasks are extremely rare and
    # Firestore's last-write-wins is acceptable. The client tracks
    # candidates from socket events anyway; the DB copy is for resume +
    # the later pick handler.
    row = vote_store.get_by_client(client_id) or {}
    candidates = list(row.get('image_candidates') or [])
    # Drop any prior entry for this idx in case of a retry.
    candidates = [c for c in candidates if c.get('idx') != idx]
    candidates.append({'idx': idx, 'url': url})
    vote_store.upsert_user_profile(client_id, {
        'image_candidates': candidates,
    })
    print(f"[image] {client_id[:8]} candidate {idx} ready")
    sio.emit('band_image_candidate_ready',
             {'idx': idx, 'url': url},
             to=room)


@voting_bp.route('/')
def index():
    options = load_options()
    vo = load_vote_options()
    voting_state = load_voting_state()
    return render_template(
        'index.html',
        options=options,
        votes=vo,
        voting_state=voting_state,
        votes_locked=(voting_state == 'closed'),
    )


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
            avoid=body.get('avoid') or None,
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


@voting_bp.route('/api/image-state', methods=['GET'])
def image_state():
    """Current image-pipeline state for a given clientId.

    Used by the image-pick step on the client. We poll this every couple
    of seconds rather than relying on the background-task socket emits to
    push candidate URLs -- those emits proved unreliable in this
    eventlet + python-socketio + Flask-SocketIO combination when emitted
    from a nested background task. The socket emits are still fired
    server-side as best-effort instant feedback, but the picker's source
    of truth is this endpoint.

    Query: ?clientId=<uuid>
    Returns: {
        status:     'pending'|'prompt_ready'|'ready'|'failed'|'missing',
        candidates: [{idx, url}],
        errors:     {idx: msg},
        chosen_url: str|null,
    }
    """
    client_id = (request.args.get('clientId') or '').strip()
    if not client_id:
        return jsonify(error='clientId required', error_code='bad_input'), 400
    row = vote_store.get_by_client(client_id)
    if not row:
        return jsonify(
            status='missing',
            candidates=[],
            errors={},
            chosen_url=None,
        )
    return jsonify(
        status=row.get('image_status') or 'pending',
        candidates=row.get('image_candidates') or [],
        errors=row.get('image_candidate_errors') or {},
        chosen_url=row.get('image_url') or None,
    )


@voting_bp.route('/api/roast-band', methods=['POST'])
def roast_band():
    """Lighthearted AI dig at a user's freshly-minted Eurovision act,
    shown while they're sitting on the "voting hasn't started yet" screen.

    Payload: {clientId: str}
    Returns: {roast: str} on success, or a 4xx/503 with `error` on failure.
    Frontend treats any non-200 as 'just hide the roast block'.
    """
    body = request.get_json(silent=True) or {}
    client_id = (body.get('clientId') or '').strip()
    if not client_id:
        return jsonify(error='clientId required', error_code='bad_input'), 400

    row = vote_store.get_by_client(client_id)
    if not row:
        return jsonify(error='no row for this client', error_code='no_row'), 404

    band_name     = (row.get('user') or '').strip()
    song_title    = (row.get('song_title') or '').strip()
    song_vibe     = (row.get('song_vibe') or '').strip()
    personal_vibe = (row.get('personal_vibe') or '').strip()
    extra         = (row.get('extra') or '').strip()

    # If we have nothing but a band name, the AI has no specifics to riff on —
    # don't bother making the call.
    if not (song_title or song_vibe or personal_vibe or extra):
        return jsonify(error='no onboarding answers yet', error_code='no_answers'), 404

    try:
        roast = openai_client.roast_band(
            band_name, song_title, song_vibe, personal_vibe, extra
        )
        return jsonify(roast=roast)
    except ModuleNotFoundError as e:
        current_app.logger.exception("roast_band: openai package not installed")
        return jsonify(error=str(e), error_code='no_openai_package'), 503
    except RuntimeError as e:
        current_app.logger.warning(f"roast_band: {e}")
        return jsonify(error=str(e), error_code='no_api_key'), 503
    except Exception as e:
        current_app.logger.exception("roast_band: unexpected failure")
        return jsonify(error=str(e), error_code='api_error', error_type=type(e).__name__), 503


@voting_bp.route('/api/roast-votes', methods=['POST'])
def roast_votes():
    """Snarky AI one-liner about a single voter's finalized ballot.

    Payload: {clientId: str}
    Returns: {roast: str} on success, or a 4xx/503 with `error` on failure.
    The frontend treats any non-200 as 'just hide the roast block'.
    """
    body = request.get_json(silent=True) or {}
    client_id = (body.get('clientId') or '').strip()
    if not client_id:
        return jsonify(error='clientId required', error_code='bad_input'), 400

    row = vote_store.get_by_client(client_id)
    if not row:
        return jsonify(error='no votes for this client', error_code='no_row'), 404

    rank = row.get('rank') or []
    if not rank:
        return jsonify(error='empty ballot', error_code='empty_ballot'), 404

    with open(OPTIONS_FILE, 'r', encoding='utf-8') as fh:
        options_data = json.load(fh)
    by_label = {o['label']: o for o in options_data.get('options', [])}
    picks_with_meta = []
    for lbl in rank:
        meta = by_label.get(lbl, {})
        picks_with_meta.append({
            'label':            lbl,
            'genre':            meta.get('genre'),
            'lead':             meta.get('lead'),
            'language':         meta.get('language'),
            'region':           meta.get('region'),
            'act_type':         meta.get('act_type'),
            'selection_type':   meta.get('selection_type'),
            'drink':            meta.get('drink'),
            'big5':             meta.get('big5'),
            'former_soviet':    meta.get('former_soviet'),
            'returning_artist': meta.get('returning_artist'),
        })

    try:
        roast = openai_client.roast_user_votes(row.get('user', ''), picks_with_meta)
        return jsonify(roast=roast)
    except ModuleNotFoundError as e:
        current_app.logger.exception("roast_votes: openai package not installed")
        return jsonify(error=str(e), error_code='no_openai_package'), 503
    except RuntimeError as e:
        current_app.logger.warning(f"roast_votes: {e}")
        return jsonify(error=str(e), error_code='no_api_key'), 503
    except Exception as e:
        current_app.logger.exception("roast_votes: unexpected failure")
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
      save_options      – reorder / delete items (also clears votes)
      clear_db          – wipe the vote store
      restore_options   – copy options_bak.json -> options.json (also clears votes)
      set_voting_state  – move the contest to "pre" / "open" / "closed"
                          (replaces the old lock_votes / unlock_votes)
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
            sio = current_app.extensions["socketio"]
            # Targeted: only the affected client (if online) gets wiped and
            # bounced back to onboarding. Other voters are not disturbed.
            sio.emit("you_were_cleared", to=_client_room(client_id))
            # Live-update any other admin tabs viewing the Users table.
            _emit_admin_user_removed(sio, client_id)
            return jsonify(status="deleted")

        if action == "clear_user_rank":
            client_id = request.form.get("client_id", "").strip()
            if not client_id:
                abort(400, "client_id required")
            if not vote_store.clear_rank_by_client(client_id):
                abort(404, "user not found")
            sio = current_app.extensions["socketio"]
            # Targeted: only the affected client (if online) clears its local
            # rank and reloads. Their band name + onboarding answers stay.
            sio.emit("your_rank_cleared", to=_client_room(client_id))
            _emit_admin_user_upsert(sio, client_id)
            return jsonify(status="rank_cleared")

        if action == "restore_options":
            if not os.path.exists(BACKUP_FILE):
                abort(500, "options_bak.json not found")
            with open(BACKUP_FILE, "r", encoding="utf-8") as fh:
                backup = json.load(fh)
            _save_options(backup)
            vote_store.truncate()
            current_app.extensions["socketio"].emit("options_updated")
            return jsonify(status="restored")

        if action == "set_voting_state":
            new_state = request.form.get("state", "")
            if new_state not in VOTING_STATES:
                abort(400, f"state must be one of {VOTING_STATES}")

            data = _load_options()
            data["voting_state"] = new_state
            data.pop("locked", None)  # one-time legacy cleanup

            timestamp = None
            if new_state == "closed":
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
                        print(f"set_voting_state: snapshot write skipped ({exc})")

            _save_options(data)

            sio = current_app.extensions["socketio"]
            sio.emit("voting_state_changed", {"state": new_state, "timestamp": timestamp})
            # Keep emitting the legacy event on close so the existing podium
            # reveal stays wired even if a client hasn't reloaded since the
            # 3-state refactor.
            if new_state == "closed":
                sio.emit("votes_finalized", {"timestamp": timestamp})

            return jsonify(status="state_set", state=new_state, timestamp=timestamp)

        abort(400, "unknown action")

    data = _load_options()
    online_ids = set(_connected_sids.values())
    users = [_user_admin_payload(row, online_ids) for row in vote_store.all()]
    users.sort(key=lambda u: (u["user"] or "").lower())
    return render_template(
        "admin.html",
        options=data["options"],
        users=users,
        voting_state=load_voting_state(),
    )


# ------------------------------------------------------------------
# SocketIO event handlers
# ------------------------------------------------------------------
def register_socketio_handlers(socket_io):
    """Register SocketIO event handlers. Called from pizzavision.py at startup."""

    @socket_io.on('joined')
    def on_joined(data):
        """Client just connected (or refreshed). Return its persisted state.

        Payload: {clientId: str, userName: str}
        Reply  : {user, rank}   if we have a row for this clientId
                 {reset: True}  if we don't (admin-deleted while client was
                                offline — the client should wipe local state
                                and re-run onboarding rather than silently
                                getting a fresh row)

        Side effects:
        - Tracks this sid as belonging to client_id (powers the admin online dot).
        - Joins the client_id-keyed SocketIO room so admin actions can target
          just this user.

        We deliberately do NOT auto-seed a row here. Seeding hid the
        admin-deleted-while-offline case: the client would silently rejoin
        with the same name and bypass onboarding. New rows are created when
        they actually need to exist — via onboarding_complete (first-time
        onboarders) or upsert_rank (first drag).
        """
        client_id = data.get('clientId')
        user_name = data.get('userName', '')
        if not client_id:
            return {'user': user_name, 'rank': []}

        was_offline = client_id not in _connected_sids.values()
        _connected_sids[request.sid] = client_id
        join_room(_client_room(client_id))

        # Only notify admins on the first sid for this client_id — opening a
        # second tab shouldn't re-fire "came online" since they never left.
        if was_offline and vote_store.get_by_client(client_id):
            _emit_admin_user_online(socket_io, client_id, True)

        existing = vote_store.get_by_client(client_id)
        if existing:
            return {
                'user': existing.get('user', user_name),
                'rank': existing.get('rank', []),
            }
        return {'reset': True}

    @socket_io.on('admin_join')
    def on_admin_join(*_):
        """Admin page subscribes to live user-table updates. Returns the
        current set of online client_ids so the page can reconcile any
        users who flipped state between server render and socket connect."""
        join_room(ADMIN_ROOM)
        return {'online_client_ids': list(set(_connected_sids.values()))}

    @socket_io.on('disconnect')
    def on_disconnect():
        cid = _connected_sids.pop(request.sid, None)
        # Only notify admins when this was the LAST connection for the user
        # — multi-tab voters stay "online" if any tab remains open.
        if cid and cid not in _connected_sids.values():
            _emit_admin_user_online(socket_io, cid, False)

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
        # First-drag may create a brand-new row; either way, push the
        # canonical state so admins see the updated rank count + timestamp.
        _emit_admin_user_upsert(socket_io, client_id)
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
        _emit_admin_user_upsert(socket_io, client_id)
        print(f"{client_id[:8]} renamed to '{new_name}'")

    @socket_io.on('onboarding_complete')
    def on_onboarding_complete(data):
        """Payload: {clientId, userName, answers: {song_title, song_vibe, personal_vibe, extra}}

        Persists the profile, then kicks off the background image pipeline:
        prompt-gen -> three parallel Nano Banana Pro calls -> per-image
        socket events the client streams into the picker. The handler
        itself returns immediately so the client transitions instantly.
        """
        client_id = data.get('clientId')
        if not client_id:
            print("onboarding_complete: missing clientId, ignoring")
            return
        answers = data.get('answers') or {}
        user_name = data.get('userName', '')
        vote_store.upsert_user_profile(client_id, {
            'user':          user_name,
            'first_name':    answers.get('first_name', ''),
            'song_title':    answers.get('song_title', ''),
            'song_vibe':     answers.get('song_vibe', ''),
            'personal_vibe': answers.get('personal_vibe', ''),
            'extra':         answers.get('extra', ''),
        })
        # Put this sid in its per-client room NOW so the upcoming background
        # task's emits actually reach the browser. Normally `joined` does
        # this, but `joined` fires after onboarding finishes — the image
        # pipeline starts mid-onboarding, so we can't wait.
        _connected_sids[request.sid] = client_id
        join_room(_client_room(client_id))
        # New row is now persisted; notify admins so it shows up live in
        # the Users tab without a refresh.
        _emit_admin_user_upsert(socket_io, client_id)
        print(f"{client_id[:8]} onboarded as '{user_name}'")

        socket_io.start_background_task(
            _generate_prompt_then_fan_out,
            socket_io,
            client_id,
            user_name,
            answers,
        )

    @socket_io.on('pick_band_image')
    def on_pick_band_image(data):
        """Payload: {clientId: str, chosenIdx: int}

        chosenIdx must be one of the candidate indices currently on the
        row. Cleans up the two unselected images and finalizes the row.
        Skip-without-picking is no longer supported -- the user must
        pick one of the generated images to leave onboarding.
        """
        client_id = data.get('clientId')
        chosen_idx = data.get('chosenIdx')
        if not client_id or not isinstance(chosen_idx, int):
            print(f"pick_band_image: bad payload {data!r}, ignoring")
            return

        # If the client reloaded mid-picker, their new SID never went
        # through on_onboarding_complete and isn't in the per-client
        # room -- our `band_image_finalized` emit would vanish and the
        # button would hang on "Saving...". Re-join here defensively;
        # join_room is idempotent for already-joined sids.
        _connected_sids[request.sid] = client_id
        join_room(_client_room(client_id))

        room = _client_room(client_id)
        row = vote_store.get_by_client(client_id) or {}

        # Verify the chosen idx actually has a landed candidate.
        valid_idxs = {c.get('idx') for c in (row.get('image_candidates') or [])}
        if chosen_idx not in valid_idxs:
            print(f"pick_band_image: {client_id[:8]} idx {chosen_idx} not in landed candidates {valid_idxs}")
            return

        try:
            chosen_url = image_store.keep_chosen_delete_rest(client_id, chosen_idx)
        except Exception as e:
            print(f"[image] {client_id[:8]} keep_chosen failed: {e!r}")
            return

        vote_store.upsert_user_profile(client_id, {
            'image_url':        chosen_url,
            'image_chosen_idx': chosen_idx,
            'image_chosen_at':  _now_iso(),
            'image_status':     'ready',
            'image_candidates': [],
        })
        socket_io.emit('band_image_finalized',
                       {'idx': chosen_idx, 'url': chosen_url},
                       to=room)
        print(f"[image] {client_id[:8]} picked image {chosen_idx}")
