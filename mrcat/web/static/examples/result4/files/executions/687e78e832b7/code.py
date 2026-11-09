from mrcat.tools import gwas_qc, resolve_ref

# Complete downloaded-study object from the completed download step.
downloaded_study = resolve_ref(
    "$ref:gwas_download_8dd34ff1f05e/gwas_download_result/downloaded_study"
)

print("Downloaded study keys:", sorted(downloaded_study.keys()))
print("raw_path:", downloaded_study.get("raw_path"))
print("sample_size:", downloaded_study.get("sample_size"))

result = gwas_qc(
    downloaded_study=downloaded_study,
    label="Hexadecanedioate levels",
    sample_size=6887,
    ancestry="european",
)

print("\n--- gwas_qc summary ---")
print(result.get("summary"))
print("outputs status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") == "ok":
    qc = result.get("outputs", {}).get("gwas_qc_result")
    if qc:
        for key in [
            "canonical_path",
            "formatted_path",
            "label",
            "ancestry",
            "sample_size",
            "genome_build",
            "genome_build_reason",
            "report_path",
            "explanation_path",
        ]:
            print(f"{key}: {qc.get(key)}")
        print("risk_notes:", qc.get("risk_notes"))
        print("missing_requirements:", qc.get("missing_requirements"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("details:", result.get("details", {}))