# Visible agent connections

2026-10-10, Asia/Manila. Creator-requested emil-design-eng follow-up; creator explicitly chose both Claude Code and Claude Desktop.

| Before | After | Why |
| --- | --- | --- |
| Codex registration buried in Local Setup | AI Agents sidebar section with Codex and Claude rows | Connection is visible during footage browsing |
| Codex-only terminal command | Native Connect actions for Codex, Claude Code and Claude Desktop; manual setup disclosed | Fewer steps; client-specific guidance |
| Local helper handshake labelled Connected | Separate Configured registration and Footage tools ready states | Saved configuration does not establish an active agent session |
| No Claude registration workflow | Preserve unrelated JSON, back up existing settings, atomically add named registration and refuse conflicts | Existing agent settings survive setup |

Native build: `xcodebuild -project app/Clipco.xcodeproj -scheme Clipco -configuration Debug -derivedDataPath /private/tmp/clipco-sidebar-build CODE_SIGNING_ALLOWED=NO build`: BUILD SUCCEEDED.

Worker regression: `cd worker && .venv/bin/python -m pytest -q`: 85 passed, 1 skipped, 3 deselected. Initial focused agent checks: 11 passed. Checks cover real stdio handshake, registration/readiness distinction, preservation/backups, idempotent reconnect, invalid/conflicting JSON, missing client, symlink refusal, and Codex argument forwarding through an isolated CLI adapter. The installed Claude Code CLI recognizes the created user-scoped configuration using CLAUDE_CONFIG_DIR in an isolated temporary directory; no chat/model call. Final focused checks: 12 passed, including unavailable footage tools leaving settings unchanged.

Actual rebuilt native app on scratch footage index and scratch Claude settings (via LSEnvironment): sidebar Codex/Claude rows visible; Claude app picker switches between Desktop and Code; each Connect button creates the correct scratch registration, reports Configured, gives restart/new-session guidance, disables duplicate connection, and updates sidebar. Codex detects the creator's existing registration points to a different index than the scratch app and disables replacement. Native screenshots inspected for dark layout; status text shortened to fit the sidebar. Local Setup remains distinct from agent registration.

No creator agent registrations were changed; only scratch registrations under /private/tmp/clipco-sidebar-review/agent-config were created by UI tests. No inference, provider request, footage edits, source uploads or local index publication. Unrelated branding/spec working changes preserved.

Limits: no new Codex registration was written with the real CLI (its argument boundary used an isolated adapter); existing registration was read. Claude Desktop configuration plus the actual local MCP helper handshake are verified, but a restarted Desktop chat consuming the tools is not demonstrated. No live provider chat or model-quality claim, full VoiceOver pass, light-mode pass or under-load frame-time profile.

Sources: installed Codex/Claude CLI help; https://code.claude.com/docs/en/mcp ; https://modelcontextprotocol.io/docs/develop/connect-local-servers .


## Connection action follow-up

Creator screenshots exposed two dead-end actions: Configured Claude retained a disabled Connect button, and conflicting Codex offered no in-app recovery. Configured clients now show Disconnect. Conflicting clients show Disconnect Existing Connection with a native confirmation; removal exposes an enabled Connect action when the client and footage tools are ready. The sheet is titled Connection rather than Connect in every state. Guidance reflects the selected client.

Disconnect removes only the named clipco registration, preserves unrelated settings, and works without a healthy footage index. Claude changes retain the existing atomic write, lock, and private backup behavior; Codex uses its installed CLI mcp remove command. Disconnect never promises to revoke already-running sessions or previously retrieved context; restart/new-session guidance is shown.

Native scratch UI: both Claude Desktop and Code disconnected and reconnected, changing Configured → Not configured/Connect → Configured/Disconnect. Codex conflict action and Cancel were verified; the creator's real registration was not removed. Native layout inspected. Worker connection checks cover all three clients, stale/disabled removal and reconnect, unrelated setting preservation, idempotent removal, and removal with unavailable footage tools. No provider chat, inference or source changes.

Final follow-up validation: native Debug BUILD SUCCEEDED; `.venv/bin/python -m pytest tests/test_agent_connections.py -q`: 19 passed in 44.63s. `git diff --check` passed.


## Agent identity artwork

Creator requested recognizable Codex/ChatGPT and Claude logos. Sidebar rows now use 22-point app artwork; connection headings reuse the artwork at 36 points. Both preserve original colors and aspect ratio, are bundled for offline display, and are hidden from accessibility because the adjacent app name supplies the label. Asset catalog registration is independent of the uncommitted Clipco branding catalog.

Artwork provenance: Codex from the installed official ChatGPT/Codex app resource `icon-codex-light.png`; Claude from the installed official Claude app resource `ion-dist/images/claude_app_icon.png`. These identify the external connection clients; they remain their owners’ trademarks. References: https://openai.com/brand/ and https://claude.com/ . Artwork is copied unchanged.

CodexAgent SHA-256: `de7d43f3386105ab20952958c2c25beb0d903e2aeb6e1aef57c49a648c0d1c07`.

ClaudeAgent SHA-256: `c7b5642f810adfba78781592d9dec18d7eb376c7ebf403c4d882fb9d39f65408`.

Logo validation: native Debug BUILD SUCCEEDED; actual rebuilt scratch app shows both logos in the sidebar and Claude artwork in the connection heading. Accessibility retains app-name/status labels without repeating decorative image names. No connection or footage settings changed. `git diff --check` passed.
