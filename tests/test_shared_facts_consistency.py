"""
Guards against the duplication bug fixed 2026-07-03: gratuities, medical
evacuation cost, off-site parking, and yellow-fever/ICVP facts used to be
hardcoded separately in build_alerts() and build_intel() with different
(sometimes contradictory) numbers. They're now built from shared constants
(GRATUITY_RATES_BY_LINE_TEXT, MEDICAL_EVACUATION_COST_TEXT, etc. -- defined
just above build_alerts() in app.py). These tests make sure a future edit
can't quietly re-introduce a mismatch between the alert and intel versions
of the same fact.
"""
import re

import app as peregrine_app


def _dollar_figures(text):
    """Extract every dollar figure ($X, $X,XXX, $X.XX) from a string, as a
    set so ordering/duplicates in the text don't matter -- only whether the
    same set of numbers appears in both places."""
    return set(re.findall(r"\$[\d,]+(?:\.\d+)?", text or ""))


def test_gratuity_figures_match_between_alert_and_intel():
    alert_profile = {
        "budget_all_in": True,
        "budget_composition_awareness": False,
    }
    alerts = peregrine_app.build_alerts(alert_profile)
    gratuity_alert = next((a for a in alerts if "gratuities" in a["headline"].lower()), None)
    assert gratuity_alert is not None, "expected the gratuities alert to fire for this profile"

    intel_profile = {
        "cruise_line_shortlist": ["carnival"],  # makes build_intel()'s late_stage True
        "budget_composition_awareness": False,
        "budget_tier": "budget_4k_7k",
    }
    intel = peregrine_app.build_intel(intel_profile)
    gratuity_intel = next((i for i in intel if "gratuities" in i["headline"].lower()), None)
    assert gratuity_intel is not None, "expected the gratuities intel card to fire for this profile"

    alert_figures = _dollar_figures(gratuity_alert["body"])
    intel_figures = _dollar_figures(gratuity_intel["body"])
    assert alert_figures == intel_figures, (
        "Gratuity alert and intel card are quoting different dollar figures again -- "
        f"alert had {alert_figures}, intel had {intel_figures}. Both should be built "
        "from GRATUITY_RATES_BY_LINE_TEXT."
    )


def test_medical_evacuation_figures_match_between_alert_and_intel():
    alerts = peregrine_app.build_alerts({"travel_insurance": "no_policy"})
    intel = peregrine_app.build_intel({"travel_insurance": "no_policy"})

    evac_alert = next(a for a in alerts if "no travel insurance" in a["headline"].lower())
    evac_intel = next(i for i in intel if "medical evacuation" in i["headline"].lower())

    alert_figures = _dollar_figures(evac_alert["body"])
    intel_figures = _dollar_figures(evac_intel["body"])
    assert alert_figures == intel_figures, (
        f"Medical evacuation figures diverged again -- alert had {alert_figures}, "
        f"intel had {intel_figures}."
    )


def test_viking_not_miscategorized_as_gratuities_included():
    """Regression check: the gratuities intel card used to list Viking
    alongside Regent/Silversea/Seabourn as 'includes gratuities in the
    fare', which was wrong -- Viking charges $17/day separately. Confirm
    Viking never appears in the 'included in fare' sentence."""
    assert "Viking" not in peregrine_app.GRATUITY_INCLUDED_IN_FARE_TEXT
    assert "Viking" in peregrine_app.GRATUITY_RATES_BY_LINE_TEXT
    assert "NOT included in fare" in peregrine_app.GRATUITY_RATES_BY_LINE_TEXT


def test_offsite_parking_figures_match_between_alert_and_intel():
    alerts = peregrine_app.build_alerts({"travel_mode": "driving"})
    intel = peregrine_app.build_intel({"travel_mode": "driving", "departing_from": "Miami"})

    parking_alert = next(a for a in alerts if "parking plan" in a["headline"].lower())
    parking_intel = next(i for i in intel if "off-site" in i["headline"].lower())

    assert _dollar_figures(parking_alert["body"]) == _dollar_figures(parking_intel["body"])
