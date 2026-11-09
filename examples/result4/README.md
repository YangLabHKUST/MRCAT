# Result 4: hexadecanedioate and coronary artery disease

This is a read-only recording of completed session `session_4cc4857090a941e3`,
the source identified by the current manuscript's Result 4 supplementary tables.
It includes the original MR analysis, the FinnGen replication and the final
scientific report. Failed attempts and subsequent corrections remain visible.

Select **Result 4 · Hexadecanedioate → CAD** in MRCAT, then browse the complete
session or select an analysis stage. Expand execution cells, inspect tables and
figures, download included artifacts or open the final report. Viewing the
recording makes no model calls and requires no API key.

The reported evidence was insufficient to establish a protective causal effect.
A completed workflow is not proof of causality. Recorded estimates and scientific
qualifications are preserved; the current frontend only changes their display.

## Standalone website

The export can also be served by any static web server, without MRCAT's Python/R
backend, model credentials or session database. Serve the generated `site/`
directory as the website root. It contains only frontend assets and the reviewed
recording. No session creation, replies, reruns or model selection are available.

## Rebuild from the source session

Run from the repository root with the MRCAT environment installed:

```bash
python examples/result4/export_recording.py \
  --session /path/to/session_4cc4857090a941e3 \
  --destination /path/to/empty-recording-directory \
  --env-file /path/to/private/config.env \
  --site /path/to/empty-site-directory
python -m http.server 7891 --bind 127.0.0.1 --directory /path/to/empty-site-directory
```

The exporter reads a private checkpoint copy and never updates the source session.
Pass every environment file used for the recorded run so its credential values
can be redacted. Machine-local paths and temporary download tokens are removed.
Audit material, environment files, report drafts, checkpoints and large GWAS
files are excluded. This is a viewing package, not a resumable execution archive.

After changing the UI, rebuild the static site with the updated frontend assets
and redeploy it. The recorded results remain fixed. The application can use the
same recording under `mrcat/web/static/examples/result4/`.
