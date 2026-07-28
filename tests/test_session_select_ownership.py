"""
Regression test for the 2026-07-28 security fix to /api/session/select.

Previously: any client-supplied session_id was restored after only an
existence check against the database -- a leaked or guessed UUID (logs,
Sentry breadcrumbs, referrer headers) was replayable forever to pull up
someone else's saved trip data with no proof the caller was ever legitimately
offered that session.

Now: the session_id must be one of the candidates this exact browser was
actually offered via /api/session/lookup-by-email in the same signed session
cookie (session["pending_email_matches"]).
"""
import app as peregrine_app


def test_unoffered_session_id_is_rejected(monkeypatch):
    """A session_id that was never offered to this browser must be rejected,
    even if it's a real, existing session_id in the database."""
    # If the ownership check is missing/broken, the code would fall through
    # to sb_get -- fail loudly if that happens, rather than silently passing
    # over a live network call in a unit test.
    def _unexpected_sb_get(table, params=None):
        raise AssertionError(
            "sb_get should never be reached -- the ownership check should "
            "reject this session_id before any database lookup happens."
        )
    monkeypatch.setattr(peregrine_app, "sb_get", _unexpected_sb_get)

    client = peregrine_app.app.test_client()
    with client.session_transaction() as sess:
        sess["pending_email_matches"] = [
            {"session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "summary": "Trip A"},
        ]

    resp = client.post(
        "/api/session/select",
        json={"session_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"},  # never offered
    )
    assert resp.status_code == 404
    assert resp.get_json()["status"] == "not_found"


def test_offered_session_id_is_accepted(monkeypatch):
    """A session_id that WAS offered via the email lookup should still work
    -- the fix must not break the legitimate multi-match flow."""
    restored = {}

    def _fake_sb_get(table, params=None):
        if table == "planning_sessions":
            return [{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}]
        return []

    def _fake_restore_session(session_id):
        restored["session_id"] = session_id

    monkeypatch.setattr(peregrine_app, "sb_get", _fake_sb_get)
    monkeypatch.setattr(peregrine_app, "_restore_session", _fake_restore_session)

    client = peregrine_app.app.test_client()
    with client.session_transaction() as sess:
        sess["pending_email_matches"] = [
            {"session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "summary": "Trip A"},
        ]

    resp = client.post(
        "/api/session/select",
        json={"session_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "matched"
    assert restored["session_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
