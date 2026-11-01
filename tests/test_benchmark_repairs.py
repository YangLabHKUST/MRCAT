"""Regression cases for the baseline26 failures, without model/API dependence."""
import csv
import importlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

import pytest
from requests import HTTPError, Response
from mrcat.execution import CodeExecutor
from mrcat.agent import Agent
from test_agent import ROOT, Model, action, create, decision

catalog = importlib.import_module('skills.gwas-search.scripts.search_gwas_catalog')
qc = importlib.import_module('skills.gwas-qc.scripts.canonicalize_study')


@pytest.fixture
def searcher(monkeypatch):
    searcher = catalog.GWASCatalogSearcher()
    monkeypatch.setattr(searcher, 'cached_json_get', lambda *a: (False, None))
    monkeypatch.setattr(searcher, 'cached_json_set', lambda *a: None)
    return searcher


def test_catalog_v2_pages_and_candidate_metadata(searcher, monkeypatch):
    calls = []
    study = dict(accession_id='GCST90002363', disease_trait='Red blood cell count',
                 initial_sample_size='545,203 European ancestry individuals',
                 replication_sample_size='100 Japanese individuals',
                 discovery_ancestry=['545203 European (U.K.)'], full_summary_stats_available=True,
                 pubmed_id=32888493)
    def get(url):
        calls.append(url)
        if '/publications/' in url:
            return dict(pubmed_id='32888493', title='Blood cell genetics', publication_date='2020-09-01')
        params = parse_qs(urlparse(url).query)
        assert params.get('disease_trait', params.get('efo_trait')) == ['red blood cell count']
        if params.get('page') == ['1']:
            return {'_embedded': {'studies': [dict(study, accession_id='GCST90002364', full_summary_stats_available=False)]}}
        return {'_embedded': {'studies': [study]}, '_links': {'next': {'href': searcher.primary_endpoint+'?disease_trait=red%20blood%20cell%20count&page=1&size=200'}}}
    monkeypatch.setattr(searcher, 'get_json', get)
    candidates = searcher.search('red blood cell count')
    assert len(candidates) == 2
    assert candidates[0]['sample_size'] == 545203
    assert candidates[0]['ancestry'] == 'european'
    assert candidates[1]['downloadability_reason'] == 'no_summary_stats'
    assert candidates[0]['study_metadata']['publication_year'] == 2020
    assert all('/v2/' in url for url in calls)


@pytest.mark.parametrize('status', [401, 410, 503])
def test_catalog_access_failure_is_not_no_study(searcher, monkeypatch, status):
    response = Response(); response.status_code = status
    def fail(url):
        raise HTTPError('remote error', response=response)
    monkeypatch.setattr(searcher, 'get_json', fail)
    with pytest.raises(HTTPError):
        searcher._fetch_study_by_accession('GCST123456')
    with pytest.raises(HTTPError):
        searcher._search_studies('red blood cell count')


def test_catalog_empty_and_malformed_responses_are_distinct(searcher, monkeypatch):
    monkeypatch.setattr(searcher, 'get_json', lambda url: {'page': {'totalElements': 0}})
    assert searcher._search_studies('unknown trait') == []
    monkeypatch.setattr(searcher, 'get_json', lambda url: {'error': 'unavailable'})
    with pytest.raises(catalog.SearchError):
        searcher._search_studies('unknown trait')


def test_catalog_repeated_pagination_fails(searcher, monkeypatch):
    monkeypatch.setattr(searcher, 'get_json', lambda url: {'_embedded': {'studies': []}, '_links': {'next': {'href': url}}})
    with pytest.raises(catalog.SearchError, match='pagination'):
        searcher._search_studies('trait')


def test_process_success_preserves_tool_failure_evidence(tmp_path):
    code = '''import json
from pathlib import Path
Path('response.json').write_text(json.dumps({'outputs': {'status': 'blocked'}, 'details': {'failure_class': 'scale_input_invalid', 'message': 'outcome N missing'}}))'''
    result = CodeExecutor(ROOT, tmp_path/'session').execute(code, 'python', 'blocked')
    assert result['returncode'] == 0
    assert result['tool_results'][0]['status'] == 'blocked'
    assert result['tool_results'][0]['failure_class'] == 'scale_input_invalid'


