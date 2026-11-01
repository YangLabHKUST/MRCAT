import sys
"""Exercise Skill JSON serializers, including embedded reference R code."""

import ast
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.r


ROOT = Path(__file__).resolve().parents[1]
RSCRIPT = os.environ.get("RSCRIPT_BIN", str(Path(sys.executable).parent / "Rscript"))


def test_skill_json_serializers_preserve_scientific_values(tmp_path):
    sources = {
        str(path.relative_to(ROOT)): path.read_text()
        for path in sorted((ROOT / "skills").rglob("*.R"))
    }
    path = ROOT / "tests/fixtures/mr_grip_reference.py"
    for index, node in enumerate(ast.walk(ast.parse(path.read_text()))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "jsonlite::" in node.value:
            sources[f"{path.relative_to(ROOT)}:reference:{index}"] = node.value
    source_path = tmp_path / "sources.json"
    source_path.write_text(json.dumps(sources))
    output = tmp_path / "records.json"
    script = tmp_path / "check.R"
    script.write_text('''
    sources <- jsonlite::read_json(commandArgs(TRUE)[1])
    records <- list()
    value <- list(pval=0.0000192392694041026, Threshold=5e-5, strict=5e-8,
                  beta=-0.0000320502034536, se=0.000000123456789,
                  near_alpha=0.05000001, tiny=1.23456789e-250,
                  zero=0, count=38L, missing=NULL, detected=FALSE,
                  bound="<0.001", covariance=c(1, -0.0000123456789))
    visit <- function(expr, source) {
      if (missing(expr)) return(invisible(NULL))
      if (is.call(expr)) {
        name <- paste(deparse(expr[[1]]), collapse="")
        if (name %in% c("jsonlite::write_json", "jsonlite::toJSON",
                        "write_json", "toJSON")) {
          args <- as.list(expr)[-1]
          if (!"digits" %in% names(args) || !identical(args$digits, NA)) {
            stop(source, ": serializer must explicitly use digits = NA")
          }
          expr[[2]] <- quote(value)
          if (grepl("write_json$", name)) {
            path <- tempfile(fileext=".json")
            expr[[3]] <- quote(path)
            eval(expr)
            saved <- jsonlite::read_json(path)
            unlink(path)
          } else {
            saved <- jsonlite::fromJSON(eval(expr), simplifyVector=FALSE)
          }
          records[[length(records) + 1L]] <<- list(source=source, value=saved)
          return(invisible(NULL))
        }
      }
      if (is.call(expr) || is.expression(expr) || is.pairlist(expr)) {
        lapply(as.list(expr), function(child) visit(child, source))
      }
      invisible(NULL)
    }
    for (source in names(sources)) visit(parse(text=sources[[source]]), source)
    jsonlite::write_json(records, commandArgs(TRUE)[2], auto_unbox=TRUE,
                         null="null", digits=NA)
    ''')
    run = subprocess.run(
        [RSCRIPT, str(script), str(source_path), str(output)],
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stderr[-6000:]
    records = json.loads(output.read_text())
    assert records
    assert any("mr_grip_reference.py" in record["source"] for record in records)
    expected = dict(
        pval=0.0000192392694041026, Threshold=5e-5, strict=5e-8,
        beta=-0.0000320502034536, se=0.000000123456789,
        near_alpha=0.05000001, tiny=1.23456789e-250, zero=0, count=38,
    )
    for record in records:
        saved = record["value"]
        for key, value in expected.items():
            assert saved[key] == pytest.approx(value, rel=1e-13, abs=0), (record["source"], key)
        assert saved["covariance"] == pytest.approx([1, -0.0000123456789], rel=1e-13, abs=0)
        assert saved["missing"] is None
        assert saved["detected"] is False
        assert saved["bound"] == "<0.001"
