from mrcat.tools import gwas_download, resolve_ref

# Load the completed selection result and take only the exposure study.
selection = resolve_ref("$ref:gwas_select_fe033a297d35/gwas_selection_result")
selected_study = selection["selected_studies"]["exposure"]

print("Downloading selected exposure study:")
print({
    "study_id": selected_study.get("study_id"),
    "trait": selected_study.get("trait"),
    "source": selected_study.get("source"),
    "ancestry": selected_study.get("ancestry"),
    "sample_size": selected_study.get("sample_size"),
    "download_descriptor_url": selected_study.get("download_descriptor", {}).get("url"),
})

result = gwas_download(selected_study=selected_study)

print("\nTool summary:")
print(result.get("summary"))

if result.get("outputs", {}).get("status") == "ok":
    downloaded = result["outputs"]["gwas_download_result"]
    study = downloaded.get("downloaded_study", {})
    print("\nDownload status: ok")
    print({
        "raw_path": study.get("raw_path"),
        "file_size": study.get("file_size"),
        "study_id": study.get("study_id"),
        "source": study.get("source"),
        "ancestry": study.get("ancestry"),
        "sample_size": study.get("sample_size"),
    })
    print("\nArtifacts:")
    for artifact in result.get("artifacts", []):
        print(artifact)
else:
    print("\nDownload status: not ok")
    print(result.get("details", {}))