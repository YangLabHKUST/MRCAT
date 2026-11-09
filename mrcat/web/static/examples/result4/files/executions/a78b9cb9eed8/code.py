from mrcat.tools import gwas_pair_prepare, resolve_ref

exposure_qc = resolve_ref("$taskref:task1/gwas_qc_6ed9a907dab5/gwas_qc_result")
outcome_qc = resolve_ref("$ref:gwas_qc_0dc4246501be/gwas_qc_result")

result = gwas_pair_prepare(
    formatted_exposure_path=exposure_qc["formatted_path"],
    formatted_outcome_path=outcome_qc["formatted_path"],
    exposure_label=exposure_qc.get("label", "Hexadecanedioate levels"),
    outcome_label=outcome_qc.get("label", "Major coronary heart disease event"),
    pop="EUR",
)

print(result["summary"])
if result["outputs"]["status"] == "ok":
    data = result["outputs"]["gwas_pair_prepare_result"]
    print("pair_prepare_result keys:", list(data.keys()))
    for key in ("mrdat_path", "c_path", "omega_path", "ancestry", "exposure_label", "outcome_label"):
        if key in data:
            print(f"{key}: {data[key]}")
    print("artifacts:", result.get("artifacts", []))
else:
    print("FAILURE DETAILS:", result.get("details", {}))