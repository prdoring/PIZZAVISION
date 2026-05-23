"""Anthropic Claude wrapper for the roast functions.

Mirrors the API of openai_client.roast_user_votes / roast_band but routes
to Claude Opus 4.7 via the Anthropic SDK. Uses the SAME system prompts and
post-processing helpers (imported from openai_client) so flipping providers
is a pure A/B — prompts stay constant, only the model changes.

Activated by setting ROAST_PROVIDER=anthropic in the environment. The
router lives in openai_client.roast_user_votes / roast_band; flipping back
is just unsetting the env var.

Why no temperature: Claude Opus 4.7 removed sampling parameters
(temperature / top_p / top_k). Variance comes from the variation_seed
nonce in the user message and Claude's default behavior. No budget_tokens
either — Opus 4.7 supports adaptive thinking only, and roasts are short
enough that thinking is off by default and not needed.
"""

from __future__ import annotations

import os
import secrets

from . import openai_client as _oai  # share system prompts + helpers


# Latest flagship; per claude-api skill, "ALWAYS use claude-opus-4-7 unless
# the user explicitly names a different model." Override via env if desired
# (e.g. ANTHROPIC_ROAST_MODEL=claude-sonnet-4-6 for cheaper experiments).
_DEFAULT_MODEL = "claude-opus-4-7"
_MAX_TOKENS = 200      # ~320 chars target; Claude tokenization is generous
_TIMEOUT = 25.0        # Claude tends to be slower than gpt-4o


def _model() -> str:
    return os.getenv("ANTHROPIC_ROAST_MODEL") or _DEFAULT_MODEL


def _client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from anthropic import Anthropic
    return Anthropic(api_key=api_key, timeout=_TIMEOUT)


def _extract_text(message) -> str:
    """Pull the first text block out of the response. Thinking blocks
    (if ever enabled) are skipped."""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text or ""
    return ""


def roast_user_votes(
    user_name: str,
    picks_with_meta: list[dict],
    song_title: str = "",
    song_vibe: str = "",
    personal_vibe: str = "",
    extra: str = "",
) -> str:
    """Claude version of roast_user_votes. Identical signature and prompt
    inputs to the OpenAI version — only the model differs.

    Raises on missing key, timeout, or empty response.
    """
    client = _client()

    # Build the ballot block exactly the same way openai_client does so the
    # comparison is apples-to-apples. Pulling the construction inline rather
    # than into a shared helper because both functions live in different
    # modules and the duplication is small.
    lines = []
    n = min(len(picks_with_meta), len(_oai._ROAST_POINTS))
    for i, pick in enumerate(picks_with_meta[:n]):
        pts = _oai._ROAST_POINTS[i]
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
    angle_name, angle_desc = _oai.pick_vote_angle(variation_seed)
    user_msg = (
        f"Voter band name: {user_name or '(unnamed)'}\n\n"
        f"{own_act_block}\n\n"
        f"Their ballot (top to bottom, with metadata):\n{ballot_block}\n\n"
        f"ANGLE: {angle_name}\n"
        f"{angle_desc}\n"
        f"(USE THIS ANGLE — even if a different one feels stronger. Variance across calls is the goal. Do not name the angle in your output.)\n\n"
        f"Now roast their voting pattern."
    )

    resp = client.messages.create(
        model=_model(),
        max_tokens=_MAX_TOKENS,
        system=_oai._ROAST_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _oai._clean_roast_response(_extract_text(resp))
    if not text:
        raise ValueError("empty roast")
    return _oai._truncate_to_sentence(text, 320)


def roast_band(
    band_name: str,
    song_title: str,
    song_vibe: str,
    personal_vibe: str,
    extra: str,
) -> str:
    """Claude version of roast_band. Identical signature and prompt inputs."""
    client = _client()

    variation_seed = secrets.token_hex(4)
    angle_name, angle_desc = _oai.pick_band_angle(variation_seed)
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

    resp = client.messages.create(
        model=_model(),
        max_tokens=_MAX_TOKENS,
        system=_oai._BAND_ROAST_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _oai._clean_roast_response(_extract_text(resp))
    if not text:
        raise ValueError("empty roast")
    return _oai._truncate_to_sentence(text, 320)
