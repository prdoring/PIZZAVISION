"""Dev tool for iterating on the roast prompts in pizzavision/openai_client.py.

Runs roast_user_votes and roast_band against a curated set of test inputs,
generating multiple samples per case so variation shows. Lets us read
outputs in bulk and tune the system prompts.

Usage:
    python roast_harness.py             # both, 3 samples each
    python roast_harness.py vote
    python roast_harness.py band
    python roast_harness.py vote 5      # 5 samples per case
"""

from __future__ import annotations

import os
import sys
import time
import traceback

# Pull OPENAI_API_KEY out of .env before importing the client.
from dotenv import load_dotenv
load_dotenv()

# Bypass pizzavision/__init__.py (Flask + Firestore setup at import time)
# by importing openai_client.py directly off its directory.
_PKG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pizzavision")
sys.path.insert(0, _PKG_DIR)
import openai_client  # type: ignore

# Windows console — make sure umlauts/accents print cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


# ---------------------------------------------------------------------------
# VOTE-ROAST test cases
# ---------------------------------------------------------------------------
# Each case stresses a specific joke vector. Ballots reference REAL labels +
# real meta dicts from pizzavision/options.json so the model has accurate
# metadata to chew on.

# Real meta from options.json, indexed by label for terseness.
META = {
    "Denmark: Før vi går hjem":       {"genre":"pop",        "lead":"M","language":"native", "region":"Nordic",           "act_type":"solo", "selection_type":"national_final", "drink":"beer"},
    "Germany: Fire":                  {"genre":"pop",        "lead":"F","language":"english","region":"Central European", "act_type":"solo", "selection_type":"national_final", "drink":"beer",      "big5":True},
    "Israel: Michelle":               {"genre":"pop",        "lead":"M","language":"english","region":"Mediterranean",    "act_type":"solo", "selection_type":"national_final", "drink":"red wine"},
    "Belgium: Dancing on the Ice":    {"genre":"electronic", "lead":"F","language":"english","region":"Western European", "act_type":"solo", "selection_type":"internal",       "drink":"beer"},
    "Albania: Nân":                   {"genre":"ballad",     "lead":"M","language":"native", "region":"Balkan",           "act_type":"solo", "selection_type":"national_final", "drink":"red wine"},
    "Greece: Ferto":                  {"genre":"pop",        "lead":"M","language":"native", "region":"Balkan",           "act_type":"solo", "selection_type":"national_final", "drink":"white wine"},
    "Ukraine: Ridnym":                {"genre":"pop",        "lead":"F","language":"native", "region":"Eastern European", "act_type":"solo", "selection_type":"national_final", "drink":"white wine", "former_soviet":True},
    "Australia: Eclipse":             {"genre":"ballad",     "lead":"F","language":"english","region":"Other",            "act_type":"solo", "selection_type":"internal",       "drink":"beer"},
    "Serbia: Kraj mene":              {"genre":"rock",       "lead":"M","language":"native", "region":"Balkan",           "act_type":"group","selection_type":"national_final", "drink":"red wine"},
    "Malta: Bella":                   {"genre":"ballad",     "lead":"M","language":"english","region":"Mediterranean",    "act_type":"solo", "selection_type":"national_final", "drink":"white wine"},
    "Czechia: Crossroads":            {"genre":"ballad",     "lead":"M","language":"english","region":"Central European", "act_type":"solo", "selection_type":"internal",       "drink":"beer"},
    "Bulgaria: Bangaranga":           {"genre":"electronic", "lead":"F","language":"english","region":"Balkan",           "act_type":"solo", "selection_type":"national_final", "drink":"beer"},
    "Croatia: Andromeda":             {"genre":"folk",       "lead":"F","language":"native", "region":"Balkan",           "act_type":"group","selection_type":"national_final", "drink":"white wine"},
    "United Kingdom: Eins, Zwei, Drei":{"genre":"electronic","lead":"M","language":"english","region":"British Isles",    "act_type":"solo", "selection_type":"internal",       "drink":"beer",      "big5":True},
    "France: Regarde !":              {"genre":"ballad",     "lead":"F","language":"native", "region":"Mediterranean",    "act_type":"solo", "selection_type":"internal",       "drink":"red wine",  "big5":True},
    "Moldova: Viva, Moldova":         {"genre":"pop",        "lead":"M","language":"native", "region":"Eastern European", "act_type":"solo", "selection_type":"national_final", "drink":"red wine",  "former_soviet":True},
    "Finland: Liekinheitin":          {"genre":"rock",       "lead":"M","language":"native", "region":"Nordic",           "act_type":"duo",  "selection_type":"national_final", "drink":"beer"},
    "Poland: Pray":                   {"genre":"pop",        "lead":"F","language":"english","region":"Central European", "act_type":"solo", "selection_type":"national_final", "drink":"beer",      "returning_artist":True},
    "Lithuania: Sólo quiero más":     {"genre":"pop",        "lead":"M","language":"native", "region":"Baltic",           "act_type":"solo", "selection_type":"national_final", "drink":"beer",      "former_soviet":True},
    "Sweden: My System":              {"genre":"electronic", "lead":"F","language":"english","region":"Nordic",           "act_type":"solo", "selection_type":"national_final", "drink":"beer"},
    "Cyprus: Jalla":                  {"genre":"pop",        "lead":"F","language":"english","region":"Mediterranean",    "act_type":"solo", "selection_type":"internal",       "drink":"red wine"},
    "Italy: Per sempre sì":           {"genre":"pop",        "lead":"M","language":"native", "region":"Mediterranean",    "act_type":"solo", "selection_type":"national_final", "drink":"red wine",  "big5":True},
    "Norway: Ya ya ya":               {"genre":"pop",        "lead":"M","language":"english","region":"Nordic",           "act_type":"solo", "selection_type":"national_final", "drink":"beer"},
    "Romania: Choke Me":              {"genre":"rock",       "lead":"F","language":"english","region":"Eastern European", "act_type":"solo", "selection_type":"national_final", "drink":"beer"},
    "Austria: Tanzschein":            {"genre":"electronic", "lead":"M","language":"native", "region":"Central European", "act_type":"solo", "selection_type":"national_final", "drink":"white wine"},
}


