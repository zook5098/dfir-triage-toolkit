"""
build_db.py

Exports a timeline CSV (see build_timeline.py) into a SQLite database plus
a copy of the static sql.js-based dashboard (timeline/viewer/), producing a
self-contained output folder an analyst can open directly:
    <output>/timeline.db     -- all rows, indexed for the dashboard's queries
    <output>/index.html      -- dashboard (queries the .db client-side via sql.js)
    <output>/sql-wasm.js
    <output>/sql-wasm.wasm

This replaces render_html.py, which embedded every row as inline JSON in
one HTML file -- fine for small cases, but a real collection's MFT alone
can produce hundreds of thousands of rows, and browsers ran out of memory
either parsing that much embedded JSON or building that many DOM rows.
SQLite (via sql.js, SQLite compiled to WebAssembly) lets the dashboard run
real indexed queries and only ever materialize one page of rows at a time,
regardless of how large the timeline is.

Usage:
    python build_db.py --input timeline.csv --output ./case001/dashboard
    python build_db.py --input timeline.csv --output ./case001/dashboard --title "CASE-2026-014"
"""

import argparse
import csv
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


TIMELINE_FIELDS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file", "attack_techniques"]
VIEWER_ASSETS = ["index.html", "sql-wasm.js", "sql-wasm.wasm"]
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


def copy_viewer_assets(output_dir):
    for name in VIEWER_ASSETS:
        src = VIEWER_SOURCE_DIR / name
        if not src.exists():
            raise SystemExit(f"Missing viewer asset {src} -- is timeline/viewer/ intact?")
        shutil.copyfile(src, output_dir / name)


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
    copy_viewer_assets(output_dir)

    print(f"Wrote {len(rows)} events ({tagged_count} ATT&CK-tagged) to {db_path}")
    print(f"Open {output_dir / 'index.html'} in a browser to view (serve over local http:// for auto-load, "
          f"or open directly and use the file picker).")


if __name__ == "__main__":
    main()
