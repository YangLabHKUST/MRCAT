from mrcat.tools import mr_primary

result = mr_primary(
    mrdat_path="$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/mrdat_path",
    input_scale="standardize",
    pvalue_threshold=5e-6,
    min_instruments=4,
)

print("summary:", result.get("summary"))
print("outputs.status:", result.get("outputs", {}).get("status"))

outputs = result.get("outputs", {})
if outputs.get("status") == "ok":
    data = outputs.get("mr_primary_result", {})
    print("result keys:", list(data.keys()))
    print("selected_mrdat_path:", data.get("selected_mrdat_path"))
    print("input_scale:", data.get("input_scale"))
    print("pvalue_threshold:", data.get("pvalue_threshold"))
    print("diagnostics:", data.get("diagnostics"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("failure details:", result.get("details", {}))