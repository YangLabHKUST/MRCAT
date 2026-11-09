"""Catalog transport recovery preserves scientific inputs and source evidence."""
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from requests import HTTPError, ReadTimeout, RequestException, Response

catalog = importlib.import_module('skills.gwas-search.scripts.search_gwas_catalog')
side = importlib.import_module('skills.gwas-search.scripts.search_side')


@pytest.fixture
def searcher(monkeypatch):
    value = catalog.GWASCatalogSearcher()
    monkeypatch.setattr(value, 'cached_json_get', lambda *args: (False, None))
    monkeypatch.setattr(value, 'cached_json_set', lambda *args: None)
    return value


def study(accession='GCST123456', trait='Example metabolite levels', downloadable=True):
    return dict(accessionId=accession, reportedTrait=trait,
                efoTraits=[dict(key='EFO_1234567', label=trait)],
                initialSampleDescription=['1,234 European ancestry individuals'],
                discoverySampleAncestry=['1234 European'],
                pubmedId='123456', publicationDate='2020-01-01', title='Example study',
                summaryStatistics='https://ftp.ebi.ac.uk/example/' if downloadable else 'NA')


def page(rows, number=0, pages=1):
    return {'_embedded': {'studies': rows},
            'page': dict(number=number, totalPages=pages, totalElements=len(rows))}


@pytest.mark.parametrize('failure', ['timeout', 'http500'])
def test_fallback_preserves_query_metadata_and_download_contract(searcher, monkeypatch, failure):
    query = 'Example metabolite levels'
    calls = []
    def get(url):
        calls.append(url)
        if url.startswith(searcher.base_api):
            if failure == 'timeout':
                raise ReadTimeout('REST unavailable')
            response = Response(); response.status_code = 500
            raise HTTPError('REST unavailable', response=response)
        params = parse_qs(urlparse(url).query)
        assert params.get('reportedTrait', params.get('efoTrait')) == [query]
        assert params['includeChildTraits'] == ['false']
        return page([study(), study('GCST123457', downloadable=False)])
    monkeypatch.setattr(searcher, 'get_json', get)
    monkeypatch.setattr(searcher, '_publication', lambda *a: pytest.fail('Must not revisit failed REST for publication'))
    monkeypatch.setattr(searcher, '_resolve_summary_stats_url',
                        lambda *a: ('https://ftp.ebi.ac.uk/example/data.tsv.gz', {'ok': True}))
    monkeypatch.setitem(side.SEARCHERS, 'gwas_catalog', lambda: searcher)
    rows, reports, _, timings, _ = side.search_one_side(
        side='target', query=query, aliases=[], sources=['gwas_catalog'],
        limit_per_source=20, check_download=True)
    assert len(rows) == 1
    row = rows[0]
    assert row['study_id'] == 'GCST123456' and row['source'] == 'gwas_catalog'
    assert row['trait'] == query and row['sample_size'] == 1234 and row['ancestry'] == 'european'
    assert row['study_metadata']['publication_title'] == 'Example study'
    assert row['study_metadata']['publication_year'] == 2020
    assert row['downloadable'] and row['download_url'].endswith('/data.tsv.gz')
    assert reports[0]['status'] == 'partial'
    assert timings['gwas_catalog']['fallback_transport'] == 'catalog_website'
    assert len(timings['gwas_catalog']['endpoint_failures']) == 2
    assert len(calls) == 4


def test_web_pagination_and_ontology_candidates_are_merged(searcher, monkeypatch):
    query = 'Example + marker (A/B) levels'
    calls = []
    def get(url):
        params = parse_qs(urlparse(url).query); calls.append(params)
        assert params.get('reportedTrait', params.get('efoTrait')) == [query]
        if 'efoTrait' in params:
            return page([study(), study('GCST123458')])
        number = int(params['page'][0])
        return page([study('GCST123456' if number == 0 else 'GCST123457')], number, 2)
    monkeypatch.setattr(searcher, 'get_json', get)
    rows = searcher._search_web_studies(query)
    assert [row['accession_id'] for row in rows] == ['GCST123456', 'GCST123457', 'GCST123458']
    assert len(calls) == 3


def test_successful_rest_does_not_use_web(searcher, monkeypatch):
    monkeypatch.setattr(searcher, '_study_pages', lambda **kw: [dict(accession_id='GCST123456')])
    monkeypatch.setattr(searcher, '_search_web_studies', lambda *a: pytest.fail('Unexpected website call'))
    assert len(searcher._search_studies('example')) == 1


@pytest.mark.parametrize('rows', [[], [study()]])
def test_partial_web_failure_retains_rows_without_claiming_absence(searcher, monkeypatch, rows):
    def get(url):
        if 'efoTrait=' in url:
            raise ReadTimeout('Website ontology unavailable')
        return page(rows)
    monkeypatch.setattr(searcher, 'get_json', get)
    if rows:
        assert searcher._search_web_studies('example')[0]['accession_id'] == 'GCST123456'
    else:
        with pytest.raises(ReadTimeout):
            searcher._search_web_studies('example')
    assert searcher.last_source_stats['endpoint_failures'][0]['field'] == 'website_efoTrait'


