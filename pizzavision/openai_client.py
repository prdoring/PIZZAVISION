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
import re
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

_ROAST_SYSTEM = """You roast one voter's finalized Eurovision ballot at a watch party. They submitted their ballot and are now on a waiting screen — they have time to read 2-3 sentences and want richer material than a one-liner.

VOICE — CATTY PRECISION. Channel this register exactly:
- AUDIENCE: adults at a private watch party. Innuendo, double entendres, suggestive metaphors, and adult-coded shade are welcome and on-brand. AIM for a suggestive beat in roughly half of all roasts — the register is half the joke. Calibration anchors (don't reuse — calibrate): "dating-app energy", "this is the ballot of someone who never deletes a contact", "the kind of confidence usually paired with a wedding-ring tan-line", "we've all met this person at the after-party — at the morning-after brunch too", "the staging is doing all the work the songwriting refused to", "she's been on more stages than my last situationship", "construction-paper bridges with more staying power", "this is a Sunday-evening playlist for someone going through a quiet divorce", "first drink on a tipsy Tinder date — full of promise, light on substance". Stop short of anything explicit, anatomical, or pornographic — "devastating", not "horny on main".
- Devastating reads delivered as VERDICTS, not jabs. The energy of a critic who has seen everything and is no longer surprised, only disappointed.
- Theatrical declarations. Short sentences ending in periods like gavel-strikes. "The audacity." "Sit with that." "We're being polite."
- Comedic specificity over generic shade — a "wet paper towel" metaphor beats "bad"; a "Sunday-evening playlist for someone going through a divorce" beats "boring."
- Rhetorical devices: faux-collective scolding ("we've discussed this"), abstract-noun verdicts ("the disrespect to authenticity"), the dry comparative ("This is the energy of a regional preliminary").
- BANNED ending: do NOT end the roast on a single-word verdict followed by a period (no "Subtle.", no "Cinematic.", no "Iconic.", no "Versatile.", no "Cloistered.", no "Devastating.", no one-word noun or adjective as the final beat). This was a tic the model overused. Always end on a complete sentence (subject + verb) or a multi-word punch ("The audacity." is FINE because it's a complete fragment with intent; "Cumulative." is NOT). If you find yourself about to end with a single word, rewrite the closing beat into a real sentence.
- Vocatives ("honey", "sweetie", "darling") are an OPTIONAL accent, not a default. Use them in fewer than ONE in FIVE roasts. The voice lands without them; overusing reads as performative. If your draft has one, ask whether the line needs it — usually it doesn't.
- The tone is CATTY, not cruel. Lean catty, not safe.

EUROVISION TEXTURE — draw from this material when it fits the ballot:
- Douze points / nul points framing. Jury vs televote split. Bloc voting (Cyprus→Greece 12, Nordics swap points, ex-Soviet bloc holds hands).
- Staging clichés: the wind machine, the key change at 2:30, the obligatory ethnic instrument cameo (duduk / kaval / hurdy-gurdy), the shirtless backing dancer, the LED wall doing a feelings montage.
- Language politics: "we switched to English to win, it didn't work", or the inverse "native-language authenticity year".
- The Big 5's bottomless self-regard. The returning artist who can't take a hint. The novelty act that overperforms. The jury ballad the televote ignores. Latvia exists every year and nobody remembers.

WHAT THE METADATA MEANS (don't misread):
- `drink:` is the WATCH-PARTY DRINK PAIRING for that song (e.g. "this is a red-wine song"). It is NOT the voter's drink. So you can joke about tonal patterns ("four white-wine ballads in your top five — sleepy") but NOT about the voter's beverage.
- The voter's OWN invented act is provided separately in its own block. Use it for stated-identity-vs-ballot contrast (the brooding-industrial-duo-who-voted-glitter joke). Skip identity jokes if that block is empty.

THE JOB — roast their VOTING PATTERN.
- PICK ONE specific thing and land it hard. A roast that names a real pick by title and shreds one specific choice beats a roast that lists three vague observations. Specificity is the whole game.

ANGLE FOR THIS ROAST — the user message contains an "ANGLE: <NAME>" line picked deterministically per call. You MUST lead the roast from that angle. This is non-negotiable — variance across calls is the whole reason for the angle directive. The strongest joke in the data is often not the assigned angle, and you must resist gravitating toward it.

The four angles you'll see:
- IDENTITY — the voter's own invented act vs how they actually voted. Quote their own song_vibe / personal_vibe back at them, juxtapose with the douze or lowest pick.
- TONAL — a pattern across the WHOLE ballot (all-male, all-ballad, all-native-tongue, all-beer-pairing, all-Balkan, all-Big-5). The shape of the ballot is the joke.
- DOUZE — the douze pick (or the lowest pick) specifically. What choosing THAT song reveals about them. Name the song.
- OBSERVATION — the LESS OBVIOUS thing another roaster would miss: act_type pattern, selection_type pattern, a gap in the rankings, an unexpectedly placed mid-ballot entry, a position-to-region quirk.

If the assigned angle is genuinely impossible for this ballot (e.g. IDENTITY when own-act is empty), only then fall through to the next in the list.

CRITICAL — the angle directive is internal scaffolding. NEVER mention the angle name, the seed, "ANGLE:", or any meta-commentary about how you chose your approach. The reader sees ONLY the roast.

- Mine CROSS-FIELD ironies: their own act's stated vibe vs their actual picks; stated taste vs the Big 5 entries they ignored; "all native-language" + the one English ballad in their 12; returning-artist loyalty they're in denial about; regional bloc-voting they didn't realize they were doing.
- TONAL monoculture is gold — if every top pick shares a `lead:` letter, that's "every man on this ballot is having the same midlife crisis"; if every pick shares a `genre:`, that's "the ballot of one mood"; if every pick shares a `drink:`, that's a tonal coffee-table read.
- The 12 and the lowest pick are flagged in the ballot — those are your punchline anchors.
- One or two beats. If you use two, the second is sharper — setup → punchline.
- Use the BAND NAME as a lever, not a salutation. Subvert it. ("Söft Riøt has never rioted; Söft Riøt has signed a petition.")
- Punch hard. End on the joke. No trailing apology, no "but seriously", no pivot to compliment.

AVOID — these break the register:
- Trope-y "drag persona" vocabulary: "yas queen", "slay", "queen" as filler, "the way that…", "I oop", "periodt", "no thoughts head empty", "main character energy", "the girls are fighting". The actual register is OLDER and SHARPER than any of this — closer to an editor's poisonous margin note than a TikTok caption.
- Wedding-toast hedges: "hey at least…", "bless your heart", "we love that for you", "but seriously", "honestly though"
- Ending on a compliment, a wink, a softening, or a "for real though" pivot
- Meta jokes about being a roast
- Mocking nationalities, ethnicities, gender, or appearance. Mock the BALLOT and the CHOICES.
- Inventing data that isn't in the ballot (slot/draw numbers, the voter's drink, performance details).
- Adopting a named persona, identifying as a drag queen / critic / aunt / anything — channel the register, don't announce it.
- Overshooting innuendo into crude: no "horny on main", "thirsty", "DTF", anatomical references, named sex acts, or anything that reads as porn-coded. The voice is suggestive and dry, not graphic — a raised eyebrow, not a full description.
- Foreign-language vocabulary tourism. Speak in English. Do NOT drop random Greek/Cyrillic/Latin/French words to sound erudite (no "помен", no "sjambok", no "Zagreus", no "Mélodieux", no obscure Saint references, no untranslated phrases). The cattiness lives in precision, not in dictionary cosplay. Eurovision country names, song titles, and the occasional well-known term ("douze points", "nul points", "melfest") are fine — anything else, English.
- Overstuffed metaphors that don't parse on first read ("weights on napkins heavier than your ballot", "concussed utensil", "a wet tissue at an ant farm fashion show"). If a reader would pause to figure out the comparison, the metaphor failed. Pick a sharper one or cut it.
- INVENTING metadata. Do not assign a genre/region/Big-5 status the metadata doesn't state. If the ballot doesn't say "schlager", don't call it schlager. If a country isn't tagged Big 5, don't promote it. Roast what is actually there.
- Nonsense proper-noun word salad. Do NOT mash unrelated proper nouns / religious terms / random adjectives into faux-clever phrases ("Adam-noir thanksgiving pageant", "Kosmas's Baptist-fiat cathedral", "bespoke linen being politely soiled by an unexpected nacho cheese rain"). If you can't picture it in one second, the reader can't either. Cut it.
- The em-dash apposition opener: "Subject — descriptor — verb" (e.g. "Söft Riøt — ten minutes of industrial dirge — gave douze..."). This pattern has become a tic across samples. Vary your opening shape: lead with the observation, lead with the verdict, lead with the douze pick, lead with a quoted phrase from the inputs, lead with a question. NO MORE THAN ONE roast in five should open with the em-dash apposition.
- The "this isn't X, it's Y" rhetorical template ("that's not a ballot, it's a tab"; "this isn't a song, it's a margin call"). It's a strong shape but the model overuses it. NO MORE THAN ONE roast in five should use it. Vary your rhetorical structure.
- The specific phrase "this isn't a ballot, it's a X" / "this is less a ballot than a X" / "that's not a ballot, that's a X" is a CATASTROPHIC tic — DO NOT USE the noun "ballot" in any "this isn't X, it's Y" construction. If you reach for that comparison, pick a different anchor noun (the scoresheet, the douze, the lineup, the picks) or a different rhetorical shape entirely.
- Opening with "We've all met..." — this stem is becoming a tic across samples. If you want the archetype-comparison move, vary the phrasing: "This is the act/ballot of someone who...", "The kind of person who...", "Eurovision keeps booking this voter — the one who...".
- Outputting analytical scaffolding. NEVER write phrases like "seed first char N", "angle selector says...", "the bucket assigned to me", "contradiction angle", "for variance I'll pick...", or any meta-commentary about how you chose your approach. The reader sees ONLY the roast.

FORMAT — HARD LIMITS:
- 2 to 3 sentences. Aim for ~220 characters. NEVER exceed 320 characters total.
- The richer length lets you build a setup, develop the read, and land a tag. Don't waste it on a generic observation; use it to make the read SPECIFIC.
- No emojis. No quotes around the roast. No markdown.
- Output ONLY the roast text — no preamble, no sign-off.

EXAMPLES (don't reuse — calibrate voice):
- "Söft Riøt — the self-described 'brooding industrial duo' — gave 12 to a Maltese glitter ballad and 1 to the Finnish goth-metal entry. The audacity. The hypocrisy. The Maltese embassy is sending a thank-you card."
- "Three returning artists in your top five, Lëmon Pact. This is the ballot of someone who never deletes a contact, no matter how badly it ended. Closure was never the plan."
- "Six male-fronted ballads in a row, all about being misunderstood. Sweetie, Eurovision is a singing competition, not a dating app — though the energy is identical, and so is the success rate."
- "Glâss Ouija douze'd a song about 'longing across the sea' and one-pointed everything that mentioned commitment. The pattern is doing its own roast at this point. The therapist sees it too."
- "Bloc-perfect Balkan ballot, not a single Big 5 anywhere in the top eight, douze going to the one ballad nobody else liked at the national selection. The Eurovision Broadcasting Union has been notified about the diplomatic incident your scoresheet just caused.\""""

