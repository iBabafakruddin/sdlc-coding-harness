#!/usr/bin/env python3
"""Git branching for the agent team: one branch + one worktree per feature / story / bug.

The main checkout always stays on the main branch. Every piece of work gets its own
branch checked out in its own worktree (default ../<repo>-worktrees/<ID>), so several
developer agents can work at the same time without touching each other's files.

Strategy "feature" (default):
    main ─┬─ feature/REQ-001-login-page          (one per requirement; integration branch)
          │     ├─ story/STORY-001-login-api     (one per story; developer works here)
          │     └─ story/STORY-002-login-form
          └─ bugfix/BUG-001-...                   (QA bugs, after the feature is in main)
    story PRs → feature branch;  feature PR → main;  qa/SPRINT-xx built from main.

Strategy "story": story branches feature/STORY-xxx-... come straight off main, PRs → main.

    python .sdlc/tools/git_flow.py feature-start REQ-001
    python .sdlc/tools/git_flow.py start STORY-001 --dev dev-1
    python .sdlc/tools/git_flow.py sync STORY-001
    python .sdlc/tools/git_flow.py merge PR-001
    python .sdlc/tools/git_flow.py finish STORY-001
    python .sdlc/tools/git_flow.py qa-build SPRINT-01
    python .sdlc/tools/git_flow.py status
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board  # noqa: E402
from board import ROOT, find, slugify  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CFG = board.load_config().get("git", {})
MAIN = CFG.get("main_branch", "main")
STRATEGY = CFG.get("strategy", "feature")


def git(*args, cwd: Path = ROOT, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{p.stdout}{p.stderr}")
    return p.stdout.strip()


def ok(*args, cwd: Path = ROOT) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


def branch_exists(name: str) -> bool:
    return ok("rev-parse", "--verify", "--quiet", f"refs/heads/{name}")


def worktrees() -> dict[str, Path]:
    """branch name -> worktree path"""
    out, path = {}, None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[9:])
        elif line.startswith("branch refs/heads/") and path:
            out[line[18:]] = path
    return out


def worktree_root() -> Path:
    return (ROOT / CFG.get("worktree_root", "../{repo}-worktrees").format(repo=ROOT.name)).resolve()


def ensure_worktree(branch: str, key: str) -> Path:
    wt = worktrees().get(branch)
    if wt:
        return wt
    path = worktree_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", path.as_posix(), branch)
    return path


def require_clean(path: Path, what: str):
    if git("status", "--porcelain", cwd=path):
        sys.exit(f"{what} at {path} has uncommitted changes. Commit or stash them first.")


def push(branch: str, cwd: Path = ROOT):
    if CFG.get("push_branches") and ok("remote", "get-url", CFG.get("remote", "origin")):
        git("push", "-u", CFG.get("remote", "origin"), branch, cwd=cwd)


def update(t: board.Ticket, by: str, **fields):
    with board.board_lock():  # re-read: another agent may have written the ticket meanwhile
        fresh = board.Ticket(t.path)
        fresh.fields.update(fields)
        fresh.log(f"{by} · set " + ", ".join(f"{k}={v}" for k, v in fields.items()))
        fresh.save()
    t.fields, t.body = fresh.fields, fresh.body


def cross_req_issues(story_ids: list[str]) -> list[str]:
    """Stories depending on stories of a REQ that is not in main yet can't see that code (workflow §9)."""
    ids = {t.id: t for t in board.all_tickets()}
    issues = []
    for sid in story_ids:
        s = ids.get(sid)
        for dep in (s.get("depends_on", []) or []) if s else []:
            if dep in ids:
                issues += board.cross_req_issues(s, ids[dep], ids)
    return issues


def other_req_deps(story: board.Ticket) -> list[str]:
    out = []
    for dep in story.get("depends_on", []) or []:
        try:
            d = find(dep)
        except SystemExit:
            continue
        if str(d.get("req")) not in ("", "none", str(story.get("req"))):
            out.append(str(d.get("req")))
    return sorted(set(out))


def require_main_checkout_on_main():
    current = git("rev-parse", "--abbrev-ref", "HEAD")
    if current != MAIN:
        sys.exit(f"The main checkout ({ROOT}) must stay on '{MAIN}' but is on '{current}'. "
                 f"Run `git checkout {MAIN}` there; work happens in worktrees.")


