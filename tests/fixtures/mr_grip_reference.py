import json, os, subprocess, sys
from pathlib import Path

def main():
    input_path = Path(sys.argv[1])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    skill_dir = Path(os.environ["MRCAT_SKILL_DIR"])
    raw_path = str(payload["mrdat_path"])
    if raw_path.startswith("$SKILL_DIR/"):
        fixture_path = skill_dir / raw_path[len("$SKILL_DIR/"):]
    else:
        fixture_path = Path(raw_path)
    threshold = float(payload.get("pvalue_threshold", 5e-08))
    rows = []
    with fixture_path.open("r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            values = line.split("\t")
            rows.append(dict(zip(header, values)))
    rows = [r for r in rows if float(r["pval.exp"]) <= threshold]
    if len(rows) < int(payload.get("min_instruments", 4)):
        raise ValueError("insufficient reference instruments")
    r_data = {
        "b_exp": [float(r["b.exp"]) for r in rows],
        "b_out": [float(r["b.out"]) for r in rows],
        "se_exp": [float(r["se.exp"]) for r in rows],
        "se_out": [float(r["se.out"]) for r in rows],
    }
    r_script = """
suppressPackageStartupMessages({library(TwoSampleMR); library(jsonlite)})
args <- jsonlite::fromJSON(Sys.getenv("MRGRIP_REFERENCE_DATA"))
res <- TwoSampleMR::mr_grip(args$b_exp, args$b_out, args$se_exp, args$se_out, parameters = list())
out <- list(b = res$b, se = res$se, pval = res$pval, b_adj = res$b.adj, se_adj = res$se.adj, pval_adj = res$pval.adj)
cat(jsonlite::toJSON(out, auto_unbox = TRUE, null = "null", na = "null", digits = NA))
""".strip()
    env = dict(os.environ)
    env["MRGRIP_REFERENCE_DATA"] = json.dumps(r_data)
    proc = subprocess.run(
        [os.environ.get("RSCRIPT_BIN") or "Rscript", "--vanilla", "-e", r_script],
        cwd=str(skill_dir),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2000:])
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("R reference produced no output")
    ref = json.loads(lines[-1])
    print(json.dumps({
        "/methods/0/beta.hat": ref["b"],
        "/methods/0/se": ref["se"],
        "/methods/0/pval": ref["pval"],
        "/methods/1/beta.hat": ref["b_adj"],
        "/methods/1/se": ref["se_adj"],
        "/methods/1/pval": ref["pval_adj"],
    }))

if __name__ == "__main__":
    main()
