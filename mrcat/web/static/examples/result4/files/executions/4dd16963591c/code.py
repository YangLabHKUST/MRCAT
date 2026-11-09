from mrcat.tools import gwas_qc

result = gwas_qc(
    downloaded_study="$ref:gwas_download_42a9e3243c1b/gwas_download_result/downloaded_study",
)

print(result.get("summary", {}))
print("outputs.status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") == "ok":
    data = result["outputs"].get("gwas_qc_result") or {}
    for key in ("label", "ancestry", "sample_size", "genome_build", "canonical_path", "formatted_path", "report_path", "explanation_path"):
        if key in data:
            print(f"{key}: {data[key]}")
    print("artifacts:", result.get("artifacts", []))
else:
    print("details:", result.get("details", {}))