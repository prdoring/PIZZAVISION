"""Google Gemini "Nano Banana Pro" image generation wrapper.

Single function: takes a director-style text prompt, returns PNG bytes.
One retry on transient errors (timeouts, 5xx). Other errors propagate so
callers can mark the slot as failed and tell the user.

The model is `gemini-3-pro-image-preview` — Google's late-2025 image model
codenamed "Nano Banana Pro." It expects narrative prose, not tag soup; the
prompt-writing happens upstream in openai_client.generate_image_prompt.
"""

from __future__ import annotations

import os
import time

# Errors that probably mean "try again in a moment" — network blips, 5xx,
# upstream load. Anything else (auth failure, safety block, bad request) is
# a permanent error and should not retry.
_TRANSIENT_HTTP_CODES = (500, 502, 503, 504)


def _is_transient(err: BaseException) -> bool:
    if isinstance(err, TimeoutError):
        return True
    # google.genai raises google.genai.errors.ServerError / APIError that
    # carry a `code` attribute. We don't import them at module top-level
    # because the package may not be installed at import time on dev.
    code = getattr(err, "code", None) or getattr(err, "status_code", None)
    if isinstance(code, int) and code in _TRANSIENT_HTTP_CODES:
        return True
    msg = str(err).lower()
    if "timeout" in msg or "timed out" in msg:
        return True
    if "connection" in msg and ("reset" in msg or "aborted" in msg or "refused" in msg):
        return True
    return False


def _call_once(prompt: str) -> bytes:
    """Single (no-retry) call. Returns the first inline image part's bytes."""
    from google import genai

    client = genai.Client()
    resp = client.models.generate_content(
        model="gemini-3-pro-image-preview",
        contents=prompt,
    )

    # google-genai responses surface generated parts via .candidates[0].content.parts;
    # the convenience `.parts` property on the response also works in current versions.
    parts = []
    candidates = getattr(resp, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) or []
    if not parts:
        parts = getattr(resp, "parts", None) or []

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None:
            data = getattr(inline, "data", None)
            if data:
                return data if isinstance(data, (bytes, bytearray)) else bytes(data)

    raise RuntimeError("Gemini response contained no image data")


def generate_image(prompt: str) -> bytes:
    """Generate one image from `prompt`. Returns raw PNG bytes.

    Raises:
        RuntimeError: if GEMINI_API_KEY is not set, or if the model returned
            no image data on both attempts.
        ModuleNotFoundError: if `google-genai` isn't installed.
        Anything else from the SDK on hard failure (auth, safety block, etc).
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY not set")

    prefixed = (
        "Cinematic 16:9 widescreen photographic still. " + (prompt or "").strip()
    )

    try:
        return _call_once(prefixed)
    except Exception as e:
        if not _is_transient(e):
            raise
        time.sleep(3.0)
        return _call_once(prefixed)
