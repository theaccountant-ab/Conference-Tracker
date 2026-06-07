from conference_tracker.extractor import _is_plausible, _split_text
from conference_tracker.models import ExtractedConference


def _conf(name):
    return ExtractedConference(name=name)


def test_accepts_normal_name():
    assert _is_plausible(_conf("SFS Cavalcade Asia-Pacific"))
    assert _is_plausible(_conf('MIT GCFP Annual Conference | "Financial Regulation"'))


def test_rejects_empty_name():
    assert not _is_plausible(_conf(""))
    assert not _is_plausible(_conf("   "))


def test_rejects_json_blob_name():
    # The kind of corrupted record a truncated response can produce.
    blob = (
        'Finance at a Time of Change ", "Submission_Deadline": " -08-09", '
        '"Url": "HTTPS://EXAMPLE.COM"}, {"Name": "Another"'
    )
    assert not _is_plausible(_conf(blob))


def test_rejects_overlong_name():
    assert not _is_plausible(_conf("A" * 201))


def test_split_text_halves_on_boundary():
    text = "\n\n".join(f"Conference {i} call for papers" for i in range(20))
    a, b = _split_text(text)
    assert a and b
    assert len(a) < len(text) and len(b) < len(text)
