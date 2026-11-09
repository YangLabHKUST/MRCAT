from mrcat.tools import mr_primary

result = mr_primary(
    mrdat_path="$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/mrdat_path",
    input_scale="standardize",
)

print(result["summary"])
print("outputs.status:", result["outputs"]["status"])

if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_primary_result"]
    print("result keys:", list(data.keys()))
    print("selected_mrdat_path:", data.get("selected_mrdat_path"))
    print("input_scale:", data.get("input_scale"))
    print("threshold:", data.get("pvalue_threshold"))
    print("selected SNP count:", data.get("selected_snp_count"))
    print("warnings:", data.get("warnings"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("failure details:", result.get("details", {}))