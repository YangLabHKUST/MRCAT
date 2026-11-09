from mrcat.tools import gwas_download, resolve_ref

# Load the completed selection result and extract the already selected CAD outcome study.
selection = resolve_ref("$ref:gwas_select_fe033a297d35/gwas_selection_result")
selected_outcome = selection["selected_studies"]["outcome"]

# Retry gwas-download for the selected CAD outcome. The tool can resume the
# partial 63% transfer already present in its cache.
result = gwas_download(selected_study=selected_outcome)

print("Summary:", result.get("summary"))
print("Output status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") != "ok":
    print("Details:", result.get("details", {}))
else:
    data = result["outputs"].get("gwas_download_result", {})
    downloaded = data.get("downloaded_study", {})
    print("Downloaded study:", downloaded.get("study_id"), downloaded.get("trait"))
    print("Raw path:", downloaded.get("raw_path"))
    print("Artifacts:", result.get("artifacts", []))