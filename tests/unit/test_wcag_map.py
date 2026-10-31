from magnacoda.findings.wcag_map import axe_tags_for, parse_wcag_criteria, resolve_wcag_level


def test_parse_wcag_criteria_single_digit():
    assert parse_wcag_criteria(["wcag111", "cat.text-alternatives"]) == ["1.1.1"]


def test_parse_wcag_criteria_multi_digit_criterion():
    assert parse_wcag_criteria(["wcag1411"]) == ["1.4.11"]


def test_parse_wcag_criteria_dedupes_and_sorts():
    assert parse_wcag_criteria(["wcag143", "wcag111", "wcag143"]) == ["1.1.1", "1.4.3"]


def test_resolve_wcag_level_aa():
    assert resolve_wcag_level(["wcag2a", "wcag2aa", "wcag143"]) == "AA"


def test_resolve_wcag_level_a_only():
    assert resolve_wcag_level(["wcag2a", "wcag111"]) == "A"


def test_resolve_wcag_level_none_for_best_practice():
    assert resolve_wcag_level(["best-practice", "cat.structure"]) is None


def test_axe_tags_for_level_aa_includes_a_and_aa():
    tags = axe_tags_for("2.2", "AA", include_best_practice=False)
    assert "wcag2a" in tags
    assert "wcag2aa" in tags
    assert "wcag2aaa" not in tags
    assert "best-practice" not in tags


def test_axe_tags_for_includes_best_practice_when_requested():
    tags = axe_tags_for("2.0", "A", include_best_practice=True)
    assert "best-practice" in tags
    assert "wcag21a" not in tags
