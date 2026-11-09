from mrcat.tools import mr_apss

result = mr_apss(
    mrdat_path="/recorded-session/workspace/outputs/a78b9cb9eed8/gwas_pair_prepare_2qwobvze/intermediate/gwas_pair_mrdat_clumped.tsv.gz",
    c_path="/recorded-session/workspace/outputs/a78b9cb9eed8/gwas_pair_prepare_2qwobvze/intermediate/gwas_pair_C.tsv",
    omega_path="/recorded-session/workspace/outputs/a78b9cb9eed8/gwas_pair_prepare_2qwobvze/intermediate/gwas_pair_Omega.tsv",
    exposure_label="Hexadecanedioate levels",
    outcome_label="Major coronary heart disease event",
    input_scale="standardize",
)

print(result.get("summary"))

outputs = result.get("outputs", {})
if outputs.get("status") == "ok":
    data = outputs.get("mrapss_result", {})
    print("status=ok")
    print("result_record_path:", data.get("result_record_path"))
    print("methods:")
    for method in data.get("methods", []):
        print(method)
    print("diagnostics:", data.get("diagnostics"))
    print("artifacts:", result.get("artifacts", []))
else:
    print("status:", outputs.get("status"))
    print("failure details:", result.get("details", {}))