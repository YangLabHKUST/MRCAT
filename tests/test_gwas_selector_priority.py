"""Selection evidence distinguishes requested labels without changing study objects."""
import copy
import importlib
import json

import pytest

selector = importlib.import_module('skills.gwas-select.scripts.llm_selector')


@pytest.mark.parametrize('source', ['opengwas', 'gwas_catalog'])
def test_label_evidence_uses_original_target_and_preserves_candidate(source):
    target = dict(kind='trait', value='Example marker levels', aliases=['Example marker'])
    exact = dict(source=source, study_id='study-1', trait='  EXAMPLE marker   levels ',
                 downloadable=True, ancestry='european', sample_size=1000,
                 download_descriptor=dict(status='ready', method='url', url='https://example.org/data.tsv.gz'),
                 study_metadata={'endpoint_definition': 'Measured circulating marker'})
    alias = dict(exact, study_id='study-2', trait='Example marker')
    pool = [exact, alias]
    original = copy.deepcopy(pool)
    package = selector.build_prompt_package(candidates_by_target={'exposure': pool},
                                           target_specs={'exposure': target})
    encoded = package.user_prompt.split('## Candidate Pool\n', 1)[1].split('\n\n##', 1)[0]
    evidence = json.loads(encoded)['exposure']
    assert [row['reported_trait_matches_request'] for row in evidence] == [True, False]
    assert evidence[0]['study_metadata'] == exact['study_metadata']
    # A label flag does not become a study identifier or rewrite the saved object.
    selected = selector.validate_selection(
        dict(selection_reason='Eligible endpoint', selected_studies={
            'exposure': dict(source=source, study_id='study-1')}),
        candidates_by_target={'exposure': pool}, target_specs={'exposure': target})
    assert selected['selected_studies']['exposure'] == exact
    assert 'reported_trait_matches_request' not in selected['selected_studies']['exposure']
    assert pool == original


def test_fixed_identifier_is_not_compared_as_a_trait_label():
    candidate = dict(source='gwas_catalog', study_id='study-1', trait='study-1')
    compact = selector._compact_candidate(candidate, dict(kind='study_id', value='study-1'))
    assert compact['reported_trait_matches_request'] is None