def test_repeated_execution_errors_pause_and_allow_explicit_continuation(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', "raise ValueError('bad parsing')")] * 3,
                  [decision('mr', 'propose', execute=True)])
    paused = Agent(ROOT, store, model=model).run(sid, 'Process the supplied data')
    assert paused['status'] == 'paused'
    task_id = paused['active_task']['task_id']
    repair = Model([action('execute', "from mrcat.tools import publish_result\nx=int('42')\npublish_result('parsed', {'value':x})"),
                    action('end', 'Plan complete after local parsing repair.', outcome='complete')],
                   [decision('mr', 'continue')])
    done = Agent(ROOT, store, model=repair).run(sid, 'Continue and repair the parsing error')
    assert done['status'] == 'completed'
    assert done['task_history'][0]['task_id'] == task_id
    roles = [call['role'] for call in model.calls + repair.calls]
    assert roles.count('evaluate') == 1
    assert roles.count('planner') == 1
    assert sum(e['type'] == 'code_execution' for e in done['events']) == 4


def test_invalid_mr_action_transport_pauses_without_scientific_review(tmp_path):
    store, sid = create(tmp_path)
    model = Model([action('execute', 'print(42)', language='unsupported')] * 2,
                  [decision('mr', 'propose', execute=True)])
    result = Agent(ROOT, store, model=model, max_rounds=2).run(sid, 'Process the supplied data')
    assert result['status'] == 'paused'
    assert not any(call['role'] == 'evaluate' for call in model.calls)
    assert not any(e['type'] == 'code_execution' for e in result['events'])


@pytest.mark.parametrize('fault', ['alleles', 'beta', 'row_order', None])
def test_q29_minor_allele_is_not_effect_allele(tmp_path, fault):
    raw = dict(variant='1:100:A:G', minor_allele='A', minor_AF='0.2', n_complete_samples='1000',
               AC='400', ytx='1', beta='0.12', se='0.03', tstat='4', pval='0.001')
    source = tmp_path/'source.tsv'
    with source.open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(raw), delimiter='\t'); writer.writeheader(); writer.writerow(raw)
    preview = qc.Preview('study', source, 'tabular', list(raw), [raw], [], '', '\t')
    out = {k: '' for k in qc.CANONICAL_COLUMNS}
    out.update(SNP='rs1', CHR='1', BP='100', effect_allele='G', other_allele='A', beta='0.12', se='0.03', pval='0.001', n='1000')
    if fault == 'alleles': out.update(effect_allele='A', other_allele='G')
    if fault == 'beta': out['beta'] = '-0.12'
    if fault == 'row_order': out['BP'] = '101'
    target = tmp_path/'canonical.tsv'
    with target.open('w') as f:
        writer = csv.DictWriter(f, fieldnames=qc.CANONICAL_COLUMNS, delimiter='\t'); writer.writeheader(); writer.writerow(out)
    def validate():
        return qc.validate_canonical_output(side='study', output_path=target, expected_rows=1,
             sample_only=True, strict_rsid=False, side_sample_size=None, source_preview=preview)
    if fault:
        with pytest.raises(qc.GwasQcCanonicalizationBlocked) as exc:
            validate()
        assert exc.value.failure_class == 'source_mapping_conflict'
    else:
        assert validate().rows_written == 1


def test_neale_check_requires_complete_signature(tmp_path):
    preview = qc.Preview('study', tmp_path/'raw', 'tabular', ['variant', 'minor_allele', 'beta'], [], [], '', '\t')
    assert not qc.has_neale_signature(preview)


@pytest.mark.r
def test_id_scale_separates_missing_n_from_instrument_count(tmp_path):
    code = '''
source("mrcat/tool/mr/gwas_statistics.R")
source("skills/mr-primary-id/scripts/mr_primary_id/prepare_scale.R")
d <- data.frame(SNP=c("rs1","rs2"), beta.exposure=c(.1,.2), se.exposure=c(.02,.03),
 beta.outcome=c(.01,.02), se.outcome=c(.01,.02), pval.exposure=c(.001,.002),
 pval.outcome=c(.1,.2), samplesize.exposure=c(1000,1000))
r <- prepare_id_scale(d, "standardize", list())
stopifnot(r$error$side == "outcome", r$error$reason == "missing_or_invalid_sample_size", nrow(r$data)==2)
r <- prepare_id_scale(d, "standardize", list(outcome_sample_size=2000))
stopifnot(is.null(r$error), nrow(r$data)==2, all(r$data$beta_native.outcome == d$beta.outcome))
stopifnot(all(r$data$se.outcome == 1/sqrt(2000)))
r <- prepare_id_scale(d, "native", list())
stopifnot(is.null(r$error), all(r$data$beta.outcome == d$beta.outcome))
d$pval.outcome[1] <- 0
r <- prepare_id_scale(d, "standardize", list(outcome_sample_size=2000))
stopifnot(r$error$reason == "invalid_signed_statistic")
'''
    test = tmp_path/'scale.R'; test.write_text(code)
    run = subprocess.run([str(Path(sys.executable).with_name('Rscript')), str(test)], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
