"""OpenAI wrapper for generating Eurovision-style band/artist names.

The prompt is tuned to produce names that actually feel like a Eurovision
entry — mononyms, accented stage names, kitschy groups — rather than random
adjective/noun salad. Names are rooted in the user's onboarding answers.

Raises on any failure (missing key, timeout, malformed JSON, validation).
Callers should treat any exception as "fall back to the local generator".
"""

from __future__ import annotations

import json
import os


SYSTEM_PROMPT = """You name fictional Eurovision Song Contest acts. The user is inventing an act: they've told you the name of their Eurovision song, the song's vibe, their own performer vibe, and any extra flavor. Your job is to name the ACT (solo artist, duo, or group) that would actually perform that song on the Eurovision stage.

Real Eurovision name shapes to draw from:
- Solo mononyms: "Loreen", "Käärijä", "Conchita", "Måneskin", "Duncan", "Salvador".
- First-name stage names: "Eleni Foureira", "Marco Mengoni", "Sam Ryder".
- Groups: "ABBA", "Daði og Gagnamagnið", "Hatari", "Subwoolfer", "The Roop", "Go_A", "We Are Domi", "Sennek".
- Collabs: "Mahmood feat. Blanco", "Marco & Friends".

Output EXACTLY 3 names. Each must FEEL like a real Eurovision entry — pronounceable, performative, theatrical, glam, kitschy, or earnestly dramatic. Match the genre/energy of the user's song. Lean into Europop, schlager, hyperpop, power-ballad, or weird-art-pop where it fits. Use accents and non-English letters when it adds flair (ö, å, æ, é, ž, ñ).

Root every name in the user's answers. The SONG TITLE and the SONG VIBE are the strongest anchors — the act's name should feel like the artist who would actually release that song. The performer's personal vibe shapes presence and aesthetic. The "anything else" line is bonus flavor — use it if it sparks something, ignore if blank.

Vary the three names so the user has a real choice:
- One that leans solo/mononym.
- One that leans group/duo.
- One that goes weirder or more theatrical than the others.

Be CREATIVE and have FUN. Avoid: corporate-sounding names, generic "DJ X" formats, English-only suburban indie-band names, anything boring. Each name should make someone smile.

Output strict JSON only: {"names": ["...", "...", "..."]}
Each name 2–40 characters. No quotes inside names, no markdown, no commentary."""


def generate_band_names(
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> list[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

    user_prompt = (
        f"Song title: {song_title}\n"
        f"Song vibe: {song_vibe}\n"
        f"Performer's personal vibe: {personal_vibe}\n"
        f"Anything else: {extra or '(none)'}"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = resp.choices[0].message.content or ""
    data = json.loads(raw)
    names = data.get("names")

    if not isinstance(names, list) or len(names) != 3:
        raise ValueError(f"expected 3 names, got: {names!r}")

    cleaned: list[str] = []
    for n in names:
        if not isinstance(n, str):
            raise ValueError(f"non-string name: {n!r}")
        s = n.strip().strip('"').strip("'")
        if not (2 <= len(s) <= 40):
            raise ValueError(f"name out of length bounds: {s!r}")
        cleaned.append(s)

    return cleaned


# ---------------------------------------------------------------
# Single-field suggestion ("Surprise me" dice button per question)
# ---------------------------------------------------------------

_FIELD_PROMPTS = {
    "song_title": (
        "Suggest ONE Eurovision song title — kitschy, theatrical, pure Eurovision. "
        "2–6 words. Examples: 'Tears in My Tracksuit', 'Volcano Soup', "
        "'My Heart Is a Disco Ball', 'Glitter Goblin', 'Daddy's a Werewolf'. "
        "Output ONLY the title — no quotes, no extra commentary, no markdown."
    ),
    "song_vibe": (
        "Describe a Eurovision song's vibe in 1–2 sentences — genre, energy, key emotional beat. "
        "Lean into Eurovision tropes (power ballad, schlager, hyperpop, drama, key change at minute 3). "
        "Output ONLY the description."
    ),
    "personal_vibe": (
        "Describe a Eurovision lead performer's stage vibe in 1–2 sentences — costume, entrance, energy. "
        "Theatrical and specific. Example: 'Sequined goblin in a smoke-filled birdcage, screaming softly'. "
        "Output ONLY the description."
    ),
    "extra": (
        "Suggest ONE fun extra detail for a Eurovision act — backup dancers, country of origin, "
        "hidden meaning, pyro plan, costume change. One short sentence. "
        "Output ONLY the suggestion."
    ),
}

_FIELD_MAXLEN = {
    "song_title": 80,
    "song_vibe": 240,
    "personal_vibe": 120,
    "extra": 240,
}


def suggest_answer(field: str, context: dict) -> str:
    """Generate a single field-appropriate suggestion. `context` is the other
    onboarding answers so far (any filled keys are passed to the model for
    coherence). Raises on missing key, validation failure, or API error.
    """
    if field not in _FIELD_PROMPTS:
        raise ValueError(f"unknown field: {field!r}")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

    # Build a context block from any filled-in fields the user has so far.
    labels = {
        "song_title": "Song title",
        "song_vibe": "Song vibe",
        "personal_vibe": "Performer's personal vibe",
        "extra": "Extra flavor",
    }
    context_lines = []
    for k, label in labels.items():
        if k == field:
            continue
        v = (context or {}).get(k, "")
        if isinstance(v, str) and v.strip():
            context_lines.append(f"- {label}: {v.strip()}")
    context_block = (
        "Existing answers from this user (stay coherent with these):\n"
        + "\n".join(context_lines)
        if context_lines
        else "No other answers yet."
    )

    system = _FIELD_PROMPTS[field]
    user_msg = f"{context_block}\n\nNow give me ONE fresh suggestion."

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )

    text = (resp.choices[0].message.content or "").strip()
    # Strip wrapping quotes/markdown the model sometimes adds.
    text = text.strip('"').strip("'").strip("*").strip("_").strip()
    # Collapse internal newlines.
    text = " ".join(text.split())

    if not text:
        raise ValueError("empty suggestion")

    max_len = _FIELD_MAXLEN[field]
    if len(text) > max_len:
        text = text[:max_len].rstrip()

    return text
