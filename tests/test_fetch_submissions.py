import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fetch_submissions import due_submissions  # noqa: E402

# A Tally -> Google Sheets export, roughly: an id column, the form fields, the
# file-upload column (a URL), and the "Approved" column the user adds.
CSV = (
    "Submission ID,Conference name,Call for papers,Approved\n"
    "sub_1,Alpha Finance Conference,https://storage.tally.so/abc/alpha.pdf,TRUE\n"
    "sub_2,Beta Accounting Workshop,https://storage.tally.so/def/beta.docx,\n"
    "sub_3,Gamma Symposium,https://storage.tally.so/ghi/gamma.pdf,yes\n"
)


def test_only_approved_rows_returned():
    due = due_submissions(CSV, processed_ids=set())
    names = [d["name"] for d in due]
    assert names == ["Alpha Finance Conference", "Gamma Symposium"]  # Beta not approved
    assert due[0]["url"] == "https://storage.tally.so/abc/alpha.pdf"
    assert due[0]["id"] == "sub_1"


def test_already_processed_skipped():
    due = due_submissions(CSV, processed_ids={"sub_1"})
    assert [d["name"] for d in due] == ["Gamma Symposium"]


def test_checkbox_and_url_detection_without_id_column():
    csv_text = (
        "Name,CFP file,Approved\n"
        "Solo Conference,see https://x.test/cfp.pdf here,x\n"
    )
    due = due_submissions(csv_text, set())
    assert len(due) == 1
    assert due[0]["url"] == "https://x.test/cfp.pdf"
    # No id column -> the URL itself is the stable key.
    assert due[0]["id"] == "https://x.test/cfp.pdf"


def test_no_approved_column_returns_nothing():
    csv_text = "Name,CFP file\nA,https://x.test/a.pdf\n"
    assert due_submissions(csv_text, set()) == []
