"""Emotional tone: a suggested effect footage may have on a viewer, interpreted from saved sampled evidence.

Tone is an attributed interpretation, never an observation or a measured probability: each suggestion names a
tone from a small vocabulary, explains it, and cites the frame/transcript IDs it rests on. The emotion a depicted
person visibly shows is kept apart from it. Possible metaphorical readings ("connotations") are kept as their
own grounded suggestions. A Segment never analysed for tone is Not analyzed, which is different from analysed
with no supported tone; the creator's correction is kept beside the suggestions, attributed separately.
"""

import json
from dataclasses import dataclass, field

from .text import words
from .vision import InferenceError

# Bump when tone prompting or validation changes; earlier tone analyses stay readable and are re-enriched only
# when the creator asks.
TONE_RECIPE = {"version": 1, "inputs": "saved sampled frames, their observations, and the Segment's transcript"}

VOCABULARY = ("calm", "hopeful", "joyful", "playful", "warm", "nostalgic", "melancholic", "tense", "energetic",
              "awe", "satisfying", "curious")

# Words a request may use for a vocabulary tone. Literal content words (e.g. "quiet", "clean") are left out so a
# content request is not mistaken for a tone request.
SYNONYMS = {
    "calm": ("calm", "calming", "peaceful", "peace", "serene", "serenity", "relaxing", "relaxed", "tranquil",
             "soothing", "gentle"),
    "hopeful": ("hopeful", "hope", "optimistic", "optimism", "uplifting", "promising", "renewal"),
    "joyful": ("joyful", "joy", "happy", "happiness", "cheerful", "delight", "delightful", "celebratory"),
    "playful": ("playful", "fun", "funny", "silly", "lighthearted", "whimsical", "humorous"),
    "warm": ("warm", "warmth", "cozy", "cosy", "comforting", "comfort", "tender", "intimate", "homey"),
    "nostalgic": ("nostalgic", "nostalgia", "wistful", "reminiscent", "memories"),
    "melancholic": ("melancholic", "melancholy", "sad", "sadness", "lonely", "loneliness", "somber", "sombre",
                    "gloomy", "sorrow", "bleak"),
    "tense": ("tense", "tension", "anxious", "anxiety", "suspense", "suspenseful", "stressful", "stress",
              "uneasy", "urgent", "frustrating", "frustration", "struggle"),
    "energetic": ("energetic", "energy", "lively", "dynamic", "exciting", "excitement", "upbeat"),
    "awe": ("awe", "wonder", "majestic", "epic", "awe-inspiring", "breathtaking", "grand"),
    "satisfying": ("satisfying", "satisfaction", "relief", "accomplishment", "accomplished"),
    "curious": ("curious", "curiosity", "intriguing", "mysterious", "mystery", "intrigue"),
}
_BY_WORD = {w: tone for tone, ws in SYNONYMS.items() for w in ws}

MAX_SUGGESTIONS = 3

LIMITATIONS = ("Interpreted by a local model from a few sampled still frames, their saved observations and the "
               "transcript only. It did not watch continuous video or hear music, ambient sound, pacing or motion; "
               "it is a possible viewer response in some stories, not a guaranteed reaction or a probability.")


def tones_in(query: str) -> list[str]:
    """Vocabulary tones a request asks for, in the order mentioned."""
    found = [_BY_WORD[w] for w in words(query.replace("-", " ")) if w in _BY_WORD]
    if "awe-inspiring" in query.casefold():
        found.append("awe")
    return list(dict.fromkeys(found))


def require_tone(tone: str | None) -> str | None:
    if tone is None:
        return None
    named = tone.strip().casefold()
    if named in VOCABULARY:
        return named
    if mapped := tones_in(named):
        return mapped[0]
    raise ValueError(f"unknown tone {tone!r}; use one of {', '.join(VOCABULARY)}")


@dataclass
class ToneReading:
    tones: list[dict]  # {"tone", "explanation", "evidence_ids"}
    connotations: list[dict]  # {"idea", "explanation", "evidence_ids"}
    depicted_emotion: str
    rejected_refs: list[str] = field(default_factory=list)


