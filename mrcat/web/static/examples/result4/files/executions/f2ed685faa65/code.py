from mrcat.tools import mr_apss

result = mr_apss(
    mrdat_path="$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/mrdat_path",
    c_path="$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/c_path",
    omega_path="$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/omega_path",
    exposure_label="Hexadecanedioate levels",
    outcome_label="Coronary artery disease",
    input_scale="standardize",
)

print("output_status:", result.get("outputs", {}).get("status"))
print("summary:")
print(result.get("summary"))

if result.get("outputs", {}).get("status") == "ok":
    payload = result["outputs"].get("mrapss_result", {})
    print("result_record_path:", payload.get("result_record_path"))
    print("diagnostics:", payload.get("diagnostics"))
    print("methods:", payload.get("methods"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("details:", result.get("details", {}))