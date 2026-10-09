# Clipcon implementation tracker

GitHub is the authoritative implementation tracker for `angelobaricante/clipcon`. Local scratch planning artifacts are historical context; GitHub issues and comments carry current task state across sessions.

## Specification and tasks

| Order | Issue | Depends on |
| --- | --- | --- |
| Spec | [Clipcon — macOS MVP specification](https://github.com/angelobaricante/clipcon/issues/1) | Approved product decisions |
| 1 | [Import one source clip and review real local context](https://github.com/angelobaricante/clipcon/issues/2) | None |
| 2 | [Retrieve indexed footage context through Codex MCP](https://github.com/angelobaricante/clipcon/issues/3) | Import one source clip |
| 3 | [Find a spoken correction and supporting B-roll across a project](https://github.com/angelobaricante/clipcon/issues/4) | Codex MCP retrieval |
| 4 | [Review footage context in the native Mac workspace](https://github.com/angelobaricante/clipcon/issues/5) | Project discovery |
| 5 | [Recover unavailable or changed footage without losing good context](https://github.com/angelobaricante/clipcon/issues/6) | Native review |
| 6 | [Prove offline usefulness and prepare the hackathon demonstration](https://github.com/angelobaricante/clipcon/issues/7) | Recovery |

The implementation tasks are native sub-issues of the specification, with native blocking relationships. `ready-for-agent` means specified; it does not mean a blocked task may start. The spec issue is context, not an independently claimable implementation task.

## Start a session

1. Read AGENTS.md, the live parent specification, the target issue, and its comments. Refresh remote Git state and inspect local changes.
2. Choose an open implementation issue whose blockers are closed and which has no active claim by another session. GitHub is authoritative if a local copy differs.
3. Claim the issue through assignment to the executing maintainer and a short starting comment identifying the task, branch, and planned verification. Do not overwrite another session's claim.
4. Work on a task branch; do not mix unrelated task scope. Check the remaining wall-clock time against the organizer's actual cutoff before using the approved time boxes.
5. Complete the external behavior and appropriate acceptance checks. A dependency install or scaffold alone does not complete the first task.

## End or hand off a session

Post an issue comment with:

- What works and which acceptance criteria have been demonstrated.
- Branch, commit, and PR link when available; whether remaining changes are uncommitted.
- Exact validation commands/results and relevant real-model evidence.
- Remaining work, concrete blockers, and the next action.
- Any approved fallback applied, with runtime/model identity and measured limitations.

Make the work recoverable from Git and issue comments. If incomplete, keep the issue open; publish a draft PR when useful and authorized. A local commit alone is not available to another machine, so state whether the branch was pushed. Do not report real inference, offline proof, or benchmark savings without evidence.

When the task's acceptance criteria are satisfied, link its PR to the issue. Close completed tasks through the agreed integration workflow, so native blockers release the next task. Avoid closing the parent specification while merely publishing tasks.

## Durable context

- Product requirements: live parent spec plus the committed spec snapshot.
- Domain terms: GLOSSARY.md.
- Approved native direction: design notes and screenshot.
- Original four-variant browser study: `prototype/footage-review-flow` branch, commit `317f2f14773f392feab8a189157a06e73f39764b`. This is throwaway source material, not the app.
- Dependencies, local model weights, real footage, and local indexes are not portable through Git; record reproducible setup requirements as they are verified.
