# matching.py -- Cruise line matching engine
# Applies hard filters and soft weights from MATCHING_RULES.md
# Called by /api/match route in app.py

import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SB_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

REST = f"{SUPABASE_URL}/rest/v1"


# ── Supabase helpers ───────────────────────────────────────────────────────

def sb_get(table, params=None):
    r = requests.get(f"{REST}/{table}", headers=SB_HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def load_line_profiles():
    """
    Returns two structures:
      lines     = {cruise_line_id: {slug, name, environment}}
      profiles  = {cruise_line_id: {char_slug: label_slug}}
    Uses a single SQL query via Supabase RPC to avoid pagination issues.
    """
    # All MVP active lines
    raw_lines = sb_get("cruise_lines", {
        "mvp_active": "eq.true",
        "select":     "cruise_line_id,slug,name,environment",
        "limit":      "200",
    })
    lines = {r["cruise_line_id"]: r for r in raw_lines}

    # Characteristics: id -> slug
    raw_chars = sb_get("characteristics", {
        "select": "characteristic_id,slug",
        "limit":  "50",
    })
    char_map = {r["characteristic_id"]: r["slug"] for r in raw_chars}

    # Labels: id -> slug
    raw_labels = sb_get("labels", {
        "select": "label_id,slug",
        "limit":  "500",
    })
    label_map = {r["label_id"]: r["slug"] for r in raw_labels}

    # All LCAs — raw IDs, map locally
    raw_lcas = sb_get("line_characteristic_assignments", {
        "select": "cruise_line_id,characteristic_id,label_id",
        "limit":  "2000",
    })

    profiles = {lid: {} for lid in lines}
    for lca in raw_lcas:
        lid        = lca["cruise_line_id"]
        char_slug  = char_map.get(lca["characteristic_id"])
        label_slug = label_map.get(lca["label_id"])
        if lid in profiles and char_slug and label_slug:
            profiles[lid][char_slug] = label_slug

    return lines, profiles


# ── Matching engine ────────────────────────────────────────────────────────

def run_matching(profile):
    """
    profile: dict of slot values from voyage_profiles
    Returns: {
        shortlist: [{slug, name, score, reasons, advisor_flags}],
        eliminated: [{slug, name, reason}],
        advisor_alerts: [str],
    }
    """
    lines, lp = load_line_profiles()

    eliminated   = []   # {line_id, slug, name, reason}
    advisor_alerts = []
    scores       = {lid: 0 for lid in lines}
    reasons      = {lid: [] for lid in lines}

    def elim(lid, reason):
        if lid in lines:
            eliminated.append({
                "slug":   lines[lid]["slug"],
                "name":   lines[lid]["name"],
                "reason": reason,
            })
            del lines[lid]
            del scores[lid]
            del reasons[lid]

    def boost(lid, points, reason):
        if lid in scores:
            scores[lid] += points
            reasons[lid].append(reason)

    def deprioritize(lid, points, reason):
        if lid in scores:
            scores[lid] -= points

    # Helper: find lines with a given characteristic label
    def lines_with(char_slug, label_slug):
        return [lid for lid in lines if lp.get(lid, {}).get(char_slug) == label_slug]

    def lines_without(char_slug, label_slug):
        return [lid for lid in lines if lp.get(lid, {}).get(char_slug) != label_slug]

    def char_val(lid, char_slug):
        return lp.get(lid, {}).get(char_slug)

    # ── Extract profile values ─────────────────────────────────────────────

    party        = str(profile.get("party_composition") or "").lower()
    has_children = profile.get("has_children")
    children_ages = profile.get("children_ages") or []
    mobility     = str(profile.get("mobility_needs") or "").lower()
    destination  = str(profile.get("destination_region") or "").lower()
    atmosphere   = str(profile.get("atmosphere_preference") or "").lower()
    budget       = str(profile.get("budget_tier") or "").lower()
    onboard      = profile.get("onboard_priorities") or []
    if isinstance(onboard, str):
        onboard = [onboard]
    onboard = [o.lower() for o in onboard]
    lines_sailed = profile.get("lines_sailed") or []
    preferred    = profile.get("preferred_lines") or []
    cruise_exp   = str(profile.get("cruise_experience") or "").lower()
    formality    = str(profile.get("atmosphere_preference") or "").lower()
    cabin        = str(profile.get("cabin_preference") or "").lower()

    # New emotional/motivational signals
    emotional_driver = profile.get("emotional_driver") or []
    if isinstance(emotional_driver, str):
        emotional_driver = [emotional_driver]
    emotional_driver = [e.lower() for e in emotional_driver]

    trip_occasion    = str(profile.get("trip_occasion") or "").lower()
    budget_flex      = str(profile.get("budget_flexibility") or "").lower()
    trip_significance = str(profile.get("trip_significance") or "").lower()

    # ── PHASE 1: Party / Accessibility ────────────────────────────────────

    # Family with children — hard filter adult-only lines
    if has_children or "famil" in party or "child" in party or "kid" in party:
        for lid in list(lines):
            if char_val(lid, "family_children") == "adult_only":
                elim(lid, "Adult-only line — not compatible with children")
        for lid in list(lines):
            if char_val(lid, "family_children") in ("child_centric_mega", "balanced_multi_gen"):
                boost(lid, 2, "Strong family/children programming")

    # Children ages
    if isinstance(children_ages, list) and children_ages:
        ages = [int(a) for a in children_ages if str(a).isdigit()]
        if any(a < 2 for a in ages):
            advisor_alerts.append(
                "Guest has children under 2 — confirm minimum age policy per shortlisted line. "
                "Disney and Royal Caribbean are most accommodating."
            )
        if any(2 <= a <= 12 for a in ages):
            for lid in list(lines):
                if char_val(lid, "family_children") == "child_centric_mega":
                    boost(lid, 2, "Full kids club for children 2–12")

    # Solo traveler
    if "solo" in party:
        advisor_alerts.append(
            "Solo traveler — flag single supplement pricing. Surface Norwegian Studios "
            "(no supplement, dedicated lounge) and other solo-friendly cabin programs."
        )

    # Mobility — wheelchair
    if "wheelchair" in mobility:
        advisor_alerts.append(
            "Wheelchair user — confirm ADA cabin availability per ship. "
            "Flag tender port itineraries as inaccessible."
        )
        for lid in list(lines):
            if char_val(lid, "hull_type") in ("boutique_ocean_yacht", "polar_expedition"):
                elim(lid, "Expedition hull with mandatory Zodiac landings — incompatible with wheelchair")

    # Mobility — scooter
    if "scooter" in mobility:
        advisor_alerts.append(
            "Scooter user — confirm elevator car size and scooter storage. "
            "Flag tender port itineraries."
        )

    # ── PHASE 2: Destination ───────────────────────────────────────────────

    polar     = any(x in destination for x in ["antarct", "arctic", "polar"])
    river     = any(x in destination for x in ["river", "danube", "rhine", "seine", "douro", "elbe"])
    galapagos = "galapagos" in destination
    alaska    = "alaska" in destination

    if polar:
        for lid in list(lines):
            if char_val(lid, "hull_type") != "polar_expedition":
                elim(lid, "Polar destination requires expedition hull")

    if river:
        for lid in list(lines):
            if char_val(lid, "hull_type") != "river_inland":
                elim(lid, "River destination requires river/inland waterway hull")

    if galapagos:
        for lid in list(lines):
            if char_val(lid, "hull_type") not in ("boutique_ocean_yacht", "polar_expedition"):
                elim(lid, "Galapagos requires small expedition or boutique hull")

    if alaska:
        for lid in list(lines):
            if char_val(lid, "hull_type") == "river_inland":
                elim(lid, "River hull not suitable for Alaska ocean itinerary")

    # Non-river destination — eliminate river lines
    if not river and destination:
        for lid in list(lines):
            if lines[lid]["environment"] == "river":
                elim(lid, "River cruise line — not suitable for ocean destination")

    # ── PHASE 3: Experience / Prior sailings ──────────────────────────────

    # First-time cruiser
    if cruise_exp in ("first", "no", "never", "first time", "first-time"):
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("expedition", "ultra_luxury"):
                deprioritize(lid, 1, "First-time cruiser — niche/expedition lines deprioritized")
        advisor_alerts.append(
            "First-time cruiser — set expectations on ship scale, muster drill, "
            "and embarkation process at handoff."
        )

    # Disney — only relevant when children are present
    if not has_children and "famil" not in party and "child" not in party and "kid" not in party:
        for lid in list(lines):
            if lines[lid]["slug"] == "disney":
                elim(lid, "Disney Cruise Line — family-focused line not recommended without children")

    # Virgin Voyages — adults-only, not suitable for families
    if has_children or "famil" in party or "child" in party or "kid" in party:
        for lid in list(lines):
            if lines[lid]["slug"] == "virgin_voyages":
                elim(lid, "Virgin Voyages — adults-only line, not suitable for families with children")

    # Lines sailed / preferred — strong signal, not just +1
    all_mentioned = []
    if isinstance(lines_sailed, list):
        all_mentioned.extend(lines_sailed)
    if isinstance(preferred, list):
        all_mentioned.extend(preferred)
    for mentioned in all_mentioned:
        mentioned_lower = str(mentioned).lower()
        for lid in list(lines):
            if mentioned_lower in lines[lid]["slug"] or mentioned_lower in lines[lid]["name"].lower():
                boost(lid, 4, "Explicitly discussed — past guest or stated preference")

    # ── PHASE 3: Atmosphere preference ────────────────────────────────────

    if atmosphere == "lively_social":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier == "mass_market":
                boost(lid, 2, "Lively atmosphere — mass market lines preferred")
            elif tier == "premium":
                boost(lid, 1, "Lively atmosphere — active premium lines preferred")
            elif tier in ("ultra_luxury", "luxury"):
                deprioritize(lid, 1, "Lively atmosphere preference pulls away from ultra-luxury")

    elif atmosphere == "relaxed_refined":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("luxury", "ultra_luxury", "upper_premium", "premium"):
                boost(lid, 2, "Relaxed/refined atmosphere — premium+ lines preferred")
            elif tier == "mass_market":
                deprioritize(lid, 2, "Relaxed/refined preference — mass market deprioritized")

    # ── PHASE 3: Onboard priorities ───────────────────────────────────────

    if any(x in onboard for x in ["entertainment", "activities", "shows", "nightlife"]):
        for lid in list(lines):
            fp = char_val(lid, "entertainment_footprint")
            if fp in ("mega_production", "full_casino_smoking"):
                boost(lid, 2, "Entertainment priority — strong entertainment footprint")
        if any(x in onboard for x in ["nightlife", "party", "night"]):
            advisor_alerts.append(
                "Nightlife priority — weight toward Norwegian, Virgin Voyages, Royal Caribbean."
            )

    if any(x in onboard for x in ["dining", "food", "restaurant", "culinary"]):
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 2, "Dining priority — premium+ dining programs preferred")
        dining_lines = ["oceania", "regent", "viking", "cunard"]
        for lid in list(lines):
            if any(d in lines[lid]["slug"] for d in dining_lines):
                boost(lid, 1, "Known dining differentiator line")

    if any(x in onboard for x in ["destination", "port", "explore", "culture", "history"]):
        for lid in list(lines):
            fp = char_val(lid, "entertainment_footprint")
            if fp == "international_rotating":
                boost(lid, 2, "Destination focus — enrichment-forward lines preferred")

    if any(x in onboard for x in ["spa", "wellness", "relax"]):
        for lid in list(lines):
            spa = char_val(lid, "spa_wellness")
            if spa in ("thermal_mega", "distributed_vip"):
                boost(lid, 2, "Spa/wellness priority — strong spa program")

    if any(x in onboard for x in ["kids", "family", "children", "teen"]):
        for lid in list(lines):
            if char_val(lid, "family_children") == "child_centric_mega":
                boost(lid, 2, "Family programming priority")

    # ── PHASE 5: Budget → Experience Tier filter ──────────────────────────

    # ── Duration preference ───────────────────────────────────────────────

    duration = str(profile.get("duration_preference") or "").lower()

    if any(x in duration for x in ["10", "11", "12", "13", "14", "longer", "long", "extended", "grand"]):
        # Longer sailings — boost lines with strong extended itinerary programs
        long_itinerary_lines = ["holland_america", "azamara", "cunard", "oceania", "regent", "silversea", "viking_ocean"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in long_itinerary_lines):
                boost(lid, 2, "Extended duration preference — strong longer itinerary program")
        # Deprioritize lines known for mostly 7-night loops
        short_loop_lines = ["carnival", "norwegian", "royal_caribbean", "msc"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in short_loop_lines):
                deprioritize(lid, 1, "Longer duration preference — line primarily known for 7-night sailings")

    elif any(x in duration for x in ["7", "week", "short", "3", "4", "5"]):
        # Shorter sailings — no hard filter but note it
        dest_region = profile.get("destination_region")
        dest_phrase = f"{dest_region} options" if dest_region else "options"
        advisor_alerts.append(
            f"Short duration preference — confirm 7-night or shorter {dest_phrase} per shortlisted line."
        )

    # ── Port intensity preference ─────────────────────────────────────────

    interests_str = " ".join(profile.get("interests") or []).lower()
    port_intensive = any(x in interests_str for x in [
        "port", "explore", "culture", "history", "destination", "shore", "excursion", "ashore"
    ])

    if port_intensive:
        port_lines = ["azamara", "holland_america", "oceania", "viking_ocean", "cunard"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in port_lines):
                boost(lid, 2, "Destination/port focus — line known for port-intensive itineraries")

    # ── Budget scoring ────────────────────────────────────────────────────

    if budget == "budget_under_2k":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier != "mass_market":
                elim(lid, "Budget under $2,000pp cruise fare — mass market lines only")

    elif budget == "budget_2k_4k":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier == "mass_market":
                boost(lid, 1, "Budget aligns with mass market range")
            elif tier == "premium":
                boost(lid, 2, "Budget aligns with premium range")
            elif tier in ("luxury", "ultra_luxury"):
                deprioritize(lid, 2, "Budget likely below luxury price point")

    elif budget == "budget_4k_7k":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier == "premium":
                boost(lid, 1, "Budget aligns with premium range")
            elif tier == "upper_premium":
                boost(lid, 2, "Budget aligns with upper-premium range")
            elif tier == "luxury":
                boost(lid, 1, "Budget reaches lower luxury tier")
            elif tier == "ultra_luxury":
                deprioritize(lid, 1, "Budget may be below ultra-luxury price point")
            elif tier == "mass_market":
                deprioritize(lid, 1, "Budget above typical mass market range")

    elif budget == "budget_7k_plus":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("luxury", "ultra_luxury"):
                boost(lid, 2, "Budget supports luxury/ultra-luxury tier")
            elif tier == "upper_premium":
                boost(lid, 1, "Budget aligns with upper-premium range")

    elif not budget or "not sure" in budget or "unsure" in budget:
        advisor_alerts.append(
            "Budget not confirmed — budget conversation is first agenda item at handoff call."
        )

    # ── Emotional driver signals ──────────────────────────────────────────

    if "escape" in emotional_driver:
        # Escape buyer wants frictionless, all-inclusive, minimal decisions
        # Norwegian (Free at Sea packaging), Celebrity (Always Included), Princess (Plus/Premier)
        escape_lines = ["norwegian", "celebrity", "princess", "virgin_voyages", "msc"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in escape_lines):
                boost(lid, 1, "Escape driver — all-inclusive/package-forward lines preferred")
        # Luxury lines are also natural escape environments
        for lid in list(lines):
            if char_val(lid, "experience_tier") in ("luxury", "ultra_luxury"):
                boost(lid, 1, "Escape driver — fully inclusive luxury removes all decisions")

    if "adventure" in emotional_driver:
        # Adventure buyer wants destination-intensive, active, smaller ships
        adventure_lines = ["azamara", "holland_america", "oceania", "viking_ocean", "seabourn", "silversea"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in adventure_lines):
                boost(lid, 2, "Adventure driver — port-intensive, destination-forward lines")
        for lid in list(lines):
            fp = char_val(lid, "entertainment_footprint")
            if fp == "international_rotating":
                boost(lid, 1, "Adventure driver — enrichment/destination footprint")

    if "connection" in emotional_driver:
        # Connection buyer needs the shared experience to work for everyone in the party
        # Celebrity, Princess, Holland America — broad appeal, mature programming
        connection_lines = ["celebrity", "princess", "holland_america", "royal_caribbean"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in connection_lines):
                boost(lid, 1, "Connection driver — broad-appeal lines serve mixed-priority parties well")

    if "status" in emotional_driver:
        # Status buyer cares about the brand, ship name, cabin tier
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 2, "Status driver — premium/luxury brand signal matters")
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 1, "Status driver — ship-within-ship enclave available")

    if "legacy" in emotional_driver:
        # Legacy buyer: "the trip the kids will talk about forever," "while we still can"
        # Budget flexibility signal — treat like a once_in_a_lifetime flag
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 2, "Legacy driver — budget flexibility implied, premium experience prioritized")
        advisor_alerts.append(
            "Legacy emotional driver — guest may have more budget flexibility than stated. "
            "Surface a premium or suite option alongside the baseline recommendation."
        )

    if "discovery" in emotional_driver:
        # Discovery buyer: learning, enrichment, culture, depth
        discovery_lines = ["viking_ocean", "oceania", "cunard", "azamara", "holland_america", "silversea"]
        for lid in list(lines):
            if any(s in lines[lid]["slug"] for s in discovery_lines):
                boost(lid, 2, "Discovery driver — enrichment and cultural programming emphasis")
        for lid in list(lines):
            fp = char_val(lid, "entertainment_footprint")
            if fp == "international_rotating":
                boost(lid, 1, "Discovery driver — enrichment-forward entertainment footprint")

    if "celebration" in emotional_driver:
        # Celebration buyer: marking a milestone, joy, indulgence
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("premium", "upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 1, "Celebration driver — premium experience elevates milestone")
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 1, "Celebration driver — suite/enclave programs suit milestone travel")
        advisor_alerts.append(
            "Celebration driver — flag suite upgrade opportunities, anniversary/milestone amenity packages, "
            "and specialty dining reservations as advisor action items."
        )

    # ── Trip occasion signals ─────────────────────────────────────────────

    if trip_occasion in ("anniversary", "honeymoon"):
        for lid in list(lines):
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 2, f"{trip_occasion.capitalize()} trip — ship-within-ship suite programs ideal")
            tier = char_val(lid, "experience_tier")
            if tier in ("luxury", "ultra_luxury"):
                boost(lid, 1, f"{trip_occasion.capitalize()} trip — intimate luxury environment")
        if trip_occasion == "honeymoon":
            # Adults-only lines get a lift (children already filtered if applicable)
            for lid in list(lines):
                if char_val(lid, "family_children") == "adult_only":
                    boost(lid, 2, "Honeymoon — adults-only line preferred")
        advisor_alerts.append(
            f"{trip_occasion.capitalize()} travel — confirm amenity packages, bottle of wine/champagne, "
            "special occasion deck setups available through the line."
        )

    elif trip_occasion == "retirement":
        # Often signals budget flexibility and willingness to invest in experience quality
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 1, "Retirement trip — strong budget flexibility signal, premium experience suits")
        advisor_alerts.append(
            "Retirement trip — budget flexibility likely. Surface premium cabin and experience upgrade "
            "options. Extended durations may be relevant."
        )

    elif trip_occasion == "bucket_list":
        # Treat like once_in_a_lifetime — budget flexibility signal
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 1, "Bucket list trip — premium experience warranted")
        advisor_alerts.append(
            "Bucket list trip — guest may have budget flexibility beyond stated tier. "
            "Surface the best version of this trip, not just the affordable one."
        )

    elif trip_occasion == "health_motivation":
        advisor_alerts.append(
            "Health motivation behind this trip — confirm onboard medical facilities per shortlisted ships. "
            "Prioritize stability (larger ships, calmer itineraries). Itinerary pacing matters more than usual."
        )

    elif trip_occasion == "family_reunion":
        advisor_alerts.append(
            "Family reunion — confirm group rate threshold and group specialist routing. "
            "Connecting cabin availability and dining coordination are key advisor action items."
        )

    elif trip_occasion in ("birthday", "graduation"):
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("premium", "upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 1, f"{trip_occasion.capitalize()} celebration — premium experience elevates the occasion")
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 1, f"{trip_occasion.capitalize()} celebration — suite/enclave programs suit milestone travel")
        advisor_alerts.append(
            f"{trip_occasion.capitalize()} celebration — flag specialty dining packages, "
            "onboard celebration amenities, and suite upgrade options as advisor action items."
        )

    elif trip_occasion == "empty_nest":
        # Children are out of the picture — adults-only lines now fully eligible
        for lid in list(lines):
            if char_val(lid, "family_children") == "adult_only":
                boost(lid, 2, "Empty nest trip — adults-only line now fully eligible and preferred")
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("premium", "upper_premium", "luxury"):
                boost(lid, 1, "Empty nest trip — elevated experience often marks this transition")
        advisor_alerts.append(
            "Empty nest trip — adults-only lines are now in play and should be presented. "
            "This trip often marks a significant personal transition; treat accordingly."
        )

    elif trip_occasion == "gift":
        advisor_alerts.append(
            "Gift trip — confirm who the actual travelers are and whether the gifter is also sailing. "
            "The person booking may have different preferences than the people going. "
            "Clarify decision authority before presenting options."
        )

    elif trip_occasion == "new_baby":
        # Celebration of a new child or grandchild — family infrastructure critical
        # Infant age policy is a hard constraint — must be flagged prominently
        for lid in list(lines):
            if char_val(lid, "family_children") in ("child_centric_mega", "balanced_multi_gen"):
                boost(lid, 2, "New baby celebration — family infrastructure and infant-friendly ships preferred")
        advisor_alerts.append(
            "New baby occasion — confirm minimum infant age policy per shortlisted line (typically 6 months, "
            "some lines 12 months for certain itineraries). If the baby will be under 6 months at sailing, "
            "flag this as a hard constraint. Timing window may be very tight. "
            "Infants require their own booking and identification documents."
        )

    # ── Trip significance — budget flexibility proxy ───────────────────────

    if trip_significance == "once_in_a_lifetime":
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury", "ultra_luxury"):
                boost(lid, 1, "Once-in-a-lifetime trip — budget flexibility signal, premium experience boosted")
        advisor_alerts.append(
            "Once-in-a-lifetime significance — guest likely has more flexibility than stated budget. "
            "Present the aspirational version of this trip alongside the baseline. "
            "Many once-in-a-lifetime travelers find the money for the right experience."
        )

    elif trip_significance == "milestone":
        for lid in list(lines):
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 1, "Milestone trip — suite/enclave experience adds meaning")
        advisor_alerts.append(
            "Milestone trip — surface suite upgrade and special occasion options."
        )

    # ── Budget flexibility — adjust tier filter sensitivity ───────────────

    if budget_flex == "find_the_money":
        # Remove hard lower-luxury deprioritizations, boost luxury lines
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("luxury", "ultra_luxury"):
                boost(lid, 2, "Budget flexibility: find the money — luxury tier actively in play")
        advisor_alerts.append(
            "Guest expressed 'find the money for the right trip' budget flexibility. "
            "Do not limit recommendations to stated budget tier — present the right experience, "
            "then address budget."
        )

    elif budget_flex in ("starting_point", "some_flexibility"):
        # Allow one tier above stated budget to enter recommendations
        for lid in list(lines):
            tier = char_val(lid, "experience_tier")
            if tier in ("upper_premium", "luxury"):
                boost(lid, 1, "Budget flexibility signal — one tier above stated range in play")
        if budget_flex == "starting_point":
            advisor_alerts.append(
                "Guest described budget as a starting point, not a ceiling. "
                "Surface one premium step-up option alongside the baseline recommendation."
            )

    elif budget_flex == "firm_ceiling":
        advisor_alerts.append(
            "Guest stated budget is a firm ceiling. Do not upsell above stated tier. "
            "Focus on maximizing value within the range."
        )

    # ── PHASE 6: Cabin / suite ────────────────────────────────────────────

    if "suite" in cabin:
        for lid in list(lines):
            enclave = char_val(lid, "ship_within_ship")
            if enclave and enclave != "no_enclave":
                boost(lid, 2, "Suite preference — ship-within-ship enclave available")
        advisor_alerts.append(
            "Suite preference — flag Haven (NCL), Star Class (Royal), Retreat (Celebrity), "
            "and equivalent enclave programs to advisor."
        )

    # ── Build shortlist ────────────────────────────────────────────────────

    if not lines:
        return {
            "shortlist":      [],
            "eliminated":     eliminated,
            "advisor_alerts": advisor_alerts,
            "error":          "All lines eliminated — profile may be contradictory or too restrictive.",
        }

    # Sort by score descending
    ranked = sorted(lines.keys(), key=lambda lid: scores[lid], reverse=True)

    # Cap at 3
    shortlist_ids = ranked[:3]

    shortlist = []
    for lid in shortlist_ids:
        shortlist.append({
            "slug":          lines[lid]["slug"],
            "name":          lines[lid]["name"],
            "environment":   lines[lid]["environment"],
            "score":         scores[lid],
            "reasons":       reasons[lid],
        })

    return {
        "shortlist":      shortlist,
        "eliminated_count": len(eliminated),
        "eliminated":     eliminated,
        "advisor_alerts": advisor_alerts,
    }
