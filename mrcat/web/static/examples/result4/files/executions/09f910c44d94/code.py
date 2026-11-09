from mrcat.tools import mr_bwmr

mrdat_path = "/recorded-session/workspace/outputs/a78b9cb9eed8/gwas_pair_prepare_2qwobvze/intermediate/gwas_pair_mrdat_clumped.tsv.gz"

# Use the same instrument threshold as the completed task2 primary fit (5e-06),
# which is below the upstream pair-preparation IV threshold and retained 10 instruments.
result = mr_bwmr(
    mrdat_path=mrdat_path,
    input_scale="standardize",
    pvalue_threshold=5e-06,
    min_instruments=4,
)

print(result["summary"])
status = result["outputs"]["status"]
print("status:", status)

if status == "ok":
    data = result["outputs"]["mr_bwmr_result"]
    print("mr_bwmr_result keys:", list(data.keys()))
    print("result_record_path:", data.get("result_record_path"))
    for method in data.get("methods", []):
        print(
            method.get("method"),
            "pvalue_threshold=", data.get("diagnostics", {}).get("pvalue_threshold"),
            "nsnp=", method.get("nsnp"),
            "beta.hat=", method.get("beta.hat"),
            "se=", method.get("se"),
            "pval=", method.get("pval"),
        )
    print("artifacts:", result.get("artifacts", []))
else:
    print(result.get("details", {}))