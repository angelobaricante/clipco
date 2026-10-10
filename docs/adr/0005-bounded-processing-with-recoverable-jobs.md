# Use bounded processing and recoverable analysis jobs

The creator accepted Sequential as the default and measured adaptive overlap in Auto, preserving analysis quality while reducing concurrency under resource pressure. Imports register immediately and enter a recoverable queue with per-job progress, safe cancellation, pause-before-new-jobs behavior, and an explicit restart-resume path. Parallel execution must preserve coordinated atomic publication and completed results; simply launching unrestricted workers cannot satisfy these lifecycle and resource constraints.

Sequential does not by itself establish that a device can fit the configured model. Temporary resource pressure produces waiting work; an unsupported configuration receives explicit guidance, without a silent smaller-model substitution. Supported-device and speed claims require measurements.

Scope amendment, 2026-10-10: the creator removed Auto/adaptive processing (#19) from the MVP to prioritize evidence-grounded MCP footage discovery. The earlier approval of adaptive overlap is superseded. Sequential resource/readiness checks, coherent publication, and the recoverable job lifecycle remain accepted; no parallel-processing implementation is required.