@pytest.mark.parametrize('payload', [
    {'error': {'code': 500}},
    {'page': dict(number=0, totalPages=1, totalElements=2)},
    page([{'reportedTrait': 'Missing identifier'}]),
    page([study()], number=1),
])
def test_malformed_web_response_is_not_an_empty_search(searcher, monkeypatch, payload):
    monkeypatch.setattr(searcher, 'get_json', lambda url: payload)
    with pytest.raises(catalog.SearchError):
        list(searcher._web_study_pages('studies', reportedTrait='example'))


def test_catalog_rest_does_not_repeat_failed_http_calls(searcher):
    assert searcher.session.get_adapter(searcher.base_api + '/studies').max_retries.total == 0


def test_web_failure_does_not_discard_valid_rest_candidates(searcher, monkeypatch):
    def rest(**filters):
        if 'efo_trait' in filters:
            raise ReadTimeout('REST partial failure')
        return [dict(accession_id='GCST123456')]
    def web(query):
        raise ReadTimeout('Website unavailable')
    monkeypatch.setattr(searcher, '_study_pages', rest)
    monkeypatch.setattr(searcher, '_search_web_studies', web)
    assert searcher._search_studies('example') == [dict(accession_id='GCST123456')]
    assert len(searcher.last_source_stats['endpoint_failures']) == 2


@pytest.mark.parametrize('responses, succeeds, attempts', [
    ([503, 200], True, 2),
    (['timeout', 200], True, 2),
    ([503, 503], False, 2),
    (['timeout', 'timeout'], False, 2),
    ([404], False, 1),
])
def test_web_transport_retries_only_once(searcher, responses, succeeds, attempts):
    paths = []
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            status = responses[min(len(paths) - 1, len(responses) - 1)]
            if status == 'timeout':
                release.wait(3)
                return
            payload = json.dumps(page([study()])).encode()
            self.send_response(status)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    adapter = searcher.session.get_adapter(searcher.web_api + '/studies')
    searcher.web_api = f'http://127.0.0.1:{server.server_port}'
    searcher.session.mount(searcher.web_api + '/', adapter)
    searcher.session.trust_env = False
    searcher.timeout = 0.2
    try:
        if succeeds:
            assert list(searcher._web_study_pages('studies', reportedTrait='example')) == [study()]
        else:
            with pytest.raises(RequestException):
                list(searcher._web_study_pages('studies', reportedTrait='example'))
        assert len(paths) == attempts
        assert len(set(paths)) == 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


def test_later_web_page_failure_preserves_earlier_page(searcher, monkeypatch):
    def get(url):
        params = parse_qs(urlparse(url).query)
        if 'efoTrait' in params:
            return page([])
        if params['page'] == ['1']:
            raise ReadTimeout('Page two unavailable')
        return page([study()], pages=2)
    monkeypatch.setattr(searcher, 'get_json', get)
    assert searcher._search_web_studies('example')[0]['accession_id'] == 'GCST123456'
    assert searcher.last_source_stats['endpoint_failures'][0]['field'] == 'website_reportedTrait'


def test_total_failure_retains_rest_and_web_diagnostics(searcher, monkeypatch):
    def get(url):
        raise ReadTimeout('Unavailable: ' + url)
    monkeypatch.setattr(searcher, 'get_json', get)
    monkeypatch.setitem(side.SEARCHERS, 'gwas_catalog', lambda: searcher)
    rows, reports, _, timings, _ = side.search_one_side(
        side='target', query='example', aliases=[], sources=['gwas_catalog'],
        limit_per_source=20, check_download=True)
    assert not rows and reports[0]['status'] == 'error'
    stats = timings['gwas_catalog']
    assert stats['fallback_transport'] == 'catalog_website'
    assert {item['field'] for item in stats['endpoint_failures']} >= {
        'disease_trait', 'efo_trait', 'website_reportedTrait', 'website_efoTrait'}


def test_later_alias_failure_preserves_downloadable_candidates(searcher, monkeypatch):
    def get(url):
        params = parse_qs(urlparse(url).query)
        query = next(params[key][0] for key in ('disease_trait', 'efo_trait', 'reportedTrait', 'efoTrait') if key in params)
        if url.startswith(searcher.base_api) or query == 'failing alias':
            raise ReadTimeout('Unavailable: ' + url)
        return page([study()])
    monkeypatch.setattr(searcher, 'get_json', get)
    monkeypatch.setattr(searcher, '_resolve_summary_stats_url',
                        lambda *a: ('https://ftp.ebi.ac.uk/example/data.tsv.gz', {'ok': True}))
    monkeypatch.setitem(side.SEARCHERS, 'gwas_catalog', lambda: searcher)
    rows, reports, _, timings, _ = side.search_one_side(
        side='target', query='Example metabolite levels', aliases=['failing alias'],
        sources=['gwas_catalog'], limit_per_source=20, check_download=True)
    assert [row['study_id'] for row in rows] == ['GCST123456']
    assert rows[0]['downloadable'] and reports[0]['status'] == 'partial'
    assert any(item['query'] == 'failing alias' for item in timings['gwas_catalog']['endpoint_failures'])
