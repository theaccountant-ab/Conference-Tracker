"""Source abstraction shared by all input channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Protocol


@dataclass
class SourceDocument:
    """A single unit of text to extract a conference from, plus provenance."""

    text: str
    origin: str  # human-readable description of where this came from
    # Optional callback the consumer invokes once the document has been
    # processed successfully (e.g. the email source uses it to mark a message
    # read only after extraction succeeds, so a transient failure is retried).
    on_success: Optional[Callable[[], None]] = None


class Source(Protocol):
    """Anything that can produce documents for extraction."""

    def iter_documents(self) -> Iterator[SourceDocument]:
        ...
