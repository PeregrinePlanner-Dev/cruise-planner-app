"""
test_db_to_email.py
-------------------
Pulls a real voyage_profile from Supabase, maps it to the
Handoff_Email_Template.html variables, renders the HTML,
and saves it to test_handoff_from_db.html.

Run from the app/ directory:
    python test_db_to_email.py              # richest recent profile
    python test_db_to_email.py --list       # show all profiles ranked by richness
    python test_db_to_email.py <session_id> # render a specific session
"""

import re, json, sys, os, requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
REST         = f"{SUPABASE_URL}/rest/v1"
HEADERS      = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

TEMPLATE_PATH = Path(__file__).parent.parent / "Handoff_Email_Template.html"
OUTPUT_PATH   = Path(__file__).parent.parent / "test_handoff_from_db.html"


# ── Supabase helpers ───────────────────────────────────────────────────────

def sb_get(table, params=None):
    r = requests.get(f"{REST}/{table}", headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


# ── Fetch profile ──────────────────────────────────────────────────────────

KEY_SLOTS = [
    "first_name", "destination_region", "party_size", "budget_tier",
    "duration_preference", "cabin_preference", "dream_image",
    "cruise_line_shortlist", "generated_narrative", "topics_covered",
    "what_they_fear_wont_work", "emotional_driver", "home_city",
    "travel_dates", "travel_month",
]

def fetch_profile(session_id=None):
    if session_id:
        rows = sb_get("voyage_profiles", {
            "session_id": f"eq.{session_id}",
            "select": "session_id,profile,created_at",
            "limit": "1",
        })
    else:
        rows = sb_get("voyage_profiles", {
            "select": "session_id,profile,created_at",
            "order":  "created_at.desc",
            "limit":  "50",
        })

    if not rows:
        print("No profile rows found.")
        return None, None

    # Find the richest profile
    best = None
    best_score = -1
    for row in rows:
        p = row.get("profile") or {}
        if isinstance(p, str):
            p = json.loads(p)
        score = sum(1 for v in p.values() if v is not None)
        if score > best_score:
            best_score = score
            best = (row["session_id"], p)

    return best


def list_profiles():
    """Print all profiles ranked by slot richness."""
    rows = sb_get("voyage_profiles", {
        "select": "session_id,profile,created_at",
        "order":  "created_at.desc",
        "limit":  "50",
    })
    scored = []
    for row in rows:
        p = row.get("profile") or {}
        if isinstance(p, str):
            p = json.loads(p)
        filled = sum(1 for v in p.values() if v is not None)
        key_present = [k for k in KEY_SLOTS if p.get(k)]
        scored.append((filled, row["session_id"], row["created_at"][:10], key_present))
    scored.sort(reverse=True)
    print(f"\n{'Slots':>5}  {'Created':<12} {'Session ID':<38} Key fields")
    print("-" * 110)
    for slots, sid, date, keys in scored:
        print(f"{slots:>5}  {date:<12} {sid:<38} {', '.join(keys) or '—'}")
    print(f"\nTotal profiles: {len(scored)}")


# ── Pull matching snapshot if available ────────────────────────────────────

def fetch_handoff_snapshot(session_id):
    """If a handoff_record exists for this session, grab snapshots from it."""
    try:
        rows = sb_get("handoff_records", {
            "session_id": f"eq.{session_id}",
            "select": "shortlist_snapshot,eliminated_snapshot,advisor_alerts_snapshot,portrait_text",
            "order":  "generated_at.desc",
            "limit":  "1",
        })
        return rows[0] if rows else {}
    except Exception:
        return {}


# ── Budget display helper ──────────────────────────────────────────────────

BUDGET_MAP = {
    "budget_under_2k": "Under $2,000 per person",
    "budget_2k_4k":    "$2,000 – $4,000 per person",
    "budget_4k_7k":    "$4,000 – $7,000 per person",
    "budget_7k_plus":  "$7,000+ per person",
}

def derive_budget_display(profile):
    tier = profile.get("budget_tier")
    if tier and tier in BUDGET_MAP:
        return BUDGET_MAP[tier]
    low  = profile.get("budget_low")
    high = profile.get("budget_high")
    if low and high:
        return f"${int(low):,} – ${int(high):,} all-in"
    if low:
        return f"${int(low):,}+"
    return "Not specified"


# ── Status color helper ────────────────────────────────────────────────────

STATUS_COLORS = {
    "needs_booking":        "#B05020",
    "already_booked":       "#3A7D5B",
    "cruise_air_requested": "#2E6DA4",
    "driving":              "#222222",
    "not_needed":           "#555555",
    "not_discussed":        "#999999",
}
DISPLAY_LABELS = {
    "needs_booking":        "Needs booking",
    "already_booked":       "Already booked",
    "cruise_air_requested": "Cruise air requested",
    "driving":              "Driving",
    "not_needed":           "Not needed",
    "not_discussed":        "Not discussed",
}

def status_display(val):
    if not val:
        return "Not discussed", STATUS_COLORS["not_discussed"]
    label = DISPLAY_LABELS.get(val, val.replace("_", " ").title())
    color = STATUS_COLORS.get(val, "#555555")
    return label, color


# ── Shortlist HTML builder ─────────────────────────────────────────────────

def build_shortlist_html(shortlist):
    if not shortlist:
        return "", False
    rows = []
    for r in shortlist[:3]:
        name    = r.get("name", "—")
        score   = r.get("score", "—")
        reasons = r.get("reasons", [])
        why     = "; ".join(reasons[:2]) if reasons else r.get("why", "—")
        rows.append(
            f'<tr style="border-bottom:1px solid #e8eef4;">'
            f'<td style="font-family:Arial,sans-serif;font-size:14px;font-weight:bold;color:#1B3A5C;padding:8px 8px 8px 0;vertical-align:top;">{name}</td>'
            f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#2E6DA4;font-weight:bold;padding:8px;vertical-align:top;text-align:center;">{score}</td>'
            f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#555555;line-height:1.5;padding:8px 0;vertical-align:top;">{why}</td>'
            f'</tr>'
        )
    return "".join(rows), True


# ── Alert model builder ────────────────────────────────────────────────────
# Stub: builds basic discussed/consideration/open items from profile signals.
# Replace with full build_handoff_alerts() once HANDOFF_ALERT_SPEC is wired in.

def build_alert_html(profile, advisor_alerts=None):
    discussed      = []
    consideration  = []
    open_items     = []

    # Topics covered (once topics_covered slot is wired)
    topics_covered = profile.get("topics_covered") or []

    # Insurance signals
    if profile.get("pre_existing_condition"):
        if "insurance_waiver_window" in topics_covered:
            discussed.append("Travel insurance — pre-existing condition waiver window discussed. "
                             "Client is aware of the 10–21 day purchase requirement from first deposit.")
        else:
            consideration.append("Insurance — pre-existing condition flagged but waiver window not confirmed. "
                                 "Raise before any deposit discussion.")

    if profile.get("age_bracket") in ("senior", "65_plus") or (profile.get("traveler_age") or 0) >= 65:
        if "insurance_primary_medical" in topics_covered:
            discussed.append("Insurance — primary medical coverage discussed for senior traveler. "
                             "Client understands Medicare ends 12 miles offshore.")
        else:
            consideration.append("Insurance — primary vs. excess medical not yet addressed. "
                                 "Medicare ends 12 miles offshore — worth confirming as early priority.")

    # Passport
    if profile.get("travel_documents") in ("passport_book", "passport_card"):
        if "passport_validity" in topics_covered:
            discussed.append("Passport validity — traveler confirmed valid passport.")
        # else silently skip — don't flag as consideration unless expiring

    if profile.get("travel_documents") == "expiring_soon":
        consideration.append("Passport — client mentioned it may be expiring soon. Confirm renewal timeline before booking.")

    # Minor non-parent
    if profile.get("minor_non_parent_flag"):
        if "minor_documentation" in topics_covered:
            discussed.append("Minor documentation — advisor-supervised documentation scenario discussed.")
        else:
            consideration.append("Minor traveling with non-parent — documentation requirements not yet confirmed. "
                                 "Notarized consent letter and custody documentation may be required at pier.")

    # Advisor alerts from matching engine (flat strings from old model)
    if advisor_alerts:
        for alert in advisor_alerts[:3]:
            if alert not in [d for d in discussed]:
                consideration.append(alert)

    # Open items — uncollected high-value slots
    if not profile.get("cabin_preference"):
        open_items.append("Cabin preference not collected — may have strong views (balcony vs. suite)")
    if not profile.get("dining_relationship"):
        open_items.append("Dining style preference — included vs. specialty-focused affects line ranking")
    if not profile.get("home_city") and not profile.get("home_airport"):
        open_items.append("Home city / departure airport not collected — needed for flight and logistics planning")
    if not profile.get("travel_documents"):
        open_items.append("Passport / travel documents not confirmed")

    def to_html(items):
        return "".join(f"<li>{i}</li>" for i in items) if items else ""

    return to_html(discussed), to_html(consideration), to_html(open_items)


# ── Profile → template variable mapper ────────────────────────────────────

def map_profile_to_template(session_id, profile, snapshot):
    now   = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    first = profile.get("first_name") or ""
    last  = profile.get("last_name")  or ""
    name  = f"{first} {last}".strip() or "Unknown Client"

    # Travel window
    dates  = profile.get("travel_dates") or ""
    month  = profile.get("travel_month") or ""
    year   = str(profile.get("travel_year") or "")
    window = dates or " ".join(filter(None, [month, year])) or "Not specified"

    # Shortlist
    shortlist       = snapshot.get("shortlist_snapshot") or profile.get("cruise_line_shortlist") or []
    eliminated      = snapshot.get("eliminated_snapshot") or []
    advisor_alerts  = snapshot.get("advisor_alerts_snapshot") or []
    portrait        = snapshot.get("portrait_text") or profile.get("generated_narrative") or ""

    shortlist_html, shortlist_fired = build_shortlist_html(shortlist)

    # Narrative
    narrative = portrait or profile.get("narrative") or ""

    # Suggested opener (from emotional_driver + dream_image)
    # emotional_driver may be a list or a string — normalise to string
    opener = ""
    raw_driver   = profile.get("emotional_driver") or profile.get("trip_occasion") or ""
    if isinstance(raw_driver, list):
        emotional_driver = ", ".join(str(x) for x in raw_driver if x)
    else:
        emotional_driver = str(raw_driver).strip()
    dream_image = profile.get("dream_image") or ""
    if isinstance(dream_image, list):
        dream_image = dream_image[0] if dream_image else ""

    if emotional_driver and dream_image:
        opener = (f'They mentioned "{dream_image.rstrip(".")}." '
                  f'The emotional driver is {emotional_driver} — that\'s the opener.')
    elif emotional_driver:
        opener = f'The emotional driver is {emotional_driver}. Lead with that on the first call.'
    elif dream_image:
        opener = f'In their own words: "{dream_image}" — start there.'

    # Ruled out
    negatives    = profile.get("cruise_line_negative_signals") or []
    ruled_html   = "".join(f"<li>{n}</li>" for n in negatives) if negatives else ""

    # Key preferences
    prefs      = profile.get("must_haves") or profile.get("onboard_priorities") or []
    if isinstance(prefs, str):
        prefs = [prefs]
    if profile.get("dining_relationship") == "centerpiece":
        prefs.append("Dining as centerpiece — specialty restaurants matter")
    if profile.get("formality_preference") in ("casual_throughout", "smart_casual"):
        prefs.append(f"No formal nights — {profile['formality_preference'].replace('_',' ')}")
    prefs_html = "".join(f"<li>{p}</li>" for p in prefs[:6]) if prefs else "<li>Not yet collected</li>"

    # Logistics / Getting There
    home_city   = profile.get("home_city") or profile.get("home_airport") or ""
    emb_port    = profile.get("embarkation_port") or ""
    fl_val      = profile.get("flight_status") or "not_discussed"
    arr_val     = profile.get("arrival_timing") or "not_discussed"
    pre_val     = profile.get("pre_cruise_hotel") or ("needs_booking" if profile.get("pre_cruise_hotel_needed") else "not_discussed")
    post_val    = profile.get("post_cruise_hotel") or "not_discussed"

    fl_label,   fl_color   = status_display(fl_val)
    pre_label,  pre_color  = status_display(pre_val)
    post_label, post_color = status_display(post_val)
    arr_label,  _          = status_display(arr_val)

    getting_there_any = any([home_city, emb_port,
                              fl_val != "not_discussed",
                              arr_val != "not_discussed",
                              pre_val != "not_discussed",
                              post_val != "not_discussed"])

    # Alerts
    discussed_html, consideration_html, open_items_html = build_alert_html(profile, advisor_alerts)

    # Completion
    handoff_id = f"PRG-{datetime.now().strftime('%Y%m%d')}-TEST"
    booking    = profile.get("booking_status") or ""

    return {
        # Header
        "advisor_name":       "Hi",
        "traveler_name":      name,
        "traveler_email":     profile.get("email") or profile.get("traveler_email") or "—",
        "conversation_date":  now,

        # Opener / narrative
        "suggested_opener":   opener,
        "generated_narrative": narrative,
        "dream_image":        dream_image,

        # Profile grid
        "destination_region":  profile.get("destination_region") or "Not specified",
        "travel_window":       window,
        "party_composition":   profile.get("party_composition") or str(profile.get("party_size") or "Not specified"),
        "budget_display":      derive_budget_display(profile),
        "duration_preference": profile.get("duration_preference") or "Not specified",
        "cabin_preference":    profile.get("cabin_preference") or "Not specified",
        "experience_level":    (profile.get("experience_tier") or profile.get("travel_experience_level") or "Not specified").replace("_", " ").title(),
        "sea_day_preference":  profile.get("sea_day_preference") or "Not specified",

        # Getting there
        "getting_there_any":   getting_there_any,
        "home_city":           home_city or "Not collected",
        "embarkation_port":    emb_port or "Not yet determined",
        "flight_status":       fl_label,
        "flight_status_color": fl_color,
        "arrival_timing":      arr_label,
        "pre_cruise_hotel":    pre_label,
        "pre_hotel_color":     pre_color,
        "post_cruise_hotel":   post_label,
        "post_hotel_color":    post_color,

        # Preferences + fears
        "ruled_out_html":       ruled_html,
        "key_preferences_html": prefs_html,
        "what_they_fear":       profile.get("what_they_fear_wont_work") or profile.get("fears") or "",

        # Shortlist
        "shortlist_fired":  shortlist_fired,
        "shortlist_html":   shortlist_html,

        # Alerts
        "discussed_html":          discussed_html,
        "for_consideration_html":  consideration_html,
        "open_items_html":         open_items_html,

        # Footer
        "booking_status":        booking,
        "completion_label":      "DB Profile",
        "return_visit":          "",
        "conversation_duration": "",
        "handoff_id":            handoff_id,
    }


# ── Template renderer ──────────────────────────────────────────────────────

def render(template, ctx):
    def replace_if(m):
        var, content = m.group(1).strip(), m.group(2)
        return content if ctx.get(var) else ""

    result = re.sub(
        r'\{\{#if\s+(\w+)\}\}(.*?)\{\{/if\}\}',
        replace_if, template, flags=re.DOTALL
    )

    def replace_var(m):
        val = ctx.get(m.group(1).strip(), "")
        return "" if val is None else str(val)

    return re.sub(r'\{\{(\w+)\}\}', replace_var, result)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        list_profiles()
        sys.exit(0)

    target_session = sys.argv[1] if len(sys.argv) > 1 else None

    result = fetch_profile(target_session)
    if not result or not result[0]:
        print("No usable profile found.")
        sys.exit(1)

    session_id, profile = result
    print(f"\nSession: {session_id}")
    print(f"Populated slots: {[k for k,v in profile.items() if v is not None]}\n")

    snapshot = fetch_handoff_snapshot(session_id)
    if snapshot:
        print(f"Handoff snapshot found (portrait: {'yes' if snapshot.get('portrait_text') else 'no'}, "
              f"shortlist: {len(snapshot.get('shortlist_snapshot') or [])} lines)")
    else:
        print("No prior handoff snapshot — using profile slots only.")

    data     = map_profile_to_template(session_id, profile, snapshot)
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = render(template, data)

    OUTPUT_PATH.write_text(rendered, encoding="utf-8")

    # Check for unresolved tokens
    remaining = re.findall(r'\{\{[^}]+\}\}', rendered)
    print(f"\nOutput: {OUTPUT_PATH}")
    print(f"Unresolved tokens: {len(remaining)}")
    if remaining:
        for t in set(remaining):
            print(f"  MISSING: {t}")
    else:
        print("All tokens resolved.")
    print("\nOpen test_handoff_from_db.html in a browser to review.")
