"""Source identity and partial-service regressions using anonymous fixtures."""
import importlib
from types import SimpleNamespace

import pytest
from requests import ReadTimeout

selector = importlib.import_module('skills.gwas-select.scripts.llm_selector')
catalog = importlib.import_module('skills.gwas-search.scripts.search_gwas_catalog')
side = importlib.import_module('skills.gwas-search.scripts.search_side')


def candidate(study_id='xxx_file', phenocode='xxx_field'):
    return dict(source='pan_ukb', study_id=study_id, downloadable=True,
                download_url='https://example.org/xxx', trait='xxx',
                study_metadata={'phenocode': phenocode})


def selection(study_id, source='pan_ukb'):
    return dict(selected_studies={'xxx': dict(source=source, study_id=study_id)},
                selection_reason='xxx')


def validate(study_id, candidates, target=None, source='pan_ukb'):
    return selector.validate_selection(selection(study_id, source),
        candidates_by_target={'xxx': candidates},
        target_specs={'xxx': target or dict(kind='study_id', value='xxx_field', source='pan_ukb')})


@pytest.mark.parametrize('returned_id', ['xxx_field', 'xxx_file'])
def test_native_identifier_resolves_without_replacing_study(returned_id):
    original = candidate()
    result = validate(returned_id, [original])
    assert result['selected_studies']['xxx'] == original
    assert result['selected_studies']['xxx']['study_id'] == 'xxx_file'


def test_fixed_id_excludes_unrelated_pool_member():
    with pytest.raises(selector.LLMSelectionError):
        validate('xxx_other', [candidate(), candidate('xxx_other', 'xxx_other_field')])


def test_ambiguous_field_is_not_automatically_selected():
    rows = [candidate(), candidate('xxx_alternative')]
    with pytest.raises(selector.LLMSelectionError):
        validate('xxx_field', rows)
    assert validate('xxx_alternative', rows)['selected_studies']['xxx']['study_id'] == 'xxx_alternative'


def test_identity_mapping_requires_matching_source_and_explicit_target():
    with pytest.raises(selector.LLMSelectionError):
        validate('xxx_field', [candidate()], source='opengwas')
    with pytest.raises(selector.LLMSelectionError):
        validate('xxx_field', [candidate()], target=dict(kind='trait', value='xxx'))
    with pytest.raises(selector.LLMSelectionError):
        validate('xxx_file', [candidate()], target=dict(kind='study_id', value='xxx_file', source='opengwas'))


def test_null_remains_valid_for_semantic_or_ancestry_boundary():
    result = selector.validate_selection(dict(selected_studies={'xxx': None}, selection_reason='Missing evidence'),
        candidates_by_target={'xxx': [candidate()]},
        target_specs={'xxx': dict(kind='study_id', value='xxx_field', source='pan_ukb')})
    assert result['selected_studies']['xxx'] is None


@pytest.mark.parametrize('failed_field', ['disease_trait', 'efo_trait'])
@pytest.mark.parametrize('has_rows', [True, False])
def test_catalog_partial_search_retains_rows_but_never_caches_as_complete(monkeypatch, failed_field, has_rows):
    searcher = catalog.GWASCatalogSearcher()
    cache = []
    monkeypatch.setattr(searcher, 'cached_json_get', lambda *a: (False, None))
    monkeypatch.setattr(searcher, 'cached_json_set', lambda *a: cache.append(a))
    def pages(**filters):
        if failed_field in filters:
            raise ReadTimeout('xxx endpoint timeout')
        return [{'accession_id': 'xxx'}] if has_rows else []
    monkeypatch.setattr(searcher, '_study_pages', pages)
    if has_rows:
        assert searcher._search_studies('xxx') == [{'accession_id': 'xxx'}]
    else:
        with pytest.raises(ReadTimeout):
            searcher._search_studies('xxx')
    assert not cache
    assert searcher.last_source_stats['search_complete'] is False
    assert searcher.last_source_stats['endpoint_failures'][0]['field'] == failed_field


