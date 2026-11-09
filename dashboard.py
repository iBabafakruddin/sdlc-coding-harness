#!/usr/bin/env python3
"""
Zero-Dependency Live Web Dashboard Server for the Lean Parallel SDLC Harness v3 (Windows, macOS, Linux).
Run:
    python dashboard.py --port 8765
"""

import argparse
import json
import re
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from providers import LocalFolderProvider

TELEMETRY_FILE = Path(".sdlc/telemetry.json")
DASHBOARD_HTML = Path("dashboard/index.html")


class DashboardHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.read_bytes())
        elif parsed.path == "/api/telemetry":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            folder_q = LocalFolderProvider().list_queue_status()
            if TELEMETRY_FILE.exists():
                try:
                    data = json.loads(TELEMETRY_FILE.read_text(encoding="utf-8"))
                except Exception:
                    data = {"status": "IDLE", "stories": [], "events": [], "tokens": {}}
            else:
                data = {"status": "IDLE", "stories": [], "events": [], "tokens": {}}
            data["requirements_queue"] = folder_q
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if parsed.path == "/api/run":
            source = body.get("source", "chat")
            req = body.get("requirement", "").strip()
            demo = bool(body.get("demo", True))

            cmd = [sys.executable, "harness.py", "--source", source]
            if source == "chat" and req:
                cmd.append(req)
            if demo:
                cmd.append("--demo")
            subprocess.Popen(cmd)

            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"started": True, "source": source, "mode": "demo" if demo else "live"}).encode("utf-8"))

        elif parsed.path == "/api/requirements/add":
            req_id = body.get("id", "REQ-NEW").strip() or "REQ-NEW"
            title = body.get("title", "New Feature Requirement").strip()
            content = body.get("body", title).strip()
            priority = body.get("priority", "high").strip()

            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", f"{req_id}-{title[:30]}").strip("-").lower()
            inbox_dir = Path("requirements/inbox")
            inbox_dir.mkdir(parents=True, exist_ok=True)
            file_path = inbox_dir / f"{slug}.md"

            md_text = (
                f"---\nid: {req_id}\ntitle: {title}\npriority: {priority}\nsource: local-folder\n---\n\n"
                f"# {title}\n\n{content}\n"
            )
            file_path.write_text(md_text, encoding="utf-8")

            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"saved": str(file_path)}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")


def main():
    parser = argparse.ArgumentParser(description="Lean SDLC Live Telemetry Dashboard v3")
    parser.add_argument("--port", type=int, default=8765, help="Port to serve dashboard on (default: 8765)")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"📊 Lean SDLC Mission Control v3 running at: http://localhost:{args.port}")
    print("   Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")


if __name__ == "__main__":
    main()