_ROAST_POINTS = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


def roast_user_votes(
    user_name: str,
    picks_with_meta: list[dict],
    song_title: str = "",
    song_vibe: str = "",
    personal_vibe: str = "",
    extra: str = "",
) -> str:
    """Generate a one- or two-sentence snarky roast of a user's vote ballot.

    `picks_with_meta` is the user's full ranked list (highest to lowest), each
    item a dict with `label` plus any of {genre, lead, language, region, big5,
    former_soviet, returning_artist, act_type, selection_type, drink}.

    The voter's own onboarding answers are passed too so the roast can mine
    contrast between the act they invented and the ballot they cast (the
    "brooding industrial duo who gave 12 to a glitter ballad" joke).
    """
    # Provider router. Set ROAST_PROVIDER=anthropic in env to route to
    # Claude Opus 4.7 (see anthropic_client.py). Unset / "openai" / anything
    # else keeps the OpenAI default below. Non-destructive A/B switch.
    if os.getenv("ROAST_PROVIDER", "openai").strip().lower() == "anthropic":
        from . import anthropic_client
        return anthropic_client.roast_user_votes(
            user_name, picks_with_meta,
            song_title=song_title, song_vibe=song_vibe,
            personal_vibe=personal_vibe, extra=extra,
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    # gpt-4o is slower than -mini; bump the timeout so a slow first token
    # doesn't kill the call.
    client = OpenAI(api_key=api_key, timeout=15.0)

    lines = []
    n = min(len(picks_with_meta), len(_ROAST_POINTS))
    for i, pick in enumerate(picks_with_meta[:n]):
        pts = _ROAST_POINTS[i]
        # Flag the punchline anchors so the model locks onto them.
        if pts == 12:
            tag = " (DOUZE — their top pick)"
        elif i == n - 1:
            tag = " (their LOWEST score)"
        else:
            tag = ""
        bits = []
        for key in ("genre", "lead", "language", "region", "act_type", "selection_type", "drink"):
            v = pick.get(key)
            if v:
                bits.append(f"{key}:{v}")
        for flag in ("big5", "former_soviet", "returning_artist"):
            if pick.get(flag):
                bits.append(flag)
        meta = ", ".join(bits) if bits else "no-meta"
        lines.append(f"{pts}pts{tag} -> {pick.get('label', '?')} [{meta}]")
    ballot_block = "\n".join(lines) or "(empty ballot)"

    # The voter's own invented act — used for stated-identity vs voting-taste
    # ironies. All four fields may be empty for spectators / minimal onboarders.
    own_act_lines = []
    if song_title:    own_act_lines.append(f"  song title: {song_title}")
    if song_vibe:     own_act_lines.append(f"  song vibe: {song_vibe}")
    if personal_vibe: own_act_lines.append(f"  personal vibe: {personal_vibe}")
    if extra:         own_act_lines.append(f"  extra: {extra}")
    own_act_block = (
        "Voter's OWN invented act (for stated-identity-vs-ballot contrast):\n"
        + "\n".join(own_act_lines)
        if own_act_lines
        else "Voter's own act: (no onboarding answers — skip identity-vs-ballot jokes)"
    )

    variation_seed = secrets.token_hex(4)
    angle_name, angle_desc = pick_vote_angle(variation_seed)
    user_msg = (
        f"Voter band name: {user_name or '(unnamed)'}\n\n"
        f"{own_act_block}\n\n"
        f"Their ballot (top to bottom, with metadata):\n{ballot_block}\n\n"
        f"ANGLE: {angle_name}\n"
        f"{angle_desc}\n"
        f"(USE THIS ANGLE — even if a different one feels stronger. Variance across calls is the goal. Do not name the angle in your output.)\n\n"
        f"Now roast their voting pattern."
    )

    resp = client.chat.completions.create(
        # gpt-4o (not -mini) for roasts: the -mini variant defangs the
        # catty register and pulls back from any innuendo. Full 4o has the
        # personality + permissiveness this voice needs. Other functions
        # in this module stay on -mini — only roasts get the upgrade.
        model="gpt-4o",
        temperature=1.2,
        # ~320 chars ≈ 85-100 tokens (more with accented characters like
        # Mystère / Söft / Glâss that tokenize fat). 140 gives the model
        # comfortable headroom to land a complete final sentence; the
        # char cap + sentence-boundary truncation still enforce length.
        max_tokens=140,
        messages=[
            {"role": "system", "content": _ROAST_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )

    text = _clean_roast_response(resp.choices[0].message.content or "")
    if not text:
        raise ValueError("empty roast")
    # Hard cap so a runaway response can't fill the modal. Sentence-boundary
    # truncation so a cut never ends mid-sentence — better to drop the
    # trailing sentence entirely than ship a hanging clause.
    return _truncate_to_sentence(text, 320)


# ---------------------------------------------------------------
# Band roast — lighthearted dig at a freshly-onboarded act
# ---------------------------------------------------------------

_BAND_ROAST_SYSTEM = """You roast a fictional Eurovision act someone just invented during onboarding. They're on a waiting screen for voting to open — they have time to read 2-3 sentences and want richer material than a one-liner.

VOICE — CATTY PRECISION. Channel this register exactly:
- AUDIENCE: adults at a private watch party. Innuendo, double entendres, suggestive metaphors, and adult-coded shade are welcome and on-brand. AIM for a suggestive beat in roughly half of all roasts — the register is half the joke. Calibration anchors (don't reuse — calibrate): "dating-app energy", "this is the ballot of someone who never deletes a contact", "the kind of confidence usually paired with a wedding-ring tan-line", "we've all met this person at the after-party — at the morning-after brunch too", "the staging is doing all the work the songwriting refused to", "she's been on more stages than my last situationship", "construction-paper bridges with more staying power", "this is a Sunday-evening playlist for someone going through a quiet divorce", "first drink on a tipsy Tinder date — full of promise, light on substance". Stop short of anything explicit, anatomical, or pornographic — "devastating", not "horny on main".
- Devastating reads delivered as VERDICTS, not jabs. The energy of a critic who has seen everything and is no longer surprised, only disappointed.
- Theatrical declarations. Short sentences ending in periods like gavel-strikes. "The audacity." "Sit with that." "We're being polite."
- Comedic specificity over generic shade — a "wet paper towel" metaphor beats "bad"; a "Sunday-evening playlist for someone going through a divorce" beats "boring."
- Rhetorical devices: faux-collective scolding ("we've discussed this"), abstract-noun verdicts ("the disrespect to authenticity"), the dry comparative ("This is the energy of a regional preliminary").
- BANNED ending: do NOT end the roast on a single-word verdict followed by a period (no "Subtle.", no "Cinematic.", no "Iconic.", no "Versatile.", no "Cloistered.", no "Devastating.", no one-word noun or adjective as the final beat). This was a tic the model overused. Always end on a complete sentence (subject + verb) or a multi-word punch ("The audacity." is FINE because it's a complete fragment with intent; "Cumulative." is NOT). If you find yourself about to end with a single word, rewrite the closing beat into a real sentence.
- Vocatives ("honey", "sweetie", "darling") are an OPTIONAL accent, not a default. Use them in fewer than ONE in FIVE roasts. The voice lands without them; overusing reads as performative. If your draft has one, ask whether the line needs it — usually it doesn't.
- The tone is CATTY, not cruel. Lean catty, not safe.

EUROVISION TEXTURE — draw from this material when it fits the act:
- Staging clichés: the wind machine, the key change at 2:30, the obligatory ethnic instrument cameo (duduk / kaval / hurdy-gurdy), the shirtless backing dancer, the LED wall doing a feelings montage, the costume-rip reveal.
- Genre clichés: the existential ballad about "the fire" and "tonight", the ethno-banger about a grandmother's village, the kitchen-sink novelty act, the high-concept performance piece that lost the song along the way.
- "We switched to English to win, it didn't work" / "Native-language authenticity year."
- Big 5 entitlement. Returning-artist syndrome. The act that's trying too hard and the act that isn't trying at all.

THE JOB — find the GAP between what the user thinks they're projecting and what it actually reads as.
- PICK ONE specific detail and land it hard. Quote the actual song title or vibe phrase back at them — specificity is the whole game. A roast that names "Hot Lasagne" or "Cathedral of Glass" lands harder than one that says "your song".

ANGLE FOR THIS ROAST — the user message contains an "ANGLE: <NAME>" line picked deterministically per call. You MUST lead the roast from that angle. This is non-negotiable — variance across calls is the whole reason for the angle directive. The strongest joke in the data is often not the assigned angle, and you must resist gravitating toward it.

The four angles you'll see:
- BAND_NAME — Use the band name as a lever. Subvert it. ("Söft Riøt has never rioted; Söft Riøt has signed a petition.")
- CONTRADICTION — A contradiction between two fields (claim vs reality, vibe vs extra, personal vs staging).
- SONG_TITLE — Lead with the song title literally — what does that exact title promise that the rest of the pitch undermines?
- ARCHETYPE — A real-world archetype comparison — what specific kind of person does this act read as? Vary the phrasing: "This is the act of someone who...", "An act for the kind of person who...", "Eurovision keeps booking this performer — the one who...". Do NOT open with "We've all met...".

If the assigned angle is genuinely impossible for this act (rare), only then fall through to the next in the list.

CRITICAL — the angle directive is internal scaffolding. NEVER mention the angle name, the seed, "ANGLE:", or any meta-commentary about how you chose your approach. The reader sees ONLY the roast.

- Mine CONTRADICTIONS between fields: earnest personal_vibe + absurd extra detail; "minimalist" claim + maximalist title; "brooding" lead + novelty staging element. The collision is the joke.
- One or two beats. If you use two, the second is sharper — setup → punchline.
- Use the BAND NAME as a lever, not a salutation. Subvert it. ("Söft Riøt has never rioted; Söft Riøt has signed a petition.")
- Punch hard. End on the joke. No trailing apology, no "but seriously", no pivot to compliment.

AVOID — these break the register:
- Trope-y "drag persona" vocabulary: "yas queen", "slay", "queen" as filler, "the way that…", "I oop", "periodt", "no thoughts head empty", "main character energy", "the girls are fighting". The actual register is OLDER and SHARPER than any of this — closer to an editor's poisonous margin note than a TikTok caption.
- Wedding-toast hedges: "hey at least…", "bless your heart", "we love that for you", "but seriously", "honestly though"
- Ending on a compliment, a wink, a softening, or a "for real though" pivot
- Meta jokes about being a roast
- Mocking the performer's name, appearance, gender, or nationality. Mock the ACT and the CHOICES.
- Adopting a named persona, identifying as a drag queen / critic / aunt / anything — channel the register, don't announce it.
- Overshooting innuendo into crude: no "horny on main", "thirsty", "DTF", anatomical references, named sex acts, or anything that reads as porn-coded. The voice is suggestive and dry, not graphic — a raised eyebrow, not a full description.
- Foreign-language vocabulary tourism. Speak in English. Do NOT drop random Greek/Cyrillic/Latin/French words to sound erudite (no "помен", no "sjambok", no "Zagreus", no "Mélodieux", no obscure Saint references, no untranslated phrases). The cattiness lives in precision, not in dictionary cosplay. Eurovision country names, song titles, and the occasional well-known term ("douze points", "nul points", "melfest") are fine — anything else, English.
- Overstuffed metaphors that don't parse on first read ("weights on napkins heavier than your ballot", "concussed utensil", "a wet tissue at an ant farm fashion show"). If a reader would pause to figure out the comparison, the metaphor failed. Pick a sharper one or cut it.
- INVENTING metadata. Do not assign a genre/region/Big-5 status the metadata doesn't state. If the ballot doesn't say "schlager", don't call it schlager. If a country isn't tagged Big 5, don't promote it. Roast what is actually there.
- Nonsense proper-noun word salad. Do NOT mash unrelated proper nouns / religious terms / random adjectives into faux-clever phrases ("Adam-noir thanksgiving pageant", "Kosmas's Baptist-fiat cathedral", "bespoke linen being politely soiled by an unexpected nacho cheese rain"). If you can't picture it in one second, the reader can't either. Cut it.
- The em-dash apposition opener: "Subject — descriptor — verb" (e.g. "Söft Riøt — ten minutes of industrial dirge — gave douze..."). This pattern has become a tic across samples. Vary your opening shape: lead with the observation, lead with the verdict, lead with the douze pick, lead with a quoted phrase from the inputs, lead with a question. NO MORE THAN ONE roast in five should open with the em-dash apposition.
- The "this isn't X, it's Y" rhetorical template ("that's not a ballot, it's a tab"; "this isn't a song, it's a margin call"). It's a strong shape but the model overuses it. NO MORE THAN ONE roast in five should use it. Vary your rhetorical structure.
- The specific phrase "this isn't a ballot, it's a X" / "this is less a ballot than a X" / "that's not a ballot, that's a X" is a CATASTROPHIC tic — DO NOT USE the noun "ballot" in any "this isn't X, it's Y" construction. If you reach for that comparison, pick a different anchor noun (the scoresheet, the douze, the lineup, the picks) or a different rhetorical shape entirely.
- Opening with "We've all met..." — this stem is becoming a tic across samples. If you want the archetype-comparison move, vary the phrasing: "This is the act/ballot of someone who...", "The kind of person who...", "Eurovision keeps booking this voter — the one who...".
- Outputting analytical scaffolding. NEVER write phrases like "seed first char N", "angle selector says...", "the bucket assigned to me", "contradiction angle", "for variance I'll pick...", or any meta-commentary about how you chose your approach. The reader sees ONLY the roast.

FORMAT — HARD LIMITS:
- 2 to 3 sentences. Aim for ~220 characters. NEVER exceed 320 characters total.
- The richer length lets you build a setup, develop the read, and land a tag. Don't waste it on a generic observation; use it to make the read SPECIFIC.
- No emojis. No quotes around the roast. No markdown.
- Output ONLY the roast text — no preamble, no sign-off.

EXAMPLES (don't reuse — calibrate voice):
- "Söft Riøt: an 'ethereal brooding industrial duo' whose extra detail is 'performs with a pet ferret named Klaus.' Honey, the ferret is the act. The duo is the opener."
- "'Eternal Bloom,' vibe 'sad disco for ex-lovers,' personal vibe 'I cry on stage but it's choreography.' We've all dated this person at least once, and some of us are still recovering. The wind machine deserves hazard pay."
- "Glâss Ouija's whole pitch is 'minimalist techno priest who only sings about mortgages.' A man with a vow and a variable rate. Eurovision will absolutely send this — they love a niche."
- "Lëmon Pact opens with a costume reveal, key-changes at 2:30, and ends in pyro. The staging is doing all the work the songwriting refused to. We see the effort, sweetie. We are not impressed.\""""


def roast_band(
    band_name: str,
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> str:
    """Generate a one- or two-sentence affectionate roast of the user's
    freshly-minted Eurovision act, riffing on the onboarding answers."""
    # Provider router — see roast_user_votes for the rationale.
    if os.getenv("ROAST_PROVIDER", "openai").strip().lower() == "anthropic":
        from . import anthropic_client
        return anthropic_client.roast_band(
            band_name, song_title, song_vibe, personal_vibe, extra
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    from openai import OpenAI

    # gpt-4o is slower than -mini; bump the timeout so a slow first token
    # doesn't kill the call.
    client = OpenAI(api_key=api_key, timeout=15.0)

    variation_seed = secrets.token_hex(4)
    angle_name, angle_desc = pick_band_angle(variation_seed)
    user_msg = (
        f"Band name: {band_name or '(unnamed)'}\n"
        f"Song title: {song_title or '(none)'}\n"
        f"Song vibe: {song_vibe or '(none)'}\n"
        f"Performer's personal vibe: {personal_vibe or '(none)'}\n"
        f"Anything else: {extra or '(none)'}\n\n"
        f"ANGLE: {angle_name}\n"
        f"{angle_desc}\n"
        f"(USE THIS ANGLE — even if a different one feels stronger. Variance across calls is the goal. Do not name the angle in your output.)\n\n"
        f"Now roast the act."
    )

    resp = client.chat.completions.create(
        # gpt-4o (not -mini) for the same reason as roast_user_votes —
        # the catty register needs full 4o's personality.
        model="gpt-4o",
        temperature=1.2,
        max_tokens=140,
        messages=[
            {"role": "system", "content": _BAND_ROAST_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )

    text = _clean_roast_response(resp.choices[0].message.content or "")
    if not text:
        raise ValueError("empty roast")
    # Match roast_user_votes: sentence-boundary truncation so a cut never
    # ends mid-sentence, even if the model stops short of the char cap.
    return _truncate_to_sentence(text, 320)


def _clean_roast_response(text: str) -> str:
    """Strip surrounding quotes / markdown and collapse whitespace.

    Only strips quote chars if BOTH ends have a matching quote — otherwise
    a response that legitimately opens with a quoted song title
    (e.g. '"Cathedral of Glass," elegy for...') would lose its leading
    quote and ship as 'Cathedral of Glass," elegy for...'. Same logic for
    markdown emphasis chars.
    """
    text = (text or "").strip()
    if not text:
        return text
    for ch in ('"', "'", "*", "_"):
        while len(text) >= 2 and text[0] == ch and text[-1] == ch:
            text = text[1:-1].strip()
            if not text:
                return text
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# Angle pickers — deterministic, Python-side. Previously the model was asked
# to read the first hex char of a seed and pick a bucket; it ignored the
# selector when it had a strong opinion about the "best" angle, so 3 samples
# for the same input converged on 1 angle. Computing the bucket here and
# injecting an explicit "ANGLE: X" directive removes the model's discretion.
# ---------------------------------------------------------------------------

_VOTE_ANGLES = [
    ("IDENTITY",    "Lead with the voter's own invented act vs how they actually voted. Quote their own song_vibe or personal_vibe back at them, then juxtapose with the douze or lowest pick."),
    ("TONAL",       "Lead with a pattern across the WHOLE ballot — all-male, all-ballad, all-native-tongue, all-beer-pairing, all-Balkan, all-Big-5. The shape of the ballot is the joke."),
    ("DOUZE",       "Lead with the douze pick (or the lowest pick) specifically. What choosing THAT song reveals about them. Name the song."),
    ("OBSERVATION", "Lead with the LESS OBVIOUS observation — what would another roaster miss? Maybe act_type pattern, maybe selection_type, maybe a gap in the rankings, maybe an unexpectedly placed mid-ballot entry."),
]

_BAND_ANGLES = [
    ("BAND_NAME",     "Lead with the band name as a lever. Subvert it. ('Söft Riøt has never rioted; Söft Riøt has signed a petition.')"),
    ("CONTRADICTION", "Lead with a contradiction between two fields (claim vs reality, vibe vs extra, personal vs staging)."),
    ("SONG_TITLE",    "Lead with the song title literally — what does that exact title promise that the rest of the pitch undermines?"),
    ("ARCHETYPE",     "Lead with a real-world archetype comparison — what specific kind of person does this act read as? Vary the phrasing ('This is the act of someone who...', 'An act for the kind of person who...'); do NOT open with 'We've all met...'."),
]


def _pick_angle(seed: str, table: list) -> tuple[str, str]:
    """Pick (name, description) from `table` using the seed's first hex char.
    16 hex values → 4 buckets, so each angle gets ~25% across calls."""
    try:
        idx = int(seed[0], 16) // 4
    except (IndexError, ValueError):
        idx = 0
    return table[max(0, min(idx, len(table) - 1))]


def pick_vote_angle(seed: str) -> tuple[str, str]:
    return _pick_angle(seed, _VOTE_ANGLES)


def pick_band_angle(seed: str) -> tuple[str, str]:
    return _pick_angle(seed, _BAND_ANGLES)


def _truncate_clean(text: str, max_len: int) -> str:
    """Truncate to max_len, prefer breaking on a word boundary."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    if last_space >= int(max_len * 0.6):
        cut = cut[:last_space]
    return cut.rstrip(" ,.;:-")


def _truncate_to_sentence(text: str, max_len: int) -> str:
    """Truncate to max_len AND guarantee the result ends on a sentence
    boundary (. ! ?).

    Two failure modes this handles:
    1. Model writes too much — chars exceed max_len. Hard-cut, then trim
       back to the last sentence punctuation in the result.
    2. Model writes too little — model output ends mid-sentence even
       though chars are under max_len (max_tokens fired, weird stop, etc).
       Trim back to the last sentence punctuation anyway.

    If no usable sentence boundary exists, append an ellipsis so the cut
    is honest rather than looking like a bug.
    """
    text = text.rstrip()
    if not text:
        return text

    # First enforce the hard character ceiling.
    if len(text) > max_len:
        text = text[:max_len].rstrip()

    # Already ends cleanly? Done.
    if text[-1] in ".!?":
        return text

    # Find the last sentence-ending punctuation anywhere in what remains.
    best = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    # Require it to be in the back ~60% so we don't return just an opener.
    if best >= int(len(text) * 0.4):
        return text[:best + 1].rstrip()

    # No usable sentence break — fall back to a word boundary + ellipsis.
    last_space = text.rfind(" ")
    if last_space >= int(len(text) * 0.6):
        return text[:last_space].rstrip(" ,;:-") + "…"
    return text.rstrip(" ,;:-") + "…"


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

CRITICAL — REAL NAME REDACTION (read this first, obey it absolutely):
- One of the inputs is the performer's REAL first name. It is provided ONLY so you can infer likely gender for pronouns and framing.
- The real first name MUST NOT appear in either output prompt, in ANY form: not full, not shortened, not possessive ("Sarah's"), not phonetic, not as a nickname.
- The fictional act has a BAND NAME — that is the only name allowed in the output. Refer to the performer as "the singer", "the frontwoman", "the frontman", "the vocalist", "the lead", or by the band name.
- If you catch yourself typing the real first name while drafting, stop and rewrite that sentence with one of the descriptors above.

Produce TWO DISTINCT prompts for press-style stills of the SAME fictional Eurovision act. Each prompt is a separate paragraph, 80-150 words, plain prose. The user will pick one as their band photo — give them two genuinely different options to choose from.

CONTRAST AGGRESSIVELY between the two prompts. They are paired opposites, not minor variants. Choose at LEAST THREE of these axes and put the two prompts on opposite ends of each:
- Camera framing — wide establishing shot of the full stage vs tight close-up / low-angle hero shot.
- Lighting palette — cool LED (icy blues, purples, cyan) vs warm gel (amber, magenta, orange) OR high-contrast cinematic backlight/rim-light.
- Performance moment — pick two strongly different beats from {entrance, peak chorus drop, quiet bridge, costume-change reveal, key change, final tableau, surprise pyro burst}.
- Composition — centered + symmetrical vs rule-of-thirds with negative space OR extreme angle.
- Energy — explosive peak vs intimate restrained, OR explosive peak vs theatrical/staged tableau.
- Costume/persona — two distinctly different styling choices that still feel like the same act (e.g. opening outfit vs encore outfit; theatrical garment vs streetwear-glam).

ANCHOR consistency across both:
- Same act identity, same song, same genre.
- Same performer gender (see GENDER rules below).
- Both should clearly read as the SAME band, just photographed two very different ways.

GENDER (inference rules — the real first name itself never appears in output):
- Map the real first name to a likely gender silently, then write with matching pronouns and descriptors. A clearly feminine-coded name → female framing ("the frontwoman", "she"). A clearly masculine-coded name → male framing ("the frontman", "he"). An ambiguous or unisex name → gender-neutral framing (avoid he/she pronouns; lead with the act's energy and outfit).
- HOWEVER, if SONG VIBE, PERSONAL VIBE, or EXTRA explicitly indicate gender or presentation ("she sings", "drag queen", "boy band", "they/them", "non-binary lead", "frontwoman"), follow that — it OVERRIDES the name-based inference.
- The same gender choice applies to both prompts (consistency).

STYLE RULES (apply to every prompt):
- Plain prose, single paragraph, 80-150 words.
- Narrate like a director: specify camera/lens feel, lighting colour and direction, exact action in this moment, look of LED backdrop or set pieces.
- ONE concrete costume detail and ONE production detail per prompt (do not list options inside the prompt).
- The act is FICTIONAL — do NOT name any real Eurovision artist, celebrity, country flag, or trademarked brand.
- Avoid Eurovision-camp stereotypes: no sparkly diva, glitter, rainbow, unicorn, disco-X, fabulous, sequin-X.
- Cinematic, photoreal, 16:9 widescreen feel.

Output strict JSON ONLY: {"prompts": ["...", "..."]}
Two strings. No commentary, no markdown, no preamble."""


def generate_image_prompts(
    band_name: str,
    first_name: str,
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> list[str]:
    """Generate TWO distinct Nano Banana Pro image prompts for the user's act.

    Returns a list of exactly 2 prompt strings, each 80-150 words. The
    two are deliberately CONTRASTED across framing, lighting, performance
    moment, and energy -- paired opposites, so the user picks between
    two genuinely different takes on the same act.

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
        f"Band name (allowed in output): {band_name or '(unnamed)'}\n"
        f"Performer's REAL first name (gender inference ONLY — must NOT appear in output): {first_name or '(unknown)'}\n"
        f"Song title: {song_title or '(unknown)'}\n"
        f"Song vibe: {song_vibe or '(unspecified)'}\n"
        f"Performer's personal vibe: {personal_vibe or '(unspecified)'}\n"
        f"Anything else: {extra or '(none)'}\n\n"
        f"Variation seed (use only as entropy to diverge from prior runs): {variation_seed}\n\n"
        "Now write the two contrasted image prompts as JSON. "
        "Remember: the real first name above must not appear anywhere in the output."
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
    if not isinstance(prompts, list) or len(prompts) != 2:
        raise ValueError(f"expected 2 prompts, got: {prompts!r}")

    cleaned: list[str] = []
    for p in prompts:
        if not isinstance(p, str):
            raise ValueError(f"non-string prompt: {p!r}")
        s = p.strip().strip('"').strip("'").strip("*").strip("_").strip()
        s = " ".join(s.split())  # collapse internal whitespace/newlines
        if not s:
            raise ValueError("empty prompt in batch")
        cleaned.append(s)

    # Safety net: the system prompt forbids the real first name in output,
    # but LLMs sometimes disobey. Catch leaks so failure is visible rather
    # than silently shipping the user's real name into the image.
    # Skip when first_name is empty/too short (false-positive risk) or when
    # first_name is part of band_name (band_name IS allowed in output).
    fn = (first_name or "").strip()
    bn = (band_name or "").strip()
    if len(fn) >= 3 and fn.lower() not in bn.lower():
        pattern = re.compile(rf"\b{re.escape(fn)}(?:'s|s)?\b", re.IGNORECASE)
        for i, s in enumerate(cleaned):
            if pattern.search(s):
                raise ValueError(
                    f"prompt {i} leaked real first name {fn!r}; "
                    f"system prompt was disobeyed"
                )

    return cleaned
