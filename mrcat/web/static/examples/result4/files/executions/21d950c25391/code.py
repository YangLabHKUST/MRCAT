from mrcat.tools import gwas_download, resolve_ref

# Load the selected candidate produced by the previous gwas-select step.
selection = resolve_ref("$ref:gwas_select_9d52e7acce42/gwas_selection_result")
candidate = selection["selected_studies"]["outcome"]

# Download the selected FinnGen coronary artery disease outcome GWAS.
result = gwas_download(selected_study=candidate)

print("Summary:", result.get("summary"))
print("Status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") != "ok":
    print("Details:", result.get("details", {}))
else:
    print("Artifacts:", result.get("artifacts", []))
    data = result.get("outputs", {}).get("gwas_download_result", {})
    print("Downloaded study:", data)