import subprocess
import unittest
from unittest.mock import patch

from mrcat.report.metadata import build_reporting_metadata
from mrcat.report.policy import _ensure_reporting_declarations
from mrcat.report.scientific import (
    render_scientific_report_html,
    render_scientific_report_markdown,
    report_spec_example,
)


class ReportMetadataTests(unittest.TestCase):
    def collect(self, result):
        with patch.dict("os.environ", {"RSCRIPT_BIN": "/test/Rscript"}), patch(
            "mrcat.report.metadata.subprocess.run",
            side_effect=result if isinstance(result, Exception) else None,
            return_value=result,
        ):
            return build_reporting_metadata()

    def test_timeout_preserves_complete_versions_in_rendered_report(self):
        for stdout in (
            b"4.5.3\nTwoSampleMR\t0.7.6\nMRPRESSO\t1.",
            "4.5.3\nTwoSampleMR\t0.7.6\nMRPRESSO\t1.",
        ):
            with self.subTest(stdout=stdout):
                metadata = self.collect(subprocess.TimeoutExpired("Rscript", 10, output=stdout))
                self.assertEqual(metadata["software"]["r_version"], "4.5.3")
                self.assertEqual(metadata["software"]["r_packages"], {"TwoSampleMR": "0.7.6"})
                spec = _ensure_reporting_declarations(report_spec_example([]), metadata)
                for rendered in (
                    render_scientific_report_html(spec, figure_assets={}),
                    render_scientific_report_markdown(spec),
                ):
                    self.assertIn("R 4.5.3", rendered)
                    self.assertIn("TwoSampleMR 0.7.6", rendered)

    def test_nonzero_exit_preserves_versions_already_emitted(self):
        result = subprocess.CompletedProcess([], 1, stdout="4.4.1\nMRPRESSO\t1.0\n")
        software = self.collect(result)["software"]
        self.assertEqual(software["r_version"], "4.4.1")
        self.assertEqual(software["r_packages"], {"MRPRESSO": "1.0"})

    def test_no_output_or_missing_r_remains_unavailable(self):
        for error in (subprocess.TimeoutExpired("Rscript", 10), FileNotFoundError()):
            with self.subTest(error=error):
                software = self.collect(error)["software"]
                self.assertEqual(software["r_version"], "")
                self.assertEqual(software["r_packages"], {})

    def test_later_report_retries_after_timeout(self):
        self.collect(subprocess.TimeoutExpired("Rscript", 10))
        result = subprocess.CompletedProcess([], 0, stdout="4.5.3\nMRAPSS\t0.0.0.9000\n")
        software = self.collect(result)["software"]
        self.assertEqual(software["r_packages"], {"MRAPSS": "0.0.0.9000"})


if __name__ == "__main__":
    unittest.main()
