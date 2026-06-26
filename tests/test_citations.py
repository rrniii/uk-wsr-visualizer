from uk_wsr_visualizer.citations import citation_payload, citation_text, format_citation_text, manifest_provenance


def test_citation_payload_contains_credit_objects():
    payload = citation_payload()

    assert payload["software"]["name"] == "UK WSR Visualizer"
    assert payload["software"]["version"]
    assert "software" in payload["citation"]
    assert "article" in payload["citation"]
    assert "source_data" in payload["citation"]
    assert "jasmin_acknowledgement" in payload["infrastructure"]
    assert "wct_inspiration" in payload["acknowledgements"]


def test_citation_text_mentions_required_citation_layers():
    text = citation_text()

    assert "Software" in text
    assert "Article" in text
    assert "Source data" in text
    assert "JASMIN acknowledgement" in text


def test_format_citation_text_alias():
    assert format_citation_text() == citation_text()


def test_manifest_provenance_contains_export_credit_layers():
    provenance = manifest_provenance()

    assert provenance["software"]["name"] == "UK WSR Visualizer"
    assert "article" in provenance
    assert "source_data" in provenance
    assert "citation" in provenance
    assert "jasmin_acknowledgement" in provenance["infrastructure"]
