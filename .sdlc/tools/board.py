#!/usr/bin/env python3
"""Local Jira replacement: tickets are markdown files with frontmatter under .sdlc/board/.

Agents MUST change ticket status through `move` so transitions are validated and
logged. Run `python .sdlc/tools/board.py -h` for commands.

Works from the main checkout or from any git worktree: the board always lives in
the main checkout, so every developer worktree shares one board.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def _main_root() -> Path:
    here = Path(__file__).resolve().parents[2]
    if (here / ".git").is_file():  # inside a linked worktree -> resolve the main checkout
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=here, capture_output=True, text=True).stdout.strip()
        if common:
            return Path(common).parent
    return here


ROOT = _main_root()
SDLC = ROOT / ".sdlc"
BOARD = SDLC / "board"
TEMPLATES = SDLC / "templates"
CONFIG = SDLC / "config.json"
IS_TEMPLATE = (ROOT / "install.py").exists() and not (SDLC / "manifest.json").exists()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def check_project(mutating: bool = True):
    """Agents start in the session's cwd, which may not be the project. Refuse the wrong board."""
    env = os.environ.get("SDLC_ROOT")
    if env and Path(env).resolve() != ROOT.resolve():
        sys.exit(f"SDLC_ROOT is {env} but this tool belongs to {ROOT}. "
                 f"Run `python <project>/.sdlc/tools/...` of the project you mean.")
    if IS_TEMPLATE and mutating and os.environ.get("SDLC_ALLOW_TEMPLATE") != "1":
        sys.exit(f"{ROOT} is the harness TEMPLATE, not a project. cd into the target project "
                 f"(or set SDLC_ALLOW_TEMPLATE=1 to use the template's own board).")


_lock_depth = 0


@contextlib.contextmanager
def board_lock(timeout: float = 60):
    """Cross-process lock for board writes (parallel agents edit the same tickets). Re-entrant."""
    global _lock_depth
    lock = BOARD / ".lock"
    if _lock_depth or not BOARD.exists():
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 120:  # stale lock from a killed process
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                sys.exit(f"board is locked by another process ({lock}); retry, or delete the file if it is stale")
            time.sleep(0.1)
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


