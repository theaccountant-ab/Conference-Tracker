from conference_tracker.models import clean_conference_name


def test_strips_leading_ordinal():
    assert (
        clean_conference_name("The 39th Australasian Finance and Banking Conference")
        == "The Australasian Finance and Banking Conference"
    )


def test_strips_inline_ordinal():
    assert (
        clean_conference_name('MIT GCFP 13th Annual Conference | "Disruption"')
        == 'MIT GCFP Annual Conference | "Disruption"'
    )


def test_strips_year_and_tidies_parens():
    assert (
        clean_conference_name("7th Financial Economics Meeting (FEM-2026)")
        == "Financial Economics Meeting (FEM)"
    )
    assert (
        clean_conference_name("2026 CLIMATE FINANCE & POLICY (CFP-2026)")
        == "CLIMATE FINANCE & POLICY (CFP)"
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
