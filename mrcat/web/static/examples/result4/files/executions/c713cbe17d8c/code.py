from mrcat.tools import gwas_select

shortlists_path = "/recorded-session/workspace/outputs/41dfedfba76e/gwas_search_1azkfd0w/gwas_search_shortlists.json"

result = gwas_select(
    shortlists={"outcome": shortlists_path},
)

print(result["summary"])
if result["outputs"]["status"] != "ok":
    print(result.get("details", {}))