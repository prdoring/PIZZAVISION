"""Seed pizzavision/db.json with 6 voters whose vote-behavior is rigged so
each new award (Juggler / Commitment Issues / Flip Flop / Markie Likey) has a
distinct, interesting winner. Each voter also has a full 25-song ranking, so
the existing category awards still produce winners.

Backdated timestamps drive Markie Likey duration math.

Run from repo root: python _seed_award_preview.py
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "pizzavision", "db.json")
OPTS_PATH = os.path.join(ROOT, "pizzavision", "options.json")

with open(OPTS_PATH, encoding="utf-8") as f:
    SONGS = [s["label"] for s in json.load(f)["options"]]

print(f"{len(SONGS)} songs in options.json")

NOW = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def cycle(start, songs):
    """Return songs starting at `start`, wrapping around — for varied rankings."""
    i = songs.index(start)
    return songs[i:] + songs[:i]


# ------------------------------------------------------------------
# Voter scripts
# ------------------------------------------------------------------
# Each entry: (band_name, final_rank, mutation_count, top1_history)
# top1_history timestamps are absolute, backdated relative to NOW.

voters = []

# ---- 1. Juggle Bells — Juggler winner. 22 total rank changes, modest #1 history.
juggle_rank = cycle("Sweden: My System", SONGS)
juggle_hist = [
    {"song": "Sweden: My System", "at": iso(NOW - timedelta(minutes=90))},
    {"song": "Finland: Liekinheitin", "at": iso(NOW - timedelta(minutes=70))},
    {"song": "Sweden: My System", "at": iso(NOW - timedelta(minutes=40))},
]
voters.append(("Juggle Bells", juggle_rank, 22, juggle_hist))

# ---- 2. Heart Wanderer — Commitment Issues winner. 6 distinct #1s.
wander_rank = cycle("Italy: Per sempre sì", SONGS)
wander_hist = [
    {"song": "Denmark: Før vi går hjem", "at": iso(NOW - timedelta(minutes=80))},
    {"song": "Germany: Fire", "at": iso(NOW - timedelta(minutes=70))},
    {"song": "Israel: Michelle", "at": iso(NOW - timedelta(minutes=55))},
    {"song": "Belgium: Dancing on the Ice", "at": iso(NOW - timedelta(minutes=40))},
    {"song": "Greece: Ferto", "at": iso(NOW - timedelta(minutes=25))},
    {"song": "Italy: Per sempre sì", "at": iso(NOW - timedelta(minutes=10))},
]
voters.append(("Heart Wanderer", wander_rank, 9, wander_hist))

# ---- 3. Flippy McFloperson — Flip Flop winner. 'Croatia: Andromeda' returns 3 times.
flip_rank = cycle("Croatia: Andromeda", SONGS)
flip_hist = [
    {"song": "Croatia: Andromeda", "at": iso(NOW - timedelta(minutes=85))},
    {"song": "Poland: Pray", "at": iso(NOW - timedelta(minutes=75))},
    {"song": "Croatia: Andromeda", "at": iso(NOW - timedelta(minutes=65))},
    {"song": "Poland: Pray", "at": iso(NOW - timedelta(minutes=50))},
    {"song": "Croatia: Andromeda", "at": iso(NOW - timedelta(minutes=35))},
    {"song": "Poland: Pray", "at": iso(NOW - timedelta(minutes=20))},
    {"song": "Croatia: Andromeda", "at": iso(NOW - timedelta(minutes=5))},
]
# Croatia appears 4 times (returns=3), Poland 3 times (returns=2). Flip Flop = 3.
voters.append(("Flippy McFloperson", flip_rank, 14, flip_hist))

# ---- 4. Locked-In Larry — Markie Likey winner. Sets #1 ~2h ago, never changes.
larry_rank = cycle("Norway: Ya ya ya", SONGS)
larry_hist = [
    {"song": "Norway: Ya ya ya", "at": iso(NOW - timedelta(minutes=120))},
]
voters.append(("Locked-In Larry", larry_rank, 6, larry_hist))

# ---- 5. Pop Princess — plain-ish voter, pop-leaning. 3 changes, 2 distinct #1s.
pop_rank = cycle("Cyprus: Jalla", SONGS)
pop_hist = [
    {"song": "Malta: Bella", "at": iso(NOW - timedelta(minutes=60))},
    {"song": "Cyprus: Jalla", "at": iso(NOW - timedelta(minutes=30))},
    {"song": "Malta: Bella", "at": iso(NOW - timedelta(minutes=15))},
]
voters.append(("Pop Princess", pop_rank, 7, pop_hist))

# ---- 6. Slow Burn — minimal voter, 1 change, sticks with it (~30min).
slow_rank = cycle("Ukraine: Ridnym", SONGS)
slow_hist = [
    {"song": "Ukraine: Ridnym", "at": iso(NOW - timedelta(minutes=30))},
]
voters.append(("Slow Burn", slow_rank, 1, slow_hist))


# ------------------------------------------------------------------
# Write TinyDB doc
# ------------------------------------------------------------------
default_table = {}
for idx, (name, rank, mc, hist) in enumerate(voters, start=1):
    earliest = hist[0]["at"] if hist else iso(NOW)
    default_table[str(idx)] = {
        "client_id": str(uuid.uuid4()),
        "user": name,
        "rank": rank,
        "created_at": earliest,
        "updated_at": iso(NOW),
        "rank_updated_at": iso(NOW),
        "mutation_count": mc,
        "top1_history": hist,
    }

with open(DB_PATH, "w", encoding="utf-8") as f:
    json.dump({"_default": default_table}, f, indent=2, ensure_ascii=False)

print(f"\nSeeded {len(voters)} voters into {DB_PATH}")
for name, _, mc, hist in voters:
    songs_in_hist = {h["song"].split(":", 1)[0] for h in hist}
    print(f"  • {name}: mc={mc}, #1 history={len(hist)} entries, "
          f"distinct top-1 countries={sorted(songs_in_hist)}")

# Sanity: import & run calculate_awards to confirm winners
from pizzavision.vote_store import TinyDBVoteStore
from pizzavision.utils import calculate_awards

store = TinyDBVoteStore(DB_PATH)
with open(OPTS_PATH, encoding="utf-8") as f:
    opts = json.load(f)
awards = calculate_awards(store, opts)
print("\n--- New award winners ---")
for code in ("Juggler", "Commitment Issues", "Flip Flop", "Markie Likey"):
    a = next((x for x in awards if x["code"] == code), None)
    if a:
        print(f"  {code}: {a['winner']}")
    else:
        print(f"  {code}: <not crowned — check seed>")
