from mrcat.tools import gwas_qc, resolve_ref

downloaded_study_ref = "$ref:gwas_download_8946701d8f85/gwas_download_result/downloaded_study"
downloaded_study = resolve_ref(downloaded_study_ref)

result = gwas_qc(
    downloaded_study=downloaded_study,
    label="Major coronary heart disease event",
    sample_size=500348,
    source="finngen",
    ancestry="finnish",
)

print(result.get("summary"))
outputs = result.get("outputs", {})
print("status:", outputs.get("status"))

if outputs.get("status") == "ok":
    qc = outputs.get("gwas_qc_result", {})
    print("gwas_qc_result keys:", sorted(qc.keys()))
    for key in [
        "canonical_path",
        "formatted_path",
        "report_path",
        "explanation_path",
        "genome_build",
        "genome_build_reason",
        "label",
        "ancestry",
        "sample_size",
    ]:
        if key in qc:
            print(f"{key}: {qc[key]}")
    print("risk_notes:", qc.get("risk_notes"))
    print("missing_requirements:", qc.get("missing_requirements"))
else:
    print("details:", result.get("details", {}))
    print("artifacts:", result.get("artifacts", []))