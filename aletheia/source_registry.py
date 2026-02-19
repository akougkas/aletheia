"""Trusted source metadata registry used by evidence scoring."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceMetadata:
    """Minimal trust metadata for an evidence source."""

    source_id: str
    label: str
    source_type: str
    base_confidence: float
    trusted_domains: tuple[str, ...] = ()


class SourceRegistry:
    """In-memory registry for source trust metadata."""

    def __init__(self, sources: list[SourceMetadata]):
        self._sources = {item.source_id: item for item in sources}

    @classmethod
    def default(cls) -> "SourceRegistry":
        return cls(
            [
                SourceMetadata(
                    source_id="methodology_kb",
                    label="Methodology Knowledge Base",
                    source_type="kg",
                    base_confidence=0.9,
                    trusted_domains=(
                        "cdc.gov",
                        "bls.gov",
                        "census.gov",
                        "ec.europa.eu",
                        "ecb.europa.eu",
                        "cso.ie",
                    ),
                ),
                SourceMetadata(
                    source_id="document_index",
                    label="Document Index",
                    source_type="documents",
                    base_confidence=0.8,
                    trusted_domains=(
                        "cdc.gov",
                        "bls.gov",
                        "census.gov",
                        "ec.europa.eu",
                        "ecb.europa.eu",
                        "nber.org",
                    ),
                ),
                SourceMetadata(
                    source_id="data_api",
                    label="Statistical API Connectors",
                    source_type="api",
                    base_confidence=0.85,
                    trusted_domains=(
                        "bls.gov",
                        "stlouisfed.org",
                        "census.gov",
                        "ec.europa.eu",
                        "ecb.europa.eu",
                    ),
                ),
                SourceMetadata(
                    source_id="retrieval_index",
                    label="Retrieved Evidence Index",
                    source_type="memory",
                    base_confidence=0.75,
                    trusted_domains=(
                        "cdc.gov",
                        "bls.gov",
                        "census.gov",
                        "ec.europa.eu",
                        "ecb.europa.eu",
                        "oecd.org",
                        "imf.org",
                        "worldbank.org",
                        "nber.org",
                    ),
                ),
                SourceMetadata(
                    source_id="paper_scholar",
                    label="Google Scholar Papers",
                    source_type="scholar",
                    base_confidence=0.78,
                    trusted_domains=(
                        "doi.org",
                        "nber.org",
                        "sciencedirect.com",
                        "springer.com",
                        "wiley.com",
                        "jamanetwork.com",
                        "thelancet.com",
                        "nature.com",
                        "science.org",
                        "oup.com",
                        "cambridge.org",
                    ),
                ),
                SourceMetadata(
                    source_id="web_fallback",
                    label="Fallback Search",
                    source_type="fallback",
                    base_confidence=0.45,
                    trusted_domains=(
                        "cdc.gov",
                        "bls.gov",
                        "census.gov",
                        "ec.europa.eu",
                        "ecb.europa.eu",
                        "oecd.org",
                        "imf.org",
                        "worldbank.org",
                        "nber.org",
                    ),
                ),
            ]
        )

    def get(self, source_id: str) -> SourceMetadata | None:
        return self._sources.get(source_id)

    def base_confidence(self, source_id: str) -> float:
        metadata = self.get(source_id)
        return metadata.base_confidence if metadata else 0.4

    def is_trusted_url(self, source_id: str, url: str | None) -> bool:
        if not url:
            return False
        metadata = self.get(source_id)
        if not metadata or not metadata.trusted_domains:
            return False
        try:
            hostname = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        if not hostname:
            return False
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in metadata.trusted_domains
        )
