"""
build_timeline.py

Merges one or more normalized artifact CSVs (see parsers/normalize_kape.py)
into a single sorted timeline, tagging each row with likely ATT&CK
technique IDs per the pattern rules in docs/attack_mapping.yaml.

Usage:
    python build_timeline.py --input normalized1.csv normalized2.csv --output timeline.csv
    python build_timeline.py --input ./case001/normalized/ --output ./case001/timeline.csv
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import yaml


NORMALIZED_FIELDS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file"]
TIMELINE_FIELDS = NORMALIZED_FIELDS + ["attack_techniques"]


def load_attack_rules(path):
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    rules = []
    for rule in config.get("rules", []):
        pattern = re.compile(rule["pattern"], re.IGNORECASE)
        artifact_types = set(rule.get("artifact_types", []))
        rules.append({"technique": rule["technique"], "pattern": pattern, "artifact_types": artifact_types})
    return rules


def tag_techniques(row, rules):
    techniques = []
    for rule in rules:
        if rule["artifact_types"] and row.get("artifact_type") not in rule["artifact_types"]:
            continue
        if rule["pattern"].search(row.get("detail", "")):
            techniques.append(rule["technique"])
    return techniques


def collect_input_files(inputs):
    files = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(path.glob("*.csv")))
        else:
            files.append(path)
    return files


def load_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = set(NORMALIZED_FIELDS) - set(reader.fieldnames or [])
        if missing:
            print(f"[skip] {csv_path} missing expected columns: {sorted(missing)}", file=sys.stderr)
            return []
        return list(reader)


def main():
    parser = argparse.ArgumentParser(description="Merge normalized artifact CSVs into a tagged, sorted timeline.")
    parser.add_argument("--input", required=True, nargs="+", help="Normalized CSV file(s) and/or directories of them")
    parser.add_argument("--output", required=True, help="Output timeline CSV path")
    parser.add_argument(
        "--attack-mapping",
        default=str(Path(__file__).resolve().parent.parent / "docs" / "attack_mapping.yaml"),
        help="Path to ATT&CK pattern rules YAML (default: docs/attack_mapping.yaml)",
    )
    args = parser.parse_args()

    rules = load_attack_rules(args.attack_mapping)

    input_files = collect_input_files(args.input)
    if not input_files:
        print("No input CSV files found.", file=sys.stderr)
        sys.exit(1)

    rows = []
    for csv_path in input_files:
        rows.extend(load_rows(csv_path))

    for row in rows:
        techniques = tag_techniques(row, rules)
        row["attack_techniques"] = ";".join(techniques)

    rows.sort(key=lambda r: r.get("timestamp", ""))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TIMELINE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    tagged = sum(1 for r in rows if r["attack_techniques"])
    print(f"Wrote {len(rows)} rows ({tagged} tagged with ATT&CK techniques) from {len(input_files)} files to {args.output}")


if __name__ == "__main__":
    main()
