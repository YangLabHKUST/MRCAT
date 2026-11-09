from mrcat.tools import analysis_sensitivity, resolve_ref

# Resolve the inner mr-primary result record, not the outer response.
primary_result_record_path = resolve_ref(
    "$ref:mr_primary_dbeab5591bb7/mr_primary_result/result_record_path"
)
print("Using primary result record:", primary_result_record_path)

# Steiger metadata is omitted because the CAD outcome is binary and no verified
# population prevalence (nor verified eaf/ncase/ncontrol columns in the selected
# SNP table) was supplied. The tool runs the other diagnostics and reports
# Steiger as unavailable rather than fabricating metadata.
result = analysis_sensitivity(
    primary_result_record_path=primary_result_record_path,
)

print("\nSummary:")
print(result["summary"])

if result["outputs"]["status"] == "ok":
    data = result["outputs"]["mr_sensitivity_result"]
    print("\nSensitivity output keys:", list(data.keys()))
    print("Steiger status:", data.get("steiger", {}).get("status"))
    print("Result record path:", data.get("result_record_path"))
    print("Artifacts:")
    for artifact in result.get("artifacts", []):
        print(" -", artifact)
else:
    print("\nTool did not return ok.")
    print("Details:", result.get("details", {}))