# ---------------------------------------------------------------- commands
def feature_start(req_id: str, by: str) -> board.Ticket:
    req = find(req_id)
    if req.kind != "REQ":
        sys.exit("feature-start takes a REQ id")
    if STRATEGY != "feature":
        sys.exit("git.strategy is 'story': no feature branches; stories branch from main.")
    branch = str(req.get("branch", "none"))
    if branch in ("", "none") or not branch_exists(branch):
        issues = cross_req_issues(list(req.get("stories", []) or []))
        if issues:
            print("WARNING: these stories need another REQ's code, which is not in main yet. They cannot start until "
                  "that REQ is integrated and this feature branch is synced (`git_flow.py sync "
                  f"{req.id}`):\n  - " + "\n  - ".join(issues))
        branch = f"feature/{req.id}-{slugify(str(req.get('title')))}"[:80]
        if not branch_exists(branch):
            git("branch", branch, MAIN)
            push(branch)
    path = ensure_worktree(branch, req.id)
    update(req, by, branch=branch, base=MAIN, worktree=path.as_posix())
    print(f"{req.id}: feature branch {branch} (from {MAIN})\nworktree: {path.as_posix()}")
    return req


def cmd_feature_start(args):
    feature_start(args.id, args.by)
    board.cmd_render(argparse.Namespace(quiet=True))


def cmd_start(args):
    t = find(args.id)
    if t.kind not in ("STORY", "BUG"):
        sys.exit("start takes a STORY or BUG id (use feature-start for a REQ)")
    by = args.dev or args.by
    branch = str(t.get("branch", "none"))
    if branch not in ("", "none") and branch_exists(branch):  # resume
        path = ensure_worktree(branch, t.id)
        update(t, by, worktree=path.as_posix())
        print(f"{t.id}: resuming {branch} (base {t.get('base')})\nworktree: {path.as_posix()}")
        return

    if t.kind == "STORY" and STRATEGY == "feature" and not args.force:
        issues = cross_req_issues([t.id])
        if issues:
            sys.exit("REFUSED: " + "\n  ".join(issues) + "\n(--force only on a human decision)")
    base = args.base or MAIN
    if t.kind == "STORY" and STRATEGY == "feature" and not args.base:
        req = find(str(t.get("req")))
        if str(req.get("integrated", "no")) == "yes":
            print(f"note: {req.id} is already integrated into {MAIN}; branching from {MAIN}.")
        else:
            if str(req.get("branch", "none")) in ("", "none") or not branch_exists(str(req.get("branch"))):
                req = feature_start(req.id, by)
            base = str(req.get("branch"))
    if not branch_exists(base):
        sys.exit(f"base branch '{base}' does not exist")
    if t.kind == "STORY" and STRATEGY == "feature" and not args.force:
        if other_req_deps(t) and base != MAIN and not ok("merge-base", "--is-ancestor", MAIN, base):
            sys.exit(f"REFUSED: {t.id} needs code from {', '.join(other_req_deps(t))}, which is in {MAIN}, but {base} "
                     f"is behind {MAIN}. Devops first: `python .sdlc/tools/git_flow.py sync {t.get('req')}`.")

    prefix = "bugfix/" if t.kind == "BUG" else ("story/" if STRATEGY == "feature" else "feature/")
    branch = f"{prefix}{t.id}-{slugify(str(t.get('title')))}"[:80]
    path = worktree_root() / t.id
    path.parent.mkdir(parents=True, exist_ok=True)
    git("worktree", "add", "-b", branch, path.as_posix(), base)
    push(branch, cwd=path)
    fields = {"branch": branch, "base": base, "worktree": path.as_posix()}
    if args.dev and str(t.get("assignee", "none")) in ("", "none"):
        fields["assignee"] = args.dev
    update(t, by, **fields)
    board.cmd_render(argparse.Namespace(quiet=True))
    print(f"{t.id}: branch {branch} from {base}\nworktree: {path.as_posix()}\n"
          f"Work ONLY inside this folder. Commit there with messages ending in [{t.id}].")


