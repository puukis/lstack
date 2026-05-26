"""LStack Dashboard local HTTP server — read-only by default."""

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .overview import _iso_now, build_dashboard_overview, build_lbrain, build_memory_detail, CLAUDE_DIR
from .actions import build_action_registry, execute_action
from .audit import read_recent_audit_entries, write_audit_entry
from .static_server import serve_static, dist_exists


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, data, code: int = 200) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        result = serve_static(path)
        if result is None:
            self._json({"error": "not found"}, 404)
            return
        code, mime, body = result
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/overview":
            self._json(build_dashboard_overview())
        elif path == "/api/lbrain":
            lb = build_lbrain()
            self._json(lb if lb is not None else {"available": False})
        elif path == "/api/memory":
            limit = 100
            try:
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                for part in qs.split("&"):
                    if part.startswith("limit="):
                        limit = int(part[6:])
            except Exception:
                pass
            self._json(build_memory_detail(limit=limit))
        elif path == "/api/health":
            self._json({
                "ok": True,
                "read_only": True,
                "project": CLAUDE_DIR.name,
                "generated_at": _iso_now(),
            })
        elif path == "/api/actions":
            self._json(build_action_registry())
        elif path == "/api/actions/audit":
            limit = 50
            try:
                qs = self.path.split("?", 1)[1] if "?" in self.path else ""
                for part in qs.split("&"):
                    if part.startswith("limit="):
                        limit = int(part[6:])
            except Exception:
                pass
            self._json({"entries": read_recent_audit_entries(limit=limit)})
        elif path.startswith("/api/"):
            self._json({"error": "not found"}, 404)
        else:
            # Serve built frontend or fallback HTML
            self._static(path)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/actions/execute":
            # V1: all actions disabled — return 403 with clear message
            self._json({
                "ok": False,
                "error": "Actions are disabled in V1. Interactive controls are coming in a later version.",
                "mode": "read_only_v1",
            }, 403)
            return
        self._method_not_allowed()

    def do_PUT(self):
        self._method_not_allowed()

    def do_PATCH(self):
        self._method_not_allowed()

    def do_DELETE(self):
        self._method_not_allowed()

    def _method_not_allowed(self):
        self._json({"error": "method not allowed"}, 405)


def _check_host(host: str, allow_lan: bool) -> None:
    safe = {"127.0.0.1", "localhost", "::1"}
    if host in safe:
        return
    if allow_lan:
        print(f"WARNING: Binding to {host} — dashboard accessible on LAN.", flush=True)
        return
    if host == "0.0.0.0":
        print("Error: --host 0.0.0.0 requires --allow-lan for safety.", flush=True)
        sys.exit(1)
    print(f"Error: Non-localhost host '{host}' requires --allow-lan.", flush=True)
    sys.exit(1)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    allow_lan: bool = False,
) -> None:
    _check_host(host, allow_lan)
    has_ui = dist_exists()
    httpd = HTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}"
    print(f"LStack dashboard running at {url}", flush=True)
    if not has_ui:
        print("  Note: frontend/dist not found — serving API only.", flush=True)
        print("  Run: cd ~/.claude/dashboard/frontend && bun run build", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


def print_json_overview() -> None:
    import json
    print(json.dumps(build_dashboard_overview(), indent=2, default=str))


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    host = "127.0.0.1"
    port = 8765
    open_browser = False
    allow_lan = False
    json_mode = False

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--host" and i + 1 < len(args):
            i += 1; host = args[i]
        elif a == "--port" and i + 1 < len(args):
            i += 1; port = int(args[i])
        elif a == "--open":
            open_browser = True
        elif a == "--no-open":
            open_browser = False
        elif a == "--allow-lan":
            allow_lan = True
        elif a == "--json":
            json_mode = True
        i += 1

    if json_mode:
        print_json_overview()
        return

    serve(host=host, port=port, open_browser=open_browser, allow_lan=allow_lan)


if __name__ == "__main__":
    main()