def _ballot(*labels):
    """Build picks_with_meta from a top-to-bottom list of labels."""
    out = []
    for lbl in labels:
        meta = dict(META[lbl])
        meta["label"] = lbl
        out.append(meta)
    return out


VOTE_CASES = [
    # 1. Identity-vs-ballot collision: brooding industrial duo gives 12
    #    to glitter pop, 1pt to the actual rock/duo entry that matches
    #    their own stated identity.
    {
        "label": "IDENTITY COLLISION: brooding industrial voter goes full glitter",
        "voter": "Söft Riøt",
        "own_act": {
            "song_title": "Static Cathedral",
            "song_vibe": "ten-minute industrial dirge with a single repeated word",
            "personal_vibe": "we don't smile on stage, we don't smile off stage",
            "extra": "the encore is one of us standing motionless for 90 seconds",
        },
        "ballot": _ballot(
            "Cyprus: Jalla",                # 12 — F pop english glitter
            "Malta: Bella",                 # 10 — ballad
            "Belgium: Dancing on the Ice",  # 9
            "Norway: Ya ya ya",             # 8
            "Sweden: My System",            # 7
            "Australia: Eclipse",           # 6
            "Israel: Michelle",             # 5
            "Bulgaria: Bangaranga",         # 4
            "Poland: Pray",                 # 3
            "Ukraine: Ridnym",              # 2
            "Finland: Liekinheitin",        # 1 — the only rock/native/duo, ie what they ARE
        ),
    },

    # 2. Bloc-perfect Balkan, deliberately ignores all Big 5.
    {
        "label": "BLOC LOYALTY: Balkan-perfect, Big 5 nowhere",
        "voter": "Glâss Ouija",
        "own_act": {
            "song_title": "Pale Vow",
            "song_vibe": "ethereal goth-folk about a sister who exists only in dreams",
            "personal_vibe": "I dress like a Macedonian widow at all times",
            "extra": "the bridge is sung entirely in glossolalia",
        },
        "ballot": _ballot(
            "Albania: Nân",         # 12
            "Greece: Ferto",        # 10
            "Serbia: Kraj mene",    # 9
            "Croatia: Andromeda",   # 8
            "Bulgaria: Bangaranga", # 7
            "Romania: Choke Me",    # 6
            "Moldova: Viva, Moldova", # 5
            "Ukraine: Ridnym",      # 4
            "Lithuania: Sólo quiero más", # 3
            "Austria: Tanzschein",  # 2
            "Germany: Fire",        # 1 — the one Big 5 grudgingly at the bottom
        ),
    },

    # 3. Native-language purist whose own onboarding is all English.
    {
        "label": "AUTHENTICITY HYPOCRISY: native-language-only ballot, English-only onboarding",
        "voter": "Maple Knife",
        "own_act": {
            "song_title": "Heart Berry",
            "song_vibe": "uplifting pop banger about resilience",
            "personal_vibe": "soft girl with a microphone and a message",
            "extra": "the second chorus drops into French for no reason",
        },
        "ballot": _ballot(
            "Albania: Nân",            # 12 — native
            "Greece: Ferto",           # 10 — native
            "France: Regarde !",       # 9 — native
            "Italy: Per sempre sì",    # 8 — native
            "Croatia: Andromeda",      # 7 — native
            "Ukraine: Ridnym",         # 6 — native
            "Moldova: Viva, Moldova",  # 5 — native
            "Denmark: Før vi går hjem",# 4 — native
            "Austria: Tanzschein",     # 3 — native
            "Finland: Liekinheitin",   # 2 — native
            "Germany: Fire",           # 1 — english, lowest
        ),
    },

    # 4. Tonal monoculture: every pick is a male-fronted ballad/midtempo.
    {
        "label": "TONAL MONOCROP: every pick is male-fronted, mostly ballads",
        "voter": "Bourgeois Klein",
        "own_act": {
            "song_title": "Ascension",
            "song_vibe": "I want this song to make grown men cry",
            "personal_vibe": "wears a single tear of mascara at the final note",
            "extra": "no choreography, just suffering",
        },
        "ballot": _ballot(
            "Albania: Nân",           # 12 — ballad M
            "Malta: Bella",           # 10 — ballad M
            "Czechia: Crossroads",    # 9 — ballad M
            "Italy: Per sempre sì",   # 8 — pop M
            "Israel: Michelle",       # 7 — pop M
            "Greece: Ferto",          # 6 — pop M
            "Lithuania: Sólo quiero más", # 5 — pop M
            "Norway: Ya ya ya",       # 4 — pop M
            "Denmark: Før vi går hjem", # 3 — pop M
            "Moldova: Viva, Moldova", # 2 — pop M
            "Cyprus: Jalla",          # 1 — F pop, the lone female down at the bottom
        ),
    },

    # 5. All-Big-5 top of ballot — the most basic, snobbiest possible vote.
    {
        "label": "BIG-5 STAN: all Big 5 at the top, everyone else punished",
        "voter": "Royale With Cheese",
        "own_act": {
            "song_title": "Continental Drift",
            "song_vibe": "high-concept pop with a key change you can see from space",
            "personal_vibe": "I studied at the Royal College and I will mention it",
            "extra": "wears bespoke linen at all times",
        },
        "ballot": _ballot(
            "Germany: Fire",                  # 12 — Big 5
            "France: Regarde !",              # 10 — Big 5
            "Italy: Per sempre sì",           # 9 — Big 5
            "United Kingdom: Eins, Zwei, Drei", # 8 — Big 5
            "Sweden: My System",              # 7 — semi-Big-5 darling
            "Norway: Ya ya ya",               # 6
            "Denmark: Før vi går hjem",       # 5
            "Australia: Eclipse",             # 4
            "Belgium: Dancing on the Ice",    # 3
            "Israel: Michelle",               # 2
            "Albania: Nân",                   # 1 — Balkan ballad, an afterthought
        ),
    },

    # 6. Spectator with no own-act details — identity-vs-ballot block is empty.
    {
        "label": "SPECTATOR: no onboarding, ballot only",
        "voter": "Anonymous Bidder",
        "own_act": {"song_title":"","song_vibe":"","personal_vibe":"","extra":""},
        "ballot": _ballot(
            "Finland: Liekinheitin",  # 12 — rock duo native
            "Romania: Choke Me",      # 10
            "Serbia: Kraj mene",      # 9
            "Bulgaria: Bangaranga",   # 8
            "Sweden: My System",      # 7
            "Belgium: Dancing on the Ice", # 6
            "Austria: Tanzschein",    # 5
            "Croatia: Andromeda",     # 4
            "Cyprus: Jalla",          # 3
            "Norway: Ya ya ya",       # 2
            "Greece: Ferto",          # 1
        ),
    },
]


