---
name: sdlc-harness
description: Trigger the parallel Claude + Antigravity SDLC harness from chat input, the local requirements/inbox/ folder, GitHub Issues/Projects, or Jira.
---

# Skill: SDLC Parallel Harness Trigger

Whenever the user asks in chat to:
- "Run SDLC on `<requirement>`" or `/sdlc <requirement>`
- "Pick up requirements from the folder" / "Run pending requirements"
- "Pull requirements from GitHub / Jira"

Run the Python orchestrator (works on Windows, macOS, and Linux):

- **Direct chat requirement**: `python harness.py --source chat "<requirement>"`
- **Local folder queue (`requirements/inbox/`)**: `python harness.py --from-folder`
- **Continuous folder watcher**: `python harness.py --watch`
- **GitHub Issues / Projects**: `python harness.py --source github`
- **Jira**: `python harness.py --source jira`