def locked(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with board_lock():
            return fn(*a, **kw)
    return wrapper

# prefix -> (folder, template, id digits)
TYPES = {
    "REQ": ("requirements", "requirement.md", 3),
    "STORY": ("stories", "story.md", 3),
    "BUG": ("bugs", "bug.md", 3),
    "PR": ("prs", "pr.md", 3),
    "SPRINT": ("sprints", "sprint.md", 2),
    "QA": ("qa", "qa-release.md", 2),
}

STORY_ACTIVE = ["OPEN", "ANALYSIS", "IN_PROGRESS", "IN_REVIEW", "CHANGES_REQUESTED", "MERGED", "IN_QA", "REOPENED"]
BUG_ACTIVE = ["OPEN", "TRIAGED", "IN_PROGRESS", "IN_REVIEW", "CHANGES_REQUESTED", "MERGED", "RETEST", "REOPENED"]

TRANSITIONS = {
    "REQ": {
        "NEW": ["REFINED", "ON_HOLD", "REJECTED"],
        "REFINED": ["GROOMED", "NEW", "ON_HOLD", "REJECTED"],
        "GROOMED": ["IN_DELIVERY", "REFINED", "ON_HOLD"],
        "IN_DELIVERY": ["DONE", "ON_HOLD"],
        "ON_HOLD": ["NEW", "REFINED", "GROOMED", "IN_DELIVERY"],
        "DONE": [], "REJECTED": [],
    },
    "STORY": {
        "DRAFT": ["READY"],
        "READY": ["OPEN", "DRAFT"],
        "OPEN": ["ANALYSIS", "READY", "BLOCKED"],
        "ANALYSIS": ["IN_PROGRESS", "BLOCKED"],
        "IN_PROGRESS": ["IN_REVIEW", "BLOCKED"],
        "IN_REVIEW": ["CHANGES_REQUESTED", "MERGED", "BLOCKED"],
        "CHANGES_REQUESTED": ["IN_PROGRESS", "BLOCKED"],
        "MERGED": ["IN_QA"],
        "IN_QA": ["DONE", "REOPENED", "BLOCKED"],
        "REOPENED": ["ANALYSIS", "IN_PROGRESS"],
        "BLOCKED": STORY_ACTIVE,
        "DONE": [],
    },
    "BUG": {
        "OPEN": ["TRIAGED", "REJECTED"],
        "TRIAGED": ["IN_PROGRESS", "REJECTED", "BLOCKED"],
        "IN_PROGRESS": ["IN_REVIEW", "BLOCKED"],
        "IN_REVIEW": ["CHANGES_REQUESTED", "MERGED", "BLOCKED"],
        "CHANGES_REQUESTED": ["IN_PROGRESS"],
        "MERGED": ["RETEST"],
        "RETEST": ["CLOSED", "REOPENED"],
        "REOPENED": ["IN_PROGRESS"],
        "BLOCKED": BUG_ACTIVE,
        "CLOSED": [], "REJECTED": [],
    },
    "PR": {
        "OPEN": ["CHANGES_REQUESTED", "APPROVED", "CLOSED"],
        "CHANGES_REQUESTED": ["OPEN", "CLOSED"],
        "APPROVED": ["MERGED", "OPEN", "CLOSED"],
        "MERGED": [], "CLOSED": [],
    },
    "SPRINT": {
        "PLANNED": ["ACTIVE"],
        "ACTIVE": ["IN_QA", "CLOSED"],
        "IN_QA": ["CLOSED", "ACTIVE"],
        "CLOSED": [],
    },
    "QA": {
        "BUILDING": ["IN_TEST", "FAILED"],
        "IN_TEST": ["PASSED", "FAILED"],
        "FAILED": ["BUILDING"],
        "PASSED": [],
    },
}

FIB = {1, 2, 3, 5, 8}
DEV_COMPLETE = ("MERGED", "IN_QA", "DONE")
SECURITY_WORDS = re.compile(r"\b(passwords?|tokens?|sessions?|auth\w*|log ?in|logout|sign[- ]?in|jwt|secrets?|pii|"
                            r"credentials?|cookies?|encrypt\w*|permissions?|roles?)\b", re.I)
COMMENT_PREFIX = {"security-reviewer": "S", "devops-engineer": "G", "qa-engineer": "Q"}  # default C (code review)
COMMENT_STATUSES = ("open", "fixed", "verified", "wont-fix", "follow-up")
STORY_FLOW = ["OPEN", "ANALYSIS", "IN_PROGRESS", "IN_REVIEW", "CHANGES_REQUESTED", "BLOCKED", "MERGED", "IN_QA", "REOPENED", "DONE"]


# ---------------------------------------------------------------- file model
class Ticket:
    def __init__(self, path: Path):
        self.path = path
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.S)
        if not m:
            raise ValueError(f"{path}: missing frontmatter")
        self.fields: dict[str, object] = {}
        for line in m.group(1).splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, _, raw = line.partition(":")
            self.fields[key.strip()] = parse_value(raw.strip())
        self.body = m.group(2)

    @property
    def id(self) -> str:
        return str(self.fields.get("id", ""))

    @property
    def kind(self) -> str:
        return self.id.split("-")[0]

    def get(self, key, default=""):
        return self.fields.get(key, default)

    def save(self):
        lines = [f"{k}: {format_value(v)}" for k, v in self.fields.items()]
        self.path.write_text("---\n" + "\n".join(lines) + "\n---\n" + self.body, encoding="utf-8")

    def log(self, message: str):
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- {stamp} · {message}\n"
        if "## Activity" not in self.body:
            self.body = self.body.rstrip() + "\n\n## Activity\n"
        if not self.body.endswith("\n"):
            self.body += "\n"
        self.body += entry

    def section(self, title: str) -> str:
        m = re.search(rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)", self.body, re.S | re.M)
        if not m:
            return ""
        # drop template placeholder lines like "_Filled by ..._"
        return "\n".join(l for l in m.group(1).splitlines() if not re.fullmatch(r"\s*_.*_\s*", l)).strip()

    def set_section(self, title: str, text: str, append: bool = False):
        """Replace (or append to) the body of `## title`; creates it before ## Activity if missing."""
        text = text.strip("\n") + "\n"
        m = re.search(rf"^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)", self.body, re.S | re.M)
        if m:
            old = m.group(1)
            if append:
                kept = "\n".join(l for l in old.rstrip().splitlines() if not re.fullmatch(r"\s*_.*_\s*", l)).strip("\n")
                new = (kept + "\n" if kept else "") + text
            else:
                new = text
            self.body = self.body[:m.start(1)] + new + "\n" + self.body[m.end(1):].lstrip("\n")
        else:
            block = f"## {title}\n{text}\n"
            i = self.body.find("## Activity")
            self.body = (self.body[:i] + block + self.body[i:]) if i >= 0 else self.body.rstrip() + "\n\n" + block

    def comment_rows(self) -> list[list[str]]:
        """Rows of the '## Review comments' table: [id, cycle, reviewer, location, severity, comment, status]."""
        rows = []
        for line in self.section("Review comments").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 7 and re.fullmatch(r"[A-Z]\d+", cells[0]):
                rows.append(cells)
        return rows

    def open_comments(self, severities=("blocker", "major", "minor", "nit")) -> list[list[str]]:
        return [r for r in self.comment_rows() if r[-1].split()[0].lower() == "open" and r[4].lower() in severities]


def parse_value(raw: str):
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()] if inner else []
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r"\\(.)", r"\1", raw[1:-1])
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    return raw


def format_value(v) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    s = str(v)
    if re.search(r":\s|\s#|^[\s\[\]{}&*!|>'\"%@`,-]|\s$", s):  # would break YAML unquoted
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def all_tickets(kind: str | None = None) -> list[Ticket]:
    out = []
    kinds = [kind] if kind else list(TYPES)
    for k in kinds:
        folder = BOARD / TYPES[k][0]
        if folder.exists():
            for p in sorted(folder.glob(f"{k}-*.md")):
                out.append(Ticket(p))
    return out


def find(ticket_id: str) -> Ticket:
    ticket_id = ticket_id.upper()
    kind = ticket_id.split("-")[0]
    if kind not in TYPES:
        sys.exit(f"Unknown ticket type in '{ticket_id}'. Known: {', '.join(TYPES)}")
    for t in all_tickets(kind):
        if t.id == ticket_id:
            return t
    sys.exit(f"{ticket_id} not found under board/{TYPES[kind][0]}/")


def next_id(kind: str) -> str:
    kind = kind.upper()
    nums = [int(t.id.split("-")[1]) for t in all_tickets(kind) if t.id.split("-")[1].isdigit()]
    return f"{kind}-{(max(nums) + 1 if nums else 1):0{TYPES[kind][2]}d}"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "item"


