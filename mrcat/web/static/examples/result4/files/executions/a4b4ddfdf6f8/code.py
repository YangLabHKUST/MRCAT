from mrcat.tools import mr_bwmr

# Verified mrdat_path returned by the completed gwas-pair-prepare step.
mrdat_path = "/recorded-session/workspace/outputs/274ede89701c/gwas_pair_prepare_lhj8b0pf/intermediate/gwas_pair_mrdat_clumped.tsv.gz"

# Use the same explicit threshold as the completed primary MR (5e-6), which retained >=4 instruments
# and is below the upstream pair-prepare iv_threshold of 5e-05.
result = mr_bwmr(
    mrdat_path=mrdat_path,
    input_scale="standardize",
    pvalue_threshold=5e-6,
    min_instruments=4,
)

print(result.get("summary", {}))
if result.get("outputs", {}).get("status") == "ok":
    data = result["outputs"].get("mr_bwmr_result", {})
    print("mr_bwmr status: ok")
    print("effective threshold:", data.get("diagnostics", {}).get("pvalue_threshold"))
    print("selected SNP count:", data.get("diagnostics", {}).get("nsnp"))
    print("methods:", [m.get("method") for m in data.get("methods", [])])
    print("result_record_path:", data.get("result_record_path"))
else:
    print("mr_bwmr status:", result.get("outputs", {}).get("status"))
    print("details:", result.get("details", {}))