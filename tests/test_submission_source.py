import os
import tempfile

from conference_tracker.sources.submission_source import (
    SubmissionSource,
    extract_text,
)


def _dirs():
    d = tempfile.mkdtemp()
    sub = os.path.join(d, "submissions")
    host = os.path.join(d, "host")
    os.makedirs(sub)
    return sub, host


def test_extract_text_txt():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfp.txt")
    with open(p, "w") as fh:
        fh.write("Call for Papers: Test Finance Conference 2030")
    assert "Test Finance Conference" in extract_text(p)


def test_extract_text_docx():
    from docx import Document

    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfp.docx")
    doc = Document()
    doc.add_paragraph("Call for Papers: Docx Finance Workshop 2030")
    doc.save(p)
    assert "Docx Finance Workshop" in extract_text(p)


def test_iter_hosts_file_and_passes_link():
    sub, host = _dirs()
    with open(os.path.join(sub, "My CFP.txt"), "w") as fh:
        fh.write("Deadline 2030-01-01. Vienna, Austria.")
    # README / hidden files are ignored.
    with open(os.path.join(sub, "README.md"), "w") as fh:
        fh.write("ignore me")

    src = SubmissionSource(submissions_dir=sub, host_dir=host)
    gen = src.iter_documents()
    doc = next(gen)
    assert doc.text.startswith("Source URL: cfps/my-cfp-")
    assert "Deadline 2030-01-01" in doc.text
    assert doc.origin == "submission:My CFP.txt"

    # Not published until the consumer signals success.
    assert not (os.path.exists(host) and
                any(f.endswith(".txt") for f in os.listdir(host)))
    doc.on_success()
    try:
        next(gen)  # runs the post-yield publish/cleanup
    except StopIteration:
        pass

    published = [f for f in os.listdir(host) if f.endswith(".txt")]
    assert len(published) == 1 and published[0].startswith("my-cfp-")
    # Original removed from the approval inbox; README left untouched.
    assert not os.path.exists(os.path.join(sub, "My CFP.txt"))
    assert os.path.exists(os.path.join(sub, "README.md"))


def test_empty_or_unsupported_left_in_place():
    sub, host = _dirs()
    open(os.path.join(sub, "note.rtf"), "w").close()  # unsupported -> no text
    src = SubmissionSource(submissions_dir=sub, host_dir=host)
    assert list(src.iter_documents()) == []
    assert os.path.exists(os.path.join(sub, "note.rtf"))  # not consumed
