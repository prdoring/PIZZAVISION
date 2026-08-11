"""Seed a full, realistic party state for screenshots and demos.

Ten voters, each wired to one of the AI portraits already sitting in
pizzavision/static/generated/. Every persona's band name and song title
match the text the image model rendered into their photo, so the guess
game and the vote card read as a coherent act rather than a mismatch.

Rankings are deterministic (fixed RNG seed) so screenshots are
reproducible, but varied enough that the leaderboard and the awards both
produce interesting spreads. Vote-behaviour fields (mutation_count,
top1_history) are rigged so the behavioural awards each crown someone
different.

Run from the repo root:
    python _seed_demo_party.py            # leaves voting_state as-is
    python _seed_demo_party.py open       # ballot screenshots
    python _seed_demo_party.py closed     # results / awards screenshots

Overwrites pizzavision/db.json. That file is gitignored; back it up first
if it holds anything you care about.
"""

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "pizzavision", "db.json")
OPTS_PATH = os.path.join(ROOT, "pizzavision", "options.json")

with open(OPTS_PATH, encoding="utf-8") as f:
    OPTS = json.load(f)
SONGS = [s["label"] for s in OPTS["options"]]

NOW = datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def img(client_id, idx=0):
    return f"/pizzavision/voting/static/generated/{client_id}/{idx}.png"


def find(fragment):
    """Resolve a song by a distinctive fragment of its label."""
    for s in SONGS:
        if fragment.lower() in s.lower():
            return s
    raise SystemExit(f"seed: no song matching {fragment!r} in options.json")


