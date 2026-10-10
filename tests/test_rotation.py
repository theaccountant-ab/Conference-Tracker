import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from due_watchlist import due_names  # noqa: E402

from conference_tracker.models import Conference
from conference_tracker.site import render_html

HEADER = "name,contact,location,submission_deadline,status,start_date,end_date,last_updated,source\n"


def _files(names, csv_rows):
    d = tempfile.mkdtemp()
    wl, csvp = os.path.join(d, "watchlist.txt"), os.path.join(d, "c.csv")
    open(wl, "w").write("\n".join(names) + "\n")
    open(csvp, "w").write(HEADER + "".join(r + "\n" for r in csv_rows))
    return wl, csvp


def test_rotation_prefers_never_and_oldest_searched_and_skips_recent():
    wl, csvp = _files(["A Conf", "B Conf", "C Conf", "D Conf"], [])
    state = {"A Conf": "2026-10-09", "B Conf": "2026-07-01", "C Conf": "2026-08-01"}
    picked = due_names(wl, csvp, state, limit=0, skip_days=30, today=date(2026, 10, 10))
    # D never searched first; then oldest B, then C; A was searched yesterday.
    assert picked == ["D Conf", "B Conf", "C Conf"]
    assert due_names(wl, csvp, state, limit=2, skip_days=30,
                     today=date(2026, 10, 10)) == ["D Conf", "B Conf"]


def test_name_covered_by_upcoming_row_from_its_own_search():
    seeded = "11th Northeastern Finance Conference, May 5-7, 2027, Boston"
    wl, csvp = _files([seeded, "Other Conf"], [
        f'Northeastern Finance Conference,x,"Boston, MA",2026-11-22,Submission,'
        f'2027-05-05,2027-05-07,2026-10-04T00:00:00Z,"search:{seeded}"'
    ])
    assert due_names(wl, csvp, {}, today=date(2026, 10, 10)) == ["Other Conf"]


def test_site_lists_only_open_calls_for_papers():
    html = render_html([
        Conference(name="Open CFP", location="X", submission_deadline="2026-11-01",
                   status="Submission", start_date="2027-01-01", end_date="2027-01-02"),
        Conference(name="Closed CFP", location="X", submission_deadline="2026-09-01",
                   status="Participation", start_date="2027-01-01", end_date="2027-01-02"),
        Conference(name="Past Conf", location="X", submission_deadline="2025-09-01",
                   status="Ended", start_date="2026-01-01", end_date="2026-01-02"),
    ])
    assert "Open CFP" in html
    assert "Closed CFP" not in html and "Past Conf" not in html
