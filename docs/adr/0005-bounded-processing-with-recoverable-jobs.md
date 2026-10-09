# Use bounded processing and recoverable analysis jobs

The creator accepted Sequential as the default and measured adaptive overlap in Auto, preserving analysis quality while reducing concurrency under resource pressure. Imports register immediately and enter a recoverable queue with per-job progress, safe cancellation, pause-before-new-jobs behavior, and an explicit restart-resume path. Parallel execution must preserve coordinated atomic publication and completed results; simply launching unrestricted workers cannot satisfy these lifecycle and resource constraints.

Sequential does not by itself establish that a device can fit the configured model. Temporary resource pressure produces waiting work; an unsupported configuration receives explicit guidance, without a silent smaller-model substitution. Supported-device and speed claims require measurements.
