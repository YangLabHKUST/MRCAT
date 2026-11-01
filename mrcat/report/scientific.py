from __future__ import annotations

import base64
from datetime import UTC, datetime
import html as html_lib
import math
import mimetypes
from pathlib import Path
import re
from typing import Any, Iterable


_FIGURE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_BLOCK_TYPES = {"paragraph", "table", "figure", "callout", "subsection"}
_FIGURE_LAYOUTS = {"full_width", "side_by_side"}


_REPORT_HTML_CSS = """
:root {
  color-scheme: light;
  --report-navy: #17324d;
  --report-blue: #2d6e8e;
  --report-teal: #2a8c82;
  --report-ink: #253746;
  --report-muted: #617384;
  --report-line: #b9c7d1;
  --report-wash: #eef5f7;
  --report-paper: #ffffff;
}

* { box-sizing: border-box; }

html {
  background: #e9eef2;
  color: var(--report-ink);
  font-family: "Times New Roman", Times, "Nimbus Roman No9 L", "Liberation Serif", Georgia, serif;
  font-size: 16px;
}

body { margin: 0; }

.report {
  width: min(960px, calc(100% - 40px));
  margin: 20px auto 48px;
  padding: clamp(36px, 5vw, 68px) clamp(28px, 6vw, 76px);
  background: var(--report-paper);
  box-shadow: 0 14px 42px rgba(23, 50, 77, 0.16);
  line-height: 1.5;
}

.report-cover {
  min-height: min(760px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  border-top: 3px solid var(--report-teal);
  padding-top: 16mm;
  break-after: page;
}

.report-title {
  margin: 0;
  color: var(--report-navy);
  font-size: 2.25rem;
  line-height: 1.12;
  letter-spacing: -0.025em;
}

.report-subtitle {
  margin: 0.8rem 0 0;
  color: var(--report-blue);
  font-size: 1.22rem;
}

.report-status { margin-top: 2.2rem; }

.abstract-block {
  margin: 2rem 0 0;
}

.abstract-block .callout { margin: 0; }

.report-brand {
  margin-top: auto;
  color: var(--report-muted);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.78rem;
}

.report-section {
  margin-top: 2.1rem;
}

.report-section.page-break-before,
.figure-block.page-break-before { break-before: page; }

.section-title {
  margin: 0 0 0.85rem;
  padding-bottom: 0.38rem;
  border-bottom: 1px solid var(--report-line);
  color: var(--report-navy);
  font-size: 1.5rem;
  line-height: 1.2;
}

.report-subsection {
  margin: 1.35rem 0 1.15rem 1rem;
  break-inside: avoid-page;
}

.subsection-title {
  margin: 0 0 0.6rem;
  color: var(--report-navy);
  font-size: 1.18rem;
  line-height: 1.25;
}

.report-paragraph {
  margin: 0.65rem 0;
  text-align: justify;
  white-space: pre-line;
}

.citation-marker {
  margin-left: 0.18rem;
  font-size: 0.72em;
  line-height: 0;
}

.citation-marker a { color: var(--report-blue); text-decoration: none; }

.reference-list {
  margin: 0.7rem 0 0;
  padding-left: 1.45rem;
  font-size: 0.84rem;
  line-height: 1.38;
}

.reference-list li { margin: 0.48rem 0; overflow-wrap: anywhere; }
.reference-list a { color: var(--report-blue); }

.callout {
  margin: 0.85rem 0;
  padding: 0.72rem 0.85rem;
  border-left: 3px solid var(--report-teal);
  background: var(--report-wash);
  break-inside: avoid-page;
}

.callout-title {
  color: var(--report-navy);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.73rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.callout-text { margin-left: 0.4rem; white-space: pre-line; }

.table-block {
  margin: 1.2rem 0 1.5rem;
  overflow-x: auto;
}

.three-line-table {
  width: 100%;
  border-collapse: collapse;
  border-top: 1.5px solid var(--report-ink);
  border-bottom: 1.5px solid var(--report-ink);
  font-size: 0.9rem;
  line-height: 1.32;
}

.three-line-table caption {
  margin-bottom: 0.45rem;
  color: var(--report-ink);
  font-weight: 700;
  text-align: left;
}

.three-line-table thead { display: table-header-group; }
.three-line-table thead tr { border-bottom: 0.8px solid var(--report-ink); }
.three-line-table tr { break-inside: avoid-page; }

.three-line-table th,
.three-line-table td {
  padding: 0.42rem 0.38rem;
  border: 0;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}

.three-line-table th {
  color: var(--report-navy);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.82em;
  font-weight: 700;
  letter-spacing: 0.015em;
}

.three-line-table.table-dense { font-size: 0.78rem; }
.three-line-table.table-wide { font-size: 0.7rem; }

.figure-block {
  margin: 1.35rem 0 1.7rem;
  break-inside: avoid-page;
}

.figure-panels {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1rem;
  align-items: start;
}

.figure-panels.side-by-side {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.figure-panel { margin: 0; min-width: 0; text-align: center; }

.figure-panel img {
  display: block;
  width: 100%;
  max-height: 112mm;
  margin: 0 auto;
  object-fit: contain;
}

.figure-panels.side-by-side .figure-panel img { max-height: 72mm; }

.panel-title {
  margin-top: 0.35rem;
  color: var(--report-muted);
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.75rem;
}

.figure-caption {
  margin: 0.65rem 0 0;
  font-size: 0.9rem;
  line-height: 1.35;
}

.figure-caption strong { color: var(--report-navy); }

@page {
  size: A4;
  margin: 17mm 18mm 18mm;
  @top-left {
    content: "MRCAT scientific report";
    color: #617384;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 8pt;
  }
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    color: #617384;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 8pt;
  }
}

@media print {
  html, body { background: #ffffff; }
  .report {
    width: auto;
    margin: 0;
    padding: 0;
    box-shadow: none;
  }
  .report-cover { min-height: 245mm; }
  .table-block { overflow: visible; }
}

@media (max-width: 760px) {
  .report { width: 100%; margin: 0; padding: 28px 20px; box-shadow: none; }
  .report-cover { min-height: auto; padding-bottom: 48px; }
  .report-title { font-size: 1.8rem; }
  .figure-panels.side-by-side { grid-template-columns: minmax(0, 1fr); }
}
""".strip()