# ------------------------------------------------------------------
# Personas. client_id is the folder its portrait already lives in, so
# image_url resolves with no file copying.
# ------------------------------------------------------------------
PERSONAS = [
    {
        "client_id": "08713d3e-f456-4d0e-ae84-d73c1fbee3cb",
        "user": "Doggulus",
        "first_name": "Mira",
        "song_title": "Long Doggul",
        "song_vibe": "Stadium glam-rock built entirely around one very long dog",
        "personal_vibe": "Head-to-toe black leather, walking a catwalk between two "
                         "inflatable dachshunds the size of buses",
        "extra": "The dachshunds inflate on the key change.",
        "fav": "Sweden",
    },
    {
        "client_id": "259b6786-9f28-4566-befe-6156cc2ff340",
        "user": "Synaesthetic Affection",
        "first_name": "Theo",
        "song_title": "Colour Me Loud",
        "song_vibe": "Disco house that insists every note has a colour",
        "personal_vibe": "Gold jumpsuit, mirrorball descending, an arena of glowsticks "
                         "moving in one wave",
        "extra": "Every chorus changes the entire room's lighting palette.",
        "fav": "Cyprus",
    },
    {
        "client_id": "a4c945dc-ccc6-4260-8d63-4b15884b97c4",
        "user": "Neon Snack",
        "first_name": "Devon",
        "song_title": "Butterfly Bicep",
        "song_vibe": "Hyperpop about going to the gym with a butterfly",
        "personal_vibe": "Metallic bodysuit on a diamond stage, flexing at a neon "
                         "butterfly the size of a building",
        "extra": "Ten thousand glowsticks, all synced to the beat drop.",
        "fav": "Finland",
    },
    {
        "client_id": "9029fc37-a6bc-432c-8287-e2b8a4b0eacd",
        "user": "Face The Wind",
        "first_name": "Sasha",
        "song_title": "Face the Wind",
        "song_vibe": "Windswept stadium ballad that refuses to stay a ballad",
        "personal_vibe": "Gold sequin suit alone on a stadium thrust, flanked by two "
                         "inflatable saxophones five storeys tall",
        "extra": "Gold confetti cannon on literally every chorus.",
        "fav": "Italy",
    },
    {
        "client_id": "e7fc3638-06bf-4cc2-9d93-4d065593d59c",
        "user": "Puppetábra",
        "first_name": "Indira",
        "song_title": "Fôrgét Me Not",
        "song_vibe": "Folk-dramatic, sung to a creature nobody else can see",
        "personal_vibe": "Whirling in a painted skirt beside a giant puppet beast "
                         "worked by six puppeteers",
        "extra": "The beast blinks on the final note.",
        "fav": "Albania",
    },
    {
        "client_id": "668d90df-1ef7-423c-b83c-d3d9fc78ac11",
        "user": "Brassé Boum",
        "first_name": "Jules",
        "song_title": "Vöyages",
        "song_vibe": "Big-band swing with a chorus you can shout in any language",
        "personal_vibe": "Gold dress spinning centre stage while a twenty-piece brass "
                         "section closes in from both wings",
        "extra": "The brass section marches into the audience at the bridge.",
        "fav": "France",
    },
    {
        "client_id": "2c066f92-4383-4bb8-80c1-bca8a2dd739f",
        "user": "Cloudfruit",
        "first_name": "Robin",
        "song_title": "Föör Yöu",
        "song_vibe": "Woozy indie-folk that keeps almost becoming a waltz",
        "personal_vibe": "Spinning in a rainbow poncho while a painter finishes the "
                         "album cover live behind me",
        "extra": "The painting is finished exactly on the last chord.",
        "fav": "Norway",
    },
    {
        "client_id": "7e309719-60b3-44b1-88ad-821ea64a8f09",
        "user": "Paper Phoenix",
        "first_name": "Nadia",
        "song_title": "Ashes and Origami",
        "song_vibe": "Slow-burn power ballad about rebuilding from scraps",
        "personal_vibe": "Black suit stitched with origami cranes, standing in blue "
                         "flame while a phoenix ignites on the screen",
        "extra": "A thousand paper cranes fall on the last chorus.",
        "fav": "Ukraine",
    },
    {
        "client_id": "6e98c1df-a6c7-4780-9985-49ffff586a9f",
        "user": "The Golden Tuba",
        "first_name": "Casper",
        "song_title": "Oompah Supernova",
        "song_vibe": "Europop with an unreasonably large brass instrument",
        "personal_vibe": "Head-to-toe gold sequins carrying a sousaphone under an "
                         "enormous paper star",
        "extra": "Solo tuba key change. No backing track. Nowhere to hide.",
        "fav": "Germany",
    },
    {
        "client_id": "248c6b7e-f45c-44a6-8ee8-6755ad9ce994",
        "user": "White Dress Riot",
        "first_name": "Elin",
        "song_title": "Paper Hearts",
        "song_vibe": "Quiet opening, then the entire brass section arrives at once",
        "personal_vibe": "Barefoot in a white dress under a confetti storm, fireworks "
                         "going off behind the band",
        "extra": "Starts alone at a piano. Ends with fireworks.",
        "fav": "Malta",
    },
]

# ------------------------------------------------------------------
# Vote-behaviour scripts. Keyed by band name; drives the four
# behavioural awards so each one crowns a different person.
# ------------------------------------------------------------------
BEHAVIOUR = {
    # Juggler: most total rank changes.
    "Doggulus": {
        "mutations": 31,
        "history": [("Sweden", 95), ("Finland", 72), ("Sweden", 38)],
    },
    # Commitment Issues: most distinct number ones.
    "Synaesthetic Affection": {
        "mutations": 12,
        "history": [("Denmark", 88), ("Germany", 74), ("Israel", 61),
                    ("Belgium", 44), ("Greece", 26), ("Cyprus", 9)],
    },
    # Flip Flop: kept returning to the same two songs.
    "Neon Snack": {
        "mutations": 18,
        "history": [("Finland", 90), ("Poland", 78), ("Finland", 64),
                    ("Poland", 49), ("Finland", 33), ("Poland", 19),
                    ("Finland", 6)],
    },
    # Markie Likey: locked in early and never moved.
    "Face The Wind": {
        "mutations": 4,
        "history": [("Italy", 142)],
    },
    "Puppetábra": {
        "mutations": 9,
        "history": [("Serbia", 70), ("Albania", 31)],
    },
    "Brassé Boum": {
        "mutations": 7,
        "history": [("Austria", 66), ("France", 28)],
    },
    "Cloudfruit": {
        "mutations": 6,
        "history": [("Norway", 55)],
    },
    "Paper Phoenix": {
        "mutations": 11,
        "history": [("Czechia", 80), ("Ukraine", 47), ("Ukraine", 21)],
    },
    "The Golden Tuba": {
        "mutations": 5,
        "history": [("Germany", 40)],
    },
    "White Dress Riot": {
        "mutations": 8,
        "history": [("Lithuania", 58), ("Malta", 24)],
    },
}


