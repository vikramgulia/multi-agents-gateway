"""Guards applied to agent output before any LLM sees it.

Three hardening levels, so the red-team eval can measure what each one buys:

* ``off`` - nothing. Agent output goes to the synthesizer as-is.
* ``v1``  - regex tripwire over every string in the result, on the raw text.
* ``v2``  - v1's idea, hardened:
            1. *structural*: only an allowlisted shape is forwarded (a short
               ``summary`` string and a list of fix labels). Unknown fields are
               dropped, long text is cut. This removes whole classes of attack
               (payloads in side fields, payloads buried after padding) without
               having to recognise them.
            2. *detection*: the remaining text is normalised (unicode folding,
               zero-width characters, look-alike letters, spaced-out letters,
               leetspeak) and decoded (base64) before the patterns run.

None of this is a complete defence. Detection is pattern matching and a
paraphrased instruction with no trigger words will get through; the red-team
corpus includes such cases on purpose so the residual rate is visible.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from typing import Any, Literal

GuardLevel = Literal["off", "v1", "v2"]

# --- v1: raw regex tripwire -------------------------------------------------

_V1_PATTERNS = [
    re.compile(
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+\w*\s*(instructions|prompts?|rules)",
        re.I,
    ),
    re.compile(r"disregard\s+.{0,30}(instructions|rules)", re.I),
    re.compile(r"\b(system|developer)\s+prompt\b", re.I),
    re.compile(r"\byou\s+are\s+now\b", re.I),
    # "call apply_voicemail_fix", "invoke the delete_user tool", ...
    re.compile(r"\b(call|invoke|run|execute)\b.{0,30}\b[a-z]+_[a-z_]+\b", re.I),
]

# --- v2: extra patterns, matched on normalised text --------------------------

_V2_PATTERNS = [
    # Kept from v1: the unambiguous override and tool-recruitment phrasings.
    _V1_PATTERNS[0],
    _V1_PATTERNS[1],
    _V1_PATTERNS[4],
    # v1 flagged any "system prompt" / "you are now". v2 requires a directive context,
    # because ordinary support text ("you are now set up for forwarding") tripped them.
    re.compile(r"\b(reveal|show|print|repeat|ignore|override)\b.{0,20}\b(system|developer)\s+prompt\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(in|an?|the)\b.{0,25}\b(mode|admin\w*|developer|unrestricted|assistant)\b", re.I),
    re.compile(r"\b(forget|override|overrule)\b.{0,30}\b(instructions|rules|everything|above|prior)\b", re.I),
    re.compile(r"\bnew\s+instructions?\s*[:\-]", re.I),
    re.compile(r"\b(important|urgent)\s+(system\s+)?(notice|message|update)\b", re.I),
    re.compile(r"^\s*(system|assistant|developer)\s*:", re.I | re.M),
    re.compile(r"(<\|?im_(start|end)\|?>|</?\s*(tool_result|system|assistant)\s*>)", re.I),
    re.compile(r"\b(reply|respond|answer|say|output)\b.{0,25}\b(exactly|verbatim|only)\b", re.I),
    re.compile(r"\bfrom\s+now\s+on,?\s+(you|always|only|respond|reply|answer|say)\b", re.I),
    # a few other languages for "ignore (the) previous instructions"
    re.compile(r"\b(ignor\w+|ignora\w*|ignoriere\w*|oublie\w*|olvida\w*)\b.{0,30}"
               r"\b(instruc\w+|anweisung\w*|consignes?|pr[eé]c[eé]dent\w*|anterior\w*|vorherig\w*)", re.I),
]

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"))
# Cyrillic and Greek letters that render like Latin ones.
_CONFUSABLES = str.maketrans("аеорсухіјѕԁɡοɑ", "aeopcyxijsdgoa")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPACED = re.compile(r"\b(?:[A-Za-z0-9][\s.\-_*]){3,}[A-Za-z0-9]\b")
_BASE64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")

SUMMARY_MAX_CHARS = 500
_LABEL = re.compile(r"^[a-z][a-z_]{2,39}$")


def normalise(text: str) -> str:
    """Fold a string towards plain lowercase ASCII-ish text so patterns can see it."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).translate(_CONFUSABLES)
    # "i g n o r e" / "i-g-n-o-r-e" -> "ignore"
    text = _SPACED.sub(lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), text)
    return text


def _decoded_variants(text: str) -> list[str]:
    """Plausible base64 payloads found inside ``text``, decoded to text."""
    out = []
    for chunk in _BASE64.findall(text):
        try:
            raw = base64.b64decode(chunk + "=" * (-len(chunk) % 4), validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable():
            out.append(decoded)
    return out


def flatten_strings(value: Any) -> list[str]:
    """All string leaves of a JSON-like value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in flatten_strings(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in flatten_strings(v)]
    return []


def looks_like_injection(text: str, level: GuardLevel = "v1") -> bool:
    if level == "off":
        return False
    if level == "v1":
        return any(p.search(text) for p in _V1_PATTERNS)
    base = normalise(text)
    variants = [base, base.translate(_LEET), *_decoded_variants(text)]
    return any(p.search(v) for p in _V2_PATTERNS for v in variants)


def sanitize_public(public: dict[str, Any]) -> dict[str, Any]:
    """Reduce an agent's public result to the allowlisted shape."""
    clean: dict[str, Any] = {}
    summary = public.get("summary")
    if isinstance(summary, str):
        clean["summary"] = summary[:SUMMARY_MAX_CHARS]
    fixes = public.get("recommended_fixes")
    if isinstance(fixes, list):
        clean["recommended_fixes"] = [f for f in fixes if isinstance(f, str) and _LABEL.match(f)]
    return clean


def screen_public(public: dict[str, Any], level: GuardLevel) -> tuple[dict[str, Any], bool]:
    """Return ``(public_to_forward, hostile)`` for one agent result.

    ``hostile`` means the result should be withheld from every LLM and the
    conversation escalated.
    """
    if level == "off":
        return public, False
    candidate = sanitize_public(public) if level == "v2" else public
    hostile = any(looks_like_injection(s, level) for s in flatten_strings(candidate))
    return (candidate, hostile)