def collect_report_figures(
    task: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    """Collect model-safe figure metadata and renderer-only local paths."""

    plan = task.get("plan") if isinstance(task.get("plan"), dict) else {}
    skill_by_step: dict[str, str] = {}
    for item in list(plan.get("items") or []):
        if isinstance(item, dict):
            step_id = str(item.get("item_id") or item.get("id") or "").strip()
            skill_id = str(item.get("skill_id") or "").strip()
        else:
            step_id = str(
                getattr(item, "item_id", "") or getattr(item, "id", "")
            ).strip()
            skill_id = str(getattr(item, "skill_id", "") or "").strip()
        if step_id:
            skill_by_step[step_id] = skill_id
    catalog: list[dict[str, Any]] = []
    assets: dict[str, Path] = {}
    seen_paths: set[str] = set()

    for step_id, skill_id, milestone_name, payload in _figure_payloads(
        task,
        skill_by_step=skill_by_step,
    ):
        manifest = (
            payload.get("plot_manifest")
            if isinstance(payload.get("plot_manifest"), dict)
            else {}
        )
        for index, raw_plot in enumerate(list(manifest.get("plots") or []), start=1):
            if not isinstance(raw_plot, dict):
                continue
            raw_path = str(raw_plot.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser().resolve()
            if (
                not path.is_file()
                or path.suffix.lower() not in _FIGURE_SUFFIXES
                or str(path) in seen_paths
            ):
                continue
            plot_id = _identifier(
                raw_plot.get("plot_id") or path.stem or f"plot_{index}"
            )
            base_id = _identifier(f"{step_id}_{plot_id}")
            figure_id = _unique_identifier(base_id, assets)
            width_px, height_px = _image_dimensions(path)
            explanation = _read_explanation(raw_plot.get("explanation_path"))
            title = str(raw_plot.get("title") or "").strip()
            if not title:
                title = path.stem.replace("_", " ").strip().title()
            catalog.append(
                {
                    "figure_id": figure_id,
                    "plot_id": str(raw_plot.get("plot_id") or path.stem).strip(),
                    "title": title,
                    "source_step_id": step_id,
                    "source_skill_id": skill_id,
                    "source_milestone": milestone_name,
                    "width_px": width_px,
                    "height_px": height_px,
                    "aspect_ratio": (
                        round(width_px / height_px, 3)
                        if width_px and height_px
                        else None
                    ),
                    "reading_guide": explanation or None,
                }
            )
            assets[figure_id] = path
            seen_paths.add(str(path))
    return catalog, assets


def report_spec_example(
    figure_ids: Iterable[str],
    *,
    reference_ids: Iterable[str] = (),
) -> dict[str, Any]:
    available = [str(value) for value in figure_ids if str(value).strip()]
    available_references = [
        str(value) for value in reference_ids if str(value).strip()
    ]
    figure_blocks: list[dict[str, Any]] = []
    for start in range(0, len(available), 2):
        group = available[start : start + 2]
        figure_blocks.append(
            {
                "type": "figure",
                "figure_ids": group,
                "layout": "side_by_side" if len(group) == 2 else "full_width",
                "caption": "Case-specific caption grounded in the supplied evidence.",
                "interpretation": (
                    "Case-specific interpretation that explains what the displayed "
                    "results contribute to the current scientific question."
                ),
                "page_break_before": False,
            }
        )
    discussion_blocks: list[dict[str, Any]] = [
        {
            "type": "paragraph",
            "text": "Interpret the supplied estimates and limitations using only the current analysis evidence.",
        },
        {
            "type": "subsection",
            "heading": "Literature evidence and comparison",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "Compare this analysis with the verified published evidence, state the support boundary, and explain direct-comparability limits.",
                    **(
                        {"citation_ids": available_references}
                        if available_references
                        else {}
                    ),
                }
            ],
        },
    ]
    return {
        "title": "Mendelian randomization analysis of exposure and outcome",
        "subtitle": "Evidence-grounded scientific report",
        "abstract": "Structured abstract grounded only in supplied evidence.",
        "sections": [
            {
                "heading": "Background and objective",
                "page_break_before": False,
                "blocks": [
                    {
                        "type": "paragraph",
                        "text": "Scientific background, rationale, and objective.",
                    }
                ],
            },
            {
                "heading": "Results",
                "page_break_before": False,
                "blocks": [
                    {
                        "type": "table",
                        "title": "Main MR estimates",
                        "columns": ["Method", "Estimate", "Uncertainty", "P value"],
                        "rows": [
                            [
                                "Method name",
                                "Evidence value",
                                "Evidence value",
                                "Evidence value",
                            ]
                        ],
                    },
                    *figure_blocks,
                ],
            },
            {
                "heading": "Discussion",
                "page_break_before": False,
                "blocks": discussion_blocks,
            },
        ],
    }


