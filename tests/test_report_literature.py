from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from unittest.mock import Mock
from pathlib import Path

from mrcat.report.literature import PubMedLiteratureClient
from mrcat.report.agent import ReportAgent
from mrcat.report.review import report_judgement_example
from mrcat.report.client import (
    _validate_literature_claims,
    _validate_literature_evaluations,
)
from types import SimpleNamespace
import json


_PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <ArticleTitle>Comparable Mendelian randomization evidence</ArticleTitle>
        <Abstract>
          <AbstractText Label="RESULTS">The Mendelian randomization estimate was directionally consistent.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Smith</LastName><ForeName>Jane A</ForeName><Initials>JA</Initials></Author>
          <Author><CollectiveName>MR Consortium</CollectiveName></Author>
        </AuthorList>
        <Journal>
          <JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue>
          <Title>Example Journal</Title>
        </Journal>
        <ELocationID EIdType="doi">10.1000/example</ELocationID>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="pubmed">12345678</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


class _ReporterClient:
    def __init__(self, *, verify_error: Exception | None = None) -> None:
        self.claim_prompt_role = ""
        self.verify_prompt_role = ""
        self.judge_prompt = ""
        self.verify_error = verify_error

    def extract_literature_claims(self, *, prompt):
        self.claim_prompt_role = prompt["stage"]
        return {
            "claims": [
                {
                    "claim_id": "LC1",
                    "claim": "The analysis evaluates BMI and coronary disease.",
                    "claim_type": "main_result",
                    "search_queries": [
                        '"body mass index" "coronary disease" Mendelian randomization'
                    ],
                }
            ]
        }

    def judge_scientific_report(self, *, prompt):
        self.judge_prompt = json.dumps(prompt["sections"])
        return deepcopy(report_judgement_example())

    def verify_literature_evidence(
        self,
        *,
        prompt,
        valid_claim_ids,
        background_claim_ids,
        valid_reference_ids,
    ):
        self.verify_prompt_role = prompt["stage"]
        if self.verify_error is not None:
            raise self.verify_error
        return {
            "evaluations": [
                {
                    "reference_id": valid_reference_ids[0],
                    "claim_ids": valid_claim_ids,
                    "support_grade": "partial_support",
                    "reasoning": "The abstract reports the same MR relationship.",
                    "citation_wording": "Prior MR evidence was directionally consistent.",
                    "evidence_basis": "abstract",
                }
            ]
        }


class _LiteratureClient:
    def __init__(self, records):
        self.records = records
        self.queries = []

    def search(self, query, *, max_results):
        self.queries.append((query, max_results))
        return list(self.records)


