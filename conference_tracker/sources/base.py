"""Source abstraction shared by all input channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol


@dataclass
class SourceDocument:
    """A single unit of text to extract a conference from, plus provenance."""

    text: str
    origin: str  # human-readable description of where this came from


class Source(Protocol):
    """Anything that can produce documents for extraction."""

    def iter_documents(self) -> Iterator[SourceDocument]:
        ...
