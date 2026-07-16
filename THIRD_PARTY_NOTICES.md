# Third-Party Notices

This repository vendors the following third-party library so the timeline
dashboard (`timeline/viewer/`) works fully offline, with no CDN or network
dependency at runtime.

## sql.js

- **What**: SQLite compiled to WebAssembly, used by `timeline/viewer/index.html`
  to run indexed SQL queries against a `.db` file entirely in the browser.
- **Version**: 1.14.1
- **Source**: https://github.com/sql-js/sql.js
- **Distribution fetched from**: https://cdn.jsdelivr.net/npm/sql.js@1.14.1/dist/
  (jsDelivr mirrors the published npm package; not modified after download)
- **License**: MIT
- **Files**: `timeline/viewer/sql-wasm.js`, `timeline/viewer/sql-wasm.wasm`
  are the pristine vendored source. `build_db.py` inlines both directly
  into the generated `index.html` (the JS as-is; the WASM base64-encoded)
  rather than shipping them as separate files, so each dashboard output
  is exactly two files (`timeline.db` + `index.html`) and the SQLite
  engine never needs to fetch anything to start, which also avoids a
  `file://`-origin restriction in Chromium (see README's Dashboard notes).

To update: download the new version's `dist/sql-wasm.js` and
`dist/sql-wasm.wasm` from the same jsDelivr path with the new version
pinned, replace the files in `timeline/viewer/`, and update the version
noted above.
