import os
import sys
import tempfile

# Make the repo-root scripts/ importable (mirrors how the workflow runs it).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from conference_tracker.models import CSV_FIELDS
from conference_tracker.store import CSVStore, Conference

from due_watchlist import due_names  # noqa: E402


def _write(tmp, lines):
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def test_due_filters_out_conferences_with_upcoming_edition():
    d = tempfile.mkdtemp()
    csv_path = os.path.join(d, "conferences.csv")
    wl_path = os.path.join(d, "watchlist.txt")

    store = CSVStore(csv_path)
    store.save([
        # Has an upcoming (non-Ended) edition -> NOT due.
        Conference(name="Alpha Finance Conference", start_date="2030-09-01",
                   end_date="2030-09-02", status="Participation"),
        # Only an ended edition -> due.
        Conference(name="Beta Accounting Workshop", start_date="2022-05-01",
                   end_date="2022-05-02", status="Ended"),
    ])

    _write(wl_path, [
        "# a comment",
        "Alpha Finance Conference",
        "Beta Accounting Workshop",
        "Gamma Symposium",   # not in the CSV at all -> always due
    ])

    due = due_names(wl_path, csv_path)
    assert "Alpha Finance Conference" not in due   # upcoming edition on file
    assert "Beta Accounting Workshop" in due       # only ended -> due
    assert "Gamma Symposium" in due                # unknown -> due
    assert due == ["Beta Accounting Workshop", "Gamma Symposium"]


def test_missing_csv_means_everything_is_due():
    d = tempfile.mkdtemp()
    wl_path = os.path.join(d, "watchlist.txt")
    _write(wl_path, ["One Conference", "Another Conference"])
    due = due_names(wl_path, os.path.join(d, "does_not_exist.csv"))
    assert due == ["One Conference", "Another Conference"]
