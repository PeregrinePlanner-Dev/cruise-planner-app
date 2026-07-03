"""
Smoke + hard-filter tests for matching.py's run_matching().

Uses a small synthetic fixture instead of hitting the real Supabase
cruise_lines/characteristics tables, so this runs offline and fast --
load_line_profiles() (the only function that makes a network call) is
monkeypatched out.

This is a starting point, not full coverage of MATCHING_RULES.md -- it
checks the shape of run_matching()'s output and one clear, well-defined
hard filter (adult-only lines get eliminated for families with children).
Expanding this to cover more of the scoring/elimination rules is Phase 2/3
territory, not this pass.
"""
import matching

FIXTURE_LINES = {
    1: {"cruise_line_id": 1, "slug": "family-line", "name": "Family Line", "environment": "mainstream"},
    2: {"cruise_line_id": 2, "slug": "adults-only-line", "name": "Adults Only Line", "environment": "premium"},
}
FIXTURE_PROFILES = {
    1: {"family_children": "child_centric_mega"},
    2: {"family_children": "adult_only"},
}


def _patch_load_line_profiles(monkeypatch):
    monkeypatch.setattr(
        matching,
        "load_line_profiles",
        lambda: (dict(FIXTURE_LINES), dict(FIXTURE_PROFILES)),
    )


def test_family_with_children_eliminates_adult_only_line(monkeypatch):
    _patch_load_line_profiles(monkeypatch)
    result = matching.run_matching({"party_composition": "family", "has_children": True})

    eliminated_slugs = {e["slug"] for e in result["eliminated"]}
    shortlist_slugs = {s["slug"] for s in result["shortlist"]}

    assert "adults-only-line" in eliminated_slugs, (
        "an adult-only line should be hard-eliminated when the traveler has children"
    )
    assert "adults-only-line" not in shortlist_slugs


def test_family_with_children_keeps_family_friendly_line(monkeypatch):
    _patch_load_line_profiles(monkeypatch)
    result = matching.run_matching({"party_composition": "family", "has_children": True})

    shortlist_slugs = {s["slug"] for s in result["shortlist"]}
    assert "family-line" in shortlist_slugs


def test_run_matching_returns_expected_shape(monkeypatch):
    _patch_load_line_profiles(monkeypatch)
    result = matching.run_matching({"party_composition": "couple"})

    assert "shortlist" in result
    assert "eliminated" in result
    assert "advisor_alerts" in result
    assert isinstance(result["shortlist"], list)
    assert isinstance(result["eliminated"], list)
    assert isinstance(result["advisor_alerts"], list)


def test_run_matching_does_not_crash_on_empty_profile(monkeypatch):
    """An empty profile is a realistic input (very first turns of a
    conversation, before much has been collected) -- it should degrade
    gracefully, not raise."""
    _patch_load_line_profiles(monkeypatch)
    result = matching.run_matching({})
    assert isinstance(result, dict)
