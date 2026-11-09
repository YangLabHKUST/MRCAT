from pathlib import Path

from mrcat.tools import gwas_pair_prepare

# Verified formatted outputs from the completed QC steps.
formatted_exposure_path = (
    "/local/jyxProject/MRCAT-langgraph/runtime_benchmark/"
    "mrcat_0902_20261027T231940_211c8b_negative_control_view/"
    "session_4cc4857090a941e3/workspace/outputs/687e78e832b7/"
    "gwas_qc_pzivenh9/formatted/study.mrapss.tsv.gz"
)
formatted_outcome_path = (
    "/local/jyxProject/MRCAT-langgraph/runtime_benchmark/"
    "mrcat_0902_20261027T231940_211c8b_negative_control_view/"
    "session_4cc4857090a941e3/workspace/outputs/4dd16963591c/"
    "gwas_qc_ggfcx930/formatted/study.mrapss.tsv.gz"
)

result = gwas_pair_prepare(
    formatted_exposure_path=formatted_exposure_path,
    formatted_outcome_path=formatted_outcome_path,
    exposure_label="Hexadecanedioate levels",
    outcome_label="Coronary artery disease",
    ancestry="european",
    pop="EUR",
)

print(result.get("summary"))
status = result.get("outputs", {}).get("status")
if status == "ok":
    data = result.get("outputs", {}).get("gwas_pair_prepare_result", {})
    if isinstance(data, dict):
        print("gwas_pair_prepare_result keys:", list(data.keys()))
    else:
        print("gwas_pair_prepare_result type:", type(data))
else:
    print("FAILED status:", status)
    print("details:", result.get("details", {}))