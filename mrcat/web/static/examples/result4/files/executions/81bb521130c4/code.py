from mrcat.tools import analysis_sensitivity

primary_result_record_path = (
    "/local/jyxProject/MRCAT-langgraph/runtime_benchmark/"
    "mrcat_0902_20261027T231940_211c8b_negative_control_view/"
    "session_4cc4857090a941e3/workspace/outputs/32e9f140fc83/"
    "mr_primary_m8lrhgrn/reports/mr_primary_result_record.json"
)

result = analysis_sensitivity(
    primary_result_record_path=primary_result_record_path,
)

print(result["summary"])
print("tool status:", result.get("outputs", {}).get("status"))

if result.get("outputs", {}).get("status") == "ok":
    sens = result["outputs"].get("mr_sensitivity_result", {})
    print("mr_sensitivity_result keys:", list(sens.keys()))
    print("result_record_path:", sens.get("result_record_path"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("failure details:", result.get("details", {}))