def validate_report_spec(
    payload: dict[str, Any],
    *,
    available_figure_ids: Iterable[str],
    available_reference_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Validate and normalize the LLM-owned semantic report plan."""

    if not isinstance(payload, dict):
        raise ValueError("scientific report response must be an object")
    _reject_extra(
        payload,
        {"title", "subtitle", "abstract", "sections"},
        "report",
    )
    title = _required_text(payload.get("title"), "report.title", 500)
    subtitle = _optional_text(payload.get("subtitle"), "report.subtitle", 500)
    abstract = _required_text(payload.get("abstract"), "report.abstract", 6000)
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError("report.sections must be a non-empty list")
    if len(raw_sections) > 30:
        raise ValueError("report.sections exceeds 30 sections")

    allowed_figures = {
        str(value).strip() for value in available_figure_ids if str(value).strip()
    }
    used_figures: set[str] = set()
    allowed_references = {
        str(value).strip()
        for value in available_reference_ids
        if str(value).strip()
    }
    sections: list[dict[str, Any]] = []
    for section_index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict):
            raise ValueError(f"report.sections[{section_index}] must be an object")
        _reject_extra(
            raw_section,
            {"heading", "page_break_before", "blocks"},
            f"report.sections[{section_index}]",
        )
        heading = _required_text(
            raw_section.get("heading"),
            f"report.sections[{section_index}].heading",
            300,
        )
        raw_blocks = raw_section.get("blocks")
        if not isinstance(raw_blocks, list) or not raw_blocks:
            raise ValueError(
                f"report.sections[{section_index}].blocks must be a non-empty list"
            )
        blocks = [
            _normalize_block(
                raw_block,
                section_index=section_index,
                block_index=block_index,
                allowed_figures=allowed_figures,
                allowed_references=allowed_references,
                used_figures=used_figures,
            )
            for block_index, raw_block in enumerate(raw_blocks)
        ]
        sections.append(
            {
                "heading": heading,
                "page_break_before": bool(raw_section.get("page_break_before")),
                "blocks": blocks,
            }
        )

    return {
        "title": title,
        "subtitle": subtitle,
        "abstract": abstract,
        "sections": sections,
    }


def render_scientific_report_html(
    spec: dict[str, Any],
    *,
    figure_assets: dict[str, Path],
    figure_titles: dict[str, str] | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Render a validated report spec into one self-contained HTML document."""

    generated = generated_at or datetime.now(UTC)
    titles = figure_titles or {}
    references = [
        item for item in list(spec.get("references") or []) if isinstance(item, dict)
    ]
    reference_numbers = {
        str(item.get("reference_id") or "").strip(): index
        for index, item in enumerate(references, start=1)
        if str(item.get("reference_id") or "").strip()
    }
    body: list[str] = ["<article class=\"report\">", "<header class=\"report-cover\">"]
    body.append(f"<h1 class=\"report-title\">{_html_escape(spec['title'])}</h1>")
    if spec.get("subtitle"):
        body.append(
            f"<p class=\"report-subtitle\">{_html_escape(spec['subtitle'])}</p>"
        )
    status = (
        "Evidence-grounded scientific report; "
        f"generated {generated.strftime('%Y-%m-%d %H:%M UTC')}"
    )
    body.extend(
        [
            f"<div class=\"report-status\">{_render_html_callout('Report status', status)}</div>",
            '<div class="abstract-block">',
            _render_html_callout("Abstract", spec["abstract"]),
            "</div>",
            "<p class=\"report-brand\">Generated by MRCAT</p>",
            "</header>",
        ]
    )

    figure_number = 0
    table_number = 0
    for section_index, section in enumerate(spec["sections"]):
        section_classes = ["report-section"]
        if section.get("page_break_before") and section_index > 0:
            section_classes.append("page-break-before")
        body.extend(
            [
                f"<section class=\"{' '.join(section_classes)}\">",
                f"<h2 class=\"section-title\">{_html_escape(section['heading'])}</h2>",
            ]
        )
        for block in section["blocks"]:
            block_type = block["type"]
            citations_html = _render_html_citations(
                block.get("citation_ids"),
                reference_numbers=reference_numbers,
            )
            if block_type == "paragraph":
                body.append(
                    f"<p class=\"report-paragraph\">{_html_escape(block['text'])}"
                    f"{citations_html}</p>"
                )
            elif block_type == "callout":
                body.append(
                    _render_html_callout(
                        block["title"],
                        block["text"],
                        citations_html=citations_html,
                    )
                )
            elif block_type == "subsection":
                body.append(
                    _render_html_subsection(
                        block,
                        reference_numbers=reference_numbers,
                    )
                )
            elif block_type == "table":
                table_number += 1
                body.append(
                    _render_html_three_line_table(
                        table_number=table_number,
                        title=block.get("title") or f"Table {table_number}",
                        columns=block["columns"],
                        rows=block["rows"],
                        citations_html=citations_html,
                    )
                )
            elif block_type == "figure":
                figure_number += 1
                body.append(
                    _render_html_figure_block(
                        block,
                        figure_number=figure_number,
                        figure_assets=figure_assets,
                        figure_titles=titles,
                        reference_numbers=reference_numbers,
                    )
                )
        body.append("</section>")
    if references:
        body.extend(_render_html_references(references))
    body.append("</article>")

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_html_escape(spec['title'])}</title>",
            f"<style>\n{_REPORT_HTML_CSS}\n</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
            "",
        ]
    )


