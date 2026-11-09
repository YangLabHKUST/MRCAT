import json
from pathlib import Path
from mrcat.tools import gwas_search

result = gwas_search(
    trait="coronary artery disease",
    source="finngen",
    aliases=["CAD"],
)

print(result["summary"])

outputs = result.get("outputs", {})
if outputs.get("status") == "ok":
    data = outputs.get("gwas_search_results", {})
    shortlists_path = data.get("shortlists_path")
    print("Shortlist path:", shortlists_path)

    if shortlists_path:
        shortlist = json.loads(Path(shortlists_path).read_text())
        candidates = shortlist.get("candidates", [])
        print("Candidate count:", len(candidates))

        fields = ("source", "study_id", "trait", "sample_size", "ancestry", "downloadable")
        preview = [
            {key: row.get(key) for key in fields}
            for row in candidates[:20]
        ]
        print(json.dumps(preview, ensure_ascii=False, indent=2))

        diagnostics = shortlist.get("diagnostics", {})
        print("Diagnostics:", json.dumps(diagnostics, ensure_ascii=False, indent=2))
else:
    print("Search failed or returned no usable outputs.")
    print("Details:", result.get("details", {}))