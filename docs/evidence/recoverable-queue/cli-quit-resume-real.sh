#!/bin/zsh
# Quit (SIGTERM to the run-queue process, as the app does on quit) mid-job, relaunch, reconcile, explicit resume.
W=/Users/angelobaricante/clipco/worker/.venv/bin/clipco-worker
D=${0:A:h}; H=$D/home2; export PATH=/opt/homebrew/bin:$PATH
states() { $W --home $H jobs | python3 -c 'import json,sys; d=json.load(sys.stdin); print({j["original_filename"]: (j["state"], j["stage"], j["error"]) for j in d["jobs"]}, "running=", d["running"])' }
children() { pgrep -fl 'whisper-cli|ffmpeg' | grep -v pgrep || echo "(no whisper-cli/ffmpeg processes)" }
$W --home $H enqueue --library $D/drop/IMG_6188.MOV $D/drop/nested/IMG_6189.MOV > /dev/null
$W --home $H run-queue > $D/quit1.jsonl 2>>$D/stderr.log & R=$!
until grep -q '"transcribing"' $D/quit1.jsonl 2>/dev/null; do sleep 0.3; done
echo "== while transcribing:"; children
kill -TERM $R; wait $R; echo "runner exit code: $?"; sleep 0.3; children; states
echo "== relaunch: reconcile"; $W --home $H reconcile > /dev/null; states
echo "== nothing runs without resume:"; $W --home $H run-queue | python3 -c 'import json,sys; print([l for l in sys.stdin][-1][:120])'; states
echo "== resume + run"; $W --home $H resume > /dev/null; date +%T; $W --home $H run-queue > $D/quit2.jsonl; date +%T; states
grep -c '"describing"' $D/quit2.jsonl
