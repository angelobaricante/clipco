"""Ollama adapter: image-plus-transcript context with validated structured output.

The model only sees evidence IDs the worker assigned. Its output is checked against
those IDs; unsupported references are rejected rather than trusted.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class InferenceError(Exception):
    pass


class ServiceUnavailable(InferenceError):
    pass


@dataclass(frozen=True)
class TranscriptItem:
    id: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class FrameItem:
    id: str
    time: float
    path: Path


@dataclass(frozen=True)
class SegmentRequest:
    project_context: str
    original_filename: str
    start: float
    end: float
    transcript: list[TranscriptItem]
    frames: list[FrameItem]


@dataclass
class Description:
    label: str
    observations: list[tuple[str, str]]  # (frame_id, text)
    interpretation: str
    evidence_ids: list[str]
    rejected_refs: list[str] = field(default_factory=list)


SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Short descriptive label, at most 8 words"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frame_id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["frame_id", "text"],
            },
        },
        "interpretation": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["label", "observations", "interpretation", "evidence_ids"],
}

SYSTEM_PROMPT = """You describe one time range of a creator's raw video footage for an editing agent.
You receive sampled still frames (each with a frame ID) and the transcript lines spoken in that range (each with a transcript ID).
Return JSON only:
- label: a short descriptive label for this range (at most 8 words).
- observations: one entry per frame, describing only what is visible in that still frame. Use the given frame_id. Do not guess what happens between frames.
- interpretation: one or two sentences on what this range is about, combining speech and visuals. Say when something is uncertain.
- evidence_ids: the frame and transcript IDs that support your interpretation. Only use IDs you were given.
Never invent timestamps, IDs, quantities, or details that are not visible or spoken."""


def build_prompt(request: SegmentRequest) -> str:
    lines = [
        f"Project context: {request.project_context or '(none given)'}",
        f"Source clip: {request.original_filename}",
        f"Range: {request.start:.1f}s to {request.end:.1f}s",
        "Frames (attached images, in this order):",
        *[f"- {f.id} at {f.time:.1f}s" for f in request.frames],
        "Transcript:",
        *([f"- {t.id} [{t.start:.1f}-{t.end:.1f}s] {t.text}" for t in request.transcript] or ["- (no speech detected)"]),
    ]
    return "\n".join(lines)


def validate(raw: object, request: SegmentRequest) -> Description:
    """Check model output against the schema and the evidence IDs actually supplied."""
    if not isinstance(raw, dict):
        raise InferenceError("model output is not a JSON object")
    label, interpretation = raw.get("label"), raw.get("interpretation")
    observations, evidence = raw.get("observations"), raw.get("evidence_ids")
    if not isinstance(label, str) or not label.strip():
        raise InferenceError("model output has no label")
    if not isinstance(interpretation, str) or not interpretation.strip():
        raise InferenceError("model output has no interpretation")
    if not isinstance(observations, list) or not isinstance(evidence, list):
        raise InferenceError("model output is missing observations or evidence_ids")
    frame_ids = {f.id for f in request.frames}
    known_ids = frame_ids | {t.id for t in request.transcript}
    rejected: list[str] = []
    kept_obs: list[tuple[str, str]] = []
    for obs in observations:
        if not isinstance(obs, dict) or not isinstance(obs.get("text"), str) or not obs["text"].strip():
            raise InferenceError("malformed observation")
        if obs.get("frame_id") in frame_ids:
            kept_obs.append((obs["frame_id"], obs["text"].strip()))
        else:
            rejected.append(str(obs.get("frame_id")))
    kept_evidence = []
    for ref in evidence:
        if ref in known_ids:
            if ref not in kept_evidence:
                kept_evidence.append(ref)
        else:
            rejected.append(str(ref))
    if request.frames and not kept_obs:
        raise InferenceError("model output has no observation for any supplied frame")
    if not kept_evidence:
        raise InferenceError("model interpretation cites no supplied evidence")
    return Description(label.strip(), kept_obs, interpretation.strip(), kept_evidence, rejected)


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OllamaVision:
    def __init__(self, model: str, host: str | None = None, timeout: float = 300):
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434").removeprefix("http://")
        self.timeout = timeout
        self._digest: str | None = None

    def _refuse_remote(self) -> None:
        """Core inference must stay on this Mac: loopback host only, no Ollama cloud models."""
        hostname = self.host.rsplit(":", 1)[0].strip("[]")
        if hostname not in LOOPBACK_HOSTS:
            raise ServiceUnavailable(f"Refusing non-loopback Ollama host {self.host}; Clipcon only uses local inference")
        if "cloud" in self.model.split(":")[-1]:
            raise ServiceUnavailable(f"Refusing Ollama cloud model {self.model}; choose a locally downloaded model")

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        self._refuse_remote()
        url = f"http://{self.host}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[-400:]
            raise InferenceError(f"Ollama {path} returned {e.code}: {detail}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise ServiceUnavailable(f"Ollama is not reachable at {self.host}: {e}") from e

    def version(self) -> str:
        return self._post("/api/version", timeout=3)["version"]

    def installed_models(self) -> dict[str, str]:
        return {m["name"]: m.get("digest", "") for m in self._post("/api/tags", timeout=3).get("models", [])}

    def loaded_models(self) -> list[str]:
        return [m["name"] for m in self._post("/api/ps", timeout=3).get("models", [])]

    def warm_up(self) -> None:
        self._post("/api/generate", {"model": self.model, "prompt": "", "keep_alive": "30m"})

    @property
    def identity(self) -> dict:
        if self._digest is None:
            try:
                self._digest = self.installed_models().get(self.model, "")
            except InferenceError:
                self._digest = ""
        return {"engine": "ollama", "model": self.model, "digest": self._digest}

    def describe(self, request: SegmentRequest) -> dict:
        images = [base64.b64encode(f.path.read_bytes()).decode() for f in request.frames]
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": SCHEMA,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(request), "images": images},
            ],
        }
        content = self._post("/api/chat", body)["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise InferenceError(f"model returned invalid JSON: {content[:200]}") from e
