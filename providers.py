#!/usr/bin/env python3
"""
Pluggable Requirement Intake Providers for Lean Parallel SDLC Harness v3 (Cross-Platform).
Supports:
  1. Chat / CLI Input       (--req "..." or via /sdlc command inside Claude / Antigravity chat)
  2. Local Folder Queue     (requirements/inbox/*.md|*.txt|*.json -> in_progress -> completed/failed)
  3. GitHub Issues/Projects (--source github, via `gh` CLI or GITHUB_TOKEN + GITHUB_REPO)
  4. Jira Cloud / Server    (--source jira, via JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)
"""

import base64
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RequirementItem:
    req_id: str
    title: str
    body: str
    source: str  # "chat" | "folder" | "github" | "jira"
    priority: str = "medium"
    file_path: Optional[Path] = None
    external_url: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def full_prompt(self) -> str:
        return f"[{self.req_id}] {self.title}\n\n{self.body}".strip()


class BaseRequirementProvider:
    source_name: str = "base"

    def fetch_next(self) -> list[RequirementItem]:
        raise NotImplementedError

    def mark_in_progress(self, item: RequirementItem):
        pass

    def mark_completed(self, item: RequirementItem, branch: str, summary: str = ""):
        pass

    def mark_failed(self, item: RequirementItem, error: str):
        pass


class ChatInputProvider(BaseRequirementProvider):
    source_name = "chat"

    def __init__(self, text: str, req_id: str = "REQ-CHAT"):
        self.text = text.strip()
        self.req_id = req_id

    def fetch_next(self) -> list[RequirementItem]:
        if not self.text:
            return []
        first_line = self.text.splitlines()[0][:80]
        return [
            RequirementItem(
                req_id=self.req_id,
                title=first_line,
                body=self.text,
                source="chat",
                priority="high",
            )
        ]


