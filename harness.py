#!/usr/bin/env python3
"""
Lean Parallel SDLC Harness v3 (Cross-Platform: Windows PowerShell/CMD, macOS, Linux)
- Resolves Windows `.cmd` / `.exe` / `.ps1` wrappers automatically via `shutil.which()`
- Normalizes `./mvnw` -> `mvnw.cmd` and `./gradlew` -> `gradlew.bat` on Windows
- Retries atomic telemetry writes on Windows if the dashboard holds a momentary read lock
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from providers import (
    BaseRequirementProvider,
    ChatInputProvider,
    GitHubProjectProvider,
    JiraProvider,
    LocalFolderProvider,
    RequirementItem,
)

MAX_RETRIES = 2
MAX_WORKERS = int(os.environ.get("SDLC_MAX_WORKERS", "2"))

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "antigravity")

STATE_DIR = Path(".sdlc")
TELEMETRY_FILE = STATE_DIR / "telemetry.json"
WORKTREES_DIR = Path(".worktrees")

git_lock = threading.Lock()
telemetry_lock = threading.Lock()
active_files_lock = threading.Lock()
locked_files: set[str] = set()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def resolve_executable(bin_name: str) -> str:
    """Resolve CLI executable across Windows (.cmd/.exe/.bat) and POSIX."""
    resolved = shutil.which(bin_name)
    if resolved:
        return resolved
    if os.name == "nt":
        for ext in (".cmd", ".exe", ".bat", ".ps1"):
            cand = shutil.which(bin_name + ext)
            if cand:
                return cand
    return bin_name


def normalize_shell_cmd(cmd_str: str) -> str:
    """Translate ./mvnw and ./gradlew to Windows equivalents when running on Windows."""
    if os.name == "nt":
        cmd_str = re.sub(r"(^|\s)\./mvnw(\s|$)", r"\1mvnw.cmd\2", cmd_str)
        cmd_str = re.sub(r"(^|\s)\./gradlew(\s|$)", r"\1gradlew.bat\2", cmd_str)
    return cmd_str


class TelemetryTracker:
    def __init__(self, requirement: str, source: str = "chat", req_id: str = "REQ-001", mode: str = "live"):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.folder_provider = LocalFolderProvider()
        self.data = {
            "project": Path.cwd().name,
            "req_id": req_id,
            "requirement": requirement,
            "source": source,
            "mode": mode,
            "status": "INITIALIZING",
            "feature_branch": "feature/pending",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "requirements_queue": self.folder_provider.list_queue_status(),
            "tokens": {
                "input": 0,
                "output": 0,
                "total": 0,
                "claude_tokens": 0,
                "antigravity_tokens": 0,
                "estimated_cost_usd": 0.0,
                "traditional_8_agent_estimate": 0,
                "saved_tokens": 0,
                "savings_pct": 0.0,
            },
            "active_agents": {
                "planner": {"status": "IDLE", "story": None, "branch": None, "detail": "Waiting", "tokens": 0},
                "claude": {"status": "IDLE", "story": None, "branch": None, "detail": "Waiting", "tokens": 0},
                "antigravity": {"status": "IDLE", "story": None, "branch": None, "detail": "Waiting", "tokens": 0},
                "ci_gate": {"status": "IDLE", "story": None, "branch": None, "detail": "0-Token Runner", "tokens": 0},
                "reviewer": {"status": "IDLE", "story": None, "branch": None, "detail": "Diff-Only Auditor", "tokens": 0},
            },
            "locked_files": [],
            "stories": [],
            "events": [],
        }
        self.save()

    def save(self):
        with telemetry_lock:
            self.data["updated_at"] = now_iso()
            self.data["locked_files"] = sorted(list(locked_files))
            self.data["requirements_queue"] = self.folder_provider.list_queue_status()
            payload = json.dumps(self.data, indent=2)
            tmp = TELEMETRY_FILE.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            # Windows-safe atomic replace with retry in case dashboard is reading telemetry.json
            for _ in range(5):
                try:
                    tmp.replace(TELEMETRY_FILE)
                    break
                except PermissionError:
                    time.sleep(0.03)
            else:
                try:
                    TELEMETRY_FILE.write_text(payload, encoding="utf-8")
                except OSError:
                    pass

    def log_event(self, agent: str, message: str, level: str = "info", tokens_added: int = 0):
        with telemetry_lock:
            self.data["events"].insert(0, {
                "time": now_iso(),
                "agent": agent,
                "level": level,
                "message": message,
                "tokens": tokens_added,
            })
            self.data["events"] = self.data["events"][:80]
        self.save()

    def set_agent_state(self, agent_key: str, status: str, story: str | None = None, branch: str | None = None, detail: str = ""):
        with telemetry_lock:
            if agent_key in self.data["active_agents"]:
                ag = self.data["active_agents"][agent_key]
                ag["status"] = status
                ag["story"] = story
                ag["branch"] = branch
                ag["detail"] = detail
        self.save()

    def record_tokens(self, runner: str, agent_role: str, story_id: str | None, in_tok: int, out_tok: int):
        total = in_tok + out_tok
        with telemetry_lock:
            t = self.data["tokens"]
            t["input"] += in_tok
            t["output"] += out_tok
            t["total"] += total
            if runner == "claude":
                t["claude_tokens"] += total
            else:
                t["antigravity_tokens"] += total

            cost = (t["input"] * 0.000003) + (t["output"] * 0.000015)
            t["estimated_cost_usd"] = round(cost, 4)

            t["traditional_8_agent_estimate"] = int(t["total"] * 4.8)
            t["saved_tokens"] = max(0, t["traditional_8_agent_estimate"] - t["total"])
            t["savings_pct"] = round((t["saved_tokens"] / t["traditional_8_agent_estimate"]) * 100, 1) if t["traditional_8_agent_estimate"] else 0.0

            if agent_role in self.data["active_agents"]:
                self.data["active_agents"][agent_role]["tokens"] += total
            if runner in self.data["active_agents"] and agent_role == "developer":
                self.data["active_agents"][runner]["tokens"] += total

            if story_id:
                for s in self.data["stories"]:
                    if s["id"] == story_id:
                        s["input_tokens"] = s.get("input_tokens", 0) + in_tok
                        s["output_tokens"] = s.get("output_tokens", 0) + out_tok
                        s["total_tokens"] = s.get("total_tokens", 0) + total
                        break
        self.save()

    def update_story(self, story_id: str, **kwargs):
        with telemetry_lock:
            for s in self.data["stories"]:
                if s["id"] == story_id:
                    s.update(kwargs)
                    break
        self.save()


def run_cmd(
    cmd: list[str] | str, cwd: Path = Path("."), shell: bool = False, input_text: str | None = None
) -> tuple[int, str]:
    if isinstance(cmd, str):
        cmd = normalize_shell_cmd(cmd)
    elif isinstance(cmd, list) and cmd:
        cmd = [resolve_executable(cmd[0])] + cmd[1:]

    res = subprocess.run(
        cmd,
        cwd=cwd,
        shell=shell,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return res.returncode, (res.stdout + "\n" + res.stderr).strip()


def ensure_git_repo(tracker: TelemetryTracker):
    code, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
    if code != 0:
        tracker.log_event("HARNESS", "Empty non-git directory detected. Initializing git repository...", "warn")
        run_cmd(["git", "init", "-b", "main"])
    code, _ = run_cmd(["git", "rev-parse", "HEAD"])
    if code != 0:
        readme = Path("README.md")
        if not readme.exists():
            readme.write_text("# Project Initialized by Lean SDLC Harness\n", encoding="utf-8")
        run_cmd(["git", "add", "README.md"])
        run_cmd(["git", "commit", "-m", "chore: initial commit"])
        tracker.log_event("HARNESS", "Created initial commit on main branch.", "info")


def load_selective_skills(skill_names: list[str]) -> str:
    blocks = []
    common_dir = Path(".agents/rules/common")
    if common_dir.exists():
        rules_text = "\n".join(p.read_text(encoding="utf-8").strip() for p in sorted(common_dir.glob("*.md")))
        if rules_text:
            blocks.append(f"=== COMMON RULES ===\n{rules_text}")

    skill_texts = []
    for name in skill_names:
        skill_path = Path(f".agents/skills/{name}/SKILL.md")
        if skill_path.exists():
            skill_texts.append(skill_path.read_text(encoding="utf-8").strip())
    if skill_texts:
        blocks.append("=== ACTIVE SKILLS ===\n" + "\n\n".join(skill_texts))
    return "\n\n".join(blocks)


# Stack coding standards always injected for a story, based on the files it touches,
# regardless of which (max 3) skills the planner selected.
BASELINE_SKILLS_BY_EXT = {
    ".java": ["java-coding-standards"],
    ".py": ["python-patterns"],
    ".ts": ["coding-standards"],
    ".tsx": ["coding-standards"],
    ".js": ["coding-standards"],
    ".jsx": ["coding-standards"],
    ".mjs": ["coding-standards"],
    ".cjs": ["coding-standards"],
}

# Backend stacks that get layered architecture + logging baselines. A stack is detected from the
# requirement text or from a tracked build file. Its skills go to the planner (which decides the
# package paths in `files_to_modify`) and to every developer/reviewer touching its file types.
# To support another backend, add an entry here plus its `<stack>-layered-architecture` skill.
BACKEND_STACKS = {
    "spring-boot": {
        "exts": (".java",),
        "skills": ["springboot-layered-architecture", "backend-logging"],
        "requirement_re": r"spring[\s-]?boot",
        "build_files": ("pom.xml", "build.gradle", "build.gradle.kts"),
        "build_markers": ("spring-boot",),
    },
    "python-web": {
        "exts": (".py",),
        "skills": ["python-layered-architecture", "backend-logging"],
        "requirement_re": r"\b(fastapi|flask|django|python\s+(backend|api|service|server|web\s*app))\b",
        "build_files": ("requirements.txt", "pyproject.toml", "Pipfile", "setup.cfg"),
        "build_markers": ("fastapi", "flask", "django", "starlette"),
    },
}


def detect_backend_stacks(requirement_text: str = "") -> list[str]:
    """Return BACKEND_STACKS keys that the requirement mentions or a tracked build file declares."""
    _, out = run_cmd(["git", "ls-files"])
    tracked = out.splitlines()
    stacks = []
    for name, spec in BACKEND_STACKS.items():
        hit = bool(re.search(spec["requirement_re"], requirement_text, re.IGNORECASE))
        for f in tracked if not hit else []:
            if Path(f).name not in spec["build_files"]:
                continue
            try:
                text = Path(f).read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            if any(m in text for m in spec["build_markers"]):
                hit = True
                break
        if hit:
            stacks.append(name)
    return stacks


def stack_skills(stacks: list[str]) -> list[str]:
    skills: list[str] = []
    for name in stacks:
        skills += [s for s in BACKEND_STACKS[name]["skills"] if s not in skills]
    return skills


def baseline_skills_for(files: list[str], stacks: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for f in files:
        suffix = Path(f).suffix.lower()
        names = list(BASELINE_SKILLS_BY_EXT.get(suffix, []))
        for name in stacks or []:
            if suffix in BACKEND_STACKS[name]["exts"]:
                names += BACKEND_STACKS[name]["skills"]
        for skill in names:
            if skill not in found and Path(f".agents/skills/{skill}/SKILL.md").exists():
                found.append(skill)
    return found


def apply_baseline_skills(story: dict, stacks: list[str] | None = None) -> list[str]:
    """Append file-type baseline skills to story['skills'] and return the ones newly added.
    The full baseline set is kept in story['baseline_skills'] for the reviewer."""
    baselines = baseline_skills_for(story.get("files_to_modify", []), stacks)
    skills = list(story.get("skills", []))
    added = [s for s in baselines if s not in skills]
    story["skills"] = skills + added
    story["baseline_skills"] = baselines
    return added


def get_compact_repo_map() -> str:
    _, out = run_cmd(["git", "ls-files"])
    lines = [
        f for f in out.splitlines()
        if not f.startswith((".agents/", ".sdlc/", ".worktrees/", "requirements/", "node_modules/", "target/", "dist/"))
    ]
    return "\n".join(lines[:250]) if lines else "(empty repository - create new files as needed)"


def call_llm_agent(
    runner: str,
    role_file: str,
    prompt: str,
    skills: list[str],
    cwd: Path,
    allow_edits: bool,
    tracker: TelemetryTracker,
    story_id: str | None = None,
) -> str:
    role_prompt = Path(f".agents/agents/{role_file}").read_text(encoding="utf-8").strip()
    skills_block = load_selective_skills(skills)
    full_prompt = f"{role_prompt}\n\n{skills_block}\n\n=== TASK ===\n{prompt}"

    in_tokens = estimate_tokens(full_prompt)

    if runner == "antigravity" and not shutil.which(resolve_executable(ANTIGRAVITY_BIN)):
        tracker.log_event("HARNESS", f"'{ANTIGRAVITY_BIN}' CLI not found; falling back to Claude for {role_file}.", "warn")
        runner = "claude"

    stdin_text = None
    if runner == "claude":
        # Prompt goes over stdin: Windows caps a command line at ~32K chars, which full diffs exceed.
        cmd = [CLAUDE_BIN, "-p", "Follow the instructions provided on standard input.", "--output-format", "text"]
        cmd.extend(["--allowedTools", "Edit,Write,Read" if allow_edits else "Read"])
        stdin_text = full_prompt
    elif runner == "antigravity":
        cmd = [ANTIGRAVITY_BIN, "-p", full_prompt]
        if allow_edits:
            cmd.append("--yolo")
    else:
        raise ValueError(f"Unknown runner: {runner}")

    code, out = run_cmd(cmd, cwd=cwd, input_text=stdin_text)
    out_tokens = estimate_tokens(out)
    role_key = role_file.replace(".md", "")
    tracker.record_tokens(runner, role_key, story_id, in_tokens, out_tokens)

    if code != 0:
        raise RuntimeError(f"[{runner}] {role_file} failed:\n{out[-1200:]}")
    return out


def extract_json(raw: str) -> dict:
    clean = raw.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1:
        clean = clean[start : end + 1]
    return json.loads(clean)


MAX_REVIEW_CHUNK_CHARS = int(os.environ.get("SDLC_REVIEW_CHUNK_CHARS", "60000"))


def _split_lines(text: str, limit: int) -> list[str]:
    pieces, cur, size = [], [], 0
    for line in text.splitlines(keepends=True):
        if cur and size + len(line) > limit:
            pieces.append("".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line)
    if cur:
        pieces.append("".join(cur))
    return pieces


def chunk_diff(diff: str, limit: int = MAX_REVIEW_CHUNK_CHARS) -> list[str]:
    """Split a git diff into chunks of at most ~limit chars, keeping whole files together where possible.
    Nothing is dropped: an oversized single-file diff is split on line boundaries."""
    files = [p for p in re.split(r"(?m)^(?=diff --git )", diff) if p.strip()]
    chunks, cur = [], ""
    for part in files:
        for piece in (_split_lines(part, limit) if len(part) > limit else [part]):
            if cur and len(cur) + len(piece) > limit:
                chunks.append(cur)
                cur = ""
            cur += piece
    if cur:
        chunks.append(cur)
    return chunks


def review_diff(
    story: dict, diff: str, changed_files: str, reviewer_runner: str,
    rev_skills: list[str], wt_dir: Path, tracker: TelemetryTracker,
) -> tuple[bool, str]:
    """Review the complete diff, one call per chunk. Approved only if every chunk is approved."""
    chunks = chunk_diff(diff)
    rejections, approvals = [], []
    for i, chunk in enumerate(chunks, 1):
        part_note = ""
        if len(chunks) > 1:
            part_note = (
                f"DIFF PART {i} of {len(chunks)}: the other parts are reviewed separately. Judge the code in this "
                "part; use CHANGED FILES to judge story-wide criteria such as whether tests exist.\n"
            )
        prompt = (
            f"STORY:\n{json.dumps(story)}\n\nCHANGED FILES:\n{changed_files}\n\n"
            f"{part_note}GIT DIFF:\n{chunk}"
        )
        review = extract_json(call_llm_agent(
            reviewer_runner, "reviewer.md", prompt, rev_skills, wt_dir, False, tracker, story["id"]
        ))
        prefix = f"[part {i}/{len(chunks)}] " if len(chunks) > 1 else ""
        if review.get("approved", False):
            approvals.append(prefix + str(review.get("feedback", "Clean & secure")))
        else:
            rejections.append(prefix + str(review.get("feedback", "Rejected without feedback.")))
    if rejections:
        return False, "\n".join(rejections)
    return True, "\n".join(approvals)


def acquire_file_locks(files: list[str]) -> bool:
    with active_files_lock:
        if any(f in locked_files for f in files):
            return False
        locked_files.update(files)
        return True


def release_file_locks(files: list[str]):
    with active_files_lock:
        for f in files:
            locked_files.discard(f)


def execute_story_live(story: dict, feature_branch: str, tracker: TelemetryTracker) -> str:
    story_id = story["id"]
    runner = story.get("runner", "claude")
    skills = story.get("skills", [])
    target_files = story.get("files_to_modify", [])
    delete_files = story.get("files_to_delete", [])
    wt_dir = (WORKTREES_DIR / story_id).resolve()
    branch_name = f"story/{story_id}"

    with git_lock:
        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
        run_cmd(["git", "worktree", "add", "-B", branch_name, str(wt_dir), feature_branch])

    if delete_files:
        # Developer agents only have Edit/Write/Read, so moves/renames need the harness to delete the old path.
        run_cmd(["git", "rm", "-q", "--ignore-unmatch", "--"] + delete_files, cwd=wt_dir)
        tracker.log_event("HARNESS", f"[{story_id}] Deleted {delete_files} in worktree (moved/removed by plan).")

    tracker.update_story(story_id, status="CODING", branch=branch_name, started_at=now_iso())
    tracker.set_agent_state(
        runner, "WORKING", story=story_id, branch=branch_name,
        detail=f"Editing {', '.join(target_files[:2])} | Skills: {', '.join(skills)}"
    )
    tracker.log_event(runner.upper(), f"[{story_id}] Started in worktree {branch_name} with skills {skills}")

    feedback = ""
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            tracker.update_story(story_id, retries=attempt - 1, status="CODING")
            dev_prompt = (
                f"STORY:\n{json.dumps(story, indent=2)}\n"
                f"STRICT SCOPE: Read and modify ONLY {target_files}.\n"
            )
            if delete_files:
                dev_prompt += f"ALREADY DELETED BY THE HARNESS (do not recreate; update references): {delete_files}\n"
            if feedback:
                dev_prompt += f"\nPREVIOUS FAILURE TO FIX:\n{feedback[-4000:]}"

            call_llm_agent(runner, "developer.md", dev_prompt, skills, wt_dir, True, tracker, story_id)

            tracker.update_story(story_id, status="CI_GATE")
            tracker.set_agent_state("ci_gate", "RUNNING", story=story_id, branch=branch_name, detail=story["test_cmd"])
            code, test_out = run_cmd(story["test_cmd"], cwd=wt_dir, shell=True)
            tracker.set_agent_state("ci_gate", "IDLE", detail="0-Token Runner")

            if code != 0:
                tracker.log_event("CI-GATE", f"[{story_id}] Test failed on attempt {attempt}. Feeding tail to {runner}.", "warn")
                feedback = f"Command `{story['test_cmd']}` failed:\n{test_out}"
                continue

            tracker.log_event("CI-GATE", f"[{story_id}] Deterministic tests passed (0 tokens used).", "success")

            run_cmd(["git", "add", "-N", "."], cwd=wt_dir)
            # Diff against the worktree's own base commit (HEAD), not the feature branch tip:
            # stories merged meanwhile would otherwise show up as deletions in this diff.
            _, diff = run_cmd(["git", "diff", "HEAD"], cwd=wt_dir)
            if not diff.strip():
                raise RuntimeError(f"[{story_id}] Developer made no file modifications.")

            reviewer_runner = "antigravity" if runner == "claude" else "claude"
            tracker.update_story(story_id, status="REVIEWING")
            tracker.set_agent_state(
                "reviewer", "AUDITING", story=story_id, branch=branch_name,
                detail=f"{reviewer_runner.upper()} auditing git diff ({len(diff.splitlines())} lines)"
            )

            _, changed_files = run_cmd(["git", "diff", "HEAD", "--name-status"], cwd=wt_dir)
            rev_skills = ["security-review"] + skills[:1]
            rev_skills += [s for s in story.get("baseline_skills", []) if s not in rev_skills]
            approved, review_notes = review_diff(
                story, diff, changed_files, reviewer_runner, rev_skills, wt_dir, tracker
            )
            tracker.set_agent_state("reviewer", "IDLE", detail="Diff-Only Auditor")

            if not approved:
                tracker.log_event(
                    f"REVIEWER ({reviewer_runner.upper()})",
                    f"[{story_id}] Rejected diff: {review_notes}",
                    "warn"
                )
                feedback = f"Reviewer rejected diff:\n{review_notes}"
                continue

            tracker.log_event(
                f"REVIEWER ({reviewer_runner.upper()})",
                f"[{story_id}] Approved diff: {review_notes}",
                "success"
            )

            with git_lock:
                run_cmd(["git", "add", "."], cwd=wt_dir)
                run_cmd(["git", "commit", "-m", f"feat({story_id}): {story['title']} [{runner}]"], cwd=wt_dir)
                run_cmd(["git", "checkout", feature_branch])
                run_cmd(["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"])

            tracker.update_story(story_id, status="MERGED", completed_at=now_iso())
            tracker.set_agent_state(runner, "IDLE", detail="Completed " + story_id)
            tracker.log_event("GIT-MERGE", f"[{story_id}] Merged {branch_name} -> {feature_branch}", "success")
            return story_id

        tracker.update_story(story_id, status="FAILED")
        raise RuntimeError(f"[{story_id}] Failed after {MAX_RETRIES} attempts.")
    finally:
        release_file_locks(target_files + delete_files)
        tracker.set_agent_state(runner, "IDLE", detail="Idle")
        with git_lock:
            run_cmd(["git", "worktree", "remove", "--force", str(wt_dir)])


def run_demo_simulation(req_item: RequirementItem, tracker: TelemetryTracker):
    tracker.data["status"] = "PLANNING"
    slug = re.sub(r"[^a-z0-9]+", "-", req_item.req_id.lower()).strip("-")
    tracker.data["feature_branch"] = f"feature/{slug}"
    tracker.set_agent_state("planner", "PLANNING", detail=f"Decomposing [{req_item.req_id}] from {req_item.source.upper()}...")
    tracker.log_event(
        "INTAKE",
        f"Picked up [{req_item.req_id}] '{req_item.title}' from source: {req_item.source.upper()}",
        "info",
    )
    time.sleep(1.2)

    mvn_bin = "mvnw.cmd" if os.name == "nt" else "./mvnw"
    demo_stories = [
        {
            "id": "STORY-001",
            "title": "Spring Boot REST Controller, JPA Entity & Postgres Migration",
            "runner": "claude",
            "skills": ["springboot-patterns", "jpa-patterns", "springboot-security", "postgres-patterns"],
            "files_to_modify": [
                "backend/src/main/java/com/app/OrderController.java",
                "backend/src/main/java/com/app/OrderEntity.java",
                "backend/src/main/resources/db/migration/V1__orders.sql"
            ],
            "test_cmd": f"{mvn_bin} test -Dtest=OrderControllerTest",
            "status": "PENDING",
            "branch": "story/STORY-001",
            "retries": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        {
            "id": "STORY-002",
            "title": "React / Angular UI View, State Hook & Component Tests",
            "runner": "antigravity",
            "skills": ["frontend-patterns", "frontend-design", "coding-standards"],
            "files_to_modify": [
                "frontend/src/features/orders/OrdersTable.tsx",
                "frontend/src/features/orders/OrdersTable.test.tsx"
            ],
            "test_cmd": "npm test -- OrdersTable.test.tsx",
            "status": "PENDING",
            "branch": "story/STORY-002",
            "retries": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        {
            "id": "STORY-003",
            "title": "Redis Cache-Aside Layer & Rate Limiter Service",
            "runner": "claude",
            "skills": ["backend-patterns", "springboot-tdd", "security-review"],
            "files_to_modify": [
                "backend/src/main/java/com/app/OrderCacheService.java",
                "backend/src/test/java/com/app/OrderCacheServiceTest.java"
            ],
            "test_cmd": f"{mvn_bin} test -Dtest=OrderCacheServiceTest",
            "status": "PENDING",
            "branch": "story/STORY-003",
            "retries": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        {
            "id": "STORY-004",
            "title": "Python Audit Exporter & Pytest Suite",
            "runner": "antigravity",
            "skills": ["python-patterns", "python-testing", "api-design"],
            "files_to_modify": [
                "workers/audit_exporter.py",
                "workers/tests/test_audit_exporter.py"
            ],
            "test_cmd": "pytest workers/tests/test_audit_exporter.py",
            "status": "PENDING",
            "branch": "story/STORY-004",
            "retries": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    ]

    tracker.data["stories"] = demo_stories
    tracker.record_tokens("claude", "planner", None, 920, 410)
    tracker.set_agent_state("planner", "IDLE", detail="Planned 4 parallel stories")
    tracker.log_event("PLANNER", "Generated 4 disjoint-file stories across Claude & Antigravity.", "success", 1330)
    tracker.data["status"] = "EXECUTING_PARALLEL_WAVE_1"
    tracker.save()

    def sim_worker(story: dict, delay_offset: float):
        sid = story["id"]
        runner = story["runner"]
        files = story["files_to_modify"]
        skills = story["skills"]
        branch = story["branch"]

        acquire_file_locks(files)
        try:
            time.sleep(delay_offset)
            tracker.update_story(sid, status="CODING")
            tracker.set_agent_state(
                runner, "WORKING", story=sid, branch=branch,
                detail=f"Coding {Path(files[0]).name} (+{len(files)-1} files) | Skills: {', '.join(skills[:2])}"
            )
            tracker.log_event(runner.upper(), f"[{sid}] Checked out worktree `{branch}`. Loaded skills: {skills}")
            time.sleep(1.8)
            tracker.record_tokens(runner, "developer", sid, 1450, 890)
            tracker.log_event(runner.upper(), f"[{sid}] Completed surgical edits on {len(files)} target files.", "info", 2340)

            tracker.update_story(sid, status="CI_GATE")
            tracker.set_agent_state("ci_gate", "RUNNING", story=sid, branch=branch, detail=f"Running: {story['test_cmd']}")
            time.sleep(1.1)
            tracker.set_agent_state("ci_gate", "IDLE", detail="0-Token Runner")
            tracker.log_event("CI-GATE", f"[{sid}] `{story['test_cmd']}` passed (0 LLM tokens).", "success")

            reviewer_runner = "antigravity" if runner == "claude" else "claude"
            tracker.update_story(sid, status="REVIEWING")
            tracker.set_agent_state(
                "reviewer", "AUDITING", story=sid, branch=branch,
                detail=f"{reviewer_runner.upper()} auditing git diff for {sid}"
            )
            time.sleep(1.2)
            tracker.record_tokens(reviewer_runner, "reviewer", sid, 620, 140)
            tracker.set_agent_state("reviewer", "IDLE", detail="Diff-Only Auditor")
            tracker.log_event(
                f"REVIEWER ({reviewer_runner.upper()})",
                f"[{sid}] Diff approved (OWASP + acceptance criteria verified).",
                "success", 760
            )

            tracker.update_story(sid, status="MERGED")
            tracker.set_agent_state(runner, "IDLE", detail=f"Merged {sid}")
            tracker.log_event("GIT-MERGE", f"[{sid}] Worktree `{branch}` merged into `{tracker.data['feature_branch']}`.", "success")
        finally:
            release_file_locks(files)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(sim_worker, demo_stories[0], 0.2)
        f2 = pool.submit(sim_worker, demo_stories[1], 0.5)
        f1.result()
        f2.result()

    tracker.data["status"] = "EXECUTING_PARALLEL_WAVE_2"
    tracker.save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f3 = pool.submit(sim_worker, demo_stories[2], 0.2)
        f4 = pool.submit(sim_worker, demo_stories[3], 0.4)
        f3.result()
        f4.result()

    tracker.data["status"] = "COMPLETED"
    tracker.log_event("QA-GATE", f"All stories for [{req_item.req_id}] merged into `{tracker.data['feature_branch']}`!", "success")
    tracker.save()


def process_requirement_item(
    req_item: RequirementItem,
    provider: BaseRequirementProvider,
    planner_runner: str,
    demo: bool,
):
    tracker = TelemetryTracker(
        requirement=f"[{req_item.req_id}] {req_item.title}",
        source=req_item.source,
        req_id=req_item.req_id,
        mode="demo" if demo else "live",
    )
    provider.mark_in_progress(req_item)
    tracker.save()

    try:
        if demo:
            run_demo_simulation(req_item, tracker)
            provider.mark_completed(req_item, tracker.data["feature_branch"], "Completed in demo simulation mode.")
            tracker.save()
            return

        ensure_git_repo(tracker)
        tracker.data["status"] = "PLANNING"
        tracker.set_agent_state("planner", "PLANNING", detail=f"Planning [{req_item.req_id}] from {req_item.source.upper()}...")
        tracker.log_event(
            "INTAKE",
            f"Picked up [{req_item.req_id}] ({req_item.source.upper()}): {req_item.title}",
            "info",
        )

        available_skills = sorted([p.parent.name for p in Path(".agents/skills").glob("*/SKILL.md")])
        repo_map = get_compact_repo_map()
        plan_prompt = (
            f"AVAILABLE SKILLS CATALOG:\n{available_skills}\n\n"
            f"REPOSITORY FILE MAP:\n{repo_map}\n\n"
            f"FEATURE REQUIREMENT ({req_item.req_id}):\n{req_item.full_prompt}"
        )

        stacks = detect_backend_stacks(req_item.full_prompt)
        if stacks:
            tracker.log_event("HARNESS", f"Detected backend stack(s) {stacks}; enforcing {stack_skills(stacks)}.")
        planner_skills = ["api-design", "strategic-compact"]
        planner_skills += [s for s in stack_skills(stacks) if Path(f".agents/skills/{s}/SKILL.md").exists()]
        raw_plan = call_llm_agent(
            planner_runner, "planner.md", plan_prompt,
            planner_skills, Path("."), False, tracker
        )
        plan = extract_json(raw_plan)
        feature_branch = plan.get("feature_branch", f"feature/{req_item.req_id.lower()}")
        stories = plan.get("stories", [])

        for s in stories:
            added = apply_baseline_skills(s, stacks)
            if added:
                tracker.log_event("HARNESS", f"[{s['id']}] Added baseline skills {added} from file types.")
            s.setdefault("status", "PENDING")
            s.setdefault("branch", f"story/{s['id']}")
            s.setdefault("retries", 0)
            s.setdefault("input_tokens", 0)
            s.setdefault("output_tokens", 0)
            s.setdefault("total_tokens", 0)

        tracker.data["feature_branch"] = feature_branch
        tracker.data["stories"] = stories
        tracker.set_agent_state("planner", "IDLE", detail=f"Created {len(stories)} stories")
        tracker.log_event("PLANNER", f"Created {len(stories)} stories on `{feature_branch}`.", "success")

        run_cmd(["git", "checkout", "-B", feature_branch])
        tracker.data["status"] = "EXECUTING_STORIES"
        tracker.save()

        pending = list(stories)
        while pending:
            batch = []
            remaining = []
            for s in pending:
                if acquire_file_locks(s.get("files_to_modify", []) + s.get("files_to_delete", [])):
                    batch.append(s)
                else:
                    remaining.append(s)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(execute_story_live, s, feature_branch, tracker): s for s in batch}
                for fut in as_completed(futures):
                    fut.result()

            pending = remaining

        qa_cmd = plan.get("qa_command", "")
        if qa_cmd:
            tracker.set_agent_state("ci_gate", "RUNNING", detail=f"Final QA: {qa_cmd}")
            code, qa_out = run_cmd(qa_cmd, shell=True)
            tracker.set_agent_state("ci_gate", "IDLE", detail="0-Token Runner")
            if code == 0:
                tracker.log_event("QA-GATE", f"Final QA build passed on `{feature_branch}`!", "success")
            else:
                tracker.log_event("QA-GATE", f"Final QA warning: {qa_out[-400:]}", "warn")

        tracker.data["status"] = "COMPLETED"
        provider.mark_completed(
            req_item,
            feature_branch,
            f"Merged {len(stories)} stories. Total tokens: {tracker.data['tokens']['total']}",
        )
        tracker.save()
        print(f"🎉 [{req_item.req_id}] completed on `{feature_branch}`! Total tokens: {tracker.data['tokens']['total']}")
    except Exception as exc:
        tracker.data["status"] = "FAILED"
        tracker.log_event("HARNESS", f"[{req_item.req_id}] Failed: {exc}", "warn")
        provider.mark_failed(req_item, str(exc))
        tracker.save()
        raise


def build_provider(source: str, requirement_arg: str | None) -> BaseRequirementProvider:
    if source == "folder":
        return LocalFolderProvider()
    if source == "github":
        return GitHubProjectProvider()
    if source == "jira":
        return JiraProvider()
    if not requirement_arg:
        folder_prov = LocalFolderProvider()
        if folder_prov.fetch_next():
            return folder_prov
        requirement_arg = "Build full-stack User Auth with Spring Boot, Postgres, Redis & React"
    return ChatInputProvider(requirement_arg)


def main():
    parser = argparse.ArgumentParser(description="Lean Parallel SDLC Harness v3 (Cross-Platform)")
    parser.add_argument("requirement", nargs="?", default=None, help="Direct requirement string (from chat or CLI)")
    parser.add_argument(
        "--source",
        choices=["auto", "chat", "folder", "github", "jira"],
        default="auto",
        help="Requirement source provider",
    )
    parser.add_argument("--from-folder", action="store_true", help="Process files in requirements/inbox/")
    parser.add_argument("--watch", action="store_true", help="Continuously watch requirements/inbox/")
    parser.add_argument("--demo", action="store_true", help="Run visual simulation mode (0 API tokens)")
    parser.add_argument("--planner-runner", default="claude", choices=["claude", "antigravity"])
    args = parser.parse_args()

    source = "folder" if (args.from_folder or args.watch) else args.source
    if source == "auto":
        source = "chat" if args.requirement else "folder"

    if args.watch:
        folder_provider = LocalFolderProvider()
        print("👀 Watching `requirements/inbox/` for new .md / .txt / .json files (Ctrl+C to stop)...")
        while True:
            items = folder_provider.fetch_next()
            for item in items:
                print(f"📥 Picked up {item.file_path} -> [{item.req_id}] {item.title}")
                process_requirement_item(item, folder_provider, args.planner_runner, args.demo)
            time.sleep(3)

    provider = build_provider(source, args.requirement)
    items = provider.fetch_next()

    if not items and source == "folder" and args.demo:
        items = [
            RequirementItem(
                req_id="REQ-DEMO",
                title="Spring Boot Order API + Redis Cache + React Order Table",
                body="Create OrderController, JPA Entity, Redis cache, and React OrdersTable.",
                source="folder",
            )
        ]

    if not items:
        print(f"ℹ️ No pending requirements found for source='{provider.source_name}'.")
        print("   Drop a .md/.txt/.json file into `requirements/inbox/` or pass a requirement via `/sdlc <text>`.")
        return

    for item in items:
        process_requirement_item(item, provider, args.planner_runner, args.demo)


if __name__ == "__main__":
    main()
