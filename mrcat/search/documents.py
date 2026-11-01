"""Focused evidence-to-document calls; the outer Search owns all decisions."""
import json
from pathlib import Path
import os
from mrcat.config.loader import load_repo_config
from mrcat.model.llm_gateway import call_validated_json
from .artifacts import result, save, trace
from .contracts import BRIEF_REQUIRED_HEADINGS, validate_brief_payload, validate_scan_design_payload


def _evidence(value):
    """Accept complete tool results, their outputs, or saved JSON/Markdown paths."""
    if not isinstance(value, list):
        raise ValueError('evidence must be a list of saved artifacts or tool outputs.')
    evidence = []
    for item in value:
        if isinstance(item, str):
            path = Path(item).expanduser().resolve()
            text = path.read_text(encoding='utf-8')
            item = dict(path=str(path), content=json.loads(text) if path.suffix == '.json' else text)
        if not isinstance(item, dict):
            raise ValueError('Each evidence item must be an artifact path or object.')
        evidence.append(item)
    return evidence


def _citation_ids(value):
    found = set()
    if isinstance(value, dict):
        for item in value.get('citations', []) if isinstance(value.get('citations'), list) else []:
            if isinstance(item, dict) and item.get('id') and item.get('url'):
                found.add(item['id'])
        for item in value.values():
            found.update(_citation_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_citation_ids(item))
    return found


def _build(payload, kind):
    request = str(payload.get('request') or '').strip()
    if not request:
        raise ValueError(f'{kind} requires the complete user request and constraints.')
    evidence = _evidence(payload.get('evidence', []))
    citation_ids = _citation_ids(evidence)
    root = Path(__file__).resolve().parents[1]
    prompt_name = 'build_brief' if kind == 'research_brief' else 'build_scan_design'
    system = (root / 'prompts' / f'search.{prompt_name}.system.md').read_text()
    if kind == 'research_brief':
        validator = validate_brief_payload
        example = dict(markdown='# Search Brief\n\n' + '\n\n'.join(
            f'## {heading}\nNot reported' for heading in BRIEF_REQUIRED_HEADINGS), pipeline_queries=[])
    else:
        def validator(value):
            validated = validate_scan_design_payload(value)
            unknown = set(validated['scan_design']['citations']) - citation_ids
            if unknown:
                raise ValueError(f'Scan design cites unknown sources: {sorted(unknown)}')
            return validated
        example = dict(markdown='# Scan Design\nReview these proposed traits before MR planning.',
                       scan_design=dict(exposure_list=[dict(trait='EXPOSURE', aliases=[])],
                                        outcome_list=[dict(trait='OUTCOME', aliases=[])],
                                        rationale='Explain using supplied evidence.', citations=[]))
    inputs = dict(request=request, memory=payload.get('context', ''), evidence=evidence,
                  available_citation_ids=sorted(citation_ids))
    input_path = save('evidence.json', inputs)
    config = load_repo_config(repo_root=root.parent).config
    document = call_validated_json(system=system, user=json.dumps(inputs, ensure_ascii=False),
                                  example=example, validator=validator, agent_config=config,
                                  thinking=False, trace_sink=trace)
    # Paths and handoff text are deterministic, not invented by the document model.
    directory = Path(os.environ['MRCAT_EXECUTION_DIR'])
    markdown_path = directory / f'{kind}.md'
    artifact_path = directory / f'{kind}.json'
    if kind == 'scan_design':
        design = document['scan_design']
        document['pipeline_queries'] = ['\n'.join([
            'PHENOME_SCAN',
            'exposure_traits=' + json.dumps([v['trait'] for v in design['exposure_list']], ensure_ascii=False),
            'outcome_traits=' + json.dumps([v['trait'] for v in design['outcome_list']], ensure_ascii=False),
            'scan_design_artifact=' + str(artifact_path),
            'Original request and constraints: ' + request,
        ])]
    markdown_path.write_text(document['markdown'], encoding='utf-8')
    saved = dict(kind=kind, **document, request=request, evidence_path=input_path)
    save(artifact_path.name, saved)
    return result(f'{kind} saved; candidate queries require user selection before MR planning.',
                  **saved, artifact_path=str(artifact_path), markdown_path=str(markdown_path))


def research_brief(payload):
    return _build(payload, 'research_brief')


def scan_design(payload):
    return _build(payload, 'scan_design')
