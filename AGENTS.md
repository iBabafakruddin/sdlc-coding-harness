# Unified Agent Instructions (Claude Code & Antigravity)

You are operating inside a **Lean Token-Optimized Parallel SDLC Harness** (Windows, macOS & Linux compatible).

## How Requirements Enter This Project
1. **From This Chat Box (Claude Code or Antigravity)**:
   - Type `/sdlc <your requirement>` (or ask *"Run SDLC harness for: ..."*) to trigger `python harness.py --source chat "<requirement>"`.
   - Type `/sdlc` or `/sdlc folder` to process all `.md`, `.txt`, and `.json` files inside `requirements/inbox/`.
   - Type `/sdlc github` or `/sdlc jira` to pull tasks from GitHub Projects/Issues or Jira.
2. **From Local Folder (`requirements/inbox/`)**:
   - Any `.md`, `.txt`, or `.json` file placed in `requirements/inbox/` is automatically picked up by `python harness.py --from-folder` (or `--watch`) and moved through `in_progress/` -> `completed/` (or `failed/`).

## Sub-Agent Worktree Rules (When Invoked by `harness.py`)
1. **Scope Discipline**: Read and modify ONLY the files listed in `files_to_modify` for your assigned story. Never scan the whole repository unless explicitly asked.
2. **Skill Adherence**: Follow the stack-specific checklists injected under `ACTIVE SKILLS` in your prompt.
3. **Zero Git Ceremony**: Do NOT run `git checkout`, `git branch`, `git commit`, `git push`, or `gh pr`. The Python harness manages git worktrees, rebases, and merges deterministically.
4. **No Conversational Filler**: Output only code edits or the exact JSON schema requested by your role prompt.
