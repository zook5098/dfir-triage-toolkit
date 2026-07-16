"""
serve_db.py

Serves a timeline .db (see build_db.py) via a small local JSON API and a
matching static dashboard (timeline/server_viewer/), for cases too large
for the default sql.js-based dashboard (timeline/viewer/) to hold in
browser memory.

That dashboard loads the whole .db as one in-memory WASM buffer, which has
a hard ceiling around 2GB regardless of available RAM. This script instead
queries the .db directly off disk with Python's stdlib sqlite3 -- only a
page of rows is ever materialized at a time, in Python or in the browser,
so there's no size ceiling tied to the database itself.

Uses only the standard library (sqlite3, http.server) -- no new
dependencies. Opens the database read-only (mode=ro) so this can never
write to evidence. Binds to 127.0.0.1 only, not the network.

Usage:
    python serve_db.py --db ./case001/dashboard/timeline.db
    python serve_db.py --db ./case001/dashboard/timeline.db --port 9000
"""

import argparse
import json
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ORDERABLE_COLUMNS = {"timestamp", "host", "artifact_type", "action", "detail", "attack_techniques", "source_file"}
SEARCH_COLUMNS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file", "attack_techniques"]
VIEWER_DIR = Path(__file__).resolve().parent / "server_viewer"
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 5000


def connect_readonly(db_path):
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def build_where(query_params):
    clauses = []
    params = []

    if "types" in query_params:
        types = [t for t in query_params["types"][0].split(",") if t]
        if not types:
            clauses.append("1 = 0")
        else:
            clauses.append(f"artifact_type IN ({', '.join('?' for _ in types)})")
            params.extend(types)

    if query_params.get("attack_only", ["0"])[0] == "1":
        clauses.append("attack_techniques != ''")

    search = query_params.get("search", [""])[0]
    if search:
        s = f"%{search}%"
        clauses.append("(" + " OR ".join(f"{col} LIKE ?" for col in SEARCH_COLUMNS) + ")")
        params.extend([s] * len(SEARCH_COLUMNS))

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def get_meta(conn):
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get_artifact_types(conn):
    rows = conn.execute("SELECT DISTINCT artifact_type FROM events ORDER BY artifact_type").fetchall()
    return [row["artifact_type"] for row in rows]


def get_events(conn, query_params):
    where, params = build_where(query_params)

    sort_key = query_params.get("sort", ["timestamp"])[0]
    if sort_key not in ORDERABLE_COLUMNS:
        sort_key = "timestamp"
    sort_dir = "DESC" if query_params.get("dir", ["asc"])[0] == "desc" else "ASC"

    try:
        page = max(0, int(query_params.get("page", ["0"])[0]))
    except ValueError:
        page = 0
    try:
        page_size = int(query_params.get("page_size", [str(DEFAULT_PAGE_SIZE)])[0])
    except ValueError:
        page_size = DEFAULT_PAGE_SIZE
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    total = conn.execute(f"SELECT COUNT(*) AS c FROM events {where}", params).fetchone()["c"]

    offset = page * page_size
    rows = conn.execute(
        f"SELECT timestamp, host, artifact_type, action, detail, source_file, attack_techniques "
        f"FROM events {where} ORDER BY {sort_key} {sort_dir} LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    ).fetchall()

    return {"total": total, "rows": [dict(row) for row in rows]}


def make_handler(db_path):
    index_html = (VIEWER_DIR / "index.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)

            if parsed.path in ("/", "/index.html"):
                body = index_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if not parsed.path.startswith("/api/"):
                self.send_error(404)
                return

            query_params = urllib.parse.parse_qs(parsed.query)
            try:
                conn = connect_readonly(db_path)
                try:
                    if parsed.path == "/api/meta":
                        self._send_json(get_meta(conn))
                    elif parsed.path == "/api/artifact_types":
                        self._send_json(get_artifact_types(conn))
                    elif parsed.path == "/api/events":
                        self._send_json(get_events(conn, query_params))
                    else:
                        self.send_error(404)
                finally:
                    conn.close()
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Serve a timeline .db via a local JSON API + dashboard (for databases too large for the sql.js viewer).")
    parser.add_argument("--db", required=True, help="Path to a timeline.db built by build_db.py")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1, local only)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    if not (VIEWER_DIR / "index.html").exists():
        raise SystemExit(f"Missing viewer template: {VIEWER_DIR / 'index.html'} -- is timeline/server_viewer/ intact?")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(db_path))
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {db_path} at {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