# ---------------------------------------------------------------- guards
def check_guards(t: Ticket, target: str) -> list[str]:
    """Process rules that a plain state machine can't express."""
    problems: list[str] = []
    if t.kind == "STORY":
        if target == "READY":
            problems += definition_of_ready(t)
        if target == "OPEN" and t.get("sprint") in ("", "none"):
            problems.append("set `sprint` before moving to OPEN (sprint planning)")
        if target == "ANALYSIS" and t.get("assignee") in ("", "none"):
            problems.append("set `assignee` before starting analysis")
        if target == "IN_PROGRESS" and t.get("status") == "ANALYSIS" and len(t.section("Developer analysis")) < 40:
            problems.append("fill the '## Developer analysis' section first")
        if target == "IN_PROGRESS":
            problems += branch_ready(t)
        if target == "IN_REVIEW" and t.get("pr") in ("", "none"):
            problems.append("set `pr` (raise the PR) before moving to IN_REVIEW")
        if target == "MERGED":
            pr = find(str(t.get("pr")))
            if pr.get("status") != "MERGED":
                problems.append(f"{pr.id} is {pr.get('status')}, must be MERGED first")
        if target == "DONE":
            for b in all_tickets("BUG"):
                if b.get("story") == t.id and b.get("status") not in ("CLOSED", "REJECTED") and b.get("severity") in ("critical", "major"):
                    problems.append(f"open {b.get('severity')} bug {b.id} blocks DONE")
    if t.kind == "BUG" and target == "IN_REVIEW" and t.get("pr") in ("", "none"):
        problems.append("set `pr` before moving to IN_REVIEW")
    if t.kind == "BUG" and target == "IN_PROGRESS":
        problems += branch_ready(t)
    if t.kind in ("STORY", "BUG") and target == "IN_REVIEW" and t.get("pr") not in ("", "none"):
        pr = find(str(t.get("pr")))
        if pr.get("branch") != t.get("branch"):
            problems.append(f"{pr.id} branch '{pr.get('branch')}' differs from ticket branch '{t.get('branch')}'")
        if pr.get("base") != t.get("base"):
            problems.append(f"{pr.id} base '{pr.get('base')}' differs from ticket base '{t.get('base')}'")
    if t.kind == "PR" and target == "APPROVED":
        if t.get("gate") != "passed":
            problems.append(f"quality gate is '{t.get('gate')}', must be 'passed'")
        if t.get("code_review") != "approved":
            problems.append(f"code_review is '{t.get('code_review')}', must be 'approved'")
        if t.get("security_review") not in ("approved", "not-required"):
            problems.append(f"security_review is '{t.get('security_review')}'")
        if t.open_comments(("blocker", "major")):
            problems.append("blocker/major review comments are still open")
        # DoD: nothing reaches main with open review comments (minor/nit included)
        if t.get("base") == load_config().get("git", {}).get("main_branch", "main"):
            prs = [t] + [p for p in all_tickets("PR") if t.get("kind") == "feature" and p.id != t.id
                         and p.get("req") == t.get("req") and p.get("status") == "MERGED"]
            for p in prs:
                ids = [r[0] for r in p.open_comments()]
                if ids:
                    problems.append(f"{p.id} has open review comments {', '.join(ids)}: resolve them as "
                                    f"fixed / wont-fix / follow-up (`board.py resolve`) before merging to main")
    if t.kind == "REQ" and target == "GROOMED":
        stories = t.get("stories", []) or []
        if not stories:
            problems.append("`stories` is empty: link the groomed stories (board.py set REQ-x stories=[STORY-1,STORY-2])")
        for sid in stories:
            try:
                s = find(sid)
            except SystemExit:
                problems.append(f"{sid} does not exist")
                continue
            if s.get("req") != t.id:
                problems.append(f"{sid} has req={s.get('req')}, expected {t.id}")
            if s.get("status") == "DRAFT":
                problems.append(f"{sid} is still DRAFT (must pass Definition of Ready)")
    if t.kind == "SPRINT" and target == "IN_QA":
        for s in all_tickets("STORY"):
            if s.get("sprint") == t.id and s.get("status") not in DEV_COMPLETE:
                problems.append(f"{s.id} is {s.get('status')}, all sprint stories must be MERGED")
    if t.kind == "SPRINT" and target == "CLOSED":
        for s in all_tickets("STORY"):
            if s.get("sprint") == t.id and s.get("status") not in DEV_COMPLETE:
                problems.append(f"{s.id} is {s.get('status')}: carry it over (set sprint=<next>) or move it "
                                f"back to READY before closing")
    return problems


def branch_ready(t: Ticket) -> list[str]:
    """Code work only happens on the ticket's own branch, created by git_flow.py start."""
    branch = str(t.get("branch", "none"))
    if branch in ("", "none"):
        return [f"no branch yet: run `python .sdlc/tools/git_flow.py start {t.id} --dev <dev-id>`"]
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=ROOT,
                      capture_output=True).returncode != 0:
        return [f"branch '{branch}' does not exist in git"]
    return []


