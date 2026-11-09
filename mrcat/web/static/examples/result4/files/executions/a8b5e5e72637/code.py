from mrcat.tools import mr_primary

mrdat_path = "/recorded-session/workspace/outputs/a78b9cb9eed8/gwas_pair_prepare_2qwobvze/intermediate/gwas_pair_mrdat_clumped.tsv.gz"

result = mr_primary(
    mrdat_path=mrdat_path,
    pvalue_threshold=5e-07,
    min_instruments=4,
)

print(result.get("summary"))
outputs = result.get("outputs", {})
print("status:", outputs.get("status"))

if outputs.get("status") == "ok":
    data = outputs.get("mr_primary_result", {})
    print("selected_mrdat_path:", data.get("selected_mrdat_path"))
    print("input_scale:", data.get("input_scale"))
    print("pvalue_threshold:", data.get("pvalue_threshold") or data.get("effective_threshold"))
    print("selected_snp_count:", data.get("selected_snp_count"))
    print("plot_manifest:", data.get("plot_manifest"))
    print("result_record_path:", data.get("result_record_path"))
else:
    print("details:", result.get("details", {}))
    print("artifacts:", result.get("artifacts", []))