# ---------------------------------------------------------------------------
# BAND-ROAST test cases — fictional acts that stress different joke vectors.
# ---------------------------------------------------------------------------

BAND_CASES = [
    # 1. Earnest pretentious — the gap to mine is "I think I'm deep" vs
    #    "this is a Eurovision party song"
    {
        "label": "EARNEST PRETENTIOUS",
        "band_name": "Velour Reverie",
        "song_title": "Cathedral of Glass",
        "song_vibe": "an extended elegy for a sister I never had",
        "personal_vibe": "I haunt the audience more than I perform",
        "extra": "the lighting dims in seven movements",
    },

    # 2. Absurd novelty — every field is a setup-payoff.
    {
        "label": "ABSURD NOVELTY",
        "band_name": "Beige Inferno",
        "song_title": "Hot Lasagne",
        "song_vibe": "Italian disco about kitchen appliances",
        "personal_vibe": "I'm an accountant by day and Eurovision is my therapy",
        "extra": "every chorus features me banging a saucepan in time",
    },

    # 3. Field contradiction — claimed minimalism, described maximalism.
    {
        "label": "FIELD CONTRADICTION (claim vs reality)",
        "band_name": "Mörgan",
        "song_title": "Minimalism",
        "song_vibe": "I just want one piano and one regret",
        "personal_vibe": "eight backup dancers, full choir, three costume changes, pyrotechnics every chorus",
        "extra": "performed entirely inside a wind machine",
    },

    # 4. Sincere boring — almost nothing to grab onto, model has to find it.
    {
        "label": "SINCERE BORING (no obvious hook)",
        "band_name": "Sunny",
        "song_title": "Run Away",
        "song_vibe": "happy pop song",
        "personal_vibe": "bubbly",
        "extra": "",
    },

    # 5. Hyper-specific weird premise.
    {
        "label": "HYPER-SPECIFIC PREMISE",
        "band_name": "Petros & The Inevitable",
        "song_title": "Tax Quarter",
        "song_vibe": "techno-priest who only sings about Greek mortgage rates",
        "personal_vibe": "I wear a chasuble made of stitched-together mortgage statements",
        "extra": "the bridge is a Gregorian chant of current EURIBOR figures",
    },

    # 6. Aggressive overclaim — main-character syndrome.
    {
        "label": "OVERCLAIM (main character energy)",
        "band_name": "VICTORÍA",
        "song_title": "TONIGHT",
        "song_vibe": "the song that will heal Europe and unify a divided continent",
        "personal_vibe": "I am the chosen one and I will not be denied",
        "extra": "I plan to win all 26 juries with a single tear that falls at exactly 2:47",
    },
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _print_header(title):
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")

def _print_case_header(idx, total, label):
    print(f"\n--- [{idx}/{total}] {label} ---")

def _run_vote_case(case, samples):
    print(f"  voter: {case['voter']}")
    own = case["own_act"]
    if any(own.values()):
        for k, v in own.items():
            if v: print(f"    own.{k}: {v}")
    else:
        print("    own act: (none — spectator)")
    print(f"  top:    {case['ballot'][0]['label']}")
    print(f"  bottom: {case['ballot'][-1]['label']}")
    for i in range(1, samples + 1):
        t0 = time.time()
        try:
            out = openai_client.roast_user_votes(
                case["voter"],
                case["ballot"],
                song_title=own.get("song_title",""),
                song_vibe=own.get("song_vibe",""),
                personal_vibe=own.get("personal_vibe",""),
                extra=own.get("extra",""),
            )
            dt = time.time() - t0
            print(f"  [{i}] ({dt:.1f}s, {len(out)} chars) {out}")
        except Exception as e:
            print(f"  [{i}] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()

def _run_band_case(case, samples):
    print(f"  band:  {case['band_name']}")
    print(f"  song:  {case['song_title']}")
    print(f"  vibe:  {case['song_vibe']}")
    print(f"  pers:  {case['personal_vibe']}")
    print(f"  extra: {case['extra']}")
    for i in range(1, samples + 1):
        t0 = time.time()
        try:
            out = openai_client.roast_band(
                case["band_name"],
                case["song_title"],
                case["song_vibe"],
                case["personal_vibe"],
                case["extra"],
            )
            dt = time.time() - t0
            print(f"  [{i}] ({dt:.1f}s, {len(out)} chars) {out}")
        except Exception as e:
            print(f"  [{i}] ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()

def run_vote(samples):
    _print_header(f"VOTE ROAST — {len(VOTE_CASES)} cases × {samples} samples")
    for i, case in enumerate(VOTE_CASES, 1):
        _print_case_header(i, len(VOTE_CASES), case["label"])
        _run_vote_case(case, samples)

def run_band(samples):
    _print_header(f"BAND ROAST — {len(BAND_CASES)} cases × {samples} samples")
    for i, case in enumerate(BAND_CASES, 1):
        _print_case_header(i, len(BAND_CASES), case["label"])
        _run_band_case(case, samples)


def main(argv):
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set (and .env didn't supply it)", file=sys.stderr)
        return 1

    mode = argv[1] if len(argv) > 1 else "all"
    samples = int(argv[2]) if len(argv) > 2 else 3

    t0 = time.time()
    if mode in ("vote", "all"):
        run_vote(samples)
    if mode in ("band", "all"):
        run_band(samples)
    print(f"\n[done in {time.time() - t0:.1f}s]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
