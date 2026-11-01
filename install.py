#!/usr/bin/env python3
"""Install (or upgrade / uninstall) the SDLC agent harness into any project.

    python install.py <target-project-dir>              # install or upgrade
    python install.py <target-project-dir> --dry-run    # show what would change
    python install.py <target-project-dir> --force      # also overwrite locally modified harness files
    python install.py <target-project-dir> --uninstall  # remove harness files you haven't modified

What gets installed into the target:
    .claude/agents/<role>.md          8 role agents
    .claude/skills/<skill>/SKILL.md   role + orchestrator skills
    .sdlc/                            tools, templates, process, config (board/ is created at runtime)
    CLAUDE.md                         a marked harness block is added/updated (rest of the file untouched)
    .gitignore                        a marked block ignoring .sdlc/board/

Upgrades are safe: .sdlc/manifest.json records the hash of every installed file. A
file you changed after install is never overwritten without --force, a file of
yours with the same name as a harness file is never touched, and .sdlc/config.json
keeps your values (new default keys are merged in).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
VERSION = (SRC / ".sdlc" / "VERSION").read_text(encoding="utf-8").strip()
MANIFEST = ".sdlc/manifest.json"
# runtime / per-project files: never copied verbatim
SKIP = {".sdlc/config.json", ".sdlc/manifest.json", ".sdlc/project-profile.md", ".sdlc/CLAUDE.snippet.md"}
GITIGNORE_START, GITIGNORE_END = "# >>> sdlc-harness", "# <<< sdlc-harness"
CLAUDE_START, CLAUDE_END = "<!-- sdlc-harness:start -->", "<!-- sdlc-harness:end -->"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def harness_files() -> list[str]:
    files = []
    for top in (".claude/agents", ".claude/skills", ".sdlc"):
        for p in sorted((SRC / top).rglob("*")):
            rel = p.relative_to(SRC).as_posix()
            if p.is_file() and rel not in SKIP and "/board/" not in f"/{rel}" and "__pycache__" not in rel:
                files.append(rel)
    return files


def git_out(target: Path, *args) -> str:
    p = subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def detect_main_branch(target: Path) -> str:
    remote_head = git_out(target, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if remote_head:
        return remote_head.split("/", 1)[1]
    for name in ("main", "master", "develop"):
        if git_out(target, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    return git_out(target, "rev-parse", "--abbrev-ref", "HEAD") or "main"


def deep_merge(defaults: dict, current: dict) -> dict:
    out = dict(current)
    for k, v in defaults.items():
        if k not in out:
            out[k] = v
        elif isinstance(v, dict) and isinstance(out[k], dict):
            out[k] = deep_merge(v, out[k])
    return out


def upsert_block(path: Path, start: str, end: str, body: str, dry: bool) -> str:
    block = f"{start}\n{body.rstrip()}\n{end}\n"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if start in text and end in text:
        before, rest = text.split(start, 1)
        after = rest.split(end, 1)[1].lstrip("\n")
        new = before + block + (("\n" + after) if after else "")
        action = "updated block"
    else:
        new = (text.rstrip() + "\n\n" if text.strip() else "") + block
        action = "added block" if text else "created"
    if new == text:
        return "unchanged"
    if not dry:
        path.write_text(new, encoding="utf-8")
    return action


def remove_block(path: Path, start: str, end: str):
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if start in text and end in text:
        before, rest = text.split(start, 1)
        after = rest.split(end, 1)[1]
        path.write_text((before.rstrip() + "\n" + after.lstrip("\n")).strip() + "\n", encoding="utf-8")


def install(target: Path, force: bool, dry: bool):
    manifest_path = target / MANIFEST
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": {}}
    old_files: dict = old.get("files", {})
    new_files: dict = {}
    report = {"added": [], "updated": [], "unchanged": [], "skipped": [], "removed": []}

    for rel in harness_files():
        src, dst = SRC / rel, target / rel
        src_hash = sha(src)
        if not dst.exists():
            report["added"].append(rel)
        elif sha(dst) == src_hash:
            report["unchanged"].append(rel)
            new_files[rel] = src_hash
            continue
        elif rel in old_files and sha(dst) == old_files[rel]:
            report["updated"].append(rel)
        elif force:
            report["updated"].append(rel + "  (FORCED: local changes overwritten, backup .bak)")
            if not dry:
                shutil.copy2(dst, dst.with_name(dst.name + ".bak"))
        else:
            why = "modified locally" if rel in old_files else "exists and is not a harness file"
            report["skipped"].append(f"{rel}  ({why}; use --force to overwrite)")
            if rel in old_files:
                new_files[rel] = old_files[rel]
            continue
        new_files[rel] = src_hash
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # files dropped from the harness since the last install
    for rel, h in old_files.items():
        dst = target / rel
        if rel not in new_files and rel not in harness_files() and dst.exists():
            if sha(dst) == h:
                report["removed"].append(rel)
                if not dry:
                    dst.unlink()
            else:
                report["skipped"].append(f"{rel}  (no longer in harness but modified locally; left in place)")

    # config: create with detected values, or merge new default keys
    cfg_dst = target / ".sdlc/config.json"
    defaults = json.loads((SRC / ".sdlc/config.json").read_text(encoding="utf-8"))
    if cfg_dst.exists():
        current = json.loads(cfg_dst.read_text(encoding="utf-8"))
        merged = deep_merge(defaults, current)
        cfg_action = "merged new default keys" if merged != current else "unchanged"
    else:
        merged = defaults
        merged["project"]["name"] = target.name
        merged["project"]["workspace"] = "."
        merged["project"]["tech_stack"] = "auto-detect"
        merged["project"]["commands"] = {k: "" for k in merged["project"]["commands"]}
        merged["git"]["main_branch"] = detect_main_branch(target)
        cfg_action = f"created (main branch: {merged['git']['main_branch']})"
    if not dry and cfg_action != "unchanged":
        cfg_dst.parent.mkdir(parents=True, exist_ok=True)
        cfg_dst.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")

    snippet = (SRC / ".sdlc/CLAUDE.snippet.md").read_text(encoding="utf-8")
    claude_action = upsert_block(target / "CLAUDE.md", CLAUDE_START, CLAUDE_END, snippet, dry)
    gi_body = ("# SDLC agent harness runtime data (the board is the team's local Jira)\n"
               ".sdlc/board/\n.sdlc/board-backups/\n.sdlc/**/__pycache__/\n*.bak")
    gi_action = upsert_block(target / ".gitignore", GITIGNORE_START, GITIGNORE_END, gi_body, dry)
    # stable line endings across Windows/macOS agents; never touch a project's own attributes
    ga = target / ".gitattributes"
    if not ga.exists() or GITIGNORE_START in ga.read_text(encoding="utf-8"):
        ga_action = upsert_block(ga, GITIGNORE_START, GITIGNORE_END, "* text=auto eol=lf", dry)
    else:
        ga_action = "kept (project has its own .gitattributes)"

    if not dry:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"version": VERSION, "files": new_files}, indent=2) + "\n", encoding="utf-8")

    print(f"{'[dry-run] ' if dry else ''}SDLC harness {old.get('version', 'none')} → {VERSION} in {target}")
    for key in ("added", "updated", "removed", "skipped"):
        if report[key]:
            print(f"\n{key} ({len(report[key])}):")
            print("\n".join(f"  {r}" for r in report[key]))
    print(f"\nunchanged: {len(report['unchanged'])} files")
    print(f".sdlc/config.json: {cfg_action}\nCLAUDE.md: {claude_action}\n.gitignore: {gi_action}\n.gitattributes: {ga_action}")
    if not dry:
        is_git = bool(git_out(target, "rev-parse", "--git-dir"))
        print("\nNext steps:")
        if not is_git:
            print("  1. python .sdlc/tools/board.py init      # creates the git repo + first commit")
        else:
            print("  1. Commit the harness files on your main branch (git add .claude .sdlc CLAUDE.md .gitignore .gitattributes)")
        print("  2. In Claude Code: /sdlc-init                # onboard the codebase, set test/lint/build commands")
        print("  3. /sdlc-feature <what you want built>")


def uninstall(target: Path, dry: bool):
    manifest_path = target / MANIFEST
    if not manifest_path.exists():
        sys.exit("No .sdlc/manifest.json — harness not installed here.")
    files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    kept = []
    for rel, h in files.items():
        dst = target / rel
        if dst.exists() and sha(dst) == h:
            if not dry:
                dst.unlink()
        elif dst.exists():
            kept.append(rel)
    if not dry:
        manifest_path.unlink()
        remove_block(target / "CLAUDE.md", CLAUDE_START, CLAUDE_END)
        remove_block(target / ".gitignore", GITIGNORE_START, GITIGNORE_END)
        if (target / ".gitattributes").exists():
            remove_block(target / ".gitattributes", GITIGNORE_START, GITIGNORE_END)
        for d in sorted({(target / r).parent for r in files}, key=lambda p: len(p.parts), reverse=True):
            if d.exists() and d != target and not any(d.iterdir()):
                d.rmdir()
    print(f"{'[dry-run] ' if dry else ''}uninstalled harness files from {target}")
    print("kept (modified locally): " + (", ".join(kept) if kept else "none"))
    print("left in place: .sdlc/config.json, .sdlc/board/, .sdlc/project-profile.md (delete manually if unwanted)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="project folder (new or existing)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    target = Path(args.target).resolve()
    if target == SRC:
        sys.exit("Target is the harness template itself.")
    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)
    if args.uninstall:
        uninstall(target, args.dry_run)
    else:
        install(target, args.force, args.dry_run)


if __name__ == "__main__":
    main()
