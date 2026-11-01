from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from mrcat.report.scientific import (
    collect_report_figures,
    render_scientific_report_html,
    render_scientific_report_markdown,
    report_spec_example,
    validate_report_spec,
)
from types import SimpleNamespace
from mrcat.report.agent import ReportAgent


class ScientificReportTests(unittest.TestCase):
    def _png(self, path: Path, *, size: tuple[int, int] = (900, 500)) -> None:
        Image.new("RGB", size, color=(238, 245, 247)).save(path)

    def test_collects_model_safe_metadata_and_keeps_paths_renderer_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plot_path = root / "forest.png"
            explanation_path = root / "forest.md"
            self._png(plot_path)
            explanation_path.write_text(
                "This guide explains how confidence intervals are encoded.",
                encoding="utf-8",
            )
            task = {
                "plan": {
                    "items": [
                        dict(
                            item_id="primary",
                            title="Primary MR",
                            skill_id="mr-primary",
                            completion_milestones=["mr_primary_result"],
                            status="done",
                        )
                    ]
                },
                "step_outputs": {
                    "primary": {
                        "mr_primary_result": {
                            "plot_manifest": {
                                "plots": [
                                    {
                                        "plot_id": "primary_forest",
                                        "path": str(plot_path),
                                        "title": "Primary MR estimates",
                                        "explanation_path": str(explanation_path),
                                    }
                                ]
                            }
                        }
                    }
                },
            }

            catalog, assets = collect_report_figures(task)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["source_skill_id"], "mr-primary")
        self.assertEqual(catalog[0]["width_px"], 900)
        self.assertNotIn("path", catalog[0])
        self.assertNotIn(str(plot_path), str(catalog[0]))
        self.assertIn("confidence intervals", catalog[0]["reading_guide"])
        self.assertEqual(assets[catalog[0]["figure_id"]], plot_path.resolve())

    def test_validator_allows_model_selected_figure_subset(self):
        spec = report_spec_example(["figure_a", "figure_b"])
        validated = validate_report_spec(
            spec,
            available_figure_ids=["figure_a", "figure_b"],
        )
        self.assertEqual(
            set(validated),
            {"title", "subtitle", "abstract", "sections"},
        )
        self.assertEqual(
            validated["sections"][1]["blocks"][1]["layout"],
            "side_by_side",
        )

        spec["sections"][1]["blocks"][1]["figure_ids"] = ["figure_a"]
        spec["sections"][1]["blocks"][1]["layout"] = "full_width"
        selected = validate_report_spec(
            spec,
            available_figure_ids=["figure_a", "figure_b"],
        )
        self.assertEqual(
            selected["sections"][1]["blocks"][1]["figure_ids"],
            ["figure_a"],
        )

        spec["sections"][1]["blocks"][1]["figure_ids"] = ["figure_unknown"]
        with self.assertRaisesRegex(ValueError, "unknown figure_id"):
            validate_report_spec(
                spec,
                available_figure_ids=["figure_a", "figure_b"],
            )

    def test_report_prompt_makes_layout_and_interpretation_model_owned(self):
        repo = Path(__file__).resolve().parents[1]
        prompt = ReportAgent(SimpleNamespace(root=repo, prompt=lambda role: ""), {}).build_structured_prompt(
            stage="report_writer",
            sections={
                "Original Analysis Evidence": {"mr_evidence": {"applies": True}},
                "Verified Literature Evidence": {},
                "Figure Catalog": [{"figure_id": "primary_forest"}],
                "Current Validated Draft": "None",
                "Review Feedback": "None",
            },
        )

        self.assertIn("position, order", prompt["system"])
        self.assertIn("major evidence roles", prompt["system"])
        self.assertIn(
            "include at least one representative plot",
            prompt["system"],
        )
        self.assertIn("do not include every sensitivity plot", prompt["system"])
        self.assertIn("generic guidance, not evidence", prompt["system"])
        self.assertIn("Omit redundant", prompt["system"])
        self.assertIn("may appear at most", prompt["system"])
        self.assertNotIn("Place every available", prompt["system"])
        self.assertIn("Figure Catalog", prompt["sections"])
        self.assertNotIn("all 20 checklist", prompt["system"])

    def test_report_judge_checks_substance_without_enforcing_presentation(self):
        repo = Path(__file__).resolve().parents[1]
        prompt = ReportAgent(SimpleNamespace(root=repo, prompt=lambda role: ""), {}).build_structured_prompt(
            stage="report_judge",
            sections={
                "Original Analysis Evidence": {"mr_evidence": {"applies": True}},
                "Verified Literature Evidence": {},
                "Figure Catalog": [{"figure_id": "sensitivity_leave_one_out"}],
                "Draft Report": {"title": "Example report"},
            },
        )

        self.assertIn("Missing essential content", prompt["system"])
        self.assertIn("Conclusions inconsistent with results", prompt["system"])
        self.assertIn("Unsupported causal claims", prompt["system"])
        self.assertIn("Do not request revisions for style", prompt["system"])
        self.assertIn("absent optional figures", prompt["system"])
        self.assertIn("Return exactly `decision` and `issues`", prompt["system"])
        self.assertIn("Figure Catalog", prompt["sections"])

    def test_verified_citations_render_from_deterministic_reference_metadata(self):
        spec = report_spec_example([], reference_ids=["PMID:123"])
        validated = validate_report_spec(
            spec,
            available_figure_ids=[],
            available_reference_ids=["PMID:123"],
        )
        validated["references"] = [
            {
                "reference_id": "PMID:123",
                "title": "Comparable <script>unsafe</script> MR evidence",
                "authors": [
                    {
                        "family": "Smith",
                        "given": "Jane",
                        "collective": "",
                        "display": "Smith, Jane",
                    }
                ],
                "journal": "Example Journal",
                "year": "2025",
                "doi": "10.1000/example",
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
            }
        ]

        markdown = render_scientific_report_markdown(validated)
        html = render_scientific_report_html(validated, figure_assets={})

        self.assertIn("[1]", markdown)
        self.assertIn("## References", markdown)
        self.assertIn('href="#ref-1"', html)
        self.assertIn('id="ref-1"', html)
        self.assertIn("doi:10.1000/example", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;unsafe&lt;/script&gt;", html)

    def test_validator_rejects_unverified_reference_id(self):
        spec = report_spec_example([])
        spec["sections"][0]["blocks"][0]["citation_ids"] = ["PMID:invented"]

        with self.assertRaisesRegex(ValueError, "unverified literature"):
            validate_report_spec(
                spec,
                available_figure_ids=[],
                available_reference_ids=["PMID:verified"],
            )

    def test_markdown_and_html_share_the_same_canonical_spec(self):
        spec = validate_report_spec(
            report_spec_example([]),
            available_figure_ids=[],
        )

        markdown = render_scientific_report_markdown(spec)
        html = render_scientific_report_html(spec, figure_assets={})

        self.assertIn(spec["title"], markdown)
        self.assertIn("Main MR estimates", markdown)
        self.assertIn("Main MR estimates", html)
        self.assertNotIn("STROBE-MR checklist", markdown)
        self.assertNotIn("STROBE-MR checklist", html)

    def test_renderer_outputs_standalone_html_with_three_line_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "first.png"
            second = root / "second.png"
            self._png(first, size=(1000, 600))
            self._png(second, size=(700, 700))
            spec = validate_report_spec(
                report_spec_example(["figure_a", "figure_b"]),
                available_figure_ids=["figure_a", "figure_b"],
            )

            html = render_scientific_report_html(
                spec,
                figure_assets={"figure_a": first, "figure_b": second},
                generated_at=datetime(2026, 8, 16, tzinfo=UTC),
            )

        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn('font-family: "Times New Roman"', html)
        self.assertIn('class="three-line-table', html)
        self.assertIn("border-top: 1.5px solid", html)
        self.assertIn("border-bottom: 1.5px solid", html)
        self.assertIn("border-bottom: 0.8px solid", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn('class="figure-panels side-by-side"', html)
        self.assertIn("width: min(960px, calc(100% - 40px))", html)
        self.assertIn("min-height: min(760px, calc(100vh - 48px))", html)
        self.assertIn(".report-cover { min-height: 245mm; }", html)
        self.assertIn('<div class="abstract-block">', html)
        self.assertIn('<span class="callout-title">Abstract</span>', html)
        self.assertIn(".abstract-block .callout { margin: 0; }", html)
        self.assertNotIn('class="abstract-label"', html)
        self.assertNotIn(str(first), html)
        self.assertNotIn(str(second), html)

    def test_html_renderer_escapes_model_authored_content(self):
        spec = report_spec_example([])
        spec["abstract"] = '<script>alert("unsafe")</script>'
        spec["sections"][0]["blocks"][0]["text"] = "A < B & C > D"
        validated = validate_report_spec(spec, available_figure_ids=[])

        html = render_scientific_report_html(validated, figure_assets={})

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("A &lt; B &amp; C &gt; D", html)


if __name__ == "__main__":
    unittest.main()
