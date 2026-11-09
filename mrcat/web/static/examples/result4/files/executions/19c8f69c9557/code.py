from mrcat.tools import analysis_replication

exposure_study = {
    "source": "gwas_catalog",
    "study_id": "GCST90243839",
    "trait": "Hexadecanedioate levels",
    "ancestry": "european",
    "ancestry_raw": "6887 European",
    "sample_size": 6887,
    "study_metadata": {
        "initial_sample_size": "6,887 European ancestry individuals",
        "population": "6887 European",
        "sample_size": 6887,
        "initialSampleSize": "6,887 European ancestry individuals",
        "replicationSampleSize": "NA",
        "pmid": "24816252",
        "publication_title": "An atlas of genetic influences on human blood metabolites.",
        "publication_date": "2014-05-11",
        "publication_year": 2014,
    },
}

original_outcome_study = {
    "source": "gwas_catalog",
    "study_id": "GCST90132314",
    "trait": "Coronary artery disease",
    "ancestry": "european",
    "ancestry_raw": "1165690 European, NR",
    "sample_size": 1165690,
    "study_metadata": {
        "initial_sample_size": "181,522 European ancestry, unknown cases; 984,168 European ancestry, unknown controls",
        "population": "1165690 European, NR",
        "sample_size": 1165690,
        "initialSampleSize": "181,522 European ancestry, unknown cases; 984,168 European ancestry, unknown controls",
        "replicationSampleSize": "NA",
        "pmid": "36474045",
        "publication_title": "Discovery and systematic characterization of risk variants and genes for coronary artery disease in over a million participants.",
        "publication_date": "2022-12-06",
        "publication_year": 2022,
    },
}

finngen_outcome_study = {
    "source": "finngen",
    "study_id": "finngen_R12_I9_CHD",
    "trait": "Major coronary heart disease event",
    "ancestry": "finnish",
    "ancestry_raw": "Finnish",
    "sample_size": 500348,
    "n_cases": 56650,
    "n_controls": 443698,
    "study_metadata": {
        "num_cases": "56650",
        "num_controls": "443698",
        "phenocode": "I9_CHD",
        "release": "R12",
        "endpoint": "I9_CHD",
        "endpoint_code": "I9_CHD",
        "population": "Finnish",
    },
}

result = analysis_replication(
    exposure="Hexadecanedioate levels",
    outcome="Coronary artery disease",
    analyses=[
        {
            "name": "Original GWAS Catalog outcome",
            "exposure_study": exposure_study,
            "outcome_study": original_outcome_study,
            "result_paths": [
                "/recorded-session/workspace/outputs/cc5ac7326e22/mr_primary_tizeuu7q/reports/mr_primary_result_record.json",
                "/recorded-session/workspace/outputs/f2ed685faa65/mr_apss_sqnnzrer/reports/mrapss_result_record.json",
                "/recorded-session/workspace/outputs/a4b4ddfdf6f8/mr_bwmr_82v_7hvf/reports/mr_bwmr_result_record.json",
            ],
        },
        {
            "name": "FinnGen outcome",
            "exposure_study": exposure_study,
            "outcome_study": finngen_outcome_study,
            "result_paths": [
                "/recorded-session/workspace/outputs/32e9f140fc83/mr_primary_m8lrhgrn/reports/mr_primary_result_record.json",
                "/recorded-session/workspace/outputs/f557bbed1fec/mr_apss_x2od2x4m/reports/mrapss_result_record.json",
                "/recorded-session/workspace/outputs/09f910c44d94/mr_bwmr_q1dkdu92/reports/mr_bwmr_result_record.json",
            ],
        },
    ],
    title="Replication of hexadecanedioate-to-CAD estimates: original GWAS Catalog vs FinnGen outcome",
)

print(result.get("summary"))
print("outputs.status:", result.get("outputs", {}).get("status"))
if result.get("outputs", {}).get("status") == "ok":
    data = result["outputs"].get("mr_replication_result", {})
    print("mr_replication_result keys:", list(data.keys()))
    print("artifacts:", result.get("artifacts", []))
else:
    print("details:", result.get("details", {}))