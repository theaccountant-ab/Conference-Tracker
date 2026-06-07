"""Input sources for the conference tracker.

Each source yields ``SourceDocument`` items (a chunk of text plus a label of
where it came from). The extractor turns those into structured records. New
sources (web-page list, Google search) can be added by implementing the same
``iter_documents`` interface used by :class:`~conference_tracker.sources.base.Source`.
"""

from .base import Source, SourceDocument

__all__ = ["Source", "SourceDocument"]
