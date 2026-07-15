"""
render_html.py

Renders a timeline CSV (see build_timeline.py) into a single self-contained
HTML file for standalone review — no server, no external assets, safe to
hand off or open on an air-gapped analysis box. Supports free-text search,
artifact-type filtering, an ATT&CK-tagged-only toggle, and click-to-sort
columns, all client-side over the embedded row data.

Usage:
    python render_html.py --input timeline.csv --output timeline.html
    python render_html.py --input timeline.csv --output timeline.html --title "CASE-2026-014"
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


TIMELINE_FIELDS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file", "attack_techniques"]


def load_rows(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = set(TIMELINE_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{csv_path} missing expected columns: {sorted(missing)}")
        return [{field: row.get(field, "") for field in TIMELINE_FIELDS} for row in reader]


def embed_json(data):
    """Serialize for inline embedding in a <script> tag, escaping '</' so a
    literal '</script>' inside string data can't terminate the block early."""
    return json.dumps(data).replace("</", "<\\/")


def render_html(rows, title):
    artifact_types = sorted({r["artifact_type"] for r in rows if r["artifact_type"]})
    tagged_count = sum(1 for r in rows if r["attack_techniques"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return HTML_TEMPLATE.format(
        title=title,
        generated_at=generated_at,
        total_count=len(rows),
        tagged_count=tagged_count,
        data_json=embed_json(rows),
        artifact_types_json=embed_json(artifact_types),
    )


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #f7f7f8; --panel: #ffffff; --text: #1a1a1a; --muted: #6b7280;
    --border: #e2e2e5; --accent: #2563eb; --tag-bg: #fee2e2; --tag-text: #991b1b;
    --row-hover: #f0f4ff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #15161a; --panel: #1d1e23; --text: #e6e6e8; --muted: #9098a4;
      --border: #33343a; --accent: #6ea8fe; --tag-bg: #4a1d1d; --tag-text: #ffb4b4;
      --row-hover: #23262f;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    background: var(--bg); color: var(--text); font-size: 13px;
  }}
  header {{ padding: 16px 20px; border-bottom: 1px solid var(--border); background: var(--panel); }}
  h1 {{ margin: 0 0 4px; font-size: 18px; }}
  .meta {{ color: var(--muted); font-size: 12px; }}
  .controls {{
    display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
    padding: 12px 20px; background: var(--panel); border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
  }}
  #search {{
    flex: 1 1 260px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px;
    background: var(--bg); color: var(--text); font-size: 13px;
  }}
  .types {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .types label {{ display: flex; align-items: center; gap: 4px; color: var(--muted); cursor: pointer; }}
  #attackOnly {{ display: flex; align-items: center; gap: 4px; color: var(--muted); cursor: pointer; white-space: nowrap; }}
  #count {{ color: var(--muted); margin-left: auto; white-space: nowrap; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    position: sticky; top: 49px; background: var(--panel); text-align: left; padding: 8px 10px;
    border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; white-space: nowrap;
    font-weight: 600; color: var(--muted);
  }}
  thead th:hover {{ color: var(--text); }}
  thead th.sorted {{ color: var(--accent); }}
  tbody td {{
    padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top;
    max-width: 480px; overflow-wrap: break-word;
  }}
  tbody tr:hover {{ background: var(--row-hover); }}
  tbody tr.tagged {{ box-shadow: inset 3px 0 0 var(--tag-text); }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }}
  .badge {{
    display: inline-block; background: var(--tag-bg); color: var(--tag-text);
    border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600;
    margin: 1px 3px 1px 0; white-space: nowrap;
  }}
  .source {{ color: var(--muted); font-size: 11px; }}
  #empty {{ display: none; padding: 40px; text-align: center; color: var(--muted); }}
</style>
</head>
<body>

<header>
  <h1>{title}</h1>
  <div class="meta">Generated {generated_at} &middot; <span id="totalMeta">{total_count}</span> events &middot; <span id="taggedMeta">{tagged_count}</span> ATT&amp;CK-tagged</div>
</header>

<div class="controls">
  <input id="search" type="text" placeholder="Search timestamp, host, action, detail, source, technique...">
  <div class="types" id="typeFilters"></div>
  <label id="attackOnly"><input type="checkbox" id="attackOnlyCheckbox"> ATT&amp;CK-tagged only</label>
  <span id="count"></span>
</div>

<table>
  <thead>
    <tr>
      <th data-key="timestamp">Timestamp</th>
      <th data-key="host">Host</th>
      <th data-key="artifact_type">Artifact</th>
      <th data-key="action">Action</th>
      <th data-key="detail">Detail</th>
      <th data-key="attack_techniques">ATT&amp;CK</th>
      <th data-key="source_file">Source</th>
    </tr>
  </thead>
  <tbody id="rows"></tbody>
