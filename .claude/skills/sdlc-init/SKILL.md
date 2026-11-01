---
name: sdlc-init
description: Orchestrator — set up the SDLC agent harness in the current project (new or existing) — initialise the board and git, check branch/worktree settings, and have the tech-lead onboard the codebase into .sdlc/project-profile.md with verified test/lint/build commands. Use right after installing the harness into a project, or when the user types /sdlc-init.
---

# /sdlc-init — onboard this project

1. **Board + git**
   ```bash
   python .sdlc/tools/board.py init
   git status --short
   git rev-parse --abbrev-ref HEAD
   ```
   - No git repo → `init` created one with a bootstrap commit.
   - Uncommitted harness files (`.claude/`, `.sdlc/`, `CLAUDE.md`, `.gitignore`) → ask the human to commit them (or offer to commit them with `chore: add SDLC agent harness`). Branches are created from the main branch, so the harness must be committed there first or worktrees won't contain it.
   - Check `git.main_branch` in `.sdlc/config.json` matches the real default branch; fix it if not.

2. **Branching check** — show the human, in 4 lines: strategy (`feature` = `feature/REQ-…` per requirement with `story/STORY-…` branches off it; `story` = story branches straight off main), worktree folder (`git.worktree_root`, resolved), whether branches are pushed (`git.push_branches`), PR mode (`workflow.pr_mode`: `local` or `github`). Ask only if something looks wrong (e.g. remote exists and they probably want `github`).

3. **Onboard** → Agent `tech-lead`: "Onboard this codebase: follow the codebase-onboarding skill." Then verify `.sdlc/project-profile.md` exists and `project.commands` is filled (or the project is greenfield).

4. **Team** — show `team.developers` (ids, capacity, strengths) and sprint length; ask the human to confirm or adjust.

5. **Optional settings** — mention `.sdlc/setup/claude-settings.example.json` (pre-approves board/git_flow/gate commands, denies force-push, re-renders the board after edits). The human decides whether to copy it into `.claude/settings.json`; don't copy it yourself.

6. Report: stack, verified commands, known issues, branching setup, and "ready: `/sdlc-feature <request>`".
