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
import secrets


_FINALISTS_PATH = os.path.join(os.path.dirname(__file__), "options.json")


def _load_finalists() -> list[dict]:
    """Load the current year's finalist entries from options.json.

    Returns an empty list on any failure — callers treat that as "no fresh
    examples available" and fall back to the static prompt examples.
    """
    try:
        with open(_FINALISTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        opts = data.get("options")
        return [o for o in opts if isinstance(o, dict)] if isinstance(opts, list) else []
    except Exception:
        return []


def _random_finalist_block(n: int = 6) -> str:
    """Format N random finalist entries as a compact example block.

    Each line is "Country: Title — region / genre / language" so the model
    sees both the *naming style* and the *vibe range* of real entries this
    year. The randomness counters the model's tendency to default to a few
    favourite archetypes (Balkan ballads, Nordic pop) every call.
    """
    finalists = _load_finalists()
    if not finalists:
        return ""
    rng = secrets.SystemRandom()
    sample = rng.sample(finalists, min(n, len(finalists)))
    lines = []
    for f in sample:
        label = (f.get("label") or "").strip()
        if not label:
            continue
        bits = []
        if f.get("region"):
            bits.append(str(f["region"]))
        if f.get("genre"):
            bits.append(str(f["genre"]))
        if f.get("language"):
            bits.append(f'{f["language"]} lyrics')
        meta = " / ".join(bits)
        lines.append(f"- {label}" + (f" — {meta}" if meta else ""))
    return "\n".join(lines)


SYSTEM_PROMPT = """You name fictional Eurovision Song Contest acts for a WATCH PARTY. The user is inventing an act for a fun night with friends — names should feel like real Eurovision entries but also make the room laugh when announced. Lean PLAYFUL. This is a party, not a record label meeting.

STUDY REAL EUROVISION ARTIST NAMES (these are the energy):
Loreen, Måneskin, Käärijä, Conchita Wurst, ABBA, Hatari, Subwoolfer, Go_A, Daði og Gagnamagnið, Salvador Sobral, Sennek, Eleni Foureira, Marco Mengoni, Mahmood, Duncan Laurence, Netta, Lordi, Alexander Rybak, Barbara Pravi, Kalush Orchestra, Rosa Linn, Tix, The Roop, We Are Domi, Sam Ryder, Olly Alexander, Bambie Thug, Slimane, Nemo, Baby Lasagna, Joost Klein, Let 3, Windows95man, Marcus & Martinus, Cornelia Jakobs, Silia Kapsis, Teya & Salena, Mae Muller, Blanca Paloma.

Notice the patterns:
- Many are SHORT — 1-2 words, often a mononym or stage name.
- Many are PLAYFUL, ABSURD, or memorable on the lyric sheet — Baby Lasagna, Subwoolfer, Windows95man, Let 3, Joost Klein, Lordi.
- Mix of languages — English AND non-English. Neither dominates.
- They feel like REAL ARTISTS — not stereotypes, not adjective-stacks.

HARD BANS (the model defaults to these — DO NOT):
- No "Sparkle X", "Glitter X", "Disco X", "Diva X", "Rainbow X".
- No "X & the Sparkles", "The Glitter Goblins", "Unicorn Y", "Fabulous Z".
- No two-adjective-noun formulas like "Velvet Disco Chickens" or "Cosmic Sequined Wolves".
- No "DJ X", no "Lil Y", no English-suburban-indie names.

Output EXACTLY 3 names. Vary them across THREE axes — language, format, and tone:

LANGUAGE MIX (do not stack three foreign names — at least ONE must be readable/sayable in English):
- Roughly: one English or English-readable, one with non-English flair (accents, foreign word), one wildcard.
- Use accents where they fit (ö, å, æ, é, ž, ñ, ø, ł) but don't force every name into another language.
- Occasionally sprinkle a gratuitous accent onto an otherwise English word (Mëtal, Söft Boi, Yäs) — this is a real Eurovision tic and it's funny. Don't do it on every name, and don't pile multiple accents into one word. One stray umlaut max.

FORMAT MIX:
- One mononym or single-name stage name (like Loreen, Slimane, Nemo).
- One duo or group name (like Subwoolfer, We Are Domi, The Roop, Teya & Salena).
- One wildcard that takes a risk — absurd noun, theatrical, or oblique (like Baby Lasagna, Windows95man, Let 3, Lordi, Daði og Gagnamagnið).

TONE: at least ONE of the three should be genuinely FUN — a name that gets a laugh or a "wait what" when the host reads it out. Think Baby Lasagna, Subwoolfer, Windows95man. Cheeky food references, weirdly specific objects, deadpan-absurd nouns, alliterative gags — all fair game. Just don't tip into the banned camp stereotypes above.

Anchor each name in the user's SONG TITLE and SONG VIBE. The act should sound like the artist who'd actually release that song — but a party crowd should also enjoy hearing the name.

Output strict JSON only: {"names": ["...", "...", "..."]}
Each name 2–35 characters. No quotes inside names, no markdown, no commentary."""


def generate_band_names(
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
    avoid: list[str] | None = None,
) -> list[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

    # Random nonce to perturb output. Two party-goers with near-identical
    # onboarding answers would otherwise tend to converge on the same names;
    # a fresh seed per call breaks the tie. Has no semantic meaning — the
    # model just uses it as entropy.
    variation_seed = secrets.token_hex(4)

    user_prompt = (
        f"Song title: {song_title}\n"
        f"Song vibe: {song_vibe}\n"
        f"Performer's personal vibe: {personal_vibe}\n"
        f"Anything else: {extra or '(none)'}\n"
        f"Variation seed (ignore for meaning, use only to diverge from prior runs): {variation_seed}"
    )

    finalist_block = _random_finalist_block(6)
    if finalist_block:
        user_prompt += (
            "\n\nFor regional and stylistic RANGE this turn, here are a random "
            "sample of actual finalists from this year's contest — DO NOT name "
            "the act after any of them, just let their spread of regions, "
            "genres, and languages broaden your imagination beyond your default "
            "Eurovision archetypes:\n"
            f"{finalist_block}"
        )

    avoid_clean = [a.strip() for a in (avoid or []) if isinstance(a, str) and a.strip()]
    if avoid_clean:
        avoid_str = ", ".join(f'"{a}"' for a in avoid_clean)
        user_prompt += (
            "\n\nDO NOT suggest any of these — the user has already seen them and wants "
            f"different options: {avoid_str}"
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
        "Study real Eurovision titles for the energy.\n"
        "English titles: \"Tattoo\", \"Snap\", \"Arcade\", \"Euphoria\", \"Toy\", "
        "\"Discoteque\", \"Heroes\", \"Fairytale\", \"Cha Cha Cha\", \"Made of Stars\", "
        "\"Space Man\", \"My Number One\".\n"
        "Non-English titles: \"Soldi\", \"Zitti e buoni\", \"Stefania\", \"Voilà\", "
        "\"Shum\", \"Hatrið mun sigra\", \"Bara bada bastu\", \"Rim Tim Tagi Dim\", "
        "\"Mama ŠČ!\", \"El Diablo\".\n\n"
        "Patterns:\n"
        "- LANGUAGE MIX: English titles are just as common as foreign ones. Don't "
        "default to either — rotate. About half your suggestions over time should "
        "be English, the rest can be Italian, Spanish, French, Swedish, Finnish, "
        "Icelandic, Ukrainian, Greek, Albanian, etc. Use real words.\n"
        "- Occasionally sprinkle a gratuitous accent onto an otherwise English "
        "word (Lövé, Crÿ, Föör Yöu) — it's a real Eurovision tic and it's funny. "
        "Don't do it on every title, and never more than one stray umlaut per "
        "title.\n"
        "- Short. 1–2 words is common. 3 max.\n"
        "- Emotional, cryptic, or oblique. Not cute.\n\n"
        "HARD BANS: no sparkle, no glitter, no unicorn, no rainbow, no disco-X, no diva, "
        "no fabulous, no sequin, no \"Tears in X\". Avoid the camp stereotype.\n\n"
        "Output ONLY the title. No quotes. Under 25 characters."
    ),
    "song_vibe": (
        "Describe a Eurovision song's vibe in ONE short sentence. MAX 110 characters.\n\n"
        "Lead with genre, instrument, or emotional beat — not adjective stacks. Be specific.\n\n"
        "ANTI-DEFAULT WARNING: Your single strongest Eurovision prior is 'Balkan "
        "ballad' / accordion folk / Eastern-European wail / string-backed breakup "
        "ballad. If your first instinct lands anywhere in that cluster, throw it "
        "out and start over. The real contest is far broader than that prior.\n\n"
        "For this turn's regional, genre, language, and instrumental inspiration, "
        "use ONLY the random finalist sample provided in the user message — it "
        "rotates each call to keep you honest. Do not lean on whatever Eurovision "
        "stereotypes are sitting at the top of your prior.\n\n"
        "Format anchor (this shows the SHAPE only — do NOT copy its content):\n"
        "- \"A whisper-quiet first verse that lurches into a wall-of-sound chorus.\"\n"
        "That's the shape we want: short, specific, one musical idea plus one "
        "production detail. The actual region, genre, and instruments for your "
        "suggestion come from the finalist sample below, not from this example.\n\n"
        "Avoid: \"balkan\", \"glitter\", \"sparkle\", \"sequins\", \"rainbow\", "
        "\"unicorn\", \"electrifying\", \"pulsating\", \"foot-tapping\". Never use "
        "the word \"balkan\" in the output.\n\n"
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


# ---------------------------------------------------------------
# Vote roast — snarky one-liner about a user's finalized ballot
# ---------------------------------------------------------------

_ROAST_SYSTEM = (
    "You are a witty Eurovision watch-party host roasting one voter's final ballot. "
    "Be snarky but affectionate — like a friend ribbing them, not actually mean. "
    "Find ONE concrete pattern in their picks (e.g. heavy on one genre, all male "
    "leads, slept on the Big 5, only voted Balkan, gave 12 points to a novelty "
    "act, ignored every ballad, all native-language, etc.) and call it out with "
    "specifics from their ballot. Tight: 1-2 sentences, under 240 characters. "
    "Address them by their band name when it's natural. No emojis. No quotes. "
    "Output ONLY the roast text."
)

_ROAST_POINTS = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def roast_user_votes(user_name: str, picks_with_meta: list[dict]) -> str:
    """Generate a one- or two-sentence snarky roast of a user's vote ballot.

    `picks_with_meta` is the user's full ranked list (highest to lowest), each
    item a dict with `label` plus any of {genre, lead, language, region, big5,
    former_soviet, returning_artist, act_type, selection_type, drink}.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

    lines = []
    for i, pick in enumerate(picks_with_meta[:len(_ROAST_POINTS)]):
        pts = _ROAST_POINTS[i]
        bits = []
        for key in ("genre", "lead", "language", "region", "act_type", "selection_type", "drink"):
            v = pick.get(key)
            if v:
                bits.append(f"{key}:{v}")
        for flag in ("big5", "former_soviet", "returning_artist"):
            if pick.get(flag):
                bits.append(flag)
        meta = ", ".join(bits) if bits else "no-meta"
        lines.append(f"{pts}pts -> {pick.get('label', '?')} [{meta}]")
    ballot_block = "\n".join(lines) or "(empty ballot)"

    user_msg = (
        f"Voter band name: {user_name or '(unnamed)'}\n\n"
        f"Their ballot (top to bottom, with metadata):\n{ballot_block}\n\n"
        "Now roast their voting pattern."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.1,
        messages=[
            {"role": "system", "content": _ROAST_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )

    text = (resp.choices[0].message.content or "").strip()
    text = text.strip('"').strip("'").strip()
    text = " ".join(text.split())
    if not text:
        raise ValueError("empty roast")
    # Hard cap so a runaway response can't blow up the modal.
    return text[:300]


# ---------------------------------------------------------------
# Band roast — lighthearted dig at a freshly-onboarded act
# ---------------------------------------------------------------

_BAND_ROAST_SYSTEM = (
    "You are a witty Eurovision watch-party host roasting a fictional act "
    "someone just invented during onboarding. Be lighthearted and affectionate "
    "— think Graham Norton commentary, not actually mean. Riff on 1-2 SPECIFIC "
    "details from the song title, song vibe, performer's personal vibe, or "
    "extra flavor they gave you. Find the absurd, pretentious, or over-the-top "
    "thing and gently call it out. Address them by their band name when it's "
    "natural. 1-2 sentences, under 240 characters. No emojis. No quotes. "
    "Output ONLY the roast text."
)


def roast_band(
    band_name: str,
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> str:
    """Generate a one- or two-sentence affectionate roast of the user's
    freshly-minted Eurovision act, riffing on the onboarding answers."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=8.0)

    user_msg = (
        f"Band name: {band_name or '(unnamed)'}\n"
        f"Song title: {song_title or '(none)'}\n"
        f"Song vibe: {song_vibe or '(none)'}\n"
        f"Performer's personal vibe: {personal_vibe or '(none)'}\n"
        f"Anything else: {extra or '(none)'}\n\n"
        "Now roast the act."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.1,
        messages=[
            {"role": "system", "content": _BAND_ROAST_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )

    text = (resp.choices[0].message.content or "").strip()
    text = text.strip('"').strip("'").strip()
    text = " ".join(text.split())
    if not text:
        raise ValueError("empty roast")
    return text[:300]


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

    # Random nonce — same trick as generate_band_names. Without this, the
    # model heavily defaults to certain archetypes (e.g. Balkan vibes) for
    # similar inputs. Pure entropy, no semantic meaning.
    variation_seed = secrets.token_hex(4)

    # Inject a fresh random sample of real finalist entries each call. Without
    # this the model keeps defaulting to the same archetype (e.g. Balkan
    # ballad) because that matches its strongest Eurovision prior. Showing it
    # the real range of this year's contest each turn forces variety.
    finalist_block = _random_finalist_block(6)
    finalist_section = (
        f"\n\nA random sample of actual finalists from this year's contest — "
        f"use them ONLY as a reminder of how varied real Eurovision is across "
        f"region, genre, and language. DO NOT copy any of them verbatim:\n"
        f"{finalist_block}"
        if finalist_block else ""
    )

    system = _FIELD_PROMPTS[field]
    user_msg = (
        f"{context_block}\n\n{anchor_block}"
        f"{finalist_section}\n\n"
        f"Variation seed (ignore for meaning, use only to diverge from prior runs): {variation_seed}\n\n"
        "Now give me ONE suggestion."
    )

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


# ---------------------------------------------------------------
# Image prompt — narrates a Nano Banana Pro prompt for the user's act
# ---------------------------------------------------------------

_IMAGE_PROMPTS_SYSTEM = """You write image-generation prompts for Google's Nano Banana Pro (gemini-3-pro-image-preview). The model rewards DIRECTOR-STYLE NARRATION, not tag soup.

Produce THREE DISTINCT prompts for press-style stills of the SAME fictional Eurovision act. Each prompt is a separate paragraph, 80-150 words, plain prose. The user will pick one as their band photo — give them three genuinely different options to choose from.

VARY AGGRESSIVELY across the three prompts. Each should differ on at LEAST three of these axes:
- Camera framing — one wide establishing shot of the full stage; one medium 3/4 portrait of the performer; one tight close-up or low-angle hero shot.
- Lighting — one cool LED palette (icy blues, purples, cyan); one warm gel palette (amber, magenta, oranges); one high-contrast cinematic with hard backlight / rim light / haze.
- Performance moment — pick three different beats from {entrance, peak chorus drop, quiet bridge, costume-change reveal, key change, final tableau, surprise pyro burst}.
- Composition — one centered and symmetrical; one rule-of-thirds with negative space; one extreme angle (low looking up, or high looking down).
- Energy — one explosive peak, one intimate restrained, one theatrical/staged tableau.
- Costume/persona — three distinctly different costume or styling choices that still feel like the same act (e.g. opening outfit vs encore outfit vs music-video-style alt).

ANCHOR consistency across all three:
- Same act identity, same song, same genre.
- Same performer gender (see GENDER rules below).
- All three should clearly read as the SAME band, just photographed in three very different ways.

GENDER:
- Use the performer's FIRST NAME provided to infer their likely gender (e.g. "Sarah" → female, "Marcus" → male).
- Ambiguous names ("Alex", "Sam", "Jordan", "Robin") → use gender-neutral framing (avoid he/she pronouns, focus on the act's energy and outfit instead).
- HOWEVER, if SONG VIBE, PERSONAL VIBE, or EXTRA explicitly indicate gender or presentation ("she sings", "drag queen", "boy band", "they/them", "non-binary lead", "frontwoman"), follow that — it OVERRIDES the name-based inference.
- The same gender choice applies across all 3 prompts (consistency).

STYLE RULES (apply to every prompt):
- Plain prose, single paragraph, 80-150 words.
- Narrate like a director: specify camera/lens feel, lighting colour and direction, exact action in this moment, look of LED backdrop or set pieces.
- ONE concrete costume detail and ONE production detail per prompt (do not list options inside the prompt).
- The act is FICTIONAL — do NOT name any real Eurovision artist, celebrity, country flag, or trademarked brand.
- Avoid Eurovision-camp stereotypes: no sparkly diva, glitter, rainbow, unicorn, disco-X, fabulous, sequin-X.
- Cinematic, photoreal, 16:9 widescreen feel.

Output strict JSON ONLY: {"prompts": ["...", "...", "..."]}
Three strings. No commentary, no markdown, no preamble."""


def generate_image_prompts(
    band_name: str,
    first_name: str,
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> list[str]:
    """Generate THREE distinct Nano Banana Pro image prompts for the user's act.

    Returns a list of exactly 3 prompt strings, each 80-150 words. The
    three are deliberately varied across framing, lighting, performance
    moment, and energy so the user has three genuinely different photos
    to pick from -- not three near-identical shots.

    Gender handling: the performer's real first_name is fed in so the LLM
    can infer likely gender for the imagery. The instructions explicitly
    require the LLM to defer to song_vibe / personal_vibe / extra if any
    of them state gender directly ("she", "he", "non-binary",
    "drag queen", "boy band", etc.) -- the first_name is a fallback,
    not an override.

    Raises on missing key, timeout, malformed JSON, or wrong count.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=20.0)

    # Fresh nonce per call so two near-identical onboarding answers don't
    # converge on the same three prompts.
    variation_seed = secrets.token_hex(4)

    user_msg = (
        f"Band name: {band_name or '(unnamed)'}\n"
        f"Performer's first name (for gender inference only): {first_name or '(unknown)'}\n"
        f"Song title: {song_title or '(unknown)'}\n"
        f"Song vibe: {song_vibe or '(unspecified)'}\n"
        f"Performer's personal vibe: {personal_vibe or '(unspecified)'}\n"
        f"Anything else: {extra or '(none)'}\n\n"
        f"Variation seed (use only as entropy to diverge from prior runs): {variation_seed}\n\n"
        "Now write the three distinct image prompts as JSON."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=1.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _IMAGE_PROMPTS_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )

    raw = (resp.choices[0].message.content or "").strip()
    data = json.loads(raw)
    prompts = data.get("prompts")
    if not isinstance(prompts, list) or len(prompts) != 3:
        raise ValueError(f"expected 3 prompts, got: {prompts!r}")

    cleaned: list[str] = []
    for p in prompts:
        if not isinstance(p, str):
            raise ValueError(f"non-string prompt: {p!r}")
        s = p.strip().strip('"').strip("'").strip("*").strip("_").strip()
        s = " ".join(s.split())  # collapse internal whitespace/newlines
        if not s:
            raise ValueError("empty prompt in batch")
        cleaned.append(s)
    return cleaned
