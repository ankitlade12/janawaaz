from janawaaz.pipeline.matching import span_in_text


def test_exact_span_passes():
    text = "The proposed tariff ceiling applies to all rural broadband subscribers."
    assert span_in_text("rural broadband subscribers", text)


def test_whitespace_normalized_span_passes():
    # PDF extraction often breaks lines mid-sentence.
    text = "applies to all rural\nbroadband   subscribers in India"
    assert span_in_text("rural broadband subscribers", text)


def test_paraphrased_span_fails():
    text = "The proposed tariff ceiling applies to all rural broadband subscribers."
    assert not span_in_text("village internet users", text)


def test_empty_span_fails():
    assert not span_in_text("", "anything")
