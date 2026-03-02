from app.analytics.layer3.graph_feature_worker import _provenance_tag_from_counts


def test_provenance_tag_from_counts_real():
    tag, ratio = _provenance_tag_from_counts({"bank": 8, "gov": 2})
    assert tag == "real"
    assert ratio == 1.0


def test_provenance_tag_from_counts_synthetic():
    tag, ratio = _provenance_tag_from_counts({"synthetic": 7})
    assert tag == "synthetic"
    assert ratio == 0.0


def test_provenance_tag_from_counts_mixed():
    tag, ratio = _provenance_tag_from_counts({"synthetic": 3, "bank": 7})
    assert tag == "mixed"
    assert ratio == 0.7
