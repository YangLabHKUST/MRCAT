from mrcat.tools import analysis_method_comparison

method_result_paths = [
    "/recorded-session/workspace/outputs/32e9f140fc83/mr_primary_m8lrhgrn/reports/mr_primary_result_record.json",
    "/recorded-session/workspace/outputs/f557bbed1fec/mr_apss_x2od2x4m/reports/mrapss_result_record.json",
    "/recorded-session/workspace/outputs/09f910c44d94/mr_bwmr_q1dkdu92/reports/mr_bwmr_result_record.json",
]

result = analysis_method_comparison(
    method_result_paths=method_result_paths,
    exposure_label="Hexadecanedioate levels",
    outcome_label="Major coronary heart disease event",
)

print(result["summary"])
outputs = result.get("outputs", {})
print("status:", outputs.get("status"))

if outputs.get("status") == "ok":
    data = outputs.get("method_comparison_result", {})
    if isinstance(data, dict):
        for key in ["comparison_table_path", "result_record_path", "plot_manifest"]:
            if key in data:
                print(key, ":", data[key])
    print("artifacts:", result.get("artifacts", []))
else:
    print("details:", result.get("details", {}))