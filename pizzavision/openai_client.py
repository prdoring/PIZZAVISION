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


SYSTEM_PROMPT = """You name fictional Eurovision Song Contest acts. The user is inventing an act and has told you about their song. Your job: name the ACT (solo artist, duo, or group) that would actually perform that song on the Eurovision stage.

STUDY REAL EUROVISION ARTIST NAMES (these are the energy):
Loreen, Måneskin, Käärijä, Conchita Wurst, ABBA, Hatari, Subwoolfer, Go_A, Daði og Gagnamagnið, Salvador Sobral, Sennek, Eleni Foureira, Marco Mengoni, Mahmood, Duncan Laurence, Netta, Lordi, Alexander Rybak, Barbara Pravi, Kalush Orchestra, Rosa Linn, Tix, The Roop, We Are Domi, Sam Ryder, Olly Alexander, Bambie Thug, Slimane, Nemo, Baby Lasagna, Joost Klein.

Notice the patterns:
- Many are SHORT — 1-2 words, often a mononym or stage name.
- Many are NOT IN ENGLISH or use non-English spellings (Käärijä, Måneskin, Slimane, Baby Lasagna).
- They feel like REAL ARTISTS — not stereotypes, not adjective-stacks.

HARD BANS (the model defaults to these — DO NOT):
- No "Sparkle X", "Glitter X", "Disco X", "Diva X", "Rainbow X".
- No "X & the Sparkles", "The Glitter Goblins", "Unicorn Y", "Fabulous Z".
- No two-adjective-noun formulas like "Velvet Disco Chickens" or "Cosmic Sequined Wolves".
- No "DJ X", no "Lil Y", no English-suburban-indie names.

Output EXACTLY 3 names. Each must feel like a REAL person/group who'd actually compete at Eurovision. Vary them:
- One mononym or single-name stage name (like Loreen, Slimane, Nemo).
- One duo or group name (like Subwoolfer, We Are Domi, The Roop).
- One that takes more risk — non-English, theatrical, or oblique (like Daði og Gagnamagnið, Käärijä, Baby Lasagna).

Anchor each name in the user's SONG TITLE and SONG VIBE. The act should sound like the artist who'd actually release that song.

Use accents and non-English letters where they fit (ö, å, æ, é, ž, ñ, ø, ł). Lean into Italian, Swedish, French, Spanish, Icelandic, Ukrainian, Greek where the vibe calls for it.

Output strict JSON only: {"names": ["...", "...", "..."]}
Each name 2–35 characters. No quotes inside names, no markdown, no commentary."""


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
        if not (2 <= len(s) <= 35):
            raise ValueError(f"name out of length bounds: {s!r}")
        cleaned.append(s)

    return cleaned


# ---------------------------------------------------------------
# Single-field suggestion ("Surprise me" dice button per question)
# ---------------------------------------------------------------

_FIELD_PROMPTS = {
    "song_title": (
        "Suggest ONE Eurovision song title. PUNCHY. 1–3 words. MAX 25 characters.\n\n"
        "Study real Eurovision titles for the energy: \"Cha Cha Cha\", \"Tattoo\", \"Soldi\", "
        "\"Zitti e buoni\", \"Stefania\", \"Snap\", \"Voilà\", \"Arcade\", \"Euphoria\", "
        "\"Fairytale\", \"Toy\", \"El Diablo\", \"Discoteque\", \"Shum\", \"Hatrið mun sigra\", "
        "\"Bara bada bastu\", \"Heroes\", \"Rim Tim Tagi Dim\", \"Mama ŠČ!\".\n\n"
        "Patterns:\n"
        "- Often NOT in English — Italian, Spanish, French, Swedish, Finnish, Icelandic, "
        "Ukrainian, Greek, Albanian. Use real words from those languages.\n"
        "- Short. 1–2 words is common. 3 max.\n"
        "- Emotional, cryptic, or oblique. Not cute.\n\n"
        "HARD BANS: no sparkle, no glitter, no unicorn, no rainbow, no disco-X, no diva, "
        "no fabulous, no sequin, no \"Tears in X\". Avoid the camp stereotype.\n\n"
        "Output ONLY the title. No quotes. Under 25 characters."
    ),
    "song_vibe": (
        "Describe a Eurovision song's vibe in ONE short sentence. MAX 110 characters.\n\n"
        "Lead with genre, instrument, or emotional beat — not adjective stacks. Be specific.\n\n"
        "Examples:\n"
        "- \"Slow-burn breakup ballad with a string section that explodes at minute 3.\"\n"
        "- \"Hyperpop revenge anthem sung in Lithuanian.\"\n"
        "- \"Italian opera-rap with a flamenco bridge.\"\n"
        "- \"Sad accordion folk that detonates into industrial techno.\"\n\n"
        "Avoid: \"glitter\", \"sparkle\", \"sequins\", \"rainbow\", \"unicorn\", "
        "\"electrifying\", \"pulsating\", \"foot-tapping\".\n\n"
        "Output ONLY the description. No quotes. Under 110 characters."
    ),
    "personal_vibe": (
        "Describe a Eurovision lead performer's stage presence in ONE short sentence. MAX 90 characters.\n\n"
        "Be specific and physical — a costume, an entrance, a movement.\n\n"
        "Examples:\n"
        "- \"Backlit silhouette in a tracksuit, screaming gently.\"\n"
        "- \"Sequined matador on a smoke-filled rotating platform.\"\n"
        "- \"Crying into a violin atop a wind machine.\"\n"
        "- \"Three identical sisters in red veils, never blinking.\"\n\n"
        "Avoid: \"sparkly diva\", \"glittery goddess\", \"fabulous queen\". "
        "Avoid cliché Eurovision-camp stereotypes.\n\n"
        "Output ONLY the description. No quotes. Under 90 characters."
    ),
    "extra": (
        "Suggest ONE fun production detail for a Eurovision act in ONE short sentence. MAX 110 characters.\n\n"
        "Backup dancers, country quirk, costume change, pyro plan, lyric Easter egg — pick one and commit.\n\n"
        "Examples:\n"
        "- \"Three backup dancers dressed as her cats from real life.\"\n"
        "- \"Sung partly in Estonian, with subtitles that lie.\"\n"
        "- \"Wind machine activated only on the second chorus.\"\n"
        "- \"Final note held while a single tear falls (real).\"\n\n"
        "Output ONLY the suggestion. No quotes. Under 110 characters."
    ),
}

_FIELD_MAXLEN = {
    "song_title": 35,
    "song_vibe": 130,
    "personal_vibe": 105,
    "extra": 130,
}


def _truncate_clean(text: str, max_len: int) -> str:
    """Truncate to max_len, prefer breaking on a word boundary."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    if last_space >= int(max_len * 0.6):
        cut = cut[:last_space]
    return cut.rstrip(" ,.;:-")


def suggest_answer(field: str, context: dict, anchor: str = "") -> str:
    """Generate a single field-appropriate suggestion.

    - `context` is the OTHER onboarding answers (caller should exclude the
      field being rolled). Used for cross-field coherence.
    - `anchor` is the user's current text in this field IF the user typed or
      modified it themselves. Empty string means "fresh seed" (user hit the
      dice on an untouched AI suggestion or an empty field).

    Raises on missing key, validation failure, or API error.
    """
    if field not in _FIELD_PROMPTS:
        raise ValueError(f"unknown field: {field!r}")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

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
        "Other answers from this user (stay coherent with these):\n"
        + "\n".join(context_lines)
        if context_lines
        else "The user hasn't answered the other questions yet — be self-contained."
    )

    anchor = (anchor or "").strip()
    if anchor:
        anchor_block = (
            f"The user has typed this in the field and wants a fresh variant in the same "
            f"DIRECTION:\n  \"{anchor}\"\n\n"
            f"Produce something that feels related — same energy, same general idea — but "
            f"distinct wording. Do NOT just reword it. Sibling, not synonym."
        )
    else:
        anchor_block = (
            "The user wants a surprise — completely fresh idea. Don't echo any pattern "
            "from your previous answers in this session."
        )

    system = _FIELD_PROMPTS[field]
    user_msg = f"{context_block}\n\n{anchor_block}\n\nNow give me ONE suggestion."

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )

    text = (resp.choices[0].message.content or "").strip()
    text = text.strip('"').strip("'").strip("*").strip("_").strip()
    text = " ".join(text.split())  # collapse internal whitespace/newlines

    if not text:
        raise ValueError("empty suggestion")

    return _truncate_clean(text, _FIELD_MAXLEN[field])
