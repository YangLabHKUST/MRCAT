"""Named research functions for CodeAct and Python users.

These are ordinary callable tools, not an agent dispatcher. The caller chooses
what to run, how to compose calls, and how to interpret the returned evidence.
"""
from contextlib import contextmanager
from importlib import import_module
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from mrcat.state.results import publish_result, resolve_ref, resolve_inputs, register_tool_result

_ENV_LOCK = RLock()


def _load(skill, module):
    return import_module(f"skills.{skill}.scripts.{module}")


@contextmanager
def _output_directory(name, output_dir):
    # Legacy numerical backends read an environment variable. Scope it to this
    # call and serialize threaded callers; CodeAct cells are separate processes.
    with _ENV_LOCK:
        previous = os.environ.get("MRCAT_EXECUTION_DIR")
        if output_dir is None:
            base = Path(previous) if previous else Path.cwd() / "outputs"
            base.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix=name + "_", dir=base)).resolve()
        else:
            directory = Path(output_dir).expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
        os.environ["MRCAT_EXECUTION_DIR"] = str(directory)
        try:
            yield directory
        finally:
            if previous is None:
                os.environ.pop("MRCAT_EXECUTION_DIR", None)
            else:
                os.environ["MRCAT_EXECUTION_DIR"] = previous


def session_history(*, start: int = 0, limit: int = 50, task_id: str | None = None) -> dict:
    """Read a page of committed conversation from the current session checkpoint."""
    from mrcat.state.store import Store
    if not isinstance(start, int) or start < 0 or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("History requires start >= 0 and 1 <= limit <= 100.")
    configured = os.environ.get("MRCAT_SESSION_DIR")
    if not configured:
        raise ValueError("No current session. Run this tool inside the agent workspace.")
    directory = Path(configured).resolve()
    messages = Store(directory.parent).load(directory.name)["messages"]
    rows = [dict(index=index, **row) for index, row in enumerate(messages)
            if index >= start and (not task_id or row.get("task_id") in (None, task_id))]
    page = rows[:limit]
    return dict(messages=page, next_start=page[-1]["index"] + 1 if page else len(messages),
                has_more=len(rows) > limit)


