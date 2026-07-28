"""
Regression test for the 2026-07-28 token-cost fix to build_system_blocks().

Previously: BLOCK_INSURANCE + BLOCK_EMBARK_DOCS + BLOCK_LOGISTICS (~16.6K
tokens combined) all loaded together the moment ANY ONE of
home_airport/travel_mode/travel_documents/travel_insurance was set on the
profile -- e.g. a traveler who only mentioned their home airport paid for
insurance and embark-docs content that was never relevant to them. This is
the same always-loaded-bloat pattern the A1a lifestyle-block split (see
BLOCK_LIFESTYLE_KIDS/SPA/LOYALTY/CASINO/PHOTOGRAPHY) was built to avoid.

These tests guard against the bundling regressing back to all-or-nothing.
"""
import app as peregrine_app


def _blocks_text(profile):
    blocks = peregrine_app.build_system_blocks(profile)
    return "\n".join(b["text"] for b in blocks)


def test_home_airport_only_loads_logistics_not_insurance_or_docs():
    combined = _blocks_text({"home_airport": "JFK"})
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" in combined
    assert "WHY INSURANCE MATTERS" not in combined
    assert "ONLINE CHECK-IN" not in combined


def test_travel_mode_only_loads_logistics_not_insurance_or_docs():
    combined = _blocks_text({"travel_mode": "flying"})
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" in combined
    assert "WHY INSURANCE MATTERS" not in combined
    assert "ONLINE CHECK-IN" not in combined


def test_insurance_only_loads_insurance_not_logistics_or_docs():
    combined = _blocks_text({"travel_insurance": "no_policy"})
    assert "WHY INSURANCE MATTERS" in combined
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" not in combined
    assert "ONLINE CHECK-IN" not in combined


def test_travel_documents_only_loads_embark_docs_not_insurance_or_logistics():
    combined = _blocks_text({"travel_documents": "has_passport"})
    assert "ONLINE CHECK-IN" in combined
    assert "WHY INSURANCE MATTERS" not in combined
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" not in combined


def test_all_four_signals_load_all_three_blocks():
    """Parity check: when every Phase-4 topic has genuinely come up, all
    three blocks should still be present -- the fix changes *when* content
    loads, not what's available once it's actually relevant."""
    combined = _blocks_text({
        "home_airport": "JFK",
        "travel_mode": "flying",
        "travel_documents": "has_passport",
        "travel_insurance": "no_policy",
    })
    assert "WHY INSURANCE MATTERS" in combined
    assert "ONLINE CHECK-IN" in combined
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" in combined


def test_no_phase4_signals_loads_none_of_the_three_blocks():
    combined = _blocks_text({"destination_region": "caribbean"})
    assert "WHY INSURANCE MATTERS" not in combined
    assert "ONLINE CHECK-IN" not in combined
    assert "THE OPTIONS AND WHEN EACH MAKES SENSE" not in combined
