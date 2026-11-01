"""One hosted search operation with the legacy DeepSeek -> OpenAI fallback."""
import os
from uuid import uuid4
from .artifacts import result, save, trace
from .providers import build_provider_registry, render_search_input
from .types import SearchRequest


def run(payload):
    query = str(payload.get('query') or '').strip()
    if not query:
        raise ValueError('web_search requires a nonempty query.')
    provider_name = str(payload.get('provider') or os.getenv('SEARCH_PROVIDER') or 'deepseek').lower()
    providers = build_provider_registry()
    if provider_name not in providers:
        raise ValueError(f'Unsupported hosted search provider: {provider_name}')
    request = SearchRequest(query=query, memory_summary=str(payload.get('context') or ''), recent_turns=[])
    save('request.json', dict(query=query, provider=provider_name, prompt=render_search_input(request)))
    attempts = []
    names = [provider_name]
    if provider_name == 'deepseek' and payload.get('fallback', True):
        names.append('openai')
    for name in names:
        try:
            response = providers[name].search(request, trace_sink=trace)
            raw_path = save(name + '_response.json', response.raw_response)
            attempts.append(dict(provider=name, status='ok', raw_response_path=raw_path))
            break
        except Exception as exc:
            error = dict(provider=name, status='failed', error=f'{type(exc).__name__}: {exc}',
                         raw_response=getattr(exc, 'raw_response', None),
                         output_item_types=getattr(exc, 'output_item_types', []))
            path = save(name + '_error.json', error)
            attempts.append(dict(provider=name, status='failed', error=error['error'], error_path=path))
            trace('search_provider_failed', attempts[-1])
    else:
        path = save('attempts.json', attempts)
        return dict(summary='Hosted web search failed; no evidence was retrieved.',
                    outputs=dict(status='failed', query=query, attempts=attempts, attempts_path=path),
                    details=dict(failure_class='web_search_failed', message='; '.join(a['error'] for a in attempts)))
    artifact_id = 'search_' + uuid4().hex[:10]
    citations = [dict(item, id=f'{artifact_id}_c{i}', title=item.get('title') or 'Untitled source')
                 for i, item in enumerate(response.citations, 1) if item.get('url')]
    payload = dict(kind='web_search', artifact_id=artifact_id, query=query, answer=response.text,
                   citations=citations, queries=response.queries, provider=response.provider,
                   model=response.model, usage=response.usage, attempts=attempts)
    path = save('search.json', payload)
    return result(f'Hosted search completed with {response.provider}; {len(citations)} sources.',
                  **payload, search_path=path, raw_response_path=raw_path)