def cmd_sync(args):
    t = find(args.id)
    branch, base = str(t.get("branch")), str(t.get("base", MAIN))
    path = worktrees().get(branch)
    if not path:
        sys.exit(f"{branch} has no worktree; run `start {t.id}` (or feature-start) first")
    require_clean(path, branch)
    p = subprocess.run(["git", "merge", "--no-edit", base], cwd=path, capture_output=True, text=True)
    if p.returncode != 0:
        conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=path, check=False)
        if conflicts:
            print(f"CONFLICTS merging {base} into {branch} (merge left in progress at {path.as_posix()}):")
            print("\n".join(f"  - {c}" for c in conflicts.splitlines()))
            print("Resolve them, `git add` the files, `git commit --no-edit`, then re-run the tests.")
            sys.exit(2)
        sys.exit(p.stdout + p.stderr)
    with board.board_lock():
        fresh = board.Ticket(t.path)
        fresh.log(f"{args.by} · synced {base} into {branch} @ {git('rev-parse', '--short', 'HEAD', cwd=path)}")
        fresh.save()
    print(f"{branch}: up to date with {base}\n{p.stdout.strip()}")


def cmd_merge(args):
    pr = find(args.id)
    if pr.kind != "PR":
        sys.exit("merge takes a PR id")
    if pr.get("status") != "APPROVED":
        sys.exit(f"{pr.id} is {pr.get('status')}; only APPROVED PRs are merged.")
    ticket = str(pr.get("story", "none"))
    if str(pr.get("kind", "story")) in ("story", "bug") and ticket not in ("", "none"):
        st = find(ticket)  # check before merging, so git and the board can't end up out of step
        if "MERGED" not in board.TRANSITIONS[st.kind].get(str(st.get("status")), []):
            sys.exit(f"{st.id} is {st.get('status')} (must be IN_REVIEW); fix the board before merging {pr.id}.")
    branch, base = str(pr.get("branch")), str(pr.get("base"))
    src = worktrees().get(branch)
    if src:
        require_clean(src, branch)
    if base == MAIN:
        require_main_checkout_on_main()
        target = ROOT
    else:
        owner = next((r for r in board.all_tickets("REQ") if r.get("branch") == base), None)
        target = ensure_worktree(base, owner.id if owner else slugify(base))
    require_clean(target, base)

    msg = f"Merge branch '{branch}' into {base} ({pr.id}: {pr.get('title')})"
    p = subprocess.run(["git", "merge", "--no-ff", branch, "-m", msg], cwd=target, capture_output=True, text=True)
    if p.returncode != 0:
        conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=target, check=False)
        git("merge", "--abort", cwd=target, check=False)
        print(f"MERGE CONFLICT {branch} → {base}; merge aborted, {base} unchanged.")
        print("\n".join(f"  - {c}" for c in conflicts.splitlines()))
        print(f"Author must run `python .sdlc/tools/git_flow.py sync <ticket>` and resolve.")
        sys.exit(2)
    sha = git("rev-parse", "--short", "HEAD", cwd=target)
    push(base, cwd=target)

    by = args.by
    update(pr, by, merge_commit=sha)
    board.cmd_move(argparse.Namespace(id=pr.id, status="MERGED", note=f"{branch} → {base} @ {sha}", by=by, force=False))
    kind = str(pr.get("kind", "story"))
    if kind in ("story", "bug") and str(pr.get("story", "none")) not in ("", "none"):
        board.cmd_move(argparse.Namespace(id=str(pr.get("story")), status="MERGED", note=f"{pr.id} @ {sha}", by=by, force=False))
    if kind == "feature":
        update(find(str(pr.get("req"))), by, integrated="yes")
    board.cmd_render(argparse.Namespace(quiet=True))
    print(f"merged {branch} → {base} @ {sha}\nrun post-merge tests in: {target.as_posix()}")


def cmd_finish(args):
    t = find(args.id)
    branch = str(t.get("branch", "none"))
    if branch in ("", "none"):
        sys.exit(f"{t.id} has no branch")
    done = (t.kind == "REQ" and str(t.get("integrated")) == "yes") or \
           str(t.get("status")) in ("MERGED", "IN_QA", "DONE", "RETEST", "CLOSED")
    if not done and not args.force:
        sys.exit(f"{t.id} is {t.get('status')}; finish only after its branch is merged (or use --force to discard).")
    path = worktrees().get(branch)
    if path:
        if path.resolve() == ROOT.resolve():
            sys.exit("refusing to remove the main checkout")
        git("worktree", "remove", path.as_posix(), *(["--force"] if args.force else []))
    # "merged" means merged into the ticket's base (a feature branch for stories), not into main
    base = str(t.get("base", MAIN))
    merged = branch_exists(base) and ok("merge-base", "--is-ancestor", branch, base)
    deleted = ok("branch", "-D" if (merged or args.force) else "-d", branch)
    update(t, args.by, worktree="none")
    print(f"{t.id}: worktree removed; branch {branch} {'deleted' if deleted else 'kept (not fully merged)'}")