def render_scientific_report_markdown(spec: dict[str, Any]) -> str:
    """Render the canonical report spec into the final Markdown artifact."""

    lines = [f"# {spec['title']}"]
    if spec.get("subtitle"):
        lines.extend(["", f"*{spec['subtitle']}*"])
    lines.extend(["", "## Abstract", "", str(spec["abstract"])])
    references = [
        item for item in list(spec.get("references") or []) if isinstance(item, dict)
    ]
    reference_numbers = {
        str(item.get("reference_id") or "").strip(): index
        for index, item in enumerate(references, start=1)
        if str(item.get("reference_id") or "").strip()
    }
    figure_number = 0
    for section in spec["sections"]:
        lines.extend(["", f"## {section['heading']}", ""])
        for block in section["blocks"]:
            block_type = block["type"]
            citations = _render_markdown_citations(
                block.get("citation_ids"),
                reference_numbers=reference_numbers,
            )
            if block_type == "paragraph":
                lines.extend([str(block["text"]) + citations, ""])
            elif block_type == "callout":
                lines.extend(
                    [f"**{block['title']}.** {block['text']}{citations}", ""]
                )
            elif block_type == "subsection":
                lines.extend([f"### {block['heading']}", ""])
                for child in block["blocks"]:
                    child_citations = _render_markdown_citations(
                        child.get("citation_ids"),
                        reference_numbers=reference_numbers,
                    )
                    if child["type"] == "paragraph":
                        lines.extend([str(child["text"]) + child_citations, ""])
                    else:
                        lines.extend(
                            [
                                f"**{child['title']}.** "
                                f"{child['text']}{child_citations}",
                                "",
                            ]
                        )
            elif block_type == "table":
                if block.get("title"):
                    lines.extend([f"**{block['title']}**{citations}", ""])
                columns = [str(value) for value in block["columns"]]
                lines.append("| " + " | ".join(columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in block["rows"]:
                    lines.append(
                        "| "
                        + " | ".join(
                            _markdown_table_cell(value) for value in row
                        )
                        + " |"
                    )
                lines.append("")
            elif block_type == "figure":
                figure_number += 1
                lines.extend(
                    [
                        f"**Figure {figure_number}.** {block['caption']}{citations}",
                        "",
                        f"**Interpretation.** {block['interpretation']}",
                        "",
                    ]
                )
    if references:
        lines.extend(["", "## References", ""])
        for index, reference in enumerate(references, start=1):
            lines.append(f"{index}. {_reference_text(reference, markdown=True)}")
    return "\n".join(lines).strip() + "\n"


def _render_html_three_line_table(
    *,
    table_number: int,
    title: str,
    columns: list[Any],
    rows: list[list[Any]],
    citations_html: str = "",
) -> str:
    """Render a scientific table with top, header, and bottom rules only."""

    widths = _table_column_fractions(columns, rows)
    count = len(columns)
    dense = len(rows) >= 12 or sum(
        len(str(value)) for row in rows for value in row
    ) >= 4000
    table_classes = ["three-line-table"]
    if dense or count >= 5:
        table_classes.append("table-dense")
    if count >= 8:
        table_classes.append("table-wide")
    columns_html = "".join(
        f'<col style="width:{width * 100:.2f}%">' for width in widths
    )
    header_html = "".join(
        f"<th>{_html_escape(value)}</th>" for value in columns
    )
    row_html = "".join(
        "<tr>"
        + "".join(f"<td>{_html_escape(value)}</td>" for value in row)
        + "</tr>"
        for row in rows
    )
    return "\n".join(
        [
            '<div class="table-block">',
            f'<table class="{" ".join(table_classes)}">',
            f"<caption>Table {table_number}. {_html_escape(title)}{citations_html}</caption>",
            f"<colgroup>{columns_html}</colgroup>",
            f"<thead><tr>{header_html}</tr></thead>",
            f"<tbody>{row_html}</tbody>",
            "</table>",
            "</div>",
        ]
    )


def _table_column_fractions(
    columns: list[Any], rows: list[list[Any]]
) -> list[float]:
    weights: list[float] = []
    for index, header in enumerate(columns):
        lengths = [len(str(header)) * 1.4]
        lengths.extend(len(str(row[index])) for row in rows if index < len(row))
        weights.append(math.sqrt(max(6.0, min(42.0, max(lengths, default=6.0)))))
    usable = max(0.84, 0.965 - 0.012 * max(0, len(columns) - 1))
    total = sum(weights) or 1.0
    return [usable * weight / total for weight in weights]


def _render_html_figure_block(
    block: dict[str, Any],
    *,
    figure_number: int,
    figure_assets: dict[str, Path],
    figure_titles: dict[str, str],
    reference_numbers: dict[str, int],
) -> str:
    figure_ids = block["figure_ids"]
    panels: list[str] = []
    for index, figure_id in enumerate(figure_ids):
        path = figure_assets.get(figure_id)
        if path is None or not path.is_file():
            raise FileNotFoundError(f"report figure is unavailable: {figure_id}")
        label = chr(65 + index) if len(figure_ids) > 1 and index < 26 else ""
        title = str(figure_titles.get(figure_id) or figure_id).strip()
        panel_title = f"{label} · {title}" if label else title
        panels.append(
            "\n".join(
                [
                    '<div class="figure-panel">',
                    (
                        f'<img src="{_image_data_uri(path)}" '
                        f'alt="{_html_escape(panel_title)}">'
                    ),
                    f'<div class="panel-title">{_html_escape(panel_title)}</div>',
                    "</div>",
                ]
            )
        )
    classes = ["figure-block"]
    if block.get("page_break_before"):
        classes.append("page-break-before")
    panel_class = (
        "figure-panels side-by-side"
        if block["layout"] == "side_by_side"
        else "figure-panels"
    )
    citations_html = _render_html_citations(
        block.get("citation_ids"),
        reference_numbers=reference_numbers,
    )
    return "\n".join(
        [
            f'<figure class="{" ".join(classes)}">',
            f'<div class="{panel_class}">',
            *panels,
            "</div>",
            (
                f'<figcaption class="figure-caption"><strong>Figure '
                f"{figure_number}.</strong> {_html_escape(block['caption'])}"
                f"{citations_html}</figcaption>"
            ),
            "</figure>",
            _render_html_callout("Interpretation", block["interpretation"]),
        ]
    )


def _render_html_callout(
    title: Any,
    text: Any,
    *,
    citations_html: str = "",
) -> str:
    return "\n".join(
        [
            '<aside class="callout">',
            f'<span class="callout-title">{_html_escape(title)}</span>',
            f'<span class="callout-text">{_html_escape(text)}{citations_html}</span>',
            "</aside>",
        ]
    )


def _render_html_subsection(
    block: dict[str, Any],
    *,
    reference_numbers: dict[str, int],
) -> str:
    body = [
        '<div class="report-subsection">',
        f'<h3 class="subsection-title">{_html_escape(block["heading"])}</h3>',
    ]
    for child in block["blocks"]:
        citations_html = _render_html_citations(
            child.get("citation_ids"),
            reference_numbers=reference_numbers,
        )
        if child["type"] == "paragraph":
            body.append(
                f'<p class="report-paragraph">{_html_escape(child["text"])}'
                f"{citations_html}</p>"
            )
        else:
            body.append(
                _render_html_callout(
                    child["title"],
                    child["text"],
                    citations_html=citations_html,
                )
            )
    body.append("</div>")
    return "\n".join(body)


def _render_html_citations(
    citation_ids: Any,
    *,
    reference_numbers: dict[str, int],
) -> str:
    numbers = [
        reference_numbers[clean_reference_id]
        for raw_reference_id in list(citation_ids or [])
        if (clean_reference_id := str(raw_reference_id or "").strip())
        in reference_numbers
    ]
    if not numbers:
        return ""
    links = ",".join(
        f'<a href="#ref-{number}" aria-label="Reference {number}">{number}</a>'
        for number in numbers
    )
    return f'<sup class="citation-marker">[{links}]</sup>'


def _render_markdown_citations(
    citation_ids: Any,
    *,
    reference_numbers: dict[str, int],
) -> str:
    numbers = [
        reference_numbers[clean_reference_id]
        for raw_reference_id in list(citation_ids or [])
        if (clean_reference_id := str(raw_reference_id or "").strip())
        in reference_numbers
    ]
    return " [" + ",".join(str(value) for value in numbers) + "]" if numbers else ""


def _render_html_references(references: list[dict[str, Any]]) -> list[str]:
    items = []
    for index, reference in enumerate(references, start=1):
        items.append(
            f'<li id="ref-{index}">{_reference_text(reference, markdown=False)}</li>'
        )
    return [
        '<section class="report-section references-section">',
        '<h2 class="section-title">References</h2>',
        '<ol class="reference-list">',
        *items,
        "</ol>",
        "</section>",
    ]


def _reference_text(reference: dict[str, Any], *, markdown: bool) -> str:
    authors = _reference_authors(reference.get("authors"))
    year = str(reference.get("year") or "").strip()
    title = str(reference.get("title") or "").strip()
    journal = str(reference.get("journal") or "").strip()
    doi = str(reference.get("doi") or "").strip()
    url = str(reference.get("url") or "").strip()
    parts = [
        value
        for value in (authors, f"({year})" if year else "", title, journal)
        if value
    ]
    text = ". ".join(parts).rstrip(".") + "."
    if markdown and doi:
        doi_url = f"https://doi.org/{doi}"
        return text + f" [doi:{doi}]({doi_url})"
    if markdown and url:
        return text + f" [PubMed]({url})"
    if markdown:
        return text

    html_text = _html_escape(text)
    if doi:
        doi_url = f"https://doi.org/{doi}"
        return (
            html_text
            + f' <a href="{_html_escape(doi_url)}" rel="noreferrer">'
            + f"doi:{_html_escape(doi)}</a>"
        )
    if url:
        return (
            html_text
            + f' <a href="{_html_escape(url)}" rel="noreferrer">PubMed</a>'
        )
    return html_text


def _reference_authors(value: Any) -> str:
    authors = []
    for raw in list(value or []):
        if not isinstance(raw, dict):
            continue
        display = str(raw.get("display") or raw.get("collective") or "").strip()
        if display:
            authors.append(display)
    if len(authors) > 6:
        return "; ".join(authors[:6]) + "; et al"
    return "; ".join(authors)


def _image_data_uri(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in {"image/png", "image/jpeg"}:
        raise ValueError(f"unsupported report image type: {path.suffix}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _figure_payloads(
    task: dict[str, Any],
    *,
    skill_by_step: dict[str, str],
) -> Iterable[tuple[str, str, str, dict[str, Any]]]:
    outputs = (
        task.get("step_outputs") if isinstance(task.get("step_outputs"), dict) else {}
    )
    for step_id, step_outputs in outputs.items():
        if not isinstance(step_outputs, dict):
            continue
        clean_step_id = str(step_id).strip() or "step"
        for milestone_name, payload in step_outputs.items():
            if isinstance(payload, dict):
                yield (
                    clean_step_id,
                    skill_by_step.get(clean_step_id, ""),
                    str(milestone_name),
                    payload,
                )

    milestones = (
        task.get("milestones") if isinstance(task.get("milestones"), dict) else {}
    )
    for milestone_name, record in milestones.items():
        if not isinstance(record, dict):
            continue
        payload = (
            record.get("payload") if isinstance(record.get("payload"), dict) else {}
        )
        if not payload:
            continue
        produced_by = str(record.get("produced_by") or "").strip()
        step_id = str(
            record.get("plan_item_id") or produced_by or milestone_name
        ).strip()
        yield (
            step_id,
            skill_by_step.get(step_id, produced_by),
            str(milestone_name),
            payload,
        )


def _normalize_block(
    raw_block: Any,
    *,
    section_index: int,
    block_index: int,
    allowed_figures: set[str],
    allowed_references: set[str],
    used_figures: set[str],
) -> dict[str, Any]:
    path = f"report.sections[{section_index}].blocks[{block_index}]"
    if not isinstance(raw_block, dict):
        raise ValueError(f"{path} must be an object")
    block_type = str(raw_block.get("type") or "").strip()
    if block_type not in _BLOCK_TYPES:
        raise ValueError(f"{path}.type is invalid")
    if block_type == "paragraph":
        _reject_extra(raw_block, {"type", "text", "citation_ids"}, path)
        block = {
            "type": block_type,
            "text": _required_text(raw_block.get("text"), f"{path}.text", 12000),
        }
        return _with_citations(
            block,
            raw_block.get("citation_ids"),
            allowed_references=allowed_references,
            path=path,
        )
    if block_type == "callout":
        _reject_extra(raw_block, {"type", "title", "text", "citation_ids"}, path)
        block = {
            "type": block_type,
            "title": _required_text(raw_block.get("title"), f"{path}.title", 300),
            "text": _required_text(raw_block.get("text"), f"{path}.text", 6000),
        }
        return _with_citations(
            block,
            raw_block.get("citation_ids"),
            allowed_references=allowed_references,
            path=path,
        )
    if block_type == "subsection":
        _reject_extra(raw_block, {"type", "heading", "blocks"}, path)
        heading = _required_text(raw_block.get("heading"), f"{path}.heading", 300)
        raw_children = raw_block.get("blocks")
        if not isinstance(raw_children, list) or not raw_children:
            raise ValueError(f"{path}.blocks must be a non-empty list")
        children: list[dict[str, Any]] = []
        for child_index, raw_child in enumerate(raw_children):
            child_path = f"{path}.blocks[{child_index}]"
            if not isinstance(raw_child, dict):
                raise ValueError(f"{child_path} must be an object")
            child_type = str(raw_child.get("type") or "").strip()
            if child_type == "paragraph":
                _reject_extra(
                    raw_child,
                    {"type", "text", "citation_ids"},
                    child_path,
                )
                child = {
                    "type": "paragraph",
                    "text": _required_text(
                        raw_child.get("text"), f"{child_path}.text", 12000
                    ),
                }
            elif child_type == "callout":
                _reject_extra(
                    raw_child,
                    {"type", "title", "text", "citation_ids"},
                    child_path,
                )
                child = {
                    "type": "callout",
                    "title": _required_text(
                        raw_child.get("title"), f"{child_path}.title", 300
                    ),
                    "text": _required_text(
                        raw_child.get("text"), f"{child_path}.text", 6000
                    ),
                }
            else:
                raise ValueError(
                    f"{child_path}.type must be paragraph or callout"
                )
            children.append(
                _with_citations(
                    child,
                    raw_child.get("citation_ids"),
                    allowed_references=allowed_references,
                    path=child_path,
                )
            )
        return {"type": block_type, "heading": heading, "blocks": children}
    if block_type == "table":
        _reject_extra(
            raw_block,
            {"type", "title", "columns", "rows", "citation_ids"},
            path,
        )
        columns = raw_block.get("columns")
        rows = raw_block.get("rows")
        if not isinstance(columns, list) or not 2 <= len(columns) <= 10:
            raise ValueError(f"{path}.columns must contain 2-10 labels")
        clean_columns = [
            _required_text(value, f"{path}.columns[{index}]", 200)
            for index, value in enumerate(columns)
        ]
        if not isinstance(rows, list) or not rows or len(rows) > 500:
            raise ValueError(f"{path}.rows must contain 1-500 rows")
        clean_rows: list[list[str]] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(clean_columns):
                raise ValueError(
                    f"{path}.rows[{row_index}] must match the column count"
                )
            clean_rows.append(
                [
                    _optional_text(
                        value, f"{path}.rows[{row_index}][{column_index}]", 1000
                    )
                    for column_index, value in enumerate(row)
                ]
            )
        block = {
            "type": block_type,
            "title": _optional_text(raw_block.get("title"), f"{path}.title", 300),
            "columns": clean_columns,
            "rows": clean_rows,
        }
        return _with_citations(
            block,
            raw_block.get("citation_ids"),
            allowed_references=allowed_references,
            path=path,
        )

    _reject_extra(
        raw_block,
        {
            "type",
            "figure_ids",
            "layout",
            "caption",
            "interpretation",
            "page_break_before",
            "citation_ids",
        },
        path,
    )
    raw_ids = raw_block.get("figure_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError(f"{path}.figure_ids must be non-empty")
    figure_ids: list[str] = []
    for figure_index, value in enumerate(raw_ids):
        figure_id = _required_text(value, f"{path}.figure_ids[{figure_index}]", 200)
        if figure_id not in allowed_figures:
            raise ValueError(f"{path} references unknown figure_id: {figure_id}")
        if figure_id in used_figures:
            raise ValueError(f"figure_id may be placed only once: {figure_id}")
        used_figures.add(figure_id)
        figure_ids.append(figure_id)
    layout = str(raw_block.get("layout") or "").strip()
    if layout not in _FIGURE_LAYOUTS:
        raise ValueError(f"{path}.layout must be full_width or side_by_side")
    if layout == "side_by_side" and len(figure_ids) != 2:
        raise ValueError(f"{path}.side_by_side requires exactly two figures")
    if layout == "full_width" and len(figure_ids) != 1:
        raise ValueError(f"{path}.full_width requires exactly one figure")
    block = {
        "type": block_type,
        "figure_ids": figure_ids,
        "layout": layout,
        "caption": _required_text(raw_block.get("caption"), f"{path}.caption", 5000),
        "interpretation": _required_text(
            raw_block.get("interpretation"),
            f"{path}.interpretation",
            6000,
        ),
        "page_break_before": bool(raw_block.get("page_break_before")),
    }
    return _with_citations(
        block,
        raw_block.get("citation_ids"),
        allowed_references=allowed_references,
        path=path,
    )


def _with_citations(
    block: dict[str, Any],
    raw_citation_ids: Any,
    *,
    allowed_references: set[str],
    path: str,
) -> dict[str, Any]:
    if raw_citation_ids is None:
        return block
    if not isinstance(raw_citation_ids, list):
        raise ValueError(f"{path}.citation_ids must be a list")
    citation_ids: list[str] = []
    for index, value in enumerate(raw_citation_ids):
        reference_id = _required_text(
            value,
            f"{path}.citation_ids[{index}]",
            200,
        )
        if reference_id not in allowed_references:
            raise ValueError(
                f"{path}.citation_ids references unverified literature: {reference_id}"
            )
        if reference_id not in citation_ids:
            citation_ids.append(reference_id)
    if citation_ids:
        block["citation_ids"] = citation_ids
    return block


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return int(width), int(height)
    except Exception:
        return None, None


def _read_explanation(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return ""
    if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:8000].strip()
    except OSError:
        return ""


def _identifier(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text.strip("_.-") or "figure"


def _unique_identifier(base: str, existing: dict[str, Any]) -> str:
    if base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


def _required_text(value: Any, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return text


def _optional_text(value: Any, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return text


def _reject_extra(payload: dict[str, Any], allowed: set[str], path: str) -> None:
    extra = sorted(set(payload).difference(allowed))
    if extra:
        raise ValueError(f"{path} contains unexpected fields: {extra}")


def _html_escape(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return html_lib.escape(text, quote=True)


def _markdown_table_cell(value: Any) -> str:
    return (
        str(value or "")
        .replace("|", r"\|")
        .replace("\r\n", "<br>")
        .replace("\r", "<br>")
        .replace("\n", "<br>")
    )