def _invoke(function, arguments, name):
    arguments = resolve_inputs(dict(arguments))
    output_dir = arguments.pop("output_dir")
    payload = {key.rstrip("_"): value for key, value in arguments.items() if value is not None}
    # Paths are accepted throughout nested study/result objects as well.
    payload = json.loads(json.dumps(payload, default=lambda value: os.fspath(value)))
    with _output_directory(name, output_dir) as directory:
        result = function(payload)
        (directory / "response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        register_tool_result(name, result, payload, directory / "response.json")
        return result


def analysis_bidirectional(
    *,
    pair_results: list,
    title: str | None = None,
    alpha: float = 0.05,
    p_adjust_method: str = 'bh',
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-bidirectional/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-bidirectional', 'run_bidirectional').run, locals(), 'analysis_bidirectional')


def analysis_mediation(
    *,
    total_effect_results: list,
    indirect_paths: list,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-mediation/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-mediation', 'run_mr_mediation').run, locals(), 'analysis_mediation')


def analysis_method_comparison(
    *,
    method_result_paths: list,
    exposure_label: str | None = None,
    outcome_label: str | None = None,
    max_snp_points: int = 5000,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-method-comparison/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-method-comparison', 'run_method_comparison').run, locals(), 'analysis_method_comparison')


def analysis_replication(
    *,
    exposure: str,
    outcome: str,
    analyses: list,
    title: str | None = None,
    alpha: float = 0.05,
    p_adjust_method: str = 'bh',
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-replication/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-replication', 'run_replication').run, locals(), 'analysis_replication')


def analysis_result_synthesis(
    *,
    pair_results: list,
    title: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-result-synthesis/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-result-synthesis', 'run_mr_result_synthesis').run, locals(), 'analysis_result_synthesis')


def analysis_risk_factor_prioritization(
    *,
    outcome: str,
    exposure_results: list,
    primary_method: str | None = None,
    title: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-risk-factor-prioritization/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-risk-factor-prioritization', 'run_mr_risk_factor_prioritization').run, locals(), 'analysis_risk_factor_prioritization')


def analysis_sensitivity(
    *,
    primary_result_record_path: str | Path,
    nb_distribution: int = 1000,
    signif_threshold: float = 0.05,
    seed: int = 1234,
    detailed_plot_max_instruments: int = 100,
    steiger_metadata: dict | None = None,
    steiger_filter: bool = False,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/analysis-sensitivity/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('analysis-sensitivity', 'run_mr_sensitivity').run, locals(), 'analysis_sensitivity')


def gwas_download(
    *,
    selected_study: dict | None = None,
    download_url: str | None = None,
    label: str | None = None,
    sample_size: int | None = None,
    ancestry: str | None = None,
    study_metadata: dict | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/gwas-download/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('gwas-download', 'run_download').run, locals(), 'gwas_download')


def gwas_pair_prepare(
    *,
    formatted_exposure_path: str | Path,
    formatted_outcome_path: str | Path,
    exposure_label: str | None = None,
    outcome_label: str | None = None,
    ancestry: str | None = None,
    M: float | None = None,
    h2_fix_intercept: bool = False,
    iv_threshold: float = 5e-05,
    clump_r2: float = 0.001,
    clump_kb: int = 10000,
    clump_p: float = 0.999,
    bfile: str | None = None,
    plink_bin: str | Path | None = None,
    pop: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/gwas-pair-prepare/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('gwas-pair-prepare', 'run_gwas_pair_prepare').run, locals(), 'gwas_pair_prepare')


def gwas_qc(
    *,
    downloaded_study: dict | None = None,
    raw_path: str | Path | None = None,
    label: str | None = None,
    sample_size: int | None = None,
    source: str | None = None,
    study_metadata: dict | None = None,
    mapping_notes: str | None = None,
    ancestry: str | None = None,
    max_attempts: int = 3,
    sample_rows: int = 50,
    sample_timeout_seconds: int = 120,
    full_timeout_seconds: int = 7200,
    min_freq: float = 0.05,
    output_dir: str | Path | None = None
) -> dict:
    """Canonicalize and QC a study; see skills/gwas-qc/SKILL.md.

    mapping_notes is reserved for explicit user-provided file explanations.
    Omit it when absent; never supply agent-inferred column mappings.
    """
    return _invoke(_load('gwas-qc', 'run_gwas_qc').run, locals(), 'gwas_qc')


def gwas_search(
    *,
    trait: str | None = None,
    study_id: str | None = None,
    source: str | None = None,
    ancestry: str | None = None,
    limit_per_source: int = 20,
    aliases: list[str] | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/gwas-search/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('gwas-search', 'run_search').run, locals(), 'gwas_search')


def gwas_select(
    *,
    shortlists: dict,
    ancestry: str | None = None,
    request: str | None = None,
    current_plan_item: str | None = None,
    memory_md: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """Select a complete study set internally; see skills/gwas-select/SKILL.md."""
    return _invoke(_load('gwas-select', 'run_select').run_select, locals(), 'gwas_select')


def mr_apss(
    *,
    mrdat_path: str | Path,
    c_path: str | Path,
    omega_path: str | Path,
    exposure_label: str | None = None,
    outcome_label: str | None = None,
    input_scale: str = 'standardize',
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-apss/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-apss', 'run_mrapss').run, locals(), 'mr_apss')


def mr_bwmr(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-bwmr/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-bwmr', 'run_mr_bwmr').run, locals(), 'mr_bwmr')


def mr_cause(
    *,
    canonical_exposure_path: str | Path,
    canonical_outcome_path: str | Path,
    exposure_label: str | None = None,
    outcome_label: str | None = None,
    ancestry: str | None = None,
    input_scale: str = 'standardize',
    exposure_sample_size: float | None = None,
    outcome_sample_size: float | None = None,
    pval_thresh: float = 0.001,
    r2_thresh: float = 0.01,
    clump_kb: int = 10000,
    param_variant_sample_size: int = 1000000,
    seed: int = 1,
    bfile: str | Path | None = None,
    plink_bin: str | Path | None = None,
    pop: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-cause/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-cause', 'run_cause').run, locals(), 'mr_cause')


def mr_cml_ma(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    random_seed: int = 1,
    random_start: int = 10,
    n_override: float | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-cml-ma/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-cml-ma', 'run_mr_cml_ma').run, locals(), 'mr_cml_ma')


def mr_conmix(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    ci_min: float | None = None,
    ci_max: float | None = None,
    ci_step: float | None = None,
    alpha: float = 0.05,
    psi: float = 0,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-conmix/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-conmix', 'run_mr_conmix').run, locals(), 'mr_conmix')


def mr_divw(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    lambda_: float | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-divw/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-divw', 'run_mr_divw').run, locals(), 'mr_divw')


def mr_grip(
    *,
    mrdat_path: str | Path,
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-grip/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-grip', 'run_mr_grip').run, locals(), 'mr_grip')


def mr_lasso(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    distribution: str = 'normal',
    alpha: float = 0.05,
    lambda_: list | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-lasso/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-lasso', 'run_mr_lasso').run, locals(), 'mr_lasso')


def mr_mrmix(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    exposure_type: str | None = None,
    outcome_type: str | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-mrmix/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-mrmix', 'run_mr_mrmix').run, locals(), 'mr_mrmix')


def mr_presso(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    nb_distribution: int = 1000,
    signif_threshold: float = 0.05,
    seed: int = 1234,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-presso/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-presso', 'run_mr_presso').run, locals(), 'mr_presso')


def mr_primary(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-primary/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-primary', 'run_mr_primary').run, locals(), 'mr_primary')


def mr_primary_id(
    *,
    exposure_gwas_id: str,
    outcome_gwas_id: str,
    exposure_label: str | None = None,
    outcome_label: str | None = None,
    input_scale: str = 'standardize',
    exposure_sample_size: float | None = None,
    outcome_sample_size: float | None = None,
    pvalue_threshold: float | list[float] = 5e-8,
    clump_r2: float = 0.001,
    clump_kb: int = 10000,
    min_instruments: int = 4,
    harmonise_action: int = 2,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-primary-id/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-primary-id', 'run_mr_primary_id').run, locals(), 'mr_primary_id')


def mr_raps(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    diagnostics: bool = True,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-raps/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-raps', 'run_mr_raps').run, locals(), 'mr_raps')


def mr_robust(
    *,
    mrdat_path: str | Path,
    input_scale: str = 'standardize',
    pvalue_threshold: float = 5e-08,
    min_instruments: int = 4,
    k_max: int = 500,
    output_dir: str | Path | None = None
) -> dict:
    """See skills/mr-robust/SKILL.md for inputs, outputs and scientific assumptions."""
    return _invoke(_load('mr-robust', 'run_mr_robust').run, locals(), 'mr_robust')


# Search capabilities are ordinary tools, not MR planning skills or agent loops.
def web_search(*, query: str, context: str = '', provider: str | None = None,
               fallback: bool = True, output_dir: str | Path | None = None) -> dict:
    """Hosted evidence search with stable citations and archived provider attempts."""
    from .search.web import run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'web_search')


def web_open(*, url: str, operation: str = 'text', max_bytes: int = 1_000_000,
             start: int = 0, end: int = 65535, output_dir: str | Path | None = None) -> dict:
    """Read public HTTPS text/JSON, HEAD metadata or a bounded byte range."""
    from .search.inspection import web_open as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'web_open')


def http_inspect(*, url: str, source: str | None = None, ancestry: str | None = None,
                 operation: str = 'text', max_bytes: int = 1_000_000,
                 start: int = 0, end: int = 65535, output_dir: str | Path | None = None) -> dict:
    """Inspect official GWAS endpoints within the requested source/ancestry route."""
    from .search.inspection import http_inspect as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'http_inspect')


def gwas_probe(*, candidates: list, source: str | None = None, ancestry: str | None = None,
               study_id: str | None = None, limit: int = 20, output_dir: str | Path | None = None) -> dict:
    """Probe complete existing-source candidate objects without repeating discovery."""
    from .search.inspection import gwas_probe as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'gwas_probe')


def web_probe(*, candidate: dict, output_dir: str | Path | None = None) -> dict:
    """Probe an external GWAS file with source provenance; does not validate its contents."""
    from .search.inspection import web_probe as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'web_probe')


def research_brief(*, request: str, evidence: list, context: str = '',
                   output_dir: str | Path | None = None) -> dict:
    """Build a source-grounded brief and candidate MR queries from saved evidence."""
    from .search.documents import research_brief as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'research_brief')


def scan_design(*, request: str, evidence: list, context: str = '',
                output_dir: str | Path | None = None) -> dict:
    """Build a proposed exposure/outcome scan design, retaining evidence and constraints."""
    from .search.documents import scan_design as run
    return _invoke(run, {k: v for k, v in locals().items() if k != 'run'}, 'scan_design')
