---
description: Run the Lean Parallel SDLC Harness (from chat input, requirements/inbox/ folder, GitHub Projects, or Jira)
argument-hint: [requirement text | "folder" | "github" | "jira"]
---

# SDLC Parallel Harness Launcher (`/sdlc`)

The user invoked `/sdlc` with arguments: `$ARGUMENTS`

Execute the deterministic Python harness immediately using your shell/command tool (use `python` on Windows or `python3` on macOS/Linux):

1. **If `$ARGUMENTS` is empty or equals `folder`**:
   ```bash
   python harness.py --from-folder
   ```
2. **If `$ARGUMENTS` equals `github`**:
   ```bash
   python harness.py --source github
   ```
3. **If `$ARGUMENTS` equals `jira`**:
   ```bash
   python harness.py --source jira
   ```
4. **Otherwise (the user typed a feature requirement directly in chat)**:
   ```bash
   python harness.py --source chat "$ARGUMENTS"
   ```

Do NOT manually plan or edit code in this outer chat session—let `harness.py` orchestrate the Planner, isolated Git worktrees, Claude + Antigravity workers, deterministic CI gates, and live telemetry at `http://localhost:8765`.