def cmd_qa_build(args):
    sprint = find(args.sprint)
    require_main_checkout_on_main()
    branch = f"qa/{sprint.id}"
    path = worktrees().get(branch)
    if path:
        require_clean(path, branch)
        git("merge", "--ff-only", MAIN, cwd=path)
    elif branch_exists(branch):
        path = ensure_worktree(branch, f"qa-{sprint.id}")
        git("merge", "--ff-only", MAIN, cwd=path)
    else:
        path = worktree_root() / f"qa-{sprint.id}"
        path.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", branch, path.as_posix(), MAIN)
    sha = git("rev-parse", "--short", "HEAD", cwd=path)
    push(branch, cwd=path)
    with board.board_lock():
        fresh = board.Ticket(sprint.path)
        fresh.log(f"{args.by} · QA build {branch} @ {sha}")
        fresh.save()
    print(f"{branch} @ {sha}\nworktree: {path.as_posix()}")


def cmd_status(args):
    wts = worktrees()
    print(f"main checkout: {ROOT.as_posix()} on {git('rev-parse', '--abbrev-ref', 'HEAD')}   strategy: {STRATEGY}")
    print(f"{'ticket':<10} {'status':<18} {'branch':<45} {'base':<35} ahead/behind  worktree")
    for t in board.all_tickets():
        branch = str(t.get("branch", "none"))
        if branch in ("", "none") or t.kind == "PR":
            continue
        base = str(t.get("base", MAIN))
        ab = "deleted"
        if branch_exists(branch) and branch_exists(base):
            behind, ahead = git("rev-list", "--left-right", "--count", f"{base}...{branch}").split()
            ab = f"+{ahead}/-{behind}"
        wt = wts.get(branch)
        print(f"{t.id:<10} {str(t.get('status')):<18} {branch:<45} {base:<35} {ab:<13} {wt.as_posix() if wt else '-'}")
    for b, p in wts.items():
        if b.startswith("qa/"):
            print(f"{'QA':<10} {'':<18} {b:<45} {MAIN:<35} {'':<13} {p.as_posix()}")


def cmd_where(args):
    p = worktrees().get(args.branch)
    if not p:
        sys.exit(f"no worktree for {args.branch}")
    print(p.as_posix())


def main():
    ap = argparse.ArgumentParser(description="Branch + worktree management for the SDLC agent team")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("feature-start", help="create the REQ's feature branch + worktree from main")
    p.add_argument("id"); p.add_argument("--by", default="devops-engineer"); p.set_defaults(func=cmd_feature_start)
    p = sub.add_parser("start", help="create (or resume) a STORY/BUG branch + worktree")
    p.add_argument("id"); p.add_argument("--dev"); p.add_argument("--base", help="override base branch")
    p.add_argument("--force", action="store_true", help="start despite unmet cross-REQ dependencies (human decision)")
    p.add_argument("--by", default="developer"); p.set_defaults(func=cmd_start)
    p = sub.add_parser("sync", help="merge the base branch into the ticket branch")
    p.add_argument("id"); p.add_argument("--by", default="developer"); p.set_defaults(func=cmd_sync)
    p = sub.add_parser("merge", help="merge an APPROVED PR into its base (no-ff)")
    p.add_argument("id"); p.add_argument("--by", default="devops-engineer"); p.set_defaults(func=cmd_merge)
    p = sub.add_parser("finish", help="remove the worktree and delete the merged branch")
    p.add_argument("id"); p.add_argument("--force", action="store_true", help="discard unmerged work")
    p.add_argument("--by", default="devops-engineer"); p.set_defaults(func=cmd_finish)
    p = sub.add_parser("qa-build", help="create/fast-forward qa/<SPRINT> from main in its own worktree")
    p.add_argument("sprint"); p.add_argument("--by", default="devops-engineer"); p.set_defaults(func=cmd_qa_build)
    sub.add_parser("status", help="branches, worktrees, ahead/behind").set_defaults(func=cmd_status)
    p = sub.add_parser("where", help="print the worktree path of a branch"); p.add_argument("branch"); p.set_defaults(func=cmd_where)
    args = ap.parse_args()
    board.check_project(mutating=args.cmd not in ("status", "where"))
    args.func(args)


if __name__ == "__main__":
    main()
