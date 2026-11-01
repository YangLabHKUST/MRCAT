from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_YEAR_RE = re.compile(r"\b(18|19|20|21)\d{2}\b")


class PubMedLiteratureClient:
    """Read-only PubMed ESearch/EFetch client with structured XML parsing."""

    def __init__(
        self,
        *,
        timeout_sec: float = 20.0,
        transport: Callable[[str], bytes] | None = None,
    ) -> None:
        self.timeout_sec = float(timeout_sec)
        self.transport = transport
        self._last_request_at = 0.0

    def search(self, query: str, *, max_results: int = 3) -> list[dict[str, Any]]:
        clean_query = " ".join(str(query or "").split()).strip()
        if not clean_query:
            return []
        params = self._common_params()
        params.update(
            {
                "db": "pubmed",
                "term": clean_query,
                "retmode": "json",
                "retmax": str(max(1, min(int(max_results), 10))),
                "sort": "relevance",
            }
        )
        payload = json.loads(
            self._get(f"{_EUTILS_BASE_URL}/esearch.fcgi?{urlencode(params)}")
        )
        result = payload.get("esearchresult") if isinstance(payload, dict) else {}
        pmids = [
            str(value).strip()
            for value in list((result or {}).get("idlist") or [])
            if str(value).strip()
        ]
        return self.fetch(pmids)

    def fetch(self, pmids: list[str]) -> list[dict[str, Any]]:
        clean_pmids = list(
            dict.fromkeys(
                str(value).strip()
                for value in pmids
                if str(value).strip().isdigit()
            )
        )
        if not clean_pmids:
            return []
        params = self._common_params()
        params.update(
            {
                "db": "pubmed",
                "id": ",".join(clean_pmids[:20]),
                "retmode": "xml",
            }
        )
        raw = self._get(f"{_EUTILS_BASE_URL}/efetch.fcgi?{urlencode(params)}")
        root = ET.fromstring(raw)
        records = [
            _parse_pubmed_article(article)
            for article in root.findall(".//PubmedArticle")
        ]
        return [record for record in records if record.get("pmid")]

    def _common_params(self) -> dict[str, str]:
        params = {"tool": "MRCAT-report-agent"}
        email = str(os.environ.get("NCBI_EMAIL") or "").strip()
        api_key = str(os.environ.get("NCBI_API_KEY") or "").strip()
        if email:
            params["email"] = email
        if api_key:
            params["api_key"] = api_key
        return params

    def _get(self, url: str) -> bytes:
        if self.transport is not None:
            return self.transport(url)
        min_interval = (
            0.11
            if str(os.environ.get("NCBI_API_KEY") or "").strip()
            else 0.34
        )
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        request = Request(
            url,
            headers={
                "Accept": "application/json, application/xml;q=0.9",
                "User-Agent": "MRCAT-report-agent/1.0",
            },
        )
        with urlopen(request, timeout=self.timeout_sec) as response:
            payload = response.read()
        self._last_request_at = time.monotonic()
        return payload


def _parse_pubmed_article(article: ET.Element) -> dict[str, Any]:
    citation = article.find("MedlineCitation")
    article_node = citation.find("Article") if citation is not None else None
    pmid = _element_text(citation.find("PMID") if citation is not None else None)
    title = _element_text(
        article_node.find("ArticleTitle") if article_node is not None else None
    )
    abstract_parts: list[str] = []
    if article_node is not None:
        for part in article_node.findall("Abstract/AbstractText"):
            text = _element_text(part)
            label = str(part.attrib.get("Label") or "").strip()
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
    authors = _parse_authors(article_node)
    journal = _element_text(
        article_node.find("Journal/Title") if article_node is not None else None
    )
    year = _publication_year(article_node, citation)
    doi = _doi(article)
    publication_types = [
        _element_text(node)
        for node in (
            article_node.findall("PublicationTypeList/PublicationType")
            if article_node is not None
            else []
        )
        if _element_text(node)
    ]
    retracted = any(
        value.lower() == "retracted publication" for value in publication_types
    ) or any(
        str(node.attrib.get("RefType") or "").lower() == "retractionin"
        for node in article.findall(".//CommentsCorrections")
    )
    return {
        "reference_id": f"PMID:{pmid}",
        "title": title,
        "abstract": "\n".join(abstract_parts).strip(),
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "pmid": pmid,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        "publication_types": publication_types,
        "metadata_source": "PubMed EFetch XML",
        "metadata_complete": bool(title and journal and year and authors),
        "retracted": retracted,
    }


def _parse_authors(article_node: ET.Element | None) -> list[dict[str, str]]:
    if article_node is None:
        return []
    authors: list[dict[str, str]] = []
    for node in article_node.findall("AuthorList/Author"):
        collective = _element_text(node.find("CollectiveName"))
        if collective:
            authors.append(
                {
                    "family": "",
                    "given": "",
                    "collective": collective,
                    "display": collective,
                }
            )
            continue
        family = _element_text(node.find("LastName"))
        given = _element_text(node.find("ForeName")) or _element_text(
            node.find("Initials")
        )
        if not family and not given:
            continue
        authors.append(
            {
                "family": family,
                "given": given,
                "collective": "",
                "display": ", ".join(value for value in (family, given) if value),
            }
        )
    return authors


def _publication_year(
    article_node: ET.Element | None,
    citation: ET.Element | None,
) -> str:
    candidates: list[str] = []
    if article_node is not None:
        for path in (
            "ArticleDate/Year",
            "Journal/JournalIssue/PubDate/Year",
            "Journal/JournalIssue/PubDate/MedlineDate",
        ):
            candidates.append(_element_text(article_node.find(path)))
    if citation is not None:
        candidates.append(_element_text(citation.find("DateCompleted/Year")))
    for candidate in candidates:
        match = _YEAR_RE.search(candidate)
        if match:
            return match.group(0)
    return ""


def _doi(article: ET.Element) -> str:
    for node in article.findall(".//ELocationID"):
        if str(node.attrib.get("EIdType") or "").lower() == "doi":
            value = _element_text(node)
            if value:
                return value
    for node in article.findall(".//ArticleId"):
        if str(node.attrib.get("IdType") or "").lower() == "doi":
            value = _element_text(node)
            if value:
                return value
    return ""


def _element_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split()).strip()
