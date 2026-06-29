from conference_tracker.models import Conference
from conference_tracker.site import render_html

_CONF = [Conference(name="Test Conf", status="Submission",
                    submission_deadline="2030-01-01")]


def test_submit_button_shown_when_url_set():
    html = render_html(_CONF, submission_url="https://forms.example.com/cfp")
    assert "Submit your CFP" in html
    assert 'href="https://forms.example.com/cfp"' in html


def test_submit_button_hidden_when_url_unset():
    html = render_html(_CONF)
    assert "Submit your CFP" not in html


def test_submit_url_is_attribute_escaped():
    # A quote in the URL must not break out of the href attribute.
    html = render_html(_CONF, submission_url='https://x.test/a"b')
    assert 'href="https://x.test/a"b"' not in html
    assert "Submit your CFP" in html


def test_ended_conferences_excluded():
    rows = [Conference(name="Old", status="Ended", start_date="2000-01-01"),
            Conference(name="Live", status="Submission", submission_deadline="2030-01-01")]
    html = render_html(rows)
    assert "Live" in html and "Old" not in html