</table>
<div id="empty">No events match the current filters.</div>

<script>
  const DATA = {data_json};
  const ARTIFACT_TYPES = {artifact_types_json};

  const state = {{ search: "", types: new Set(ARTIFACT_TYPES), attackOnly: false, sortKey: "timestamp", sortDir: 1 }};

  const typeFiltersEl = document.getElementById("typeFilters");
  ARTIFACT_TYPES.forEach(t => {{
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.dataset.type = t;
    cb.addEventListener("change", () => {{
      if (cb.checked) state.types.add(t); else state.types.delete(t);
      render();
    }});
    label.appendChild(cb);
    label.appendChild(document.createTextNode(" " + t));
    typeFiltersEl.appendChild(label);
  }});

  document.getElementById("attackOnlyCheckbox").addEventListener("change", (e) => {{
    state.attackOnly = e.target.checked;
    render();
  }});

  let searchTimer = null;
  document.getElementById("search").addEventListener("input", (e) => {{
    clearTimeout(searchTimer);
    const value = e.target.value;
    searchTimer = setTimeout(() => {{ state.search = value.toLowerCase(); render(); }}, 120);
  }});

  document.querySelectorAll("thead th[data-key]").forEach(th => {{
    th.addEventListener("click", () => {{
      const key = th.dataset.key;
      if (state.sortKey === key) {{ state.sortDir *= -1; }} else {{ state.sortKey = key; state.sortDir = 1; }}
      document.querySelectorAll("thead th").forEach(h => h.classList.remove("sorted"));
      th.classList.add("sorted");
      render();
    }});
  }});

  function escapeHtml(s) {{
    return String(s).replace(/[&<>"']/g, c => ({{
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }})[c]);
  }}

  function matches(row) {{
    if (!state.types.has(row.artifact_type)) return false;
    if (state.attackOnly && !row.attack_techniques) return false;
    if (!state.search) return true;
    return TIMELINE_FIELDS_JS.some(k => (row[k] || "").toLowerCase().includes(state.search));
  }}

  const TIMELINE_FIELDS_JS = ["timestamp", "host", "artifact_type", "action", "detail", "source_file", "attack_techniques"];

  function render() {{
    const filtered = DATA.filter(matches);
    filtered.sort((a, b) => {{
      const av = (a[state.sortKey] || ""), bv = (b[state.sortKey] || "");
      return av < bv ? -state.sortDir : av > bv ? state.sortDir : 0;
    }});

    const tbody = document.getElementById("rows");
    const empty = document.getElementById("empty");
    document.getElementById("count").textContent = `Showing ${{filtered.length}} of ${{DATA.length}}`;

    if (filtered.length === 0) {{
      tbody.innerHTML = "";
      empty.style.display = "block";
      return;
    }}
    empty.style.display = "none";

    tbody.innerHTML = filtered.map(row => {{
      const techniques = row.attack_techniques
        ? row.attack_techniques.split(";").filter(Boolean).map(t => `<span class="badge">${{escapeHtml(t)}}</span>`).join("")
        : "";
      const tagged = row.attack_techniques ? "tagged" : "";
      return `<tr class="${{tagged}}">
        <td class="mono">${{escapeHtml(row.timestamp)}}</td>
        <td>${{escapeHtml(row.host)}}</td>
        <td>${{escapeHtml(row.artifact_type)}}</td>
        <td>${{escapeHtml(row.action)}}</td>
        <td>${{escapeHtml(row.detail)}}</td>
        <td>${{techniques}}</td>
        <td class="source" title="${{escapeHtml(row.source_file)}}">${{escapeHtml(row.source_file)}}</td>
      </tr>`;
    }}).join("");
  }}

  document.querySelector('thead th[data-key="timestamp"]').classList.add("sorted");
  render();
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Render a timeline CSV into a self-contained HTML viewer.")
    parser.add_argument("--input", required=True, help="Timeline CSV path (output of build_timeline.py)")
    parser.add_argument("--output", required=True, help="Output HTML path")
    parser.add_argument("--title", default=None, help="Title/case name shown in the viewer (default: input filename)")
    args = parser.parse_args()

    input_path = Path(args.input)
    rows = load_rows(input_path)
    title = args.title or f"DFIR Timeline — {input_path.stem}"

    html = render_html(rows, title)
    Path(args.output).write_text(html, encoding="utf-8")

    print(f"Wrote {len(rows)} events to {args.output}")


if __name__ == "__main__":
    main()