def test_partial_diagnostics_survive_candidate_conversion_and_probe(monkeypatch):
    searcher = catalog.GWASCatalogSearcher()
    monkeypatch.setattr(searcher, 'cached_json_get', lambda *a: (False, None))
    def pages(**filters):
        if 'efo_trait' in filters:
            raise ReadTimeout('xxx')
        return [{'accession_id': 'xxx'}]
    monkeypatch.setattr(searcher, '_study_pages', pages)
    monkeypatch.setattr(searcher, '_candidate_from_study', lambda *a: dict(candidate(), source='gwas_catalog'))
    monkeypatch.setattr(searcher, '_resolve_summary_stats_url', lambda *a: ('https://example.org/xxx', {'ok': True}))
    monkeypatch.setitem(side.SEARCHERS, 'gwas_catalog', lambda: searcher)
    rows, reports, _, timings, _ = side.search_one_side(side='xxx', query='xxx', aliases=[],
        sources=['gwas_catalog'], limit_per_source=1, check_download=True)
    assert len(rows) == 1 and reports[0]['status'] == 'partial'
    assert timings['gwas_catalog']['search_complete'] is False
    assert timings['gwas_catalog']['endpoint_failures'][0]['field'] == 'efo_trait'


def test_review_receives_scale_and_instrument_recovery_guidance(tmp_path):
    from pathlib import Path
    from mrcat.review import evidence_context
    root = Path(__file__).resolve().parents[1]
    skill_dir = root/'skills/mr-primary-id'
    skill = SimpleNamespace(skill_dir=skill_dir, instruction_body=(skill_dir/'SKILL.md').read_text())
    agent = SimpleNamespace(store=SimpleNamespace(directory=lambda _: tmp_path), skills={'mr-primary-id': skill})
    task = dict(task_id='xxx', request='xxx', plan='xxx', guide='mr-primary-id', artifacts=[])
    context = evidence_context(agent, dict(active_task=task, events=[], session_id='xxx', task_history=[]))
    guidance = context['skill_requirements'][0]['requirements']
    assert 'Scale failure recovery' in guidance
    assert 'Instrument-count recovery' in guidance
    assert 'does not turn tool defaults' in guidance
    assert 'Do not reinterpret this as absent instruments' in guidance
    assert 'never guess endpoints or invent N' in guidance


def test_review_preserves_middle_requirements_in_long_skill_guidance(tmp_path):
    from mrcat.review import evidence_context
    scale_rule = 'Missing sample size must be resolved from the same study; never invent N.'
    instrument_rule = 'Preserve the user-fixed threshold and minimum instrument count.'
    skill = SimpleNamespace(skill_dir=tmp_path/'long-method', instruction_body=(
        '# Long method\n\n## Input checks\nPreserve the selected study IDs.\n'
        + 'Documented input requirements.\n' * 240
        + '\n## Scale failure recovery\n' + scale_rule + '\n'
        + 'Documented recovery constraints.\n' * 240
        + '\n## Instrument-count recovery\n' + instrument_rule + '\n'))
    agent = SimpleNamespace(store=SimpleNamespace(directory=lambda _: tmp_path),
                            skills={'long-method': skill})
    task = dict(task_id='task1', request='Review the method', plan='Fit the selected study',
                guide='long-method', artifacts=[])
    context = evidence_context(agent, dict(active_task=task, events=[], session_id='session_test',
                                         task_history=[]))
    guidance = context['skill_requirements'][0]['requirements']
    assert len(guidance) > 12000
    assert 'Preserve the selected study IDs.' in guidance
    assert scale_rule in guidance
    assert instrument_rule in guidance


def test_catalog_optional_publication_failure_preserves_candidate(monkeypatch):
    searcher = catalog.GWASCatalogSearcher()
    monkeypatch.setattr(searcher, 'cached_json_get', lambda *a: (False, None))
    calls = []
    def fail(url):
        calls.append(url)
        raise ReadTimeout('xxx publication endpoint unavailable')
    monkeypatch.setattr(searcher, 'get_json', fail)
    study = dict(accession_id='xxx', disease_trait='xxx', initial_sample_size='1000 European individuals',
                 full_summary_stats_available=True, pubmed_id='xxx')
    for _ in range(2):
        row = searcher._candidate_from_study('xxx', study)
        assert row['study_id'] == 'xxx'
        assert row['study_metadata']['pmid'] == 'xxx'
    assert len(calls) == 1
    assert searcher.last_source_stats['publication_enrichment_failed'] is True


