#!/usr/bin/env python3
"""
Universal Cross-Platform Installer for Lean Parallel SDLC Harness (Windows, macOS, Linux).
Works on Windows WITHOUT requiring Administrator privileges or Developer Mode:
  - Attempts native symlinks first
  - On Windows without symlink privileges, automatically falls back to NTFS Directory Junctions (`mklink /J`)
    and file hardlinks/copies so Claude Code and Antigravity work out-of-the-box.

Usage:
    python install.py [target_project_dir]
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def link_or_copy_file(src: Path, dst: Path):
    """Link src -> dst using symlink, hardlink, or file copy fallback (Windows-safe)."""
    if dst.exists() or dst.is_symlink():
        try:
            dst.unlink()
        except OSError:
            pass
    # 1. Try symlink
    try:
        rel_src = os.path.relpath(src, dst.parent)
        dst.symlink_to(rel_src)
        return "symlink"
    except OSError:
        pass
    # 2. Try hardlink (works on Windows without Admin/Developer Mode on same drive)
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        pass
    # 3. Fallback to direct file copy
    shutil.copy2(src, dst)
    return "copy"


def link_or_junction_dir(src: Path, dst: Path):
    """Link directory src -> dst using symlink, NTFS Junction (`mklink /J` on Windows), or copytree fallback."""
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink():
            dst.unlink()
        elif os.name == "nt":
            # Remove junction or directory safely on Windows
            subprocess.run(["cmd", "/c", "rmdir", "/S", "/Q", str(dst)], capture_output=True)
        else:
            shutil.rmtree(dst, ignore_errors=True)

    # 1. Try native symlink
    try:
        rel_src = os.path.relpath(src, dst.parent)
        dst.symlink_to(rel_src, target_is_directory=True)
        return "symlink"
    except OSError:
        pass

    # 2. On Windows, try NTFS Directory Junction (`mklink /J` requires zero Admin rights!)
    if os.name == "nt":
        res = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dst), str(src.resolve())],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return "junction (mklink /J)"

    # 3. Fallback to directory copy
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return "copytree"


def main():
    script_dir = Path(__file__).resolve().parent
    target_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    target_dir = Path(target_arg).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"⚡ Installing Lean Parallel SDLC Harness into: {target_dir}")
    print(f"🖥️  Detected OS: {'Windows (NT)' if os.name == 'nt' else os.uname().sysname}")

    # Copy core files if installing into another directory
    if script_dir != target_dir:
        for folder in (".agents", "dashboard", ".sdlc", "requirements"):
            src_f = script_dir / folder
            if src_f.exists():
                shutil.copytree(src_f, target_dir / folder, dirs_exist_ok=True)
        for fname in (
            "AGENTS.md",
            "providers.py",
            "harness.py",
            "dashboard.py",
            "sync_ecc_skills.py",
            "install.py",
            "install.ps1",
            "install.bat",
            "install.sh",
        ):
            src_file = script_dir / fname
            if src_file.exists():
                shutil.copy2(src_file, target_dir / fname)

    os.chdir(target_dir)

    # Create required directories
    for d in (
        ".claude",
        ".gemini",
        ".worktrees",
        ".sdlc",
        "requirements/inbox",
        "requirements/in_progress",
        "requirements/completed",
        "requirements/failed",
    ):
        Path(d).mkdir(parents=True, exist_ok=True)

    # Link AGENTS.md -> CLAUDE.md and GEMINI.md
    m1 = link_or_copy_file(Path("AGENTS.md"), Path("CLAUDE.md"))
    m2 = link_or_copy_file(Path("AGENTS.md"), Path("GEMINI.md"))
    print(f"  ✓ Linked CLAUDE.md ({m1}) & GEMINI.md ({m2}) -> AGENTS.md")

    # Link .agents/* into .claude/* and .gemini/*
    for sub in ("skills", "agents", "rules", "commands"):
        mode = link_or_junction_dir(Path(".agents") / sub, Path(".claude") / sub)
        print(f"  ✓ Linked .claude/{sub} -> .agents/{sub} ({mode})")

    for sub in ("skills", "commands"):
        mode = link_or_junction_dir(Path(".agents") / sub, Path(".gemini") / sub)
        print(f"  ✓ Linked .gemini/{sub} -> .agents/{sub} ({mode})")

    # Update .gitignore
    gitignore = Path(".gitignore")
    existing_lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    for pattern in (".worktrees/", ".sdlc/", "__pycache__/"):
        if pattern not in existing_lines:
            existing_lines.append(pattern)
    gitignore.write_text("\n".join(existing_lines).strip() + "\n", encoding="utf-8")

    # Initialize Git repository if target is a new empty directory
    res = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if res.returncode != 0:
        print("🌱 Initializing new Git repository on branch 'main'...")
        subprocess.run(["git", "init", "-b", "main"], check=False)

    res_head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    if res_head.returncode != 0:
        print("📝 Creating initial commit so git worktrees can branch cleanly...")
        subprocess.run(["git", "add", "AGENTS.md", ".gitignore"], check=False)
        subprocess.run(["git", "commit", "-m", "chore: bootstrap lean sdlc harness"], check=False)

    py_cmd = "python" if os.name == "nt" else "python3"
    print("\n✅ Lean SDLC Harness v3 (Cross-Platform) installed successfully!")
    print("------------------------------------------------------------------")
    print(f"1. Launch the Live Dashboard:       {py_cmd} dashboard.py --port 8765")
    print("   Open in browser:                 http://localhost:8765")
    print(f"2. Run Visual Demo (0 Tokens):      {py_cmd} harness.py --demo")
    print(f"3. Run Local Folder Queue:          {py_cmd} harness.py --from-folder")
    print(f"4. Watch Folder Continuously:       {py_cmd} harness.py --watch")
    print("5. Inside Claude/Antigravity Chat:  /sdlc <your requirement>")
    print("------------------------------------------------------------------")


if __name__ == "__main__":
    main()