def definition_of_ready(t: Ticket) -> list[str]:
    """workflow.md §4, checked section by section against the story template."""
    p = []
    try:
        pts = int(str(t.get("points", "0")))
        if pts == 13 or pts > 8:
            p.append(f"{pts} points is too big: split the story (max 8)")
        elif pts not in FIB:
            p.append("points must be one of 1,2,3,5,8")
    except ValueError:
        pts = 0
        p.append("points must be a number")
    if t.get("req") in ("", "none", "REQ-000"):
        p.append("link a requirement in `req`")
    if re.search(r"<(persona|capability|benefit)>", t.section("User story")) or not t.section("User story"):
        p.append("user story still has template placeholders")
    ac = t.section("Acceptance criteria")
    if not re.findall(r"^- AC-\d+(?:\s*\([^)]*\))?:\s*Given\s+(?!<context>)", ac, re.M | re.I):
        p.append("at least one real Given/When/Then acceptance criterion (`- AC-1: Given …` or `- AC-1 (FR-2): Given …`)")
    if "<context>" in ac or "<outcome>" in ac:
        p.append("acceptance criteria still contain the template line")
    if not re.search(r"^\|\s*\d+\s*\|[^|\n]*\|[ \t]*[^|\s][^|\n]*\|", t.section("Technical breakdown (Tech Lead)"), re.M):
        p.append("technical breakdown has no filled row (area + change)")
    api = t.section("API contract")
    if not api or "None / or:" in api or "/api/..." in api:
        p.append("API contract: write `None` or the real contract (template text still there)")
    deps = t.section("Dependencies & blockers")
    for label in ("Depends on", "External blockers"):
        if not re.search(rf"^- {label}:[ \t]*\S", deps, re.M):
            p.append(f"Dependencies & blockers: fill '- {label}:' (write `none` if there are none)")
    tests = t.section("Test approach")
    if not re.search(r"\*\*Unit tests[^\n]*\*\*[ \t]*\n(?:[ \t]*\n)*[ \t]*-[ \t]*\S", tests):
        p.append("test approach: list the unit tests to add")
    if not re.search(r"TC-STORY-\d+-\d+:[ \t]*\S", tests):
        p.append("test approach needs QA scenarios (TC-STORY-x-n)")
    sec = t.section("Security / NFR notes")
    if not re.search(r"^-[ \t]*\S", sec, re.M):
        p.append("Security / NFR notes: fill them (write `- none` with a reason if not relevant)")
    rationale = t.section("Estimate rationale")
    if not rationale or rationale.startswith("Why these points"):
        p.append("estimate rationale missing" + (" (8 points needs a justification for not splitting)" if pts == 8 else ""))
    labels = [str(x).lower() for x in (t.get("labels", []) or [])]
    text = "\n".join(t.section(s) for s in ("User story", "Acceptance criteria", "Technical breakdown (Tech Lead)", "API contract"))
    if SECURITY_WORDS.search(text) and "security" not in labels and "no-security" not in labels:
        word = SECURITY_WORDS.search(text).group(0)
        p.append(f"mentions '{word}': add label `security` (or `no-security` if a human/TL confirms it is not security relevant)")
    for dep in t.get("depends_on", []) or []:
        try:
            find(dep)
        except SystemExit:
            p.append(f"dependency {dep} does not exist")
    return p


# ---------------------------------------------------------------- commands
def cmd_init(args):
    for folder, _, _ in TYPES.values():
        (BOARD / folder).mkdir(parents=True, exist_ok=True)
    (BOARD / "reports").mkdir(exist_ok=True)
    cfg = load_config()
    ws = (ROOT / cfg.get("project", {}).get("workspace", ".")).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    main = cfg.get("git", {}).get("main_branch", "main")
    if not (ROOT / ".git").exists():
        run_git(["init", "-b", main])
        run_git(["add", "-A"])
        run_git(["commit", "--allow-empty", "-m", "chore: bootstrap project with SDLC agent harness"])
        print(f"git repository initialised on '{main}' with a bootstrap commit")
    elif subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=ROOT, capture_output=True).returncode != 0:
        print("WARNING: repository has no commits yet; commit once so branches can be created from "
              f"'{main}'.")
    cmd_render(argparse.Namespace(quiet=True))
    print("board ready:", BOARD.relative_to(ROOT).as_posix())


def run_git(cmd: list[str]):
    subprocess.run(["git", *cmd], cwd=ROOT, check=True)


@locked
def cmd_new(args):
    kind = args.type.upper()
    folder, template, _ = TYPES[kind]
    new = next_id(kind)
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    zero = f"{kind}-" + "0" * TYPES[kind][2]
    text = text.replace(zero, new)
    text = re.sub(r"^title: .*$", f"title: {args.title}", text, count=1, flags=re.M)
    text = text.replace("<short title>", args.title, 1).replace("<title>", args.title, 1)
    text = text.replace("<YYYY-MM-DD>", dt.date.today().isoformat())
    path = BOARD / folder / f"{new}-{slugify(args.title)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    t = Ticket(path)
    for kv in args.set or []:
        k, _, v = kv.partition("=")
        t.fields[k] = parse_value(v)
    t.log(f"{args.by} · created")
    t.save()
    print(f"{new} {path.relative_to(ROOT).as_posix()}")


def cmd_next_id(args):
    print(next_id(args.type))


def cmd_show(args):
    t = find(args.id)
    print(t.path.relative_to(ROOT).as_posix())
    for k, v in t.fields.items():
        print(f"  {k}: {format_value(v)}")
    allowed = TRANSITIONS[t.kind].get(str(t.get("status")), [])
    print(f"  -> allowed next: {', '.join(allowed) or '(final)'}")


def cmd_list(args):
    rows = all_tickets(args.type.upper() if args.type else None)
    for t in rows:
        if args.status and str(t.get("status")) not in args.status.upper().split(","):
            continue
        if args.sprint and t.get("sprint") != args.sprint.upper():
            continue
        if args.assignee and t.get("assignee") != args.assignee:
            continue
        extra = []
        for k in ("points", "assignee", "sprint", "severity", "story"):
            if t.get(k) not in ("", "none", None):
                extra.append(f"{k}={t.get(k)}")
        print(f"{t.id:<10} {str(t.get('status')):<18} {t.get('title')}" + (f"  ({', '.join(extra)})" if extra else ""))


