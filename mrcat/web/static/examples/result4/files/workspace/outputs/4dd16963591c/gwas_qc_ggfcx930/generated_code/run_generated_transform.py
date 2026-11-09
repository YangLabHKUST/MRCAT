from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path

code_path = Path(sys.argv[1]).resolve()
input_path = sys.argv[2]
output_path = sys.argv[3]
context = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("gwas_qc_generated_transform", code_path)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)
transform = getattr(module, "transform")
result = transform(input_path, output_path, context)
print(json.dumps({"result": result}, ensure_ascii=False, default=str))
