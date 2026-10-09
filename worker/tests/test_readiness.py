from clipcon_worker.readiness import check, warm_up
from clipcon_worker.vision import InferenceError, ServiceUnavailable

MODEL = "qwen3.5:4b-q4_K_M"


class FakeOllama:
    model = MODEL

    def __init__(self, reachable=True, installed=(MODEL,), loaded=(), warm_error=None):
        self.reachable, self.installed, self.loaded, self.warm_error = reachable, installed, loaded, warm_error

    def _up(self):
        if not self.reachable:
            raise ServiceUnavailable("connection refused")

    def version(self):
        self._up()
        return "0.40.2"

    def installed_models(self):
        self._up()
        return {name: "sha256:abc" for name in self.installed}

    def loaded_models(self):
        self._up()
        return list(self.loaded)

    def warm_up(self):
        self._up()
        if self.warm_error:
            raise self.warm_error
        self.loaded = (MODEL,)


def tools_present(name):
    return f"/opt/homebrew/bin/{name}"


def test_unreachable_service_is_reported_with_setup_guidance(tmp_path):
    whisper = tmp_path / "ggml-small.en.bin"
    whisper.write_bytes(b"x")
    r = check(FakeOllama(reachable=False), whisper, which=tools_present)
    assert r["state"] == "service_unavailable"
    assert "ollama serve" in r["guidance"]


def test_missing_vision_or_speech_model_is_reported(tmp_path):
    whisper = tmp_path / "ggml-small.en.bin"
    r = check(FakeOllama(installed=()), whisper, which=tools_present)
    assert r["state"] == "model_missing"
    assert f"ollama pull {MODEL}" in r["guidance"]

    r = check(FakeOllama(), whisper, which=tools_present)
    assert r["state"] == "model_missing"
    assert "ggml-small.en.bin" in r["guidance"]


def test_missing_media_tools_are_reported(tmp_path):
    whisper = tmp_path / "ggml-small.en.bin"
    whisper.write_bytes(b"x")
    r = check(FakeOllama(), whisper, which=lambda name: None if name == "whisper-cli" else tools_present(name))
    assert r["state"] == "tools_missing"
    assert "whisper-cli" in r["guidance"]


def test_installed_model_is_cold_until_warm_up_reports_loading_then_ready(tmp_path):
    whisper = tmp_path / "ggml-small.en.bin"
    whisper.write_bytes(b"x")
    ollama = FakeOllama()
    assert check(ollama, whisper, which=tools_present)["state"] == "cold"

    seen = []
    final = warm_up(ollama, whisper, which=tools_present, progress=seen.append)

    assert [s["state"] for s in seen] == ["loading"]
    assert final["state"] == "ready"
    assert check(ollama, whisper, which=tools_present)["state"] == "ready"


def test_failed_warm_up_is_an_inference_failure(tmp_path):
    whisper = tmp_path / "ggml-small.en.bin"
    whisper.write_bytes(b"x")
    final = warm_up(FakeOllama(warm_error=InferenceError("model runner crashed")), whisper,
                    which=tools_present, progress=lambda s: None)
    assert final["state"] == "inference_failed"
    assert "model runner crashed" in final["detail"]


def test_non_loopback_or_cloud_inference_is_refused(tmp_path):
    from clipcon_worker.vision import OllamaVision

    whisper = tmp_path / "ggml-small.en.bin"
    whisper.write_bytes(b"x")
    remote = check(OllamaVision(MODEL, host="ollama.example.com:11434"), whisper, which=tools_present)
    assert remote["state"] == "service_unavailable"
    assert "loopback" in remote["detail"]

    cloud = check(OllamaVision("gpt-oss:120b-cloud", host="127.0.0.1:1"), whisper, which=tools_present)
    assert cloud["state"] == "service_unavailable"
    assert "cloud" in cloud["detail"]
