"""Footage roles of Segments: suggested in code from analysed evidence, correctable by the creator.

A Segment's suggested role and the creator's correction are kept apart so each stays attributable; the
effective role is the creator's when there is one. Only B-roll can be reused outside a Project's context.
"""

ROLES = ("a-roll", "b-roll", "mixed", "needs_review")
NAMES = {"a-roll": "A-roll", "b-roll": "B-roll", "mixed": "Mixed", "needs_review": "Needs review"}

# Share of a Segment's duration that must be speech before it counts as someone speaking in it.
SPEAKING_SHARE = 0.5


def suggest(start: float, end: float, speech_seconds: float, facing_camera: bool) -> tuple[str, str]:
    """(role, basis) for one Segment from its own speech coverage and whether its sampled frames show a person
    facing the camera. Disagreeing evidence is Mixed or Needs review rather than a guess."""
    share = speech_seconds / (end - start) if end > start else 0.0
    speaking = share >= SPEAKING_SHARE
    basis = (f"speech covers {share:.0%} of this Segment; sampled frames "
             f"{'show' if facing_camera else 'do not show'} a person facing the camera")
    if speaking and facing_camera:
        return "a-roll", basis
    if not speaking and not facing_camera:
        return ("b-roll", basis) if share == 0 else ("needs_review", basis + "; some speech, check if it narrates")
    if speaking:
        return "mixed", basis + "; narration over other visuals"
    return "needs_review", basis + "; a person faces the camera without speaking"


def legacy_basis(clip_role: str | None, clip_basis: str | None) -> str:
    return (f"Indexed before Segment roles: the whole clip was classified {NAMES.get(clip_role, 'unknown')}"
            f" ({clip_basis or 'no basis recorded'}). Confirm this Segment's role or re-analyse.")


def effective(suggested: str, creator: str | None) -> str:
    return creator or suggested


def summary(roles: list[str]) -> dict:
    """A clip-level browsing summary of its Segments' effective roles."""
    counts = {r: roles.count(r) for r in ROLES if r in roles}
    if not roles:
        text = "Not analysed"
    elif len(counts) == 1:
        text = NAMES[roles[0]]
    else:
        unresolved = counts.get("mixed", 0) + counts.get("needs_review", 0)
        clear = " and ".join(NAMES[r] for r in ("a-roll", "b-roll") if r in counts)
        text = (f"{clear}, {unresolved} to review" if clear and unresolved else clear or "Needs review")
    return {"text": text, "counts": counts}
