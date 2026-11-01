"""Bounded HTTPS inspection and existing-source GWAS download probes."""
from copy import deepcopy
from importlib import import_module
import ipaddress
import json
import os
import socket
from urllib.parse import urljoin, urlparse
import requests
from .artifacts import result, save

MAX_BYTES = 1_000_000
MAX_RANGE_BYTES = 262_144


def _public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('Inspection accepts public HTTPS URLs only.')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('URL credentials are not allowed.')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Inspection blocked a non-public address.')


def _official_source(url):
    parsed = urlparse(url)
    host, path = parsed.hostname, parsed.path
    if host in {'api.opengwas.io', 'gwas.mrcieu.ac.uk', 'files.opengwas.io'}:
        return 'opengwas'
    if (host == 'www.ebi.ac.uk' and path.startswith('/gwas/')) or (
            host == 'ftp.ebi.ac.uk' and path.startswith('/pub/databases/gwas/')):
        return 'gwas_catalog'
    if host == 'r10.finngen.fi' or (host == 'storage.googleapis.com' and path.startswith('/finngen-public-data-')):
        return 'finngen'
    if host == 'pan-ukb-us-east-1.s3.amazonaws.com':
        return 'pan_ukb'
    raise ValueError('URL is not an official GWAS endpoint; use web_open for public discovery.')


def _sources():
    return import_module('skills.gwas-search.scripts.search_sources')


def _route(payload):
    sources = _sources()
    route = sources.resolve_search_route(
        study_id=payload.get('study_id', ''), source=payload.get('source', ''),
        ancestry=payload.get('ancestry'), default_sources=list(sources.SEARCHERS),
        preferred_sources=[], allow_source_fallback=False)
    if route.get('failure_class'):
        raise ValueError(route.get('message') or route['failure_class'])
    return route


def _summary_file(url):
    return urlparse(url).path.lower().endswith(('.bgz', '.csv', '.csv.gz', '.tsv', '.tsv.gz',
                                             '.txt', '.txt.gz', '.vcf', '.vcf.gz', '.zip', '.gz'))


def _request(url, *, operation='text', max_bytes=MAX_BYTES, start=0, end=65535, allowed_sources=None):
    if operation not in {'text', 'json', 'head', 'range'}:
        raise ValueError('operation must be text, json, head, or range.')
    method = 'HEAD' if operation == 'head' else 'GET'
    limit = max(1, min(int(max_bytes), MAX_BYTES))
    if operation == 'range':
        start = max(0, int(start))
        end = min(max(start, int(end)), start + MAX_RANGE_BYTES - 1)
        limit = end - start + 1
    current, redirects = str(url), []
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'MRCAT-Search/0.1'})
        for _ in range(6):
            _public_url(current)
            if allowed_sources is not None and _official_source(current) not in allowed_sources:
                raise ValueError('URL source is outside the requested source/ancestry route.')
            if operation in {'text', 'json'} and _summary_file(current):
                raise ValueError('Use head or range to inspect summary data; use gwas_download for full files.')
            headers = {'Range': f'bytes={start}-{end}'} if operation == 'range' else {}
            if allowed_sources is not None and urlparse(current).hostname == 'api.opengwas.io':
                token = os.getenv('OPENGWAS_JWT')
                if token:
                    headers['Authorization'] = 'Bearer ' + token
            with session.request(method, current, headers=headers, timeout=30,
                                 allow_redirects=False, stream=True) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get('location')
                    if not location:
                        raise ValueError('HTTPS redirect omitted Location.')
                    redirects.append(current)
                    current = urljoin(current, location)
                    continue
                body = bytearray()
                if method != 'HEAD':
                    for chunk in response.iter_content(chunk_size=min(65536, limit + 1)):
                        body.extend(chunk[:max(0, limit + 1 - len(body))])
                        if len(body) > limit:
                            break
                truncated = len(body) > limit
                body = body[:limit]
                inspected = dict(url=response.url, status_code=response.status_code, redirects=redirects,
                                 headers={k: response.headers[k] for k in ('content-type', 'content-length',
                                          'content-range', 'etag', 'last-modified', 'accept-ranges') if k in response.headers},
                                 bytes_read=len(body), truncated=truncated,
                                 text=body.decode(response.encoding or 'utf-8', errors='replace'))
                if operation == 'json' and response.status_code < 400:
                    if truncated:
                        raise ValueError('JSON response exceeds max_bytes; no partial JSON was parsed.')
                    inspected['data'] = json.loads(inspected.pop('text'))
                return inspected
    raise ValueError('HTTPS inspection exceeded redirect limit.')


