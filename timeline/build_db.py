"""
build_db.py

Exports a timeline CSV (see build_timeline.py) into a SQLite database plus
a self-contained dashboard, producing exactly two files an analyst can
hand off or open directly:
    <output>/timeline.db     -- all rows, indexed for the dashboard's queries
    <output>/index.html      -- dashboard (queries the .db client-side via sql.js)

index.html is rendered from the timeline/viewer/ template with sql.js's
JS and WASM inlined directly into it (see VIEWER_TEMPLATE / build_index_html
below) rather than shipped as separate files. sql.js's normal loader
fetches its .wasm file, and modern Chromium blocks that under file:// --
inlining means the SQLite engine never needs to fetch anything, so
index.html works identically whether it's opened directly or served.

This replaces render_html.py, which embedded every row as inline JSON in
one HTML file -- fine for small cases, but a real collection's MFT alone
can produce hundreds of thousands of rows, and browsers ran out of memory
either parsing that much embedded JSON or building that many DOM rows.
SQLite (via sql.js, SQLite compiled to WebAssembly) lets the dashboard run
real indexed queries and only ever materialize one page of rows at a time,
regardless of how large the timeline is.

sql.js still loads the whole .db as one in-memory WASM buffer, though, so
it has its own hard ceiling -- roughly 2GB, regardless of the machine's
actual RAM (verified: Chromium fails to read a single File/Blob above
~1.5GB, worked around here by reading in slices, and fails to allocate
one contiguous buffer above ~2GB with no workaround). For a timeline.db
past that size, use serve_db.py instead: it queries the .db directly off
disk with Python's stdlib sqlite3, so there's no size ceiling tied to the
database at all.

Usage:
    python build_db.py --input timeline.csv --output ./case001/dashboard
    python build_db.py --input timeline.csv --output ./case001/dashboard --title "CASE-2026-014"
"""

import argparse
import base64
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TIMELINE_FIELDS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file", "attack_techniques"]
VIEWER_SOURCE_DIR = Path(__file__).resolve().parent / "viewer"


def load_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = set(TIMELINE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{csv_path} missing expected columns: {sorted(missing)}")
        return [{field: row.get(field, "") for field in TIMELINE_FIELDS} for row in reader]


def build_database(db_path, rows, title):
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                host TEXT,
                artifact_type TEXT,
                action TEXT,
                detail TEXT,
                source_file TEXT,
                attack_techniques TEXT
            )
        """)
        conn.execute("CREATE INDEX idx_events_timestamp ON events(timestamp)")
        conn.execute("CREATE INDEX idx_events_artifact_type ON events(artifact_type)")
        conn.execute("CREATE INDEX idx_events_attack_techniques ON events(attack_techniques)")

        conn.executemany(
            f"INSERT INTO events ({', '.join(TIMELINE_FIELDS)}) VALUES ({', '.join('?' for _ in TIMELINE_FIELDS)})",
            [tuple(row[field] for field in TIMELINE_FIELDS) for row in rows],
        )

        tagged_count = sum(1 for r in rows if r["attack_techniques"])
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("title", title),
                ("generated_at", generated_at),
                ("total_count", str(len(rows))),
                ("tagged_count", str(tagged_count)),
            ],
        )

        conn.commit()
    finally:
        conn.close()

    return tagged_count


def build_index_html(output_dir):
    template_path = VIEWER_SOURCE_DIR / "index.html"
    sql_wasm_js_path = VIEWER_SOURCE_DIR / "sql-wasm.js"
    sql_wasm_wasm_path = VIEWER_SOURCE_DIR / "sql-wasm.wasm"
    for path in (template_path, sql_wasm_js_path, sql_wasm_wasm_path):
        if not path.exists():
            raise SystemExit(f"Missing viewer asset {path} -- is timeline/viewer/ intact?")

    template = template_path.read_text(encoding="utf-8")
    sql_wasm_js = sql_wasm_js_path.read_text(encoding="utf-8")
    sql_wasm_base64 = base64.b64encode(sql_wasm_wasm_path.read_bytes()).decode("ascii")

    if "/*__SQL_WASM_JS__*/" not in template or "__SQL_WASM_BASE64__" not in template:
        raise SystemExit(f"{template_path} is missing the expected inlining placeholders -- did the template change?")

    rendered = template.replace("/*__SQL_WASM_JS__*/", sql_wasm_js).replace("__SQL_WASM_BASE64__", sql_wasm_base64)
    (output_dir / "index.html").write_text(rendered, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Export a timeline CSV into a SQLite database plus dashboard.")
    parser.add_argument("--input", required=True, help="Timeline CSV path (output of build_timeline.py)")
    parser.add_argument("--output", required=True, help="Output directory (created if missing)")
    parser.add_argument("--title", default=None, help="Title/case name shown in the dashboard (default: input filename)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(input_path)
    title = args.title or f"DFIR Timeline — {input_path.stem}"

    db_path = output_dir / "timeline.db"
    tagged_count = build_database(db_path, rows, title)
    build_index_html(output_dir)

    print(f"Wrote {len(rows)} events ({tagged_count} ATT&CK-tagged) to {db_path}")
    print(f"Open {output_dir / 'index.html'} in a browser to view -- works opened directly, "
          f"or serve over local http:// to auto-load timeline.db without the file picker.")
    if db_path.stat().st_size > 1_000_000_000:
        print(f"Note: {db_path.name} is over 1GB -- if the dashboard can't load it "
              f"(browsers have a ~2GB in-memory ceiling), use serve_db.py instead: "
              f"python timeline/serve_db.py --db {db_path}")


if __name__ == "__main__":
    main()
