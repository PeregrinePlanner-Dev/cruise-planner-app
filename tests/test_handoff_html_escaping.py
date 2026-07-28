"""
Regression tests for the 2026-07-28 fix: render_handoff_html(), render_client_page(),
and _render_template() (used for the Handoff_Email_Template.html advisor email) all
interpolated profile fields directly into HTML with no escaping. Profile slots are
populated by Haiku extraction of freeform traveler chat text, so they're untrusted
input as far as HTML rendering goes -- a traveler typing markup/script in an answer
would previously render unescaped in the advisor's inbox and on both the advisor-facing
and client-facing handoff pages.

These tests guard against that exact class of mistake recurring on any of the three
rendering paths, using a payload that would be unambiguously detectable (and would
execute, if it were ever reflected raw into a browser or an HTML email client).
"""
import app as peregrine_app

PAYLOAD = "<script>alert('xss')</script>"


def _payload_profile(**extra):
    profile = {
        "first_name": PAYLOAD,
        "last_name": "Smith",
        "destination_region": PAYLOAD,
        "party_size": 2,
        "party_composition": PAYLOAD,
        "duration_preference": "7_nights",
        "budget_tier": "budget_7k_plus",
        "generated_narrative": f"Paragraph one.\n\n{PAYLOAD}",
        "departing_from": PAYLOAD,
        "destination_specific": PAYLOAD,
    }
    profile.update(extra)
    return profile


def test_render_handoff_html_escapes_profile_fields():
    profile = _payload_profile()
    html = peregrine_app.render_handoff_html(
        profile, shortlist=[], eliminated=[], advisor_alerts=[], portrait=PAYLOAD
    )
    assert "<script>" not in html, "raw <script> tag leaked into advisor handoff HTML"
    assert "&lt;script&gt;" in html, "expected the payload to be escaped, not just missing"


def test_render_handoff_html_escapes_shortlist_and_eliminated():
    profile = _payload_profile()
    shortlist = [{"name": PAYLOAD, "score": 90, "reasons": [PAYLOAD]}]
    eliminated = [{"name": PAYLOAD, "reason": PAYLOAD}]
    html = peregrine_app.render_handoff_html(
        profile, shortlist=shortlist, eliminated=eliminated, advisor_alerts=[PAYLOAD], portrait=""
    )
    assert "<script>" not in html, "raw <script> tag leaked via shortlist/eliminated/alerts"


def test_render_handoff_html_escapes_raw_slot_data_table():
    """The 'Raw Slot Data' section dumps arbitrary profile keys/values verbatim --
    this is the highest-risk spot since it's the least curated of the three."""
    profile = _payload_profile(some_custom_slot=PAYLOAD)
    html = peregrine_app.render_handoff_html(
        profile, shortlist=[], eliminated=[], advisor_alerts=[], portrait=""
    )
    assert "<script>" not in html


def test_render_client_page_escapes_profile_fields():
    """Note: the client page legitimately contains its own static <script> block
    (the sail-date save handler), so this checks for the specific payload string
    rather than asserting no <script> tag exists at all."""
    rec = {
        "profile_snapshot": _payload_profile(),
        "portrait_text": "",
        "client_token": "test-token-123",
    }
    html = peregrine_app.render_client_page(rec)
    assert PAYLOAD not in html, "raw payload leaked unescaped into client-facing handoff page"
    assert "&lt;script&gt;" in html


def test_render_template_escapes_context_values():
    """Covers the Handoff_Email_Template.html path used by send_handoff_email()."""
    result = peregrine_app._render_template(
        "Hello {{traveler_name}}, destination: {{destination}}",
        {"traveler_name": PAYLOAD, "destination": "Alaska"},
    )
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_esc_helper_handles_none_and_non_strings():
    """Sanity check the helper itself doesn't blow up on the value types actually
    seen in profile dicts (None, int, already-safe strings)."""
    assert peregrine_app._esc(None) == ""
    assert peregrine_app._esc(2) == "2"
    assert peregrine_app._esc("Alaska") == "Alaska"
    assert peregrine_app._esc("<b>") == "&lt;b&gt;"
