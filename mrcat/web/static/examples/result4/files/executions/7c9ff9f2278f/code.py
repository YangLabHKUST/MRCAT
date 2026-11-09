import json
from pathlib import Path
from mrcat.tools import gwas_search

# Search remote GWAS candidates for the outcome phenotype.
result = gwas_search(
    trait="coronary artery disease",
    aliases=["coronary heart disease", "CAD"],
)

print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_search_results"]
    shortlist = json.loads(Path(data["shortlists_path"]).read_text())
    candidates = shortlist.get("candidates", [])
    print("Candidate count:", len(candidates))
    fields = ("source", "study_id", "trait", "sample_size", "ancestry", "downloadable")
    print(json.dumps([{key: row.get(key) for key in fields} for row in candidates[:20]], ensure_ascii=False))
    print("Shortlist:", data["shortlists_path"])
    print("XLSX:", data.get("shortlists_xlsx_path"))
    print("Artifacts:", result.get("artifacts", []))
else:
    print("Status:", result["outputs"]["status"])
    print("Details:", result.get("details", {}))