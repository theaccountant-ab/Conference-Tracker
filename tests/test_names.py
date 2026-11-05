from conference_tracker.models import clean_conference_name


def test_strips_leading_ordinal():
    assert (
        clean_conference_name("The 39th Australasian Finance and Banking Conference")
        == "The Australasian Finance and Banking Conference"
    )


def test_strips_inline_ordinal():
    assert (
        clean_conference_name('MIT GCFP 13th Annual Conference | "Disruption"')
        == 'MIT GCFP Conference | "Disruption"'
    )


def test_strips_year_and_paren_abbreviation():
    assert (
        clean_conference_name("7th Financial Economics Meeting (FEM-2026)")
        == "Financial Economics Meeting"
    )
    assert (
        clean_conference_name("2026 CLIMATE FINANCE & POLICY (CFP-2026)")
        == "CLIMATE FINANCE & POLICY"
    )
    assert (
        clean_conference_name(
            "International Conference in Banking and Financial Studies (ICBFS)"
        )
        == "International Conference in Banking and Financial Studies"
    )


def test_strips_trailing_year():
    assert clean_conference_name("ICBFS 2026") == "ICBFS"
    assert (
        clean_conference_name("SFS Cavalcade Asia-Pacific 2026")
        == "SFS Cavalcade Asia-Pacific"
    )


def test_keeps_meaningful_hyphens_and_plain_names():
    # Internal hyphens that aren't years are preserved.
    assert (
        clean_conference_name("2026 ABFER-JFDS Conference on AI for Finance")
        == "ABFER-JFDS Conference on AI for Finance"
    )
    assert (
        clean_conference_name("EUROFIDAI-ESSEC Paris December Finance Meeting")
        == "EUROFIDAI-ESSEC Paris December Finance Meeting"
    )


def test_empty():
    assert clean_conference_name("") == ""


from conference_tracker.models import titlecase_conference_name as tc


def test_titlecase_all_caps_with_acronym():
    assert tc("CLIMATE FINANCE & POLICY (CFP)") == "Climate Finance & Policy (CFP)"
    assert tc("CHICAGO FED/UNIVERSITY OF CHICAGO CONFERENCE ON MUNICIPAL BOND MARKETS") == (
        "Chicago Fed/University of Chicago Conference on Municipal Bond Markets"
    )


def test_titlecase_preserves_acronyms():
    assert tc("MIT GCFP Annual Conference") == "MIT GCFP Annual Conference"
    assert tc("ABFER-JFDS Conference on AI for Finance") == "ABFER-JFDS Conference on AI for Finance"
    assert tc("Financial Economics Meeting (FEM)") == "Financial Economics Meeting (FEM)"
    assert tc("The CUHK-RAPS-RCFS Conference on Asset Pricing and Corporate Finance") == (
        "The CUHK-RAPS-RCFS Conference on Asset Pricing and Corporate Finance"
    )


def test_titlecase_minor_words_and_edges():
    assert tc("finance at a time of change and uncertainty") == (
        "Finance at a Time of Change and Uncertainty"
    )
    # leading minor word is still capitalized
    assert tc("the colorado finance summit") == "The Colorado Finance Summit"


def test_drops_annual():
    from conference_tracker.models import drop_annual

    assert drop_annual("European Finance Association Annual Meeting") == (
        "European Finance Association Meeting"
    )
    assert clean_conference_name("22nd Annual Olin Finance Conference") == (
        "Olin Finance Conference"
    )
    assert drop_annual("Annual Finance Conference, Isenberg School") == (
        "Finance Conference, Isenberg School"
    )


def test_keeps_annual_where_it_is_part_of_the_name():
    from conference_tracker.models import drop_annual

    # A journal title, a different word, and names that would be left bare.
    assert drop_annual("Annual Review of Financial Economics Conference") == (
        "Annual Review of Financial Economics Conference"
    )
    assert drop_annual("Semi-Annual Banking Workshop") == "Semi-Annual Banking Workshop"
    assert drop_annual("Annual Conference") == "Annual Conference"
    assert drop_annual("The Annual Meeting") == "The Annual Meeting"
