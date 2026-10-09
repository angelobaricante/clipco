"""Suggested relationships between saved Segments, derived in code from their indexed evidence.

These are suggestions for the creator and the editing agent: each cites the evidence it rests on, keeps
both sides in the index, and never decides which statement or take is preferred.
"""

import hashlib
import json
import re

from .text import matches, terms, words

# Bump when these rules change: the store then re-derives every Project's relationships when it opens.
VERSION = 1

# Spoken phrases that commonly revise what was just said (English and Tagalog/Taglish).
CORRECTION_CUE = re.compile(
    r"\b(actually|i mean|sorry|correction|scratch that|i misspoke|let me (?:rephrase|correct) (?:that|myself)"
    r"|no wait|wait no|pala|ay mali|hindi pala)\b", re.IGNORECASE)
# How far back a correction may refer to an earlier statement in the same Source clip.
CORRECTION_LOOKBACK_SECONDS = 120.0
# With no shared words, a correction is linked to the line just before it only if that line is this close.
CORRECTION_ADJACENT_SECONDS = 30.0

# Two utterances are takes of the same point when this share of their meaningful words is common to both.
TAKE_SIMILARITY = 0.6
TAKE_MIN_TERMS = 4

# Words describing how something is said or filmed rather than what it shows, ignored when pairing footage.
FILLER = frozenset("""
actually also back can could does doing get gets going gonna got here into just let lets like make mean now
okay ok one onto out over really see show shows thing things up very want will would yeah
""".split())
# A B-roll Segment is suggested for an explanation when its observations share this many meaningful words.
BROLL_MIN_SHARED = 2
BROLL_PER_EXPLANATION = 2


def relationship(kind: str, a: dict, b: dict, a_evidence: list[str], b_evidence: list[str], basis: str) -> dict:
    material = json.dumps([kind, a_evidence, b_evidence])
    return {"id": "rel_" + hashlib.sha256(material.encode()).hexdigest()[:16], "kind": kind,
            "a_segment": a["id"], "b_segment": b["id"], "a_evidence": a_evidence, "b_evidence": b_evidence,
            "basis": basis}


def spoken_corrections(segments: list[dict]) -> list[dict]:
    """Link each line carrying a correction cue to the earlier statement in the same clip it most likely revises."""
    found = []
    by_clip: dict[str, list[tuple[dict, dict]]] = {}
    for seg in segments:
        by_clip.setdefault(seg["clip_id"], []).extend((seg, line) for line in seg["transcript"])
    for lines in by_clip.values():
        lines.sort(key=lambda sl: sl[1]["start"])
        for i, (seg, line) in enumerate(lines):
            cue = CORRECTION_CUE.search(line["text"])
            if not cue:
                continue
            revised = set(terms(CORRECTION_CUE.sub(" ", line["text"])))
            candidates = [(len(revised & set(terms(prev["text"]))), j)
                          for j, (_, prev) in enumerate(lines[:i])
                          if line["start"] - prev["start"] <= CORRECTION_LOOKBACK_SECONDS]
            if not candidates:
                continue
            shared, j = max(candidates)  # most shared words; among ties, the nearest earlier line
            earlier_seg, earlier = lines[j]
            if not shared and line["start"] - earlier["end"] > CORRECTION_ADJACENT_SECONDS:
                continue
            common = sorted(revised & set(terms(earlier["text"])))
            basis = f"correction cue “{cue.group(0)}”" + (f"; shares: {', '.join(common)}" if common
                                                          else "; follows the previous line")
            found.append(relationship("spoken_correction", earlier_seg, seg, [earlier["id"]], [line["id"]], basis))
    return found


def repeated_takes(segments: list[dict], exclude: set[frozenset[str]]) -> list[dict]:
    """Link utterances (a line, or two consecutive lines) that say substantially the same thing elsewhere."""
    units = []  # (segment, evidence ids, start, words)
    for seg in segments:
        lines = seg["transcript"]
        for i, line in enumerate(lines):
            units.append((seg, [line["id"]], line["start"], set(terms(line["text"]))))
            if i + 1 < len(lines):
                pair = lines[i:i + 2]
                units.append((seg, [p["id"] for p in pair], line["start"],
                              set(terms(" ".join(p["text"] for p in pair)))))
    best: dict[tuple[str, str], tuple[float, dict]] = {}
    for i, (seg_a, ev_a, _, words_a) in enumerate(units):
        for seg_b, ev_b, _, words_b in units[i + 1:]:
            if min(len(words_a), len(words_b)) < TAKE_MIN_TERMS or set(ev_a) & set(ev_b):
                continue
            similarity = len(words_a & words_b) / len(words_a | words_b)
            if similarity < TAKE_SIMILARITY or frozenset(ev_a + ev_b) in exclude:
                continue
            key = (seg_a["id"], seg_b["id"])
            if key not in best or similarity > best[key][0]:
                basis = f"{similarity:.0%} of meaningful words in common"
                best[key] = (similarity, relationship("repeated_take", seg_a, seg_b, ev_a, ev_b, basis))
    return [r for _, r in best.values()]


def supporting_broll(segments: list[dict]) -> list[dict]:
    """Suggest B-roll whose sampled-frame observations share meaningful words with an A-roll explanation."""
    found = []
    broll = [s for s in segments if s["role"] == "b-roll" and s["observations"]]
    for seg in (s for s in segments if s["role"] == "a-roll" and s["transcript"]):
        candidates = []
        for other in broll:
            seen = {o["id"]: set(words(o["text"])) for o in other["observations"]}
            seen_any = set().union(*seen.values())
            lines, shared = [], set()
            for line in seg["transcript"]:
                hit = {t for t in terms(line["text"]) if t not in FILLER and matches(t, seen_any)}
                if hit:
                    lines.append(line["id"])
                    shared |= hit
            if len(shared) < BROLL_MIN_SHARED:
                continue
            frames = [fid for fid, ws in seen.items() if any(matches(t, ws) for t in shared)]
            basis = f"sampled-frame observations share words with what is said: {', '.join(sorted(shared))}"
            candidates.append((len(shared), relationship("supporting_broll", seg, other, lines, frames, basis)))
        candidates.sort(key=lambda c: -c[0])  # stable: ties keep source order
        found += [r for _, r in candidates[:BROLL_PER_EXPLANATION]]
    return found


def relate(segments: list[dict]) -> list[dict]:
    """All suggested relationships among a Project's published Segments, in source order."""
    corrections = spoken_corrections(segments)
    linked = {frozenset(r["a_evidence"] + r["b_evidence"]) for r in corrections}
    return corrections + repeated_takes(segments, linked) + supporting_broll(segments)
