#!/usr/bin/env python3
"""
Cross-Platform ECC Skill Syncer (Works on Windows, macOS, and Linux).
Pulls the latest curated 18 skills + common rules from https://github.com/iBabafakruddin/ECC
using Python's `tempfile` and `shutil` (no bash or /tmp dependencies).
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

ECC_REPO = "https://github.com/iBabafakruddin/ECC.git"

SKILLS = [
    "java-coding-standards",
    "springboot-patterns",
    "jpa-patterns",
    "springboot-tdd",
    "springboot-verification",
    "springboot-security",
    "postgres-patterns",
    "database-migrations",
    "backend-patterns",
    "python-patterns",
    "python-testing",
    "frontend-patterns",
    "coding-standards",
    "api-design",
    "frontend-design",
    "security-review",
    "tdd-workflow",
    "strategic-compact",
]


def main():
    tmp_dir = Path(tempfile.mkdtemp(prefix="ecc-upstream-"))
    print(f"🔄 Fetching latest curated skills from {ECC_REPO} ...")
    try:
        res = subprocess.run(["git", "clone", "--depth", "1", ECC_REPO, str(tmp_dir)], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git clone failed: {res.stderr}")

        skills_dst = Path(".agents/skills")
        rules_dst = Path(".agents/rules/common")
        skills_dst.mkdir(parents=True, exist_ok=True)
        rules_dst.mkdir(parents=True, exist_ok=True)

        for skill in SKILLS:
            src = tmp_dir / "skills" / skill
            if src.exists():
                shutil.copytree(src, skills_dst / skill, dirs_exist_ok=True)
                print(f"  ✓ Synced skill: {skill}")

        common_src = tmp_dir / "rules" / "common"
        if common_src.exists():
            shutil.copytree(common_src, rules_dst, dirs_exist_ok=True)
            print("  ✓ Synced rules/common")

        print("✅ Upstream ECC skills synced into .agents/skills/")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