@pytest.mark.r
def test_id_metadata_recovery_preserves_identity_existing_n_and_overrides(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = tmp_path/'sample_size_recovery.R'
    script.write_text('''
source("mrcat/tool/MRTool/gwas_statistics.R")
source("skills/mr-primary-id/scripts/mr_primary_id/prepare_scale.R")
d <- data.frame(SNP=c("xxx_1","xxx_2"), beta.exposure=c(.1,.2), se.exposure=c(.02,.03),
 beta.outcome=c(.01,.02), se.outcome=c(.01,.02), pval.exposure=c(.001,.002),
 pval.outcome=c(.1,.2), samplesize.exposure=c(900,NA))
p <- list(exposure_gwas_id="xxx_exposure", outcome_gwas_id="xxx_outcome")
calls <- 0L
lookup <- function(ids) {
 calls <<- calls + 1L
 stopifnot(setequal(ids, c("xxx_exposure","xxx_outcome")))
 data.frame(id=c("xxx_exposure","xxx_outcome"), sample_size=c(1000,NA),
            ncase=c(NA,500), ncontrol=c(NA,1500))
}
r <- resolve_id_sample_sizes(d,p,lookup)
stopifnot(calls==1L, identical(r$data$samplesize.exposure,c(900,1000)),
 all(r$data$samplesize.outcome==2000), r$resolved$outcome$source=="ncase+ncontrol",
 identical(d$samplesize.exposure,c(900,NA_real_)), !is.null(r$metadata))
scaled <- prepare_id_scale(r$data,"standardize",p)
stopifnot(is.null(scaled$error), all.equal(scaled$data$se.exposure,1/sqrt(c(900,1000)))==TRUE)
override <- p; override$outcome_sample_size <- 3000
r <- resolve_id_sample_sizes(d,override,function(ids) {
 stopifnot(identical(unname(ids),"xxx_exposure"))
 data.frame(id="xxx_exposure",sample_size=1000)
})
stopifnot(is.null(r$data$samplesize.outcome), all(id_sample_sizes(r$data,"outcome",override)$value==3000))
filled <- r$data; filled$samplesize.outcome <- c(2000,2000)
r <- resolve_id_sample_sizes(filled,p,function(ids) stop("No lookup should occur"))
stopifnot(is.null(r$error), is.null(r$metadata), identical(r$data,filled))
for (meta in list(data.frame(id="xxx_wrong",sample_size=1000),
                 data.frame(id=c("xxx_exposure","xxx_exposure"),sample_size=c(1000,2000)),
                 data.frame(id="xxx_exposure",ncase=1000),
                 data.frame(sample_size=1000))) {
 r <- resolve_id_sample_sizes(d,p,function(ids) meta)
 stopifnot(identical(r$data,d), is.null(r$resolved$exposure))
}
r <- resolve_id_sample_sizes(d,p,function(ids) stop("xxx network unavailable"))
stopifnot(identical(r$data,d), grepl("network unavailable",r$error),
 prepare_id_scale(r$data,"standardize",p)$error$reason=="missing_or_invalid_sample_size")
''')
    result = subprocess.run([str(Path(sys.executable).with_name('Rscript')), str(script)],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('threshold', [[], [1e-5, 1e-6], [1e-6, 1e-6], [1e-6, 'xxx'],
                                       [1e-6, float('nan')], True, 0, 2])
def test_invalid_threshold_schedule_never_runs_analysis(monkeypatch, threshold):
    runner = importlib.import_module('skills.mr-primary-id.scripts.run_mr_primary_id')
    def unexpected(*args, **kwargs):
        pytest.fail('Invalid thresholds must be rejected before starting R or network calls')
    monkeypatch.setattr(runner, 'run_streaming', unexpected)
    result = runner.run(dict(exposure_gwas_id='xxx_exposure', outcome_gwas_id='xxx_outcome',
                             pvalue_threshold=threshold))
    assert result['outputs']['status'] == 'blocked'
    assert result['details']['failure_class'] == 'invalid_threshold'
