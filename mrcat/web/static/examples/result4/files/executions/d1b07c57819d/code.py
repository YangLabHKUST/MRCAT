from mrcat.tools import gwas_select

shortlists = {
    "exposure": "/recorded-session/workspace/outputs/35e7b060eec7/gwas_search_j5v9g102/gwas_search_shortlists.json",
    "outcome": "/recorded-session/workspace/outputs/7c9ff9f2278f/gwas_search_2hrft58h/gwas_search_shortlists.json",
}

result = gwas_select(shortlists=shortlists)

print("summary:", result.get("summary", "No summary returned"))
outputs = result.get("outputs", {})
print("status:", outputs.get("status"))

if outputs.get("status") != "ok":
    print("failure_class:", outputs.get("failure_class"))
    print("details:", result.get("details", {}))
else:
    selection = outputs.get("gwas_selection_result", {})
    selected = selection.get("selected_studies", {})
    print("selected_target_keys:", list(selected.keys()))
    print("selection_reason:", selection.get("selection_reason"))