@locked
def cmd_move(args):
    t = find(args.id)
    current = str(t.get("status"))
    target = args.status.upper()
    allowed = TRANSITIONS[t.kind].get(current, [])
    if target not in allowed and not args.force:
        sys.exit(f"REFUSED {t.id}: {current} -> {target} not allowed. Allowed: {', '.join(allowed) or '(final)'}")
    problems = check_guards(t, target)
    if t.kind == "SPRINT" and current == "ACTIVE" and target == "CLOSED" and not args.note:
        problems.append("closing a sprint without a QA phase needs --note (why, and what happens to the work)")
    if problems and not args.force:
        sys.exit(f"REFUSED {t.id} -> {target}:\n  - " + "\n  - ".join(problems))
    if t.kind == "STORY" and target == "REOPENED":
        t.fields["reopen_count"] = int(str(t.get("reopen_count", "0")) or 0) + 1
    if t.kind == "PR" and current == "CHANGES_REQUESTED" and target == "OPEN":  # next review cycle
        t.fields["review_cycle"] = int(str(t.get("review_cycle", "1")) or 1) + 1
        t.fields["gate"] = t.fields["code_review"] = "pending"
        if t.get("security_review") != "not-required":
            t.fields["security_review"] = "pending"
    if t.kind == "SPRINT" and target in ("ACTIVE", "CLOSED"):
        t.fields.update(sprint_snapshot(t.id, closing=target == "CLOSED"))
    t.fields["status"] = target
    note = f" · {args.note}" if args.note else ""
    forced = " · FORCED" if args.force and (problems or target not in allowed) else ""
    t.log(f"{args.by} · {current} → {target}{forced}{note}")
    t.save()
    print(f"{t.id}: {current} -> {target}")
    cmd_render(argparse.Namespace(quiet=True))


@locked
def cmd_set(args):
    t = find(args.id)
    changed = []
    for kv in args.pairs:
        k, _, v = kv.partition("=")
        if k == "status":
            sys.exit("Use `move` to change status.")
        if k in ("code_review", "security_review", "gate") and t.kind == "PR":
            print(f"note: prefer `board.py verdict` for {k}", file=sys.stderr)
        t.fields[k] = parse_value(v)
        changed.append(f"{k}={v}")
    t.log(f"{args.by} · set {', '.join(changed)}")
    t.save()
    print(f"{t.id}: {', '.join(changed)}")
    cmd_render(argparse.Namespace(quiet=True))


@locked
def cmd_log(args):
    t = find(args.id)
    t.log(f"{args.by} · {args.message}")
    t.save()
    print(f"{t.id}: logged")