def web_open(payload):
    inspected = _request(payload['url'], operation=payload.get('operation', 'text'),
                         max_bytes=payload.get('max_bytes', MAX_BYTES), start=payload.get('start', 0),
                         end=payload.get('end', 65535))
    return _inspection_result(inspected)


def http_inspect(payload):
    route = _route(payload)
    inspected = _request(payload['url'], operation=payload.get('operation', 'text'),
                         max_bytes=payload.get('max_bytes', MAX_BYTES), start=payload.get('start', 0),
                         end=payload.get('end', 65535), allowed_sources=route['sources'])
    return _inspection_result(inspected)


def _inspection_result(inspected):
    path = save('inspection.json', inspected)
    return dict(summary=f"HTTPS inspection returned HTTP {inspected['status_code']}.",
                outputs=dict(status='ok' if inspected['status_code'] < 400 else 'failed',
                             **inspected, inspection_path=path))


def gwas_probe(payload):
    candidates = deepcopy(payload['candidates'])
    if not isinstance(candidates, list) or not candidates or not all(isinstance(v, dict) for v in candidates):
        raise ValueError('gwas_probe requires a nonempty list of complete candidate objects.')
    route = _route(payload)
    sources = _sources()
    source = route.get('source') or sources.normalize_source_name(candidates[0].get('source'))
    if source not in route['sources'] or any(sources.normalize_source_name(v.get('source')) != source for v in candidates):
        raise ValueError('Candidates must share one source within the requested route.')
    matches = import_module('skills.gwas-search.scripts.search_exact_id').candidate_matches_exact_id
    ancestry_matches = import_module('skills.gwas-search.scripts.search_side').candidate_matches_requested_ancestry
    for candidate in candidates:
        if payload.get('study_id') and not matches(candidate, payload['study_id'], source):
            raise ValueError('Candidate does not match the exact requested study ID.')
        if route.get('ancestry') and not ancestry_matches(candidate, route['ancestry']):
            raise ValueError('Candidate does not match the requested ancestry.')
    probed = sources.SEARCHERS[source]().probe_candidates(
        candidates, probe_limit=min(len(candidates), max(1, min(int(payload.get('limit', 20)), 100))),
        check_download=True)
    path = save('probed_candidates.json', probed)
    return result('GWAS candidates probed; only downloadable=true candidates passed the probe.',
                  candidates=probed, candidates_path=path)


def web_probe(payload):
    candidate = deepcopy(payload['candidate'])
    if candidate.get('data_kind') != 'gwas_summary_statistics':
        raise ValueError("web_probe requires data_kind='gwas_summary_statistics'.")
    if not candidate.get('source') or not candidate.get('study_id'):
        raise ValueError('web_probe requires source and study_id from observed evidence.')
    _public_url(candidate.get('study_metadata', {}).get('provenance_url', ''))
    descriptor = candidate.get('download_descriptor') or {}
    url = descriptor.get('url') or candidate.get('download_url')
    if not url or not _summary_file(url):
        raise ValueError('web_probe requires a recognizable summary-statistics file URL.')
    inspected = _request(url, operation='head')
    inspection_path = save('inspection.json', inspected)
    if inspected['status_code'] >= 400 or 'text/html' in inspected['headers'].get('content-type', '').lower():
        return dict(summary='External GWAS file probe failed.', outputs=dict(status='failed',
                    inspection_path=inspection_path, inspection=inspected))
    candidate.pop('download_url', None)
    candidate.update(downloadable=True, download_descriptor=dict(descriptor, source=candidate['source'],
                     study_id=candidate['study_id'], status='ready', method='url', requires_auth=False, url=inspected['url']))
    path = save('probed_candidate.json', candidate)
    return result('External GWAS URL is reachable; file contents and scientific suitability remain unverified.',
                  candidate=candidate, candidate_path=path, inspection_path=inspection_path)
