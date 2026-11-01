#!/usr/bin/env python3
"""Quality gate — a local stand-in for CI + SonarQube.

Runs the project's lint / test / build commands and static checks on the files
changed by a branch, writes a markdown report to .sdlc/board/reports/, and exits 1
when the gate fails. It runs inside the worktree where the branch is checked out,
so nobody has to switch branches in the main checkout.

    python .sdlc/tools/quality_gate.py --pr PR-001                 # branch & base from the PR ticket
    python .sdlc/tools/quality_gate.py --branch story/STORY-001-x --base feature/REQ-001-y
    python .sdlc/tools/quality_gate.py --branch main --tests-only  # post-merge check
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board  # noqa: E402

ROOT = board.ROOT

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
    (r"(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "hard-coded credential"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub token"),
    (r"sk-[A-Za-z0-9]{20,}", "API secret key"),
]
REAL_KEY_LABELS = {"AWS access key", "private key", "GitHub token", "API secret key"}  # blocker even in tests
WAIVER = "sdlc:allow"  # inline comment that waives a static finding on that line (reviewers see it in the diff)
DEBUG_PATTERNS = [r"\bconsole\.log\(", r"\bdebugger;", r"^\s*print\(.*#\s*debug", r"\bpdb\.set_trace\(", r"\bbreakpoint\(\)"]
CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".go", ".cs", ".rb", ".php", ".vue", ".svelte", ".css", ".scss", ".html"}
TEST_HINT = re.compile(r"(test|spec)", re.I)


def sh(cmd: str, cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr)[-4000:]


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


LOCKFILES = [("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm"),
             ("yarn.lock", "yarn install --frozen-lockfile", "yarn"),
             ("package-lock.json", "npm ci --no-audit --no-fund", "npm")]


def node_install(ws: Path) -> tuple[str, str]:
    """Lockfile-respecting install (fails on lockfile drift, like CI) and the package runner."""
    for lock, cmd, runner in LOCKFILES:
        if (ws / lock).exists():
            return cmd, runner
    return "npm install --no-audit --no-fund", "npm"


def install_stamp(ws: Path) -> str | None:
    """Hash of manifest + lockfile; an install is skipped when node_modules was built from the same hash."""
    files = [ws / f for f in ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json") if (ws / f).exists()]
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()


def detect_commands(ws: Path) -> list[tuple[str, str]]:
    cmds = []
    pkg = ws / "package.json"
    if pkg.exists():
        scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        install, runner = node_install(ws)
        cmds.append(("install", install))
        for name in ("lint", "typecheck", "test", "build"):
            if name in scripts:
                cmds.append((name, f"{runner} run {name}" if name != "test" else f"{runner} test"))
    elif any((ws / f).exists() for f in ("pyproject.toml", "requirements.txt", "setup.py")):
        if shutil.which("ruff"):
            cmds.append(("lint", "ruff check ."))
        cov = "--cov=. --cov-report=json:coverage.json" if _has_module("pytest_cov") else ""
        cmds.append(("test", f"{sys.executable} -m pytest -q {cov}".strip()))
    return cmds


def _has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


COVERAGE_FILES = ("coverage/coverage-summary.json", "coverage.json")


def clear_coverage(ws: Path):
    """A failed test run must not be judged on an old coverage file."""
    for f in COVERAGE_FILES:
        (ws / f).unlink(missing_ok=True)


def read_coverage(ws: Path) -> dict | None:
    """{'lines': pct, ...}; the gate judges total line coverage of the workspace (workflow §5)."""
    summary = ws / COVERAGE_FILES[0]  # istanbul json-summary (jest/vitest)
    if summary.exists():
        total = json.loads(summary.read_text())["total"]
        return {k: float(total[k]["pct"]) for k in ("lines", "statements", "branches", "functions") if k in total}
    pycov = ws / COVERAGE_FILES[1]
    if pycov.exists():
        t = json.loads(pycov.read_text())["totals"]
        out = {"lines": float(t["percent_covered"])}
        if t.get("num_branches"):
            out["branches"] = 100.0 * t.get("covered_branches", 0) / t["num_branches"]
        return out
    return None


def checkout_of(branch: str) -> Path:
    """The folder where `branch` is checked out: its worktree, or the main checkout."""
    path = None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[9:])
        elif line == f"branch refs/heads/{branch}" and path:
            return path
    sys.exit(f"'{branch}' is not checked out anywhere. Run `python .sdlc/tools/git_flow.py start <ticket>` "
             f"(or `git_flow.py where {branch}`).")


def changed_files(checkout: Path, branch: str, base: str) -> list[Path]:
    names = git("diff", "--name-only", "--diff-filter=AM", f"{base}...{branch}")
    return [checkout / n for n in names.splitlines() if n]


def project_commands(cfg: dict, ws: Path, tests_only: bool) -> list[tuple[str, str]]:
    configured = {k: v for k, v in cfg.get("project", {}).get("commands", {}).items() if v}
    if configured:
        cmds = [(k, configured[k]) for k in ("install", "lint", "typecheck", "test", "build") if k in configured]
    else:
        cmds = detect_commands(ws)
    if tests_only:
        return [c for c in cmds if c[0] in ("install", "test")]
    extra = cfg.get("quality_gates", {}).get("extra_commands", [])
    return cmds + [(c.get("name", c["run"]), c["run"]) for c in extra]


def static_checks(files: list[Path], gates: dict, checkout: Path) -> list[tuple[str, str, str]]:
    """Returns (severity, location, message); severity in blocker|major|minor."""
    findings = []
    max_lines = int(gates.get("max_file_lines", 400))
    code_files = [f for f in files if f.suffix in CODE_EXT and f.exists()]
    for f in code_files:
        rel = f.relative_to(checkout).as_posix()
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        if len(lines) > max_lines:
            findings.append(("minor", rel, f"{len(lines)} lines (> {max_lines}); consider splitting"))
        is_test = bool(TEST_HINT.search(rel))
        for i, line in enumerate(lines, 1):
            if WAIVER in line:
                findings.append(("info", f"{rel}:{i}", f"static checks waived by `{WAIVER}`"))
                continue
            for pat, label in SECRET_PATTERNS:
                if re.search(pat, line):
                    if is_test and label not in REAL_KEY_LABELS:  # fixtures like password = "Secret123!"
                        findings.append(("minor", f"{rel}:{i}", f"credential-like literal in test code ({label}); "
                                                               f"use a fixture helper"))
                    else:
                        findings.append(("blocker", f"{rel}:{i}", f"possible {label}"))
            if not is_test:
                for pat in DEBUG_PATTERNS:
                    if re.search(pat, line):
                        sev = "major" if gates.get("fail_on_debug_statements", True) else "minor"
                        findings.append((sev, f"{rel}:{i}", "debug statement left in code"))
            if re.search(r"\b(TODO|FIXME|HACK)\b", line):
                findings.append(("major" if gates.get("fail_on_todo") else "minor", f"{rel}:{i}", "TODO/FIXME marker"))
    src = [f for f in code_files if not TEST_HINT.search(f.name) and f.suffix not in {".css", ".scss", ".html"}]
    tests = [f for f in files if TEST_HINT.search(f.name)]
    if src and not tests:
        findings.append(("major", "(branch)", f"{len(src)} source file(s) changed but no test files added/changed"))
    return findings, len(code_files)


def run_install(cmd: str, ws: Path, fresh: bool) -> tuple[bool, str, str]:
    stamp_file = ws / "node_modules" / ".sdlc-install-stamp"
    stamp = install_stamp(ws)
    if not fresh and stamp and stamp_file.exists() and stamp_file.read_text().strip() == stamp:
        return True, "skipped: node_modules already built from this package.json + lockfile", f"{cmd} (cached)"
    code, out = sh(cmd, ws)
    if code == 0 and stamp and stamp_file.parent.exists():
        stamp_file.write_text(stamp)
    return code == 0, out, cmd


def write_pr_section(pr, passed: bool, report_rel: str, sha: str, coverage: dict | None, cov_min: float, cycle: str):
    cov = "n/a" if coverage is None else ", ".join(f"{k} {v:.1f}%" for k, v in coverage.items())
    line = (f"- cycle {cycle} · {'PASSED' if passed else 'FAILED'} · `{sha}` · coverage {cov} (min {cov_min:.0f}% lines) · "
            f"[report]({report_rel})")
    pr.set_section("Quality gate", line, append=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr")
    ap.add_argument("--branch")
    ap.add_argument("--base")
    ap.add_argument("--skip-commands", action="store_true", help="static checks only (docs-only changes)")
    ap.add_argument("--tests-only", action="store_true", help="install + test only, e.g. after a merge")
    ap.add_argument("--fresh-install", action="store_true", help="always run the install step")
    args = ap.parse_args()
    board.check_project(mutating=bool(args.pr))

    cfg = board.load_config()
    gates = cfg.get("quality_gates", {})
    main_branch = cfg.get("git", {}).get("main_branch", "main")
    pr = board.find(args.pr) if args.pr else None
    branch = args.branch or (str(pr.get("branch")) if pr else git("rev-parse", "--abbrev-ref", "HEAD"))
    base = args.base or (str(pr.get("base")) if pr else main_branch)
    if pr and args.tests_only and pr.get("status") == "MERGED" and not args.branch:
        branch = base  # post-merge check: test the branch the PR was merged into
    checkout = checkout_of(branch)
    ws = (checkout / cfg.get("project", {}).get("workspace", ".")).resolve()
    if git("-C", str(checkout), "status", "--porcelain"):
        print("WARNING: uncommitted changes present; the report reflects the working tree, not the commit.")

    results = []  # (name, command, ok, output)
    commands = [] if args.skip_commands else project_commands(cfg, ws, args.tests_only)
    if not args.skip_commands and not commands:
        results.append(("detect", "", False, "No lint/test/build commands found. Set project.commands in "
                                              ".sdlc/config.json (run /sdlc-init) or add package.json/pyproject scripts."))
    if any(n == "test" for n, _ in commands):
        clear_coverage(ws)
    for name, cmd in commands:
        if name == "install":
            ok_, out, shown = run_install(cmd, ws, args.fresh_install)
            results.append((name, shown, ok_, out))
            if not ok_:
                break  # nothing else can run without dependencies
            continue
        code, out = sh(cmd, ws)
        results.append((name, cmd, code == 0, out))

    coverage = read_coverage(ws)
    cov_min = float(gates.get("coverage_min", 0))
    cov_ok = coverage is None or coverage.get("lines", 0) >= cov_min

    findings, scanned = ([], 0) if args.tests_only else static_checks(changed_files(checkout, branch, base), gates, checkout)
    if not args.tests_only and coverage is None and cov_min > 0 and any(r[0] == "test" for r in results):
        findings.append(("major", "(coverage)", "tests ran but no coverage report found; enable json-summary (jest/vitest) or pytest-cov"))
    blocking = [f for f in findings if f[0] in ("blocker", "major")]
    passed = all(r[2] for r in results) and cov_ok and not blocking

    sha = git("-C", str(checkout), "rev-parse", "--short", "HEAD")
    cycle = str(pr.get("review_cycle", 1)) if pr else "x"
    if pr:  # PR gate, or post-merge check of a PR (every run kept as evidence)
        name = f"{pr.id}-gate-{cycle}.md" if not args.tests_only else f"{pr.id}-postmerge-{sha}.md"
    elif args.tests_only:  # post-merge / QA build check of a shared branch
        name = f"branch/{branch.replace('/', '_')}-tests-{sha}.md"
    else:  # developer pre-check before raising a PR
        name = f"precheck/{branch.replace('/', '_')}.md"
    report = board.BOARD / "reports" / name
    report.parent.mkdir(parents=True, exist_ok=True)
    if coverage is None:
        cov_text, cov_verdict = "n/a (no coverage report found)", "WARN"
    else:
        cov_text = ", ".join(f"{k} {v:.1f}%" for k, v in coverage.items())
        cov_verdict = "PASS" if cov_ok else "FAIL"
    md = [f"# Quality gate — {'PASSED' if passed else 'FAILED'}", "",
          f"- Branch: `{branch}` @ `{sha}`" + (f" vs `{base}`" if branch != base and not args.tests_only else ""),
          f"- Checkout: `{checkout.as_posix()}`",
          f"- Run at: {dt.datetime.now():%Y-%m-%d %H:%M}",
          f"- Coverage: {cov_text} (gate: total lines >= {cov_min:.0f}%) {cov_verdict}",
          f"- Static analysis: {scanned} changed code file(s) scanned" if not args.tests_only else "- Static analysis: skipped (tests only)",
          "", "## Commands", "", "| Step | Command | Result |", "|---|---|---|"]
    md += [f"| {n} | `{c}` | {'PASS' if ok else 'FAIL'} |" for n, c, ok, _ in results] or ["| (skipped) | | |"]
    if not args.tests_only:
        md += ["", "## Static analysis (changed files)", "", "| Severity | Location | Finding |", "|---|---|---|"]
        md += [f"| {sev} | `{loc}` | {msg} |" for sev, loc, msg in findings] or ["| - | - | no findings |"]
    for n, _, ok, out in results:
        if not ok:
            md += ["", f"## Output: {n}", "```", out.strip(), "```"]
    report.write_text("\n".join(md) + "\n", encoding="utf-8")

    if pr:
        rel = f"../reports/{name}"
        with board.board_lock():  # re-read: reviewers may have written the PR while tests ran
            fresh = board.Ticket(pr.path)
            if not args.tests_only:
                fresh.fields["gate"] = "passed" if passed else "failed"
                write_pr_section(fresh, passed, rel, sha, coverage, cov_min, cycle)
                fresh.log(f"devops-engineer · quality gate cycle {cycle}: {'PASSED' if passed else 'FAILED'} → reports/{name}")
            else:
                fresh.log(f"devops-engineer · post-merge tests on {branch} @ {sha}: {'PASSED' if passed else 'FAILED'} → reports/{name}")
            fresh.save()
        board.cmd_render(argparse.Namespace(quiet=True))

    print("\n".join(md))
    print(f"\nreport: {report.relative_to(board.ROOT).as_posix()}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
