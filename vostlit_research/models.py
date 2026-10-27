"""Pydantic models used at the boundaries (JSONL import/export, CLI output).

The DB schema is the source of truth; these models mirror it for validation
and for stable (de)serialisation. They are intentionally permissive: missing
historical metadata is ``None``, never guessed.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

# ---------------------------------------------------------------------- enums

EntityType = Literal[
    "person", "place", "settlement", "society", "state",
    "ethnonym", "organisation", "event", "work",
]
SectionType = Literal[
    "body", "heading", "footnote", "note", "bibliography",
    "caption", "page_break", "chapter_marker",
]
DocStatus = Literal[
    "discovered", "queued", "fetched", "parsed", "skipped",
    "unchanged", "error",
]
Confidence = Literal["verified", "probable", "possible", "unestablished"]
VerificationStatus = Literal["unverified", "candidate", "confirmed", "rejected"]
ResearchStatus = Literal["source_fact", "interpretation", "hypothesis", "refuted"]


class VRBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------- sections

class SectionIn(VRBaseModel):
    section_type: SectionType
    heading: str | None = None
    text: str | None = None
    sequence_number: int
    page_number: str | None = None
    anchor: str | None = None
    source_url: str | None = None


# ---------------------------------------------------------------------- document

class DocumentIn(VRBaseModel):
    """Shape accepted by the JSONL importer and produced by the exporter.

    Either ``canonical_url`` (required) identifies the document; sections are
    optional (a document may be inventoried before its text is fetched).
    """
    canonical_url: str
    stable_id: str | None = None
    page_type: str | None = None
    title: str | None = None
    author: str | None = None
    translator: str | None = None
    editor: str | None = None
    original_creation_date: str | None = None
    publication_year: str | None = None
    publication_title: str | None = None
    source_type: str | None = None
    language: str | None = None
    region: str | None = None
    collection: str | None = None
    description: str | None = None
    bibliography: str | None = None
    source_metadata: dict[str, Any] | None = None
    extracted_text: str | None = None
    extraction_method: str | None = None
    extraction_warnings: list[str] | None = None
    sections: list[SectionIn] | None = None


# ---------------------------------------------------------------------- entities

class NameVariantIn(VRBaseModel):
    original_form: str
    entity_id: int | None = None
    canonical_name: str | None = None  # if entity_id is None, look up/create by this
    entity_type: EntityType | None = None
    language: str | None = None
    script: str | None = None
    transliteration_system: str | None = None
    variant_type: str | None = None
    date_range: str | None = None
    confidence: Confidence | None = None
    verification_status: VerificationStatus = "unverified"
    evidence_section_id: int | None = None


class EntityIn(VRBaseModel):
    canonical_name: str
    entity_type: EntityType
    description: str | None = None
    earliest_attested_date: str | None = None
    latest_attested_date: str | None = None
    confidence: Confidence | None = None
    notes: str | None = None


# ---------------------------------------------------------------------- research

class FragmentRef(VRBaseModel):
    section_id: int | None = None
    document_id: int | None = None
    quote: str | None = None
    url: str | None = None


class ResearchNoteIn(VRBaseModel):
    claim: str
    status: ResearchStatus
    supporting_fragments: list[FragmentRef] = Field(default_factory=list)
    contradicting_fragments: list[FragmentRef] = Field(default_factory=list)
    argumentation: str | None = None
    author_or_mechanism: str | None = None
    confidence: Confidence | None = None
