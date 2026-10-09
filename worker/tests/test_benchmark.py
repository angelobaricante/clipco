"""Benchmark accounting: one Codex session log, summarised per discovery request as recorded, never estimated."""

from pathlib import Path

from clipco_worker.benchmark import summarize_rollout

ROLLOUT = Path(__file__).parent / "fixtures" / "codex-rollout.jsonl"


def test_each_request_reports_the_tokens_tools_and_time_codex_recorded():
    summary = summarize_rollout(ROLLOUT.read_text().splitlines())

    assert summary["model"] == "gpt-6.1-sol" and summary["cli_version"] == "0.162.0-alpha.2"
    first, repeat = summary["turns"]
    assert first == {
        "turn_id": "turn-1", "answer": "Segment seg_a at 0-30s", "wall_seconds": 6.4, "model_requests": 2,
        "input_tokens": 25000, "cached_input_tokens": 20000, "uncached_input_tokens": 5000,
        "output_tokens": 240, "reasoning_output_tokens": 40,
        "tool_calls": {"mcp:clipco.search_footage": 1, "shell": 1, "image_view": 1},
        "failed_tool_calls": 1, "tool_result_text_chars": 370, "tool_result_images": 1, "clipco_index_reads": 0,
    }
    assert repeat["input_tokens"] == 14000 and repeat["cached_input_tokens"] == 13000
    assert repeat["tool_calls"] == {"shell": 1} and repeat["wall_seconds"] == 2.5
    assert summary["session_total"]["input_tokens"] == 39000


def test_categories_the_log_does_not_expose_are_named_rather_than_guessed():
    summary = summarize_rollout(ROLLOUT.read_text().splitlines())

    assert any("image" in u and "token" in u for u in summary["unavailable"])
    assert any("tool result" in u for u in summary["unavailable"])


def test_a_direct_inspection_route_that_reads_clipco_s_own_index_is_flagged():
    summary = summarize_rollout(ROLLOUT.read_text().splitlines())

    first, repeat = summary["turns"]
    assert first["clipco_index_reads"] == 0 and repeat["clipco_index_reads"] == 1
