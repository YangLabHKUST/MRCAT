import json
from pathlib import Path
from mrcat.tools import gwas_search

result = gwas_search(
    trait="hexadecanedioate levels",
    aliases=[
        "hexadecanedioate",
        "hexadecanedioic acid",
        "1,16-hexadecanedioic acid",
        "hexadecane-1,16-dioic acid",
    ],
)

print(result["summary"])
print("Output status:", result["outputs"]["status"])

if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_search_results"]
    shortlist = json.loads(Path(data["shortlists_path"]).read_text())
    candidates = shortlist.get("candidates", [])
    print("Target:", shortlist.get("target"))
    print("Candidate count:", len(candidates))

    fields = ("source", "study_id", "trait", "sample_size", "ancestry", "downloadable")
    print(json.dumps([{key: row.get(key) for key in fields} for row in candidates], ensure_ascii=False, indent=2))
    print("Shortlist path:", data["shortlists_path"])
    print("Artifacts:", result.get("artifacts", []))
else:
    print("Details:", json.dumps(result.get("details", {}), ensure_ascii=False, indent=2))