class ReportLiteratureTests(unittest.TestCase):
    def test_background_question_can_share_the_existing_claim_contract(self):
        claims = [
            {"claim_id": "LC1", "claim": "What motivates studying BMI and coronary disease?",
             "claim_type": "background", "search_queries": ["BMI coronary disease"]},
            {"claim_id": "LC2", "claim": "The primary result is inconclusive.",
             "claim_type": "null_result", "search_queries": ["BMI coronary disease Mendelian randomization"]},
            {"claim_id": "LC3", "claim": "Sensitivity methods disagree.",
             "claim_type": "sensitivity_result", "search_queries": ["BMI coronary disease sensitivity Mendelian randomization"]},
        ]
        self.assertEqual(_validate_literature_claims({"claims": claims}), {"claims": claims})
        claims[1]["claim_type"] = "background"
        with self.assertRaisesRegex(ValueError, "at most one background"):
            _validate_literature_claims({"claims": claims})

    def test_background_only_evidence_cannot_be_graded_as_result_support(self):
        evaluation = {
            "reference_id": "PMID:123", "claim_ids": ["LC1"],
            "support_grade": "background_support",
            "reasoning": "The abstract describes an observational relationship.",
            "citation_wording": "Previous observations motivated the research question.",
        }
        def validate():
            return _validate_literature_evaluations(
                {"evaluations": [evaluation]}, valid_claim_ids={"LC1", "LC2"},
                background_claim_ids={"LC1"}, valid_reference_ids={"PMID:123"},
            )
        self.assertEqual(validate()["evaluations"][0]["support_grade"], "background_support")
        for grade in ("strong_support", "partial_support", "contradictory_or_limiting"):
            evaluation["support_grade"] = grade
            with self.subTest(grade=grade):
                with self.assertRaisesRegex(ValueError, "background-only"):
                    validate()
        evaluation["claim_ids"] = ["LC2"]
        evaluation["support_grade"] = "partial_support"
        self.assertEqual(validate()["evaluations"][0]["support_grade"], "partial_support")

    def test_background_and_result_searches_share_collection_and_verification(self):
        repo = Path(__file__).resolve().parents[1]
        record = PubMedLiteratureClient(transport=lambda url: _PUBMED_XML).fetch(["12345678"])[0]
        background = {**record, "reference_id": "PMID:123", "pmid": "123"}
        claims = [
            {"claim_id": "LC1", "claim": "What prior evidence motivates this question?",
             "claim_type": "background", "search_queries": ["BMI coronary disease"]},
            {"claim_id": "LC2", "claim": "The MR result is inconclusive.",
             "claim_type": "null_result", "search_queries": ["BMI coronary disease Mendelian randomization"]},
        ]
        client = _ReporterClient()
        client.extract_literature_claims = Mock(return_value={"claims": claims})
        client.verify_literature_evidence = Mock(return_value={"evaluations": [
            {"reference_id": "PMID:123", "claim_ids": ["LC1"],
             "support_grade": "background_support", "reasoning": "Relevant prior observations.",
             "citation_wording": "Observations motivate the question."},
            {"reference_id": record["reference_id"], "claim_ids": ["LC2"],
             "support_grade": "partial_support", "reasoning": "Comparable MR study.",
             "citation_wording": "Earlier MR evidence addresses a similar question."},
        ]})
        search = Mock()
        search.search.side_effect = [[background], [record]]
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ReportAgent(SimpleNamespace(root=repo, prompt=lambda role: ""), {},
                                literature_client=search)
            agent.reporter_client = client
            evidence = agent.collect_literature_evidence(finalization_context={
                "task_contract": {"user_goal": "BMI and coronary disease"},
                "mr_evidence": {"applies": True},
            })
        self.assertEqual([call.args[0] for call in search.search.call_args_list],
                         [claim["search_queries"][0] for claim in claims])
        self.assertEqual(client.verify_literature_evidence.call_args.kwargs["background_claim_ids"], ["LC1"])
        self.assertIn("Literature Questions and Claims", client.verify_literature_evidence.call_args.kwargs["prompt"]["sections"])
        self.assertEqual(len(evidence["studies"]), 2)
        self.assertEqual(evidence["studies"][0]["support_grade"], "background_support")
        self.assertEqual(evidence["studies"][1]["support_grade"], "partial_support")

    def test_pubmed_client_uses_esearch_and_parses_structured_efetch_metadata(self):
        urls = []

        def transport(url: str) -> bytes:
            urls.append(url)
            if "esearch.fcgi" in url:
                return b'{"esearchresult":{"idlist":["12345678"]}}'
            return _PUBMED_XML

        records = PubMedLiteratureClient(transport=transport).search(
            '"body mass index" Mendelian randomization',
            max_results=3,
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["reference_id"], "PMID:12345678")
        self.assertEqual(record["doi"], "10.1000/example")
        self.assertEqual(record["year"], "2025")
        self.assertEqual(record["authors"][0]["display"], "Smith, Jane A")
        self.assertEqual(record["authors"][1]["display"], "MR Consortium")
        self.assertIn("directionally consistent", record["abstract"])
        self.assertIn("sort=relevance", urls[0])
        self.assertIn("efetch.fcgi", urls[1])

    def test_report_agent_builds_verified_literature_evidence_with_reporter_role(self):
        parsed_record = PubMedLiteratureClient(
            transport=lambda url: _PUBMED_XML
        ).fetch(["12345678"])[0]
        reporter_client = _ReporterClient()
        literature_client = _LiteratureClient([parsed_record])
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ReportAgent(SimpleNamespace(root=repo, prompt=lambda role: ""), {},
                                literature_client=literature_client)
            agent.reporter_client = reporter_client
            evidence = agent.collect_literature_evidence(
                finalization_context={
                    "task_contract": {"user_goal": "BMI to coronary disease"},
                    "mr_evidence": {"applies": True},
                }
            )
            agent.judge_scientific_report(
                finalization_context={
                    "mr_evidence": {"applies": True},
                    "literature_evidence": evidence,
                },
                figure_catalog=[],
                report_spec={"title": "Test report"},
            )

        self.assertEqual(evidence["status"], "completed")
        self.assertEqual(evidence["studies"][0]["support_grade"], "partial_support")
        self.assertEqual(evidence["studies"][0]["reference_id"], "PMID:12345678")
        self.assertEqual(reporter_client.claim_prompt_role, "literature_claims")
        self.assertEqual(reporter_client.verify_prompt_role, "literature_verify")
        self.assertIn("PMID:12345678", reporter_client.judge_prompt)
        self.assertIn("Verified Literature Evidence", reporter_client.judge_prompt)
        self.assertEqual(literature_client.queries[0][1], 3)

    def test_verifier_failure_preserves_candidates_but_exposes_no_citable_studies(self):
        parsed_record = PubMedLiteratureClient(
            transport=lambda url: _PUBMED_XML
        ).fetch(["12345678"])[0]
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ReportAgent(SimpleNamespace(root=repo, prompt=lambda role: ""), {},
                                literature_client=_LiteratureClient([parsed_record]))
            agent.reporter_client = _ReporterClient(
                    verify_error=RuntimeError("verifier unavailable")
                )
            evidence = agent.collect_literature_evidence(
                finalization_context={"mr_evidence": {"applies": True}}
            )

        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["studies"], [])
        self.assertEqual(
            evidence["screened_candidates"][0]["support_grade"],
            "verification_failed",
        )
        self.assertEqual(evidence["failures"][-1]["phase"], "literature_verification")


if __name__ == "__main__":
    unittest.main()
