"""Artifacts belonging to a single native tool invocation."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone


def save(name, payload):
    path = Path(os.environ['MRCAT_EXECUTION_DIR']) / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return str(path)


def trace(event, payload):
    path = Path(os.environ['MRCAT_EXECUTION_DIR']) / 'trace.jsonl'
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(dict(event=event, time=datetime.now(timezone.utc).isoformat(),
                                     details=payload), ensure_ascii=False, default=str) + '\n')


def result(summary, **outputs):
    return dict(summary=summary, outputs=dict(status='ok', **outputs))