def read_text_arg(args) -> str:
    if args.file:
        return (sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8"))
    if args.text is None:
        sys.exit("give --text \"...\" or --file <path> (use --file - for stdin)")
    return args.text.replace("\\n", "\n")


@locked
def cmd_section(args):
    t = find(args.id)
    if args.heading.strip().lower() == "activity":
        sys.exit("the Activity log is written by board.py itself (use `log`)")
    if args.heading.strip().lower() in ("raw request",) and t.section("Raw request") and not args.force:
        sys.exit("'Raw request' is never edited after intake (--force to override, logged)")
    t.set_section(args.heading.strip(), read_text_arg(args), append=args.append)
    t.log(f"{args.by} · {'appended to' if args.append else 'wrote'} section '{args.heading.strip()}'")
    t.save()
    print(f"{t.id}: section '{args.heading.strip()}' {'appended' if args.append else 'written'}")


def _cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


@locked
def cmd_comment(args):
    t = find(args.id)
    if t.kind != "PR":
        sys.exit("comment takes a PR id")
    prefix = COMMENT_PREFIX.get(args.by, "C")
    nums = [int(r[0][1:]) for r in t.comment_rows() if r[0][0] == prefix]
    cid = f"{prefix}{max(nums, default=0) + 1}"
    row = (f"| {cid} | {t.get('review_cycle', 1)} | {args.by} | {_cell(args.loc)} | {args.sev} | "
           f"{_cell(read_text_arg(args))} | open |")
    sec = t.section("Review comments")
    lines = sec.splitlines()
    # insert after the last table row (header + separator + rows), keep the legend below it
    last = max((i for i, l in enumerate(lines) if l.lstrip().startswith("|")), default=-1)
    if last < 0:
        lines = ["| ID | Cycle | Reviewer | File:line | Severity | Comment | Status |",
                 "|----|-------|----------|-----------|----------|---------|--------|", row, ""] + lines
    else:
        lines.insert(last + 1, row)
    t.set_section("Review comments", "\n".join(lines))
    t.log(f"{args.by} · comment {cid} ({args.sev}) on {args.loc}")
    t.save()
    print(f"{t.id}: {cid} added")


@locked
def cmd_resolve(args):
    t = find(args.id)
    status = args.status.lower()
    if status == "follow-up" and not args.ticket:
        sys.exit("follow-up needs --ticket <STORY/BUG id> that carries the work")
    sec = t.section("Review comments")
    out, hit = [], False
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and cells[0] == args.cid.upper():
            cells[-1] = f"{status} ({args.ticket})" if args.ticket else status
            line = "| " + " | ".join(cells) + " |"
            hit = True
        out.append(line)
    if not hit:
        sys.exit(f"{args.cid} not found in {t.id} review comments")
    t.set_section("Review comments", "\n".join(out))
    note = f" · {args.note}" if args.note else ""
    t.log(f"{args.by} · {args.cid.upper()} → {status}{f' ({args.ticket})' if args.ticket else ''}{note}")
    t.save()
    print(f"{t.id}: {args.cid.upper()} → {status}")


@locked
def cmd_verdict(args):
    """Reviewers record their verdict only; status moves belong to the orchestrator / devops (workflow §3)."""
    t = find(args.id)
    if t.kind != "PR":
        sys.exit("verdict takes a PR id")
    field = "security_review" if args.by == "security-reviewer" else "code_review"
    verdict = args.verdict.lower()
    if verdict == "approved" and t.open_comments(("blocker", "major")):
        mine = [r[0] for r in t.open_comments(("blocker", "major"))]
        sys.exit(f"cannot approve: open blocker/major comments {', '.join(mine)}")
    t.fields[field] = verdict
    cycle = t.get("review_cycle", 1)
    line = f"- cycle {cycle} · {args.by} · {verdict.upper()} · {args.note or ''}".rstrip(" ·")
    t.set_section("Review verdicts", line, append=True)
    t.log(f"{args.by} · {field}={verdict} (cycle {cycle})")
    t.save()
    print(f"{t.id}: {field}={verdict}")
    cmd_render(argparse.Namespace(quiet=True))


def sprint_capacity(sprint_id: str) -> dict:
    cfg = load_config()
    team = cfg.get("team", {})
    focus = float(team.get("focus_factor", 1.0))
    devs = {d["id"]: round(d.get("capacity_points", 0) * focus, 1) for d in team.get("developers", [])}
    load = {d: 0 for d in devs}
    committed = 0
    for s in all_tickets("STORY"):
        if s.get("sprint") == sprint_id:
            pts = int(str(s.get("points", "0")) or 0)
            committed += pts
            a = str(s.get("assignee"))
            load[a] = load.get(a, 0) + pts
    return {"capacity": round(sum(devs.values()), 1), "committed": committed, "per_dev": devs, "load": load}


def _pts(s: Ticket) -> int:
    try:
        return int(str(s.get("points", "0")) or 0)
    except ValueError:
        return 0


def _pts_field(t: Ticket, key: str) -> int:
    try:
        return int(str(t.get(key, "0")) or 0)
    except ValueError:
        return 0


def sprint_snapshot(sprint_id: str, closing: bool) -> dict:
    """Frozen numbers so later carry-overs don't rewrite a sprint's history."""
    stories = [s for s in all_tickets("STORY") if s.get("sprint") == sprint_id]
    snap = {"stories": [s.id for s in stories]} if not closing else {}
    if not closing:
        snap["committed"] = sum(_pts(s) for s in stories)
    else:
        snap["dev_complete"] = sum(_pts(s) for s in stories if s.get("status") in DEV_COMPLETE)
        snap["completed"] = sum(_pts(s) for s in stories if s.get("status") == "DONE")
        snap["closed_stories"] = [s.id for s in stories]
    return snap


def cmd_capacity(args):
    c = sprint_capacity(args.sprint.upper())
    print(f"{args.sprint.upper()}: committed {c['committed']} / capacity {c['capacity']} pts")
    for dev, cap in c["per_dev"].items():
        flag = "  OVER" if c["load"].get(dev, 0) > cap else ""
        print(f"  {dev:<10} {c['load'].get(dev, 0):>4} / {cap}{flag}")
    for dev, pts in c["load"].items():
        if dev not in c["per_dev"]:
            print(f"  {dev:<10} {pts:>4} (not in team config)")


def cmd_validate(args):
    issues = []
    ids = {}
    for t in all_tickets():
        if t.id in ids:
            issues.append(f"duplicate id {t.id}")
        ids[t.id] = t
        if str(t.get("status")) not in TRANSITIONS[t.kind]:
            issues.append(f"{t.id}: unknown status {t.get('status')}")
    for t in ids.values():
        if t.kind == "REQ":
            for sid in t.get("stories", []) or []:
                s = ids.get(sid)
                if s is None:
                    issues.append(f"{t.id}: stories lists {sid}, which does not exist")
                elif s.get("req") != t.id:
                    issues.append(f"{t.id}: stories lists {sid}, but {sid} has req={s.get('req')}")
            for rid in t.get("related", []) or []:
                if rid not in ids:
                    issues.append(f"{t.id}: related {rid} does not exist")
        if t.kind != "STORY":
            continue
        req = ids.get(str(t.get("req")))
        if req is not None and t.id not in (req.get("stories", []) or []) and req.get("status") not in ("NEW", "REFINED"):
            issues.append(f"{t.id}: req={req.id} but {req.id}.stories does not list it")
        if t.get("status") == "READY":
            issues += [f"{t.id}: DoR — {p}" for p in definition_of_ready(t)]
        for dep in t.get("depends_on", []) or []:
            d = ids.get(dep)
            if d is None:
                continue
            if t.get("sprint") not in ("", "none") and d.get("sprint") in ("", "none") and d.get("status") != "DONE":
                issues.append(f"{t.id}: depends on {dep} which is not planned in any sprint")
            issues += cross_req_issues(t, d, ids)
    # dependency cycles
    graph = {t.id: list(t.get("depends_on", []) or []) for t in ids.values() if t.kind == "STORY"}
    seen, stack = set(), set()

    def visit(n, path):
        if n in stack:
            issues.append("dependency cycle: " + " -> ".join(path + [n]))
            return
        if n in seen:
            return
        seen.add(n); stack.add(n)
        for m in graph.get(n, []):
            visit(m, path + [n])
        stack.discard(n)

    for n in graph:
        visit(n, [])
    if issues:
        print("\n".join(f"- {i}" for i in issues))
        sys.exit(1)
    print("board valid")


def cross_req_issues(t: Ticket, dep: Ticket, ids: dict) -> list[str]:
    """Feature strategy: a story's branch comes from its own REQ's feature branch, which comes from main.
    Work of another REQ is only visible once that REQ is integrated into main (workflow §9)."""
    if load_config().get("git", {}).get("strategy", "feature") != "feature":
        return []
    mine, theirs = str(t.get("req")), str(dep.get("req"))
    if mine == theirs or theirs in ("", "none"):
        return []
    other = ids.get(theirs) if ids else None
    if other is None:
        try:
            other = find(theirs)
        except SystemExit:
            return []
    if str(other.get("integrated", "no")) == "yes":
        return []
    return [f"{t.id} ({mine}) depends on {dep.id} of {theirs}, which is not integrated into main yet: "
            f"integrate {theirs} first (workflow §9 cross-REQ rule), or move {dep.id} into a foundation REQ"]


def cmd_metrics(args):
    print("## Sprint metrics  (dev-complete = MERGED or later; done = DONE after QA)")
    for sp in all_tickets("SPRINT"):
        if sp.get("status") == "CLOSED" and sp.get("closed_stories") not in ("", None):
            committed, dev, done = _pts_field(sp, "committed"), _pts_field(sp, "dev_complete"), _pts_field(sp, "completed")
            stories = [s for s in all_tickets("STORY") if s.id in (sp.get("closed_stories") or [])]
        else:
            stories = [s for s in all_tickets("STORY") if s.get("sprint") == sp.id]
            committed = _pts_field(sp, "committed") or sum(_pts(s) for s in stories)
            dev = sum(_pts(s) for s in stories if s.get("status") in DEV_COMPLETE)
            done = sum(_pts(s) for s in stories if s.get("status") == "DONE")
        reopened = sum(int(str(s.get("reopen_count", 0)) or 0) for s in stories)
        print(f"- {sp.id} [{sp.get('status')}]: committed {committed} pts · dev-complete {dev} · done {done} · "
              f"stories {len(stories)} · reopens {reopened}")
    prs = all_tickets("PR")
    if prs:
        cycles = [int(str(p.get("review_cycle", 1)) or 1) for p in prs]
        print(f"## PRs: {len(prs)} total, avg review cycles {sum(cycles) / len(cycles):.1f}, first-pass approvals {sum(1 for c in cycles if c == 1)}")
    bugs = all_tickets("BUG")
    if bugs:
        sev = {}
        for b in bugs:
            sev[str(b.get("severity"))] = sev.get(str(b.get("severity")), 0) + 1
        print("## Bugs by severity: " + ", ".join(f"{k}={v}" for k, v in sorted(sev.items())))


@locked
def cmd_render(args):
    if not BOARD.exists():
        return
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# Board", "", f"_Auto-generated by `.sdlc/tools/board.py render` at {now}. Do not edit by hand._", ""]

    def card(t: Ticket) -> str:
        bits = [str(t.get("title"))]
        if t.get("points") not in ("", "0", 0, None):
            bits.append(f"{t.get('points')}pt")
        if t.get("assignee") not in ("", "none", None):
            bits.append(str(t.get("assignee")))
        if t.get("pr") not in ("", "none", None):
            bits.append(str(t.get("pr")))
        if t.get("branch") not in ("", "none", None):
            bits.append(f"`{t.get('branch')}`")
        return f"[{t.id}]({t.path.relative_to(BOARD).as_posix()}) " + " · ".join(bits)

    sprints = all_tickets("SPRINT")
    stories = all_tickets("STORY")
    for sp in [s for s in sprints if s.get("status") in ("ACTIVE", "IN_QA", "PLANNED")]:
        c = sprint_capacity(sp.id)
        dev = sum(_pts(s) for s in stories if s.get("sprint") == sp.id and s.get("status") in DEV_COMPLETE)
        out += [f"## {sp.id} — {sp.get('status')} ({sp.get('start')} → {sp.get('end')})",
                f"Committed {c['committed']} / capacity {c['capacity']} pts · dev-complete {dev} pts", "",
                "| Status | Stories |", "|---|---|"]
        for st in STORY_FLOW:
            items = [card(s) for s in stories if s.get("sprint") == sp.id and s.get("status") == st]
            if items:
                out.append(f"| **{st}** | " + "<br>".join(items) + " |")
        out.append("")

    out += ["## Backlog (READY, groomed)", ""]
    ready = [s for s in stories if s.get("status") == "READY"]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ready.sort(key=lambda s: (order.get(str(s.get("priority")), 9), s.id))
    out += [f"- {card(s)}" for s in ready] or ["_empty_"]
    out += ["", "## Drafts (needs grooming)", ""]
    out += [f"- {card(s)}" for s in stories if s.get("status") == "DRAFT"] or ["_empty_"]

    out += ["", "## Requirements", "", "| ID | Status | Title | Feature branch | In main | Stories | Related |",
            "|---|---|---|---|---|---|---|"]
    for r in all_tickets("REQ"):
        out.append(f"| [{r.id}]({r.path.relative_to(BOARD).as_posix()}) | {r.get('status')} | {r.get('title')} | "
                   f"`{r.get('branch', 'none')}` | {r.get('integrated', 'no')} | {format_value(r.get('stories', []))} | "
                   f"{format_value(r.get('related', []))} |")

    open_prs = [p for p in all_tickets("PR") if p.get("status") not in ("MERGED", "CLOSED")]
    out += ["", "## Open pull requests", ""]
    out += [f"- [{p.id}]({p.path.relative_to(BOARD).as_posix()}) {p.get('status')} · {p.get('title')} · gate={p.get('gate')} review={p.get('code_review')} sec={p.get('security_review')} cycle={p.get('review_cycle')}" for p in open_prs] or ["_none_"]

    open_bugs = [b for b in all_tickets("BUG") if b.get("status") not in ("CLOSED", "REJECTED")]
    out += ["", "## Open bugs", ""]
    out += [f"- [{b.id}]({b.path.relative_to(BOARD).as_posix()}) {b.get('status')} · {b.get('severity')} · {b.get('title')} · {b.get('story')} · {b.get('assignee')}" for b in open_bugs] or ["_none_"]

    qa = all_tickets("QA")
    if qa:
        out += ["", "## QA builds", ""]
        out += [f"- [{q.id}]({q.path.relative_to(BOARD).as_posix()}) {q.get('status')} · {q.get('branch')} · {q.get('sprint')}" for q in qa]

    (BOARD / "BOARD.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    if not getattr(args, "quiet", False):
        print("rendered board/BOARD.md")


def main():
    ap = argparse.ArgumentParser(description="Local markdown ticket board for the SDLC agent harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create board folders, workspace and git repo").set_defaults(func=cmd_init)

    p = sub.add_parser("new", help="create a ticket from its template")
    p.add_argument("type", choices=[k for k in TYPES] + [k.lower() for k in TYPES])
    p.add_argument("title")
    p.add_argument("--set", nargs="*", help="extra key=value frontmatter fields")
    p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("next-id"); p.add_argument("type"); p.set_defaults(func=cmd_next_id)
    p = sub.add_parser("show"); p.add_argument("id"); p.set_defaults(func=cmd_show)

    p = sub.add_parser("list")
    p.add_argument("--type"); p.add_argument("--status", help="comma separated")
    p.add_argument("--sprint"); p.add_argument("--assignee")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("move", help="validated status transition")
    p.add_argument("id"); p.add_argument("status")
    p.add_argument("--note", default=""); p.add_argument("--by", default="human")
    p.add_argument("--force", action="store_true", help="human override of rules (logged)")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("set", help="set frontmatter fields (not status)")
    p.add_argument("id"); p.add_argument("pairs", nargs="+", metavar="key=value")
    p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("log", help="append a note to the Activity log")
    p.add_argument("id"); p.add_argument("message"); p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_log)

    def text_args(p):
        p.add_argument("--text", help="content; '\\n' becomes a newline")
        p.add_argument("--file", help="read content from a file ('-' = stdin)")

    p = sub.add_parser("section", help="write a ticket body section (Developer analysis, Implementation notes, ...)")
    p.add_argument("id"); p.add_argument("heading", help="section heading without '## '")
    text_args(p)
    p.add_argument("--append", action="store_true", help="add below the existing content")
    p.add_argument("--force", action="store_true"); p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_section)

    p = sub.add_parser("comment", help="add a review comment row to a PR (auto id: C code, S security, G gate, Q QA)")
    p.add_argument("id"); p.add_argument("--sev", required=True, choices=["blocker", "major", "minor", "nit"])
    p.add_argument("--loc", default="general", help="file:line (any repo file, also outside the diff) or 'general'")
    text_args(p); p.add_argument("--by", required=True)
    p.set_defaults(func=cmd_comment)

    p = sub.add_parser("resolve", help="set a review comment's status")
    p.add_argument("id"); p.add_argument("cid", help="comment id, e.g. C3")
    p.add_argument("status", choices=list(COMMENT_STATUSES))
    p.add_argument("--ticket", help="follow-up ticket that carries the work")
    p.add_argument("--note", default=""); p.add_argument("--by", default="human")
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("verdict", help="record a reviewer verdict on a PR (does not move status)")
    p.add_argument("id"); p.add_argument("verdict", choices=["approved", "changes-requested"])
    p.add_argument("--note", default=""); p.add_argument("--by", required=True)
    p.set_defaults(func=cmd_verdict)

    p = sub.add_parser("capacity"); p.add_argument("sprint"); p.set_defaults(func=cmd_capacity)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    sub.add_parser("metrics").set_defaults(func=cmd_metrics)
    p = sub.add_parser("render"); p.add_argument("--quiet", action="store_true"); p.set_defaults(func=cmd_render)
    p = sub.add_parser("export", help="zip the board (it is git-ignored) as a backup")
    p.add_argument("--to", default=None, help="folder for the zip (default .sdlc/board-backups)")
    p.set_defaults(func=cmd_export)

    args = ap.parse_args()
    check_project(mutating=args.cmd in MUTATING)
    args.func(args)


MUTATING = {"init", "new", "move", "set", "log", "section", "comment", "resolve", "verdict"}


def cmd_export(args):
    import shutil
    dest = Path(args.to) if args.to else SDLC / "board-backups"
    dest.mkdir(parents=True, exist_ok=True)
    name = dest / f"board-{dt.datetime.now():%Y%m%d-%H%M%S}"
    with board_lock():
        out = shutil.make_archive(str(name), "zip", BOARD)
    print(f"board exported: {out}")


if __name__ == "__main__":
    main()
