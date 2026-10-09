#!/bin/zsh
# Real-model queue lifecycle at the CLI entry point (scratch home; originals only read).
set -u
W=/Users/angelobaricante/clipco/worker/.venv/bin/clipco-worker
D=${0:A:h}; H=$D/home; export PATH=/opt/homebrew/bin:$PATH
q() { $W --home $H "$@" }
states() { q jobs | python3 -c 'import json,sys; d=json.load(sys.stdin); print({j["original_filename"]: (j["state"], j["stage"]) for j in d["jobs"]}, "paused=",d["paused"],"running=",d["running"])' }
children() { pgrep -fl 'whisper-cli|ffmpeg' | grep -v pgrep || echo "(no whisper-cli/ffmpeg processes)" }
P=$(q create-project --name "Queue proof" | python3 -c 'import json,sys; print(json.load(sys.stdin)["project"]["id"])')
echo "== enqueue mixed drop (folder + overlapping file + unsupported + missing)"; date +%T
q enqueue --project $P $D/drop $D/drop/IMG_6188.MOV $D/gone.mp4 | python3 -c 'import json,sys; d=json.load(sys.stdin); print("jobs", [j["original_filename"] for j in d["jobs"]], "skipped", d["skipped"])'
states
echo "== run-queue (background)"; q run-queue > $D/run1.jsonl 2>>$D/stderr.log & R=$!
until grep -q '"transcribing"' $D/run1.jsonl 2>/dev/null; do sleep 0.5; done
A=$(q jobs | python3 -c 'import json,sys; print(next(j["id"] for j in json.load(sys.stdin)["jobs"] if j["state"]=="active"))')
echo "== cancel active job $A while transcribing"; children; T0=$(python3 -c 'import time; print(time.time())')
q cancel $A > /dev/null
until q jobs | python3 -c 'import json,sys; sys.exit(0 if any(j["id"]=="'$A'" and j["state"]=="cancelled" for j in json.load(sys.stdin)["jobs"]) else 1)'; do sleep 0.2; done
python3 -c "import time; print('cancelled after %.1fs' % (time.time()-$T0))"; sleep 0.5; children; states
echo "== pause while the next job runs"; until grep -q '"describing"' $D/run1.jsonl; do sleep 0.5; done
q pause > /dev/null; states
wait $R; echo "runner exited (paused): $?"; states
echo "== resume, then quit the runner (SIGTERM, as the app does) mid-job"
q resume > /dev/null; q run-queue > $D/run2.jsonl 2>>$D/stderr.log & R=$!
until grep -q '"job_started"' $D/run2.jsonl; do sleep 0.3; done; sleep 4
children; kill -TERM $R; wait $R; echo "runner exited: $?"; sleep 0.5; children; states
echo "== relaunch: reconcile, then explicit resume"; q reconcile > /dev/null; states
q resume > /dev/null; q retry-jobs $A > /dev/null; date +%T; q run-queue > $D/run3.jsonl 2>>$D/stderr.log; date +%T; states
echo "== MCP overview of the Project"
cd /Users/angelobaricante/clipco/worker && .venv/bin/python - $H $P <<'PY'
import sys; sys.path.insert(0, "tests")
from pathlib import Path
from test_mcp import call, payload
[o] = call(Path(sys.argv[1]), ("get_project_overview", {"project_id": sys.argv[2]}))
for c in payload(o)["clips"]: print(c["original_filename"], c["status"], c.get("segment_count"))
PY
