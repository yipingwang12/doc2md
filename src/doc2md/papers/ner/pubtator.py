"""PubTator 3.0 HTTP client.

Fetches pre-computed biomedical entity annotations by PMID.
Returns NamedEntity objects with normalised IDs (NCBIGene:*, MeSH:*).

Rate limit: NCBI allows ~3 req/s. Callers pass rate_delay=0 in tests.
"""

from __future__ import annotations

import time

import requests

from doc2md.papers.models import NamedEntity

_BASE_URL = "https://api.ncbi.nlm.nih.gov/lit/pubtator3"

# Maps PubTator type strings → canonical entity_type
_TYPE_MAP: dict[str, str] = {
    "gene": "gene",
    "protein": "gene",          # PubTator uses Gene for proteins too
    "disease": "disease",
    "chemical": "chemical",
    "drug": "chemical",
    "species": "species",
    "organism": "species",
    "mutation": "variant",
    "variant": "variant",
    "genomicvariant": "variant",
    "cellline": "cell_line",
    "cell_line": "cell_line",
    "celltype": "cell_type",
    "cell_type": "cell_type",
}

# Maps PubTator passage type → section_label
_SECTION_MAP: dict[str, str] = {
    "title": "preamble",
    "abstract": "abstract",
    "intro": "introduction",
    "introduction": "introduction",
    "methods": "methods",
    "results": "results",
    "discussion": "discussion",
    "conclusions": "discussion",
    "ref": "references",
    "references": "references",
    "supplementary": "supplementary",
}


def _normalise_id(raw_id: str, entity_type: str) -> str:
    """Add a namespace prefix if missing."""
    if ":" in raw_id:
        return raw_id.replace("MESH:", "MeSH:")
    if entity_type == "gene":
        return f"NCBIGene:{raw_id}"
    if entity_type in ("disease", "chemical"):
        return f"MeSH:{raw_id}"
    if entity_type == "species":
        return f"NCBITaxon:{raw_id}"
    return raw_id


def parse_bioc_response(doc: dict, section_label: str = "") -> list[NamedEntity]:
    """Parse a single PubTator BioC document dict into NamedEntity objects."""
    entities: list[NamedEntity] = []
    for passage in doc.get("passages", []):
        passage_type = passage.get("infons", {}).get("type", "").lower()
        label = _SECTION_MAP.get(passage_type, section_label or passage_type)

        for ann in passage.get("annotations", []):
            infons = ann.get("infons", {})
            raw_id = infons.get("identifier", "")
            if not raw_id:
                continue
            raw_type = infons.get("type", "").lower()
            entity_type = _TYPE_MAP.get(raw_type, "other")
            entity_id = _normalise_id(raw_id, entity_type)

            locs = ann.get("locations", [])
            start = locs[0]["offset"] if locs else 0
            length = locs[0].get("length", len(ann.get("text", ""))) if locs else 0

            entities.append(NamedEntity(
                text=ann.get("text", ""),
                entity_type=entity_type,
                entity_id=entity_id,
                source="pubtator",
                section_label=label,
                start=start,
                end=start + length,
            ))
    return entities


def fetch_entities_by_pmid(
    pmid: str,
    base_url: str = _BASE_URL,
    rate_delay: float = 0.34,
) -> list[NamedEntity]:
    """Fetch and parse BioC JSON from PubTator 3.0 by PMID.

    Raises requests.HTTPError on non-2xx responses.
    """
    url = f"{base_url}/publications/export/biocjson"
    resp = requests.get(url, params={"pmids": pmid}, timeout=30)
    resp.raise_for_status()
    if rate_delay:
        time.sleep(rate_delay)

    data = resp.json()
    docs = data.get("PubTator3", [])
    if not docs:
        return []
    return parse_bioc_response(docs[0])
