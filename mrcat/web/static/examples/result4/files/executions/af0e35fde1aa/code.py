from mrcat.tools import mr_primary

mrdat_path = "$ref:gwas_pair_prepare_01cdbd27d3ad/gwas_pair_prepare_result/mrdat_path"
min_instruments = 4
attempted_thresholds = [5e-7, 5e-6, 5e-5]  # authorized relaxation, not exceeding pair-prepare iv_threshold=5e-05

final_result = None
success = False

for pvalue_threshold in attempted_thresholds:
    print(f"\n=== mr_primary attempt: pvalue_threshold={pvalue_threshold:g} ===")
    result = mr_primary(
        mrdat_path=mrdat_path,
        input_scale="standardize",
        pvalue_threshold=pvalue_threshold,
        min_instruments=min_instruments,
    )
    final_result = result

    print("summary:", result.get("summary"))
    outputs = result.get("outputs", {})
    details = result.get("details", {})
    status = outputs.get("status")
    nsnp = outputs.get("nsnp", details.get("nsnp"))
    failure_class = outputs.get("failure_class", details.get("failure_class"))
    print("outputs.status:", status)
    print("nsnp:", nsnp)
    print("failure_class:", failure_class)

    if status == "ok":
        data = outputs.get("mr_primary_result", {})
        print("Success with pvalue_threshold:", pvalue_threshold)
        print("selected_snp_count:", data.get("selected_snp_count"))
        print("selected_mrdat_path:", data.get("selected_mrdat_path"))
        print("input_scale:", data.get("input_scale"))
        print("result_record_path:", data.get("result_record_path"))
        success = True
        break

    # Only relax further if the specific insufficiency persisted.
    if failure_class != "insufficient_instruments":
        print("Stopping: failure is not insufficient_instruments")
        break

if not success:
    print("\nAll attempted mr_primary thresholds failed or remained blocked.")
    print("Last observed details:", final_result.get("details", {}))