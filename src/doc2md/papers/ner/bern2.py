"""BERN2 HTTP client.

Annotates arbitrary text with biomedical named entities.
Use for sections beyond the abstract, or when PMID is unavailable.

API: POST {base_url}/plain with JSON body {"text": "..."}.
"""

from __future__ import annotations

import requests

from doc2md.papers.models import NamedEntity

_DEFAULT_BASE_URL = "http://bern2.korea.ac.kr"

_TYPE_MAP: dict[str, str] = {
    "gene": "gene",
    "protein": "gene",
    "disease": "disease",
    "drug": "chemical",
    "chemical": "chemical",
    "species": "species",
    "organism": "species",
    "mutation": "variant",
    "variant": "variant",
    "cell_line": "cell_line",
    "cellline": "cell_line",
    "cell_type": "cell_type",
    "celltype": "cell_type",
}


def parse_bern2_response(response_json: dict, section_label: str = "") -> list[NamedEntity]:
    """Parse BERN2 JSON response into NamedEntity objects."""
    entities: list[NamedEntity] = []
    for ann in response_json.get("annotations", []):
        text = ann.get("mention", "")
        raw_type = ann.get("obj", "").lower()
        entity_type = _TYPE_MAP.get(raw_type, "other")

        ids = ann.get("id", [])
        if ids:
            entity_id = ids[0]
        else:
            entity_id = f"bern2:{text.lower().replace(' ', '_')}"

        span = ann.get("span", {})
        start = span.get("begin", 0)
        end = span.get("end", start + len(text))

        entities.append(NamedEntity(
            text=text,
            entity_type=entity_type,
            entity_id=entity_id,
            source="bern2",
            section_label=section_label,
            start=start,
            end=end,
        ))
    return entities


def annotate_text(
    text: str,
    section_label: str = "",
    base_url: str = _DEFAULT_BASE_URL,
    timeout: int = 60,
) -> list[NamedEntity]:
    """Send text to BERN2 and parse response into NamedEntity objects.

    Raises requests.HTTPError on non-2xx, requests.Timeout on timeout.
    """
    url = f"{base_url.rstrip('/')}/plain"
    resp = requests.post(url, json={"text": text}, timeout=timeout)
    resp.raise_for_status()
    return parse_bern2_response(resp.json(), section_label=section_label)
