from uk_wsr_visualizer.citations import citation_payload, format_citation_text


def test_citation_payload_contains_credit_objects():
    payload = citation_payload()

    assert payload["software"]["name"] == "UK WSR Visualizer"
    assert payload["software"]["version"]
    assert "software" in payload["citation"]
    assert "article" in payload["citation"]
    assert "source_data" in payload["citation"]
    assert "jasmin_acknowledgement" in payload["infrastructure"]


def test_citation_text_mentions_required_citation_layers():
    text = format_citation_text()

    assert "Software" in text
    assert "Article" in text
    assert "Source data" in text
    assert "JASMIN acknowledgement" in text