SCHEMA = {
    "type": "object",
    "properties": {
        "tones": {"type": "array", "items": {"type": "object", "properties": {
            "tone": {"type": "string", "enum": list(VOCABULARY)}, "explanation": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["tone", "explanation", "evidence_ids"]}},
        "connotations": {"type": "array", "items": {"type": "object", "properties": {
            "idea": {"type": "string"}, "explanation": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["idea", "explanation", "evidence_ids"]}},
        "depicted_emotion": {"type": "string"},
    },
    "required": ["tones", "connotations", "depicted_emotion"],
}

SYSTEM_PROMPT = f"""You suggest the emotional tone a short piece of raw footage could lend to a video, for an editing agent choosing B-roll.
You receive sampled still frames (each with a frame ID), what was observed in each frame, and the transcript lines spoken in that range (each with a transcript ID).
Return JSON only:
- tones: zero to {MAX_SUGGESTIONS} tones a viewer might feel from this footage, each from this list only: {", ".join(VOCABULARY)}. Give each a one-sentence explanation tied to visible or spoken evidence, and the frame/transcript IDs it rests on. Give more than one only when the evidence supports different readings. Return an empty list when nothing supports a tone; never pick one just to fill the list.
- connotations: zero to {MAX_SUGGESTIONS} abstract ideas the imagery could stand for when used metaphorically (for example "a fresh start" or "slow progress"), each with a one-sentence explanation and evidence IDs. Empty when none is natural.
- depicted_emotion: the emotion a visible person clearly expresses (for example "smiling"), or an empty string when no person shows one. This is about the people shown, not the viewer.
You only see still frames: never mention music, sound, camera motion, pacing or anything happening between frames. Do not claim a viewer will certainly feel anything. Only use IDs you were given."""


def build_prompt(request) -> str:
    lines = [
        f"Source clip: {request.original_filename}",
        f"Range: {request.start:.1f}s to {request.end:.1f}s",
        "Frames (attached images, in this order) and what was observed in each:",
        *[f"- {f.id} at {f.time:.1f}s: {request.observations.get(f.id, '(no observation saved)')}"
          for f in request.frames],
        "Transcript:",
        *([f"- {t.id} [{t.start:.1f}-{t.end:.1f}s] {t.text}" for t in request.transcript]
          or ["- (no speech detected)"]),
    ]
    return "\n".join(lines)


def validate(raw: object, known_ids: set[str]) -> ToneReading:
    """Keep suggestions that name a vocabulary tone and cite supplied evidence; reject the rest by name."""
    if not isinstance(raw, dict):
        raise InferenceError("tone output is not a JSON object")
    rejected: list[str] = []

    def cited(item: dict) -> list[str]:
        refs = item.get("evidence_ids") if isinstance(item.get("evidence_ids"), list) else []
        kept = []
        for ref in refs:
            head = str(ref).split()[0] if str(ref).strip() else str(ref)
            if head in known_ids:
                if head not in kept:
                    kept.append(head)
            else:
                rejected.append(str(ref))
        return kept

    def readings(key: str, name: str) -> list[dict]:
        out = []
        for item in raw.get(key) or []:
            if not isinstance(item, dict):
                continue
            value = item.get(name)
            value = value.strip().casefold() if isinstance(value, str) else ""
            explanation = item.get("explanation").strip() if isinstance(item.get("explanation"), str) else ""
            evidence = cited(item)
            if name == "tone" and value not in VOCABULARY:
                rejected.append(f"tone:{value}")
                continue
            if not value or not explanation or not evidence:  # an ungrounded suggestion is not kept
                rejected.append(f"{name}:{value or '?'}")
                continue
            if all(r[name] != value for r in out):
                out.append({name: value, "explanation": explanation, "evidence_ids": evidence})
        return out[:MAX_SUGGESTIONS]

    depicted = raw.get("depicted_emotion")
    return ToneReading(readings("tones", "tone"), readings("connotations", "idea"),
                       depicted.strip() if isinstance(depicted, str) else "", rejected)


@dataclass(frozen=True)
class ToneRequest:
    original_filename: str
    start: float
    end: float
    transcript: list  # vision.TranscriptItem
    frames: list  # vision.FrameItem
    observations: dict[str, str]  # local frame ID -> saved observation


def read(db, seg) -> dict:
    """A Segment's tone state: Not analyzed, analysed with none supported, suggested, or the creator's tones.
    `tones` is what counts for discovery: the creator's when they set any, otherwise the suggestions."""
    saved = db.execute("SELECT * FROM tone_analyses WHERE segment_id=?", (seg["id"],)).fetchone()
    creator = db.execute("SELECT tones, updated_at FROM tone_corrections WHERE clip_id=? AND start=? AND end_=?",
                         (seg["clip_id"], seg["start"], seg["end_"])).fetchone()
    suggested = json.loads(saved["tones"]) if saved else []
    creator_tones = json.loads(creator["tones"]) if creator else None
    if creator_tones is not None:
        state = "creator"
    elif saved is None:
        state = "not_analyzed"
    else:
        state = "suggested" if suggested else "none_supported"
    return {
        "state": state,
        "tones": creator_tones if creator_tones is not None else [s["tone"] for s in suggested],
        "suggested": suggested,
        "connotations": json.loads(saved["connotations"]) if saved else [],
        "depicted_emotion": saved["depicted_emotion"] if saved else None,
        "creator": creator_tones,
        "creator_updated_at": creator["updated_at"] if creator else None,
        "model": json.loads(saved["model"]).get("model") if saved else None,
        "recipe_version": json.loads(saved["recipe"]).get("version") if saved else None,
        "analyzed_at": saved["analyzed_at"] if saved else None,
        "limitations": LIMITATIONS if saved else "Not analyzed for emotional tone yet; this is not a neutral tone.",
    }
