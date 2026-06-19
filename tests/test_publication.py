from datetime import date

from conference_tracker.models import PaperPublication
from conference_tracker.publication import (
    PublicationAnalysis,
    is_top_tier_journal,
    recent_years,
)


def test_recent_years_are_completed_years_most_recent_first():
    # In mid-2026, the past 3 completed years are 2025, 2024, 2023.
    assert recent_years(3, today=date(2026, 6, 19)) == [2025, 2024, 2023]
    assert recent_years(1, today=date(2026, 1, 1)) == [2025]


def test_is_top_tier_journal_substring_and_case_insensitive():
    tier = ["Journal of Finance", "American Economic Review"]
    # Leading "The" / different casing still matches.
    assert is_top_tier_journal("The Journal of Finance", tier)
    assert is_top_tier_journal("AMERICAN ECONOMIC REVIEW", tier)
    # A non-top-tier journal does not match.
    assert not is_top_tier_journal("Journal of Banking & Finance", tier)
    # No journal (unpublished) is never top-tier.
    assert not is_top_tier_journal(None, tier)
    assert not is_top_tier_journal("", tier)


def _paper(title, journal=None, top=None):
    return PaperPublication(title=title, published_journal=journal, is_top_tier=top)


def test_analysis_counts_and_fraction():
    analysis = PublicationAnalysis(
        conference="Test Conf",
        years=[2025, 2024, 2023],
        papers=[
            _paper("A", "Journal of Finance", True),
            _paper("B", "Journal of Banking & Finance", False),
            _paper("C"),  # unpublished
            _paper("D", "Review of Financial Studies", True),
        ],
    )
    assert analysis.total_papers == 4
    assert analysis.published_papers == 3
    assert analysis.top_tier_papers == 2
    assert analysis.top_tier_fraction == 0.5


def test_fraction_is_none_when_no_papers_found():
    analysis = PublicationAnalysis(conference="Empty", years=[2025])
    assert analysis.total_papers == 0
    assert analysis.top_tier_fraction is None
