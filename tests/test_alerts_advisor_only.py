"""
Regression tests for K22 (found 2026-07-03): the health_context alert's
headline claimed "(advisor only)" in its display text but never set the
advisor_only key the actual filter checks (`/api/alerts` and
`/api/panel-refresh` both do `[a for a in all_alerts if not
a.get("advisor_only")]`), so it silently passed through to the traveler's
screen despite its own headline saying otherwise.

These tests guard against that exact class of mistake -- both the specific
alert that already broke, and the general pattern (any future alert whose
text claims advisor-only status must actually set the flag).
"""
import app as peregrine_app


def _user_facing_filter(alerts):
    """Mirrors the exact filter used by /api/alerts and /api/panel-refresh
    in app.py. If that filter logic ever changes, update this to match --
    the point is testing what travelers actually see, not a copy that could
    drift from the real thing."""
    return [a for a in alerts if not a.get("advisor_only")]


def _profile_that_triggers_every_conditional_alert():
    """One profile dict designed to make as many build_alerts() branches
    fire as possible, so these tests inspect the full realistic set of
    alerts rather than just the one that already broke."""
    return {
        "party_composition": "solo",
        "children_ages": [0],
        "dietary_requirements": "gluten-free",
        "trip_significance": "milestone",
        "budget_tier": "budget_under_2k",
        "destination_region": "mediterranean",
        "trip_occasion": "honeymoon",
        "mobility_needs": "wheelchair",
        "health_context": "manages a heart condition with medication",
        "travel_insurance": "no_policy",
        "travel_mode": "flying",
        "departing_from": "JFK",
        "port_interests": "santorini",
        "budget_all_in": True,
        "home_airport": None,
        "travel_documents": "no_passport",
        "party_composition_narrative": "grandmother traveling with grandchild without both parents",
        "travel_anxiety": "seasick",
        "budget_composition_awareness": False,
        "ports_of_interest": "nassau",
    }


def test_no_alert_claims_advisor_only_without_the_flag():
    """General regression guard: if ANY alert's headline text says
    'advisor only' / 'advisor-only', it must also set advisor_only=True.
    This catches the K22 bug recurring on a *different* alert in the
    future, not just the one that already broke."""
    alerts = peregrine_app.build_alerts(_profile_that_triggers_every_conditional_alert())
    assert alerts, "expected build_alerts() to produce at least one alert for this profile"

    offenders = []
    for alert in alerts:
        headline = (alert.get("headline") or "").lower()
        claims_advisor_only = "advisor only" in headline or "advisor-only" in headline
        if claims_advisor_only and not alert.get("advisor_only"):
            offenders.append(alert["headline"])

    assert not offenders, (
        f"Alert(s) claim advisor-only in their headline text but don't set "
        f"advisor_only=True, so they will leak to travelers: {offenders}"
    )


def test_advisor_only_alerts_never_reach_traveler_filter():
    """Direct check: whatever IS correctly flagged advisor_only must be
    excluded by the same filter logic the app actually uses."""
    profile = {"health_context": "manages a heart condition with medication"}
    alerts = peregrine_app.build_alerts(profile)
    user_facing = _user_facing_filter(alerts)

    advisor_only_headlines = {a["headline"] for a in alerts if a.get("advisor_only")}
    user_facing_headlines = {a["headline"] for a in user_facing}

    leaked = advisor_only_headlines & user_facing_headlines
    assert not leaked, f"advisor_only alert(s) leaked into the traveler-facing filter: {leaked}"


def test_health_context_alert_specifically_is_advisor_only_and_hidden():
    """The exact K22 regression: this specific alert must be flagged
    advisor_only and must never appear in the filtered/user-facing list."""
    profile = {"health_context": "manages a heart condition with medication"}
    alerts = peregrine_app.build_alerts(profile)

    health_alert = next(
        (a for a in alerts if a["headline"] == "Health context noted (advisor only)"), None
    )
    assert health_alert is not None, "expected the health_context alert to fire for this profile"
    assert health_alert.get("advisor_only") is True

    user_facing = _user_facing_filter(alerts)
    assert "Health context noted (advisor only)" not in {a["headline"] for a in user_facing}