def build_rank(persona, seed):
    """Deterministic ballot: favourite on top, rest shuffled per voter.

    Two shared 'consensus' songs are nudged into most voters' top five so
    the leaderboard has a real winner instead of ten-way noise.
    """
    rng = random.Random(seed)
    rest = [s for s in SONGS if s != persona["fav_label"]]
    rng.shuffle(rest)
    rank = [persona["fav_label"]] + rest

    # Nudge the two crowd-pleasers up for 7 of the 10 voters.
    if seed % 10 < 7:
        for consensus, target in ((CONSENSUS_A, 1), (CONSENSUS_B, 3)):
            if consensus == persona["fav_label"]:
                continue
            rank.remove(consensus)
            rank.insert(target, consensus)
    return rank


CONSENSUS_A = find("Sweden")
CONSENSUS_B = find("Italy")


def main():
    state_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if state_arg and state_arg not in ("pre", "open", "closed"):
        raise SystemExit("usage: python _seed_demo_party.py [pre|open|closed]")

    table = {}
    for i, p in enumerate(PERSONAS, start=1):
        p["fav_label"] = find(p["fav"])
        beh = BEHAVIOUR[p["user"]]
        history = [
            {"song": find(country), "at": iso(NOW - timedelta(minutes=mins))}
            for country, mins in beh["history"]
        ]
        created = history[0]["at"] if history else iso(NOW)
        table[str(i)] = {
            "client_id": p["client_id"],
            "user": p["user"],
            "first_name": p["first_name"],
            "song_title": p["song_title"],
            "song_vibe": p["song_vibe"],
            "personal_vibe": p["personal_vibe"],
            "extra": p["extra"],
            "rank": build_rank(p, seed=i * 7),
            "created_at": created,
            "updated_at": iso(NOW),
            "rank_updated_at": iso(NOW - timedelta(minutes=i * 2)),
            "mutation_count": beh["mutations"],
            "top1_history": history,
            "image_url": img(p["client_id"]),
            "image_status": "ready",
            "image_chosen_idx": 0,
            "image_chosen_at": iso(NOW - timedelta(minutes=100)),
            "image_candidates": [],
        }

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump({"_default": table}, f, indent=2, ensure_ascii=False)
    print(f"Seeded {len(table)} voters into {DB_PATH}")

    if state_arg:
        OPTS["voting_state"] = state_arg
        with open(OPTS_PATH, "w", encoding="utf-8") as f:
            json.dump(OPTS, f, indent=4, ensure_ascii=False)
        print(f"voting_state -> {state_arg}")

    # Report the resulting leaderboard + award winners as a sanity check.
    from pizzavision.vote_store import TinyDBVoteStore
    from pizzavision.utils import calculate_awards, calculate_ranked_choice

    store = TinyDBVoteStore(DB_PATH)
    votes = [r["rank"] for r in store.all() if r.get("rank")]
    ranked, _ = calculate_ranked_choice(votes, OPTS["votes"])
    print("\n--- Leaderboard top 5 ---")
    for label, pts in ranked[:5]:
        print(f"  {pts:>4}  {label}")

    awards = calculate_awards(store, OPTS)
    print(f"\n--- {len(awards)} awards crowned ---")
    for code in ("Juggler", "Commitment Issues", "Flip Flop", "Markie Likey",
                 "Tastemaker", "Contrarian", "Twinzies"):
        a = next((x for x in awards if x["code"] == code), None)
        print(f"  {code}: {a['winner'] if a else '<none>'}")


if __name__ == "__main__":
    main()