class LocalFolderProvider(BaseRequirementProvider):
    source_name = "folder"

    def __init__(self, root_dir: Path = Path("requirements")):
        self.root = root_dir
        self.inbox = self.root / "inbox"
        self.in_progress = self.root / "in_progress"
        self.completed = self.root / "completed"
        self.failed = self.root / "failed"
        for d in (self.inbox, self.in_progress, self.completed, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_frontmatter(raw: str, fallback_id: str, fallback_title: str) -> tuple[str, str, str, str]:
        req_id = fallback_id
        title = fallback_title
        priority = "medium"
        body = raw.strip()

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                fm, body = parts[1], parts[2].strip()
                for line in fm.splitlines():
                    if ":" in line:
                        k, v = [x.strip() for x in line.split(":", 1)]
                        if k.lower() == "id" and v:
                            req_id = v
                        elif k.lower() == "title" and v:
                            title = v
                        elif k.lower() == "priority" and v:
                            priority = v
        if title == fallback_title:
            for line in body.splitlines():
                if line.startswith("#"):
                    title = line.lstrip("#").strip()[:90]
                    break
        return req_id, title, priority, body

    def list_queue_status(self) -> dict:
        def list_files(folder: Path) -> list[dict]:
            items = []
            if not folder.exists():
                return items
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in (".md", ".txt", ".json") and p.name != "README.md":
                    raw = p.read_text(encoding="utf-8", errors="replace")
                    rid, title, prio, _ = self._parse_frontmatter(raw, p.stem.upper(), p.stem)
                    items.append({"file": p.name, "id": rid, "title": title, "priority": prio})
            return items

        return {
            "inbox": list_files(self.inbox),
            "in_progress": list_files(self.in_progress),
            "completed": list_files(self.completed),
            "failed": list_files(self.failed),
        }

    def fetch_next(self) -> list[RequirementItem]:
        items: list[RequirementItem] = []
        for path in sorted(self.inbox.iterdir()):
            if not path.is_file() or path.name == "README.md":
                continue
            if path.suffix.lower() not in (".md", ".txt", ".json"):
                continue

            raw = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".json":
                data = json.loads(raw)
                req_id = data.get("id", path.stem.upper())
                title = data.get("title", path.stem)
                priority = data.get("priority", "medium")
                body = data.get("description") or data.get("body") or raw
            else:
                req_id, title, priority, body = self._parse_frontmatter(raw, path.stem.upper(), path.stem)

            items.append(
                RequirementItem(
                    req_id=req_id,
                    title=title,
                    body=body,
                    source="folder",
                    priority=priority,
                    file_path=path,
                )
            )
        return items

    def mark_in_progress(self, item: RequirementItem):
        if item.file_path and item.file_path.exists():
            dest = self.in_progress / item.file_path.name
            shutil.move(str(item.file_path), str(dest))
            item.file_path = dest

    def mark_completed(self, item: RequirementItem, branch: str, summary: str = ""):
        if item.file_path and item.file_path.exists():
            dest = self.completed / item.file_path.name
            shutil.move(str(item.file_path), str(dest))
            item.file_path = dest

    def mark_failed(self, item: RequirementItem, error: str):
        if item.file_path and item.file_path.exists():
            dest = self.failed / item.file_path.name
            shutil.move(str(item.file_path), str(dest))
            err_log = dest.with_suffix(dest.suffix + ".error.log")
            err_log.write_text(error, encoding="utf-8")
            item.file_path = dest


class GitHubProjectProvider(BaseRequirementProvider):
    source_name = "github"

    def __init__(self, label: str = "sdlc-ready", limit: int = 5):
        self.label = os.environ.get("GITHUB_SDLC_LABEL", label)
        self.repo = os.environ.get("GITHUB_REPO", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.limit = limit

    def fetch_next(self) -> list[RequirementItem]:
        gh_bin = shutil.which("gh")
        if gh_bin:
            cmd = [gh_bin, "issue", "list", "--label", self.label, "--state", "open", "--limit", str(self.limit), "--json", "number,title,body,url"]
            if self.repo:
                cmd.extend(["--repo", self.repo])
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode == 0 and res.stdout.strip():
                issues = json.loads(res.stdout)
                return [
                    RequirementItem(
                        req_id=f"GH-{iss['number']}",
                        title=iss["title"],
                        body=iss.get("body") or iss["title"],
                        source="github",
                        external_url=iss.get("url"),
                        metadata={"number": iss["number"]},
                    )
                    for iss in issues
                ]

        if self.token and self.repo:
            url = f"https://api.github.com/repos/{self.repo}/issues?labels={urllib.parse.quote(self.label)}&state=open&per_page={self.limit}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "lean-sdlc-harness",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                issues = json.loads(resp.read().decode("utf-8"))
                return [
                    RequirementItem(
                        req_id=f"GH-{iss['number']}",
                        title=iss["title"],
                        body=iss.get("body") or iss["title"],
                        source="github",
                        external_url=iss.get("html_url"),
                        metadata={"number": iss["number"]},
                    )
                    for iss in issues
                    if "pull_request" not in iss
                ]

        raise RuntimeError(
            "GitHub integration requires either `gh auth login` or environment variables GITHUB_REPO='owner/repo' and GITHUB_TOKEN='ghp_...'."
        )

    def mark_completed(self, item: RequirementItem, branch: str, summary: str = ""):
        num = item.metadata.get("number")
        gh_bin = shutil.which("gh")
        if not num or not gh_bin:
            return
        comment = f"✅ Automated SDLC Harness completed implementation on branch `{branch}`.\n\n{summary}"
        cmd = [gh_bin, "issue", "comment", str(num), "--body", comment]
        if self.repo:
            cmd.extend(["--repo", self.repo])
        subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


class JiraProvider(BaseRequirementProvider):
    source_name = "jira"

    def __init__(self):
        self.base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
        self.email = os.environ.get("JIRA_EMAIL", "")
        self.api_token = os.environ.get("JIRA_API_TOKEN", "")
        self.jql = os.environ.get(
            "JIRA_JQL",
            'labels = "sdlc-ready" AND statusCategory != Done ORDER BY priority DESC',
        )

    def _headers(self) -> dict:
        auth_str = f"{self.email}:{self.api_token}".encode("utf-8")
        b64 = base64.b64encode(auth_str).decode("ascii")
        return {
            "Authorization": f"Basic {b64}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def fetch_next(self) -> list[RequirementItem]:
        if not (self.base_url and self.email and self.api_token):
            raise RuntimeError(
                "Jira integration requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN environment variables."
            )
        query = urllib.parse.urlencode({"jql": self.jql, "maxResults": 5, "fields": "summary,description,priority"})
        url = f"{self.base_url}/rest/api/3/search?{query}"
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items: list[RequirementItem] = []
        for issue in data.get("issues", []):
            key = issue["key"]
            fields = issue.get("fields", {})
            title = fields.get("summary", key)
            desc = fields.get("description")
            body = json.dumps(desc, indent=2) if isinstance(desc, dict) else str(desc or title)
            prio = (fields.get("priority") or {}).get("name", "Medium").lower()
            items.append(
                RequirementItem(
                    req_id=key,
                    title=title,
                    body=body,
                    source="jira",
                    priority=prio,
                    external_url=f"{self.base_url}/browse/{key}",
                    metadata={"key": key},
                )
            )
        return items
