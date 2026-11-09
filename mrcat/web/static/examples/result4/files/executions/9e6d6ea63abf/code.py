from mrcat.tools import analysis_method_comparison

method_result_paths = [
    "/recorded-session/workspace/outputs/cc5ac7326e22/mr_primary_tizeuu7q/reports/mr_primary_result_record.json",
    "/recorded-session/workspace/outputs/f2ed685faa65/mr_apss_sqnnzrer/reports/mrapss_result_record.json",
    "/recorded-session/workspace/outputs/a4b4ddfdf6f8/mr_bwmr_82v_7hvf/reports/mr_bwmr_result_record.json",
]

result = analysis_method_comparison(
    method_result_paths=method_result_paths,
    exposure_label="Hexadecanedioate levels",
    outcome_label="Coronary artery disease",
)

print("Summary:", result.get("summary"))
print("Status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") == "ok":
    comparison = result["outputs"]["method_comparison_result"]
    print("comparison_table_path:", comparison.get("comparison_table_path"))
    print("result_record_path:", comparison.get("result_record_path"))
    print("plot_manifest:", comparison.get("plot_manifest"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("Details:", result.get("details", {}))