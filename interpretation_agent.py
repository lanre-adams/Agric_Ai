import os
import json
import re

from app.services.agents.state import FarmWatchState


# ── Scope vocabulary ─────────────────────────────────────────────
# What a field-level reading actually describes, per assessment_scope.
#
# This used to be a boolean on coverage_tier == "partial", which had two
# holes. The frozen gee.py can return coverage_tier == "insufficient"
# alongside real index values — it only refuses outright when no zone at
# all is usable — and "insufficient" is not "partial", so the old test
# was False and every sentence claimed whole-field scope for a field
# less than half visible.
#
# The second hole is subtler and is why coverage_tier is not consulted
# here at all: gee.py can return coverage_tier == "full" together with
# assessment_scope == "local_only", when the clear pixels were plentiful
# but clustered in one part of the field. Coverage percentage does not
# capture distribution. assessment_scope does, and is the only input to
# the scope decision below.
FIELD_SCOPE_PHRASE = {
    "whole_field": "the field",
    "partial_field": "the clearly visible portion of the field",
    "local_only": "the areas of the field that could be observed",
}

# Unknown or missing scope resolves to the most cautious phrasing, never
# the most flattering one.
DEFAULT_SCOPE = "local_only"

# Spatial availability. detection_agent is the source of truth and
# records technical_details["spatial_status"]; this set exists only for
# an older detection result that has none.
#
# The old test was `attention_source != "insufficient_data"` — a single
# string. gee.py emits six non-index values, so the other five read as
# "comparison available", and the report said no area stood out while
# hotspot_summary simultaneously explained that no comparison could be
# made.
SPATIAL_AVAILABLE_SOURCES = frozenset({
    "ndre", "ndvi_fallback", "field_uniform",
})


def _resolve_scope(assessment_scope):
    """
    Returns a valid assessment_scope string.

    processing_agent guarantees assessment_scope in the frozen pipeline
    and hard-fails without it. If it is nevertheless absent or invalid
    here, the fallback is the most cautious wording — NOT a scope
    reconstructed from coverage_tier.

    Reconstructing would reintroduce the overclaim this file just
    removed. gee.py can return coverage_tier="full" together with
    assessment_scope="local_only" when the clear pixels were adequate in
    quantity but clustered in one part of the field. Coverage percentage
    does not capture spatial distribution, so it cannot stand in for
    scope.
    """
    if assessment_scope in FIELD_SCOPE_PHRASE:
        return assessment_scope

    return DEFAULT_SCOPE


def _field_scope(assessment_scope):
    """
    What the field-level reading actually describes.

    The index means come from the usable pixels only. Saying "the field"
    would generalise a measurement of part of it to all of it — and the
    qualifier must carry through every sentence in a branch, not only
    the summary.
    """
    return FIELD_SCOPE_PHRASE.get(
        assessment_scope, FIELD_SCOPE_PHRASE[DEFAULT_SCOPE]
    )


def _scope_caveat(assessment_scope, assessment_scope_message):
    """
    Appends the coverage caveat gee.py already composed.

    Reusing it rather than re-deriving one here means the caveat reads
    the same wherever it appears and stays correct if the coverage rules
    change upstream. It is None at whole_field scope, where no caveat is
    warranted.
    """
    if assessment_scope == "whole_field" or not assessment_scope_message:
        return ""
    return f" {assessment_scope_message}"


# Crop timing modes, matching crop_context.py exactly.
#
# MODE_STANDARD must be defined and handled. Without it, a main-growth
# field falls to the generic clause and a corn crop 115 days after
# planting is told its low cover might be because it "has not yet
# emerged" — the opposite of what the crop calendar says. Silently
# reaching a default is how crop context ends up doing nothing.
MODE_LEGACY = "legacy"
MODE_PRE_PLANTING = "pre_planting_context"
MODE_EARLY = "early_stage_context"
MODE_STANDARD = "standard"
MODE_LATE = "late_season_context"


def _cover_timing_clause(cover_screen_mode):
    """
    Replaces the generic "harvested, not emerged, or resting" list with
    the explanation that actually fits the season.

    Without crop context that sentence has to cover every possibility at
    once, which is honest but useless. With a planting date, only one or
    two of them are plausible, and saying so is the point of Step 3.
    """
    if cover_screen_mode == MODE_EARLY:
        return (
            " The crop is early in its season, so low cover here can "
            "simply mean it has not filled in yet. Check emergence and "
            "stand uniformity if parts of the field look delayed."
        )

    if cover_screen_mode == MODE_STANDARD:
        # No claim about what is "normal" at this point. Days after
        # planting is broad calendar timing, not measured phenology, so
        # it cannot establish what the crop should look like — the same
        # rule that governs every other sentence in this file.
        return (
            " This observation falls within the crop's broad main-growth "
            "calendar window. Reduced vegetation cover at this point is "
            "worth checking against crop establishment and current field "
            "conditions before deciding what may be contributing to the "
            "finding."
        )

    if cover_screen_mode == MODE_LATE:
        # "rather than a problem" removed deliberately. Late-season
        # timing is context, not evidence that the finding is harmless,
        # and the phrasing here matches stress_classifier.py.
        return (
            " This observation falls within the crop's broad late-season "
            "calendar window, when harvest, natural maturity or dry-down "
            "may contribute to reduced vegetation cover. Timing alone "
            "does not show that the finding is normal, so confirm what "
            "has happened in the field."
        )

    # Legacy only: with no planting date the sentence has to cover every
    # possibility at once.
    return (
        " If the field has already been harvested, has not yet emerged, "
        "or is intentionally resting, this can be normal."
    )


def _resolve_spatial_available(technical_details, attention_source):
    """
    Whether a within-field comparison was actually possible.

    Prefers spatial_status from detection_agent; falls back to the local
    set only for results written before that field existed.
    """
    spatial_status = (technical_details or {}).get("spatial_status")
    if spatial_status:
        return spatial_status in ("ranked", "uniform")
    return attention_source in SPATIAL_AVAILABLE_SOURCES


def interpretation_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Interpretation Agent — turns detection results into plain language.

    No index names. No jargon. Sentences a farmer can act on.

    WHAT GPT DOES HERE: rewriting only, and only when explicitly
    enabled. Every finding — the indices, thresholds, classification,
    severity, spatial analysis, possible causes — is decided
    deterministically upstream. GPT receives a finished finding and
    rewrites it in farmer-friendly English.

    GPT is OFF by default. During scientific validation the report
    wording must be reproducible: the same field and the same image
    should produce identical text every run, so the output can be
    compared against a manual Earth Engine reproduction. Set
    USE_GPT_INTERPRETATION=true once the science is validated.

    Six rules this agent must hold to:

    1. Observation vs hypothesis. The detection layer reports WHAT was
       measured; possible_causes are hypotheses. This agent presents
       them as possibilities and recommends ground inspection — it does
       not assert a cause.

    2. No spatial claim without matching spatial evidence. The zone
       grid is sampled with NDRE (NDVI fallback), while the moisture
       finding comes from a field-wide NDMI average. Attaching the zone
       location to a moisture statement would claim something the
       pipeline never measured. Field-level findings and within-field
       variation are therefore reported as SEPARATE statements, using
       hotspot_summary for anything spatial.

    3. "Could not assess" is never "looks fine". An unassessable field
       gets its own branch, keyed on condition_signal — never on
       severity, which is "none" in both cases. The same separation
       applies to the spatial comparison: "we looked and the field is
       uniform" and "we could not look" are different statements.

    4. Never say "the latest image". gee.py may deliberately select an
       older, clearer pass when the most recent one is too cloudy. The
       phrase used throughout is "the satellite image used for this
       analysis". Which image was chosen, and why, is Results.tsx's job
       to explain — not this agent's.

    5. Never overclaim scope. assessment_scope says how far a claim may
       generalise, and that qualifier must persist through every
       sentence in a branch, not just the first. The coverage caveat
       itself comes from gee.py via assessment_scope_message rather than
       being re-derived here; the coverage percentage belongs in the UI.

    6. No internal vocabulary, and no claims about the ground. Tagintell
       does not know the expected value for a given crop, variety and
       growth stage, so nothing is described as below what is
       "expected" or "usual". The farmer is not told about thresholds
       or system names. And the satellite cannot establish what the
       crop looks like from ground level, so this agent never says it
       does.
    """
    # `or []` rather than a default argument: state.get("errors", [])
    # returns None when an earlier agent wrote errors=None explicitly,
    # and list(None) raises TypeError here — outside the try block, so
    # it would surface as an unhandled crash rather than a handled one.
    errors = list(state.get("errors") or [])

    # If an earlier agent failed, its message is the one the farmer
    # should see. Continuing would find no detection result and replace
    # a specific "cloud is blocking your field" message with a generic
    # internal one.
    if state.get("processing_error") or state.get("detection_error"):
        return dict(state)

    severity         = state.get("severity")
    stress_type      = state.get("stress_type")
    condition_signal = state.get("condition_signal") or "not_assessed"
    recommendation   = state.get("recommendation")
    title            = state.get("title")
    hotspot_summary  = state.get("hotspot_summary")

    # None means no area was flagged. Do NOT substitute a placeholder.
    attention_area   = state.get("attention_area")

    possible_causes       = state.get("possible_causes") or []
    corroborating_signals = state.get("corroborating_signals") or []

    technical_details = state.get("technical_details") or {}
    confidence        = technical_details.get("confidence", "medium")

    # How far any claim may generalise. assessment_scope is the only
    # input to this decision; coverage_tier is deliberately not consulted
    # (see _resolve_scope).
    assessment_scope = _resolve_scope(state.get("assessment_scope"))

    # The caveat gee.py already wrote, reused rather than re-derived.
    assessment_scope_message = state.get("assessment_scope_message")

    # The farmer-facing visibility figure describes the boundary the
    # farmer drew. valid_pixel_fraction describes the edge-buffered
    # interior and is NOT the number to show them.
    field_coverage = state.get("field_coverage") or {}
    field_clear_fraction = field_coverage.get("clear_fraction")

    # Crop / season context. Optional at every layer: a polygon-only
    # farm arrives with cover_screen_mode="legacy" and every wording
    # branch below falls back to its pre-Step-3 text.
    crop_context = state.get("crop_context") or {}
    cover_screen_mode = crop_context.get("cover_screen_mode") or "legacy"

    # Whether there was enough spatial information to compare areas
    # within the field. A field can have a valid overall reading while
    # still being too small or too obscured for reliable 3x3 analysis.
    attention_source = state.get("attention_source") or "insufficient_data"
    spatial_available = _resolve_spatial_available(
        technical_details, attention_source
    )

    if not stress_type:
        msg = "No detection result was available for interpretation."
        errors.append(msg)
        return {
            **state,
            "interpretation_error": msg,
            "status": "failed",
            "errors": errors,
        }

    try:
        openai_key = os.getenv("OPENAI_API_KEY")

        # GPT rewriting is OFF by default — see the docstring.
        use_gpt_interpretation = (
            os.getenv("USE_GPT_INTERPRETATION", "false").lower() == "true"
        )

        if (
            use_gpt_interpretation
            and openai_key
            and condition_signal != "not_assessed"
        ):
            try:
                summary, explanation, action = _interpret_with_gpt(
                    condition_signal=condition_signal,
                    severity=severity,
                    title=title,
                    attention_area=attention_area,
                    hotspot_summary=hotspot_summary,
                    possible_causes=possible_causes,
                    corroborating_signals=corroborating_signals,
                    recommendation=recommendation,
                    confidence=confidence,
                    assessment_scope=assessment_scope,
                    assessment_scope_message=assessment_scope_message,
                    field_clear_fraction=field_clear_fraction,
                    crop_context=crop_context,
                    openai_key=openai_key,
                )
                return {
                    **state,
                    "summary": summary,
                    "explanation": explanation,
                    "action": action,
                    "interpretation_error": None,
                    "status": "ok",
                    "errors": errors,
                }
            except Exception as exc:
                errors.append(
                    f"GPT interpretation failed, using fallback: {str(exc)}"
                )

        summary, explanation, action = _interpret_rule_based(
            condition_signal=condition_signal,
            severity=severity,
            title=title,
            hotspot_summary=hotspot_summary,
            possible_causes=possible_causes,
            corroborating_signals=corroborating_signals,
            recommendation=recommendation,
            confidence=confidence,
            assessment_scope=assessment_scope,
            assessment_scope_message=assessment_scope_message,
            spatial_available=spatial_available,
            crop_context=crop_context,
            cover_screen_mode=cover_screen_mode,
        )

        return {
            **state,
            "summary": summary,
            "explanation": explanation,
            "action": action,
            "interpretation_error": None,
            "status": "ok",
            "errors": errors,
        }

    except Exception as exc:
        # Internal detail stays in errors; the farmer gets nothing that
        # describes our architecture.
        internal_msg = (
            f"Interpretation agent failed: {type(exc).__name__}: {exc}"
        )
        errors.append(internal_msg)
        return {
            **state,
            "interpretation_error": (
                "The report could not be written. Please try again."
            ),
            "status": "failed",
            "errors": errors,
        }


# ── Shared language helpers ──────────────────────────────────────

SIGNAL_PLAIN_NAME = {
    "moisture_condition":           "moisture",
    "chlorophyll_condition":        "crop condition",
    "vegetation_cover":             "vegetation cover",
    "general_vegetation_condition": "overall vegetation",
    "early_signal":                 "crop condition",
    "no_warning_signal":            "overall condition",
    "not_assessed":                 "condition",
    "supporting_vegetation_signal": "supporting vegetation",
    "dense_canopy_masking":         "canopy density",
}

# Not an indicator that is "low" — it is a context flag meaning a dense
# canopy may be hiding a change. Excluded from any "also low" listing.
NON_INDICATOR_SIGNALS = {"dense_canopy_masking"}

# Title returned by the classifier for the bare-cover case. Severity is
# MILD for both bare and sparse cover, so severity cannot distinguish
# them — the title is the only reliable discriminator. If this string
# changes in stress_classifier.py, change it here too.
TITLE_VERY_LOW_COVER = "Very low vegetation cover"

AREA_TERMS = (
    "northwest", "northeast", "southwest", "southeast",
    "north", "south", "east", "west", "central", "center",
)


# Irrigation equipment whose NAME contains a direction word. These are
# stripped before the location check.
#
# This is not hypothetical. stress_classifier writes "This field is
# recorded as center-pivot irrigated" into the recommendation, the
# prompt passes that to GPT as the suggested action, and GPT echoes it
# into the action field — which guard 1 inspects. Without this, almost
# every center-pivot moisture report would be rejected as having named
# an area, and the irrigation-aware advice would never survive the GPT
# path.
EQUIPMENT_PHRASES = (
    r"\bcent(?:er|re)[-\s]?pivots?\b",
)


def _contains_area_term(text):
    """
    Detects genuine directional words using whole-word matching.

    Plain substring matching produces false positives: "east" appears
    inside "at least", "west" inside "lowest". Either would wrongly
    reject a valid GPT response and force an unnecessary fallback.

    Equipment names containing a direction word are removed first, so
    "center-pivot" is not read as the centre of the field. A genuine
    "central area of the farm" is untouched.
    """
    location_text = text

    for pattern in EQUIPMENT_PHRASES:
        location_text = re.sub(
            pattern, " ", location_text, flags=re.IGNORECASE
        )

    return any(
        re.search(rf"\b{re.escape(term)}\b", location_text,
                  flags=re.IGNORECASE)
        for term in AREA_TERMS
    )


def _spatial_sentence(hotspot_summary):
    """
    Returns the spatial finding as a SEPARATE sentence.

    Never merged into a signal-specific claim. The zone grid uses NDRE
    while the moisture finding uses NDMI, so combining them would
    attribute a location to a measurement that never had one.
    """
    return f" {hotspot_summary}" if hotspot_summary else ""


def _causes_sentence(possible_causes, limit=3):
    """
    Frames possible causes explicitly as possibilities, never as fact.
    """
    if not possible_causes:
        return ""
    shown = [c.lower() for c in possible_causes[:limit]]
    if len(shown) == 1:
        joined = shown[0]
    else:
        joined = ", ".join(shown[:-1]) + " or " + shown[-1]
    return (
        f" Possible reasons include {joined}, though the satellite cannot "
        "tell which."
    )


def _corroborating_sentence(corroborating_signals):
    """
    Mentions other indicators that were also low in this observation.
    """
    names = [
        SIGNAL_PLAIN_NAME.get(s, s.replace("_", " "))
        for s in corroborating_signals
        if s not in NON_INDICATOR_SIGNALS
    ]
    if not names:
        return ""
    if len(names) == 1:
        return f" The {names[0]} reading is also low in this observation."
    joined = ", ".join(names[:-1]) + " and " + names[-1]
    return f" The {joined} readings are also low in this observation."


# ── GPT interpretation ───────────────────────────────────────────

def _interpret_with_gpt(
    condition_signal, severity, title, attention_area, hotspot_summary,
    possible_causes, corroborating_signals, recommendation, confidence,
    assessment_scope, assessment_scope_message, field_clear_fraction,
    crop_context, openai_key
):
    """
    Calls GPT-4o-mini and returns (summary, explanation, action).

    GPT rewrites the finding in farmer-friendly language. It does not
    decide what the finding is, and it is explicitly forbidden from
    inventing a location, asserting a cause, attaching the spatial
    finding to the field-level signal, or claiming whole-field scope
    when coverage was partial or local.

    Two post-response guards enforce the spatial rules. Any violation
    raises, and the caller falls back to the deterministic path — which
    we fully control.
    """
    import urllib.request

    # dense_canopy_masking is context, not a low indicator. Filtered
    # here to match the rule-based path.
    listed_corroborating = [
        s for s in corroborating_signals if s not in NON_INDICATOR_SIGNALS
    ]

    causes_block = (
        "\n".join(f"- {c}" for c in possible_causes)
        if possible_causes else "None listed"
    )

    corroborating_block = (
        "\n".join(
            f"- {SIGNAL_PLAIN_NAME.get(s, s)}" for s in listed_corroborating
        )
        if listed_corroborating else "None"
    )

    spatial_block = hotspot_summary or "No spatial comparison available."

    # The farmer-facing figure describes the boundary they drew, not the
    # edge-buffered interior the indices were computed over.
    coverage_percent = (
        round(field_clear_fraction * 100)
        if field_clear_fraction is not None else None
    )
    coverage_line = (
        f"Share of this field with a reliable observation: "
        f"{coverage_percent}%"
        if coverage_percent is not None else
        "Share of this field with a reliable observation: not reported"
    )

    # Three states, not two. LOCAL_ONLY previously fell through to FULL
    # and told the model it could speak for the whole field.
    coverage_state = {
        "whole_field": "FULL",
        "partial_field": "PARTIAL",
        "local_only": "LOCAL_ONLY",
    }.get(assessment_scope, "LOCAL_ONLY")

    scope_phrase = _field_scope(assessment_scope)
    caveat_line = assessment_scope_message or "None"

    # Crop context block. Only rendered when the farmer supplied
    # something; a polygon-only farm gets the pre-Step-3 prompt.
    crop_context = crop_context or {}
    crop_timing = crop_context.get("crop_timing_context") or {}

    if crop_context.get("has_crop_context"):
        crop_block = "\n".join(
            line for line in (
                f"Crop: {crop_context.get('crop_type')}"
                if crop_context.get("crop_type") else None,
                f"Planting date: {crop_context.get('planting_date')}"
                if crop_context.get("planting_date") else None,
                (
                    f"Days after planting on the observation date: "
                    f"{crop_context.get('days_after_planting')}"
                )
                if crop_context.get("days_after_planting") is not None
                else None,
                (
                    f"Broad calendar timing: "
                    f"{crop_timing.get('timing_phase')}"
                )
                if crop_timing.get("timing_phase") else None,
                f"Water management: {crop_context.get('irrigation_type')}"
                if crop_context.get("irrigation_type") else None,
            ) if line
        ) or "None supplied"
    else:
        crop_block = "None supplied"

    prompt = f"""You are an agronomist writing a satellite field report for a farmer.

The farmer does not know remote sensing. Write plain, clear English.
Never mention NDVI, NDRE, NDMI, SAVI, GNDVI or any index name.

FIELD-LEVEL FINDING
Calculated from the reliably observed satellite pixels in the analysed
area of the field. Edge pixels may have been excluded upstream to reduce
boundary contamination. Where coverage is partial or local, this
describes only the part of the field that was reliably observed, not the
whole field.

Finding: {title}
Signal type: {condition_signal}
Severity: {severity}
Confidence: {confidence}
{coverage_line}
Coverage state: {coverage_state}
Refer to the measured area as: {scope_phrase}
Coverage caveat already written for this report: {caveat_line}

CROP CONTEXT SUPPLIED BY THE FARMER
{crop_block}

This is broad calendar timing derived from the planting date. It is NOT
a measured growth stage, and variety, weather and management all shift
real development. Use it to frame the finding; never state it as an
observed fact about the crop.

WITHIN-FIELD SPATIAL FINDING (a SEPARATE measurement)
{spatial_block}

POSSIBLE CAUSES (hypotheses only — the satellite cannot confirm any):
{causes_block}

OTHER INDICATORS ALSO LOW:
{corroborating_block}

SUGGESTED ACTION FROM THE ANALYSIS:
{recommendation}

RULES YOU MUST FOLLOW
1. The field-level finding and the spatial finding come from DIFFERENT
   measurements. Never merge them into one sentence. Do not write
   anything like "moisture is low in the northwest" — the location was
   found using a different measurement than the moisture reading.
   Report them as two separate statements.
2. Never name a part of the field unless the spatial finding above
   names it. Do not invent a location and do not say "the general area".
3. Never state a cause as fact. Say "one possible reason is" or "this
   may be linked to".
4. Do not tell the farmer about internal thresholds, rules or system
   names. Describe a reading only as "low", "lower", or "worth
   checking", and only when the finding above supplies that
   description. Do not say a reading is below what is "normal",
   "expected" or "usual" for this crop, and do not say it is lower than
   we "normally look for" — that implies the same baseline. Broad
   calendar timing may be supplied above, but the index values
   themselves are still not calibrated against crop, variety or growth
   stage, so no reading can be called normal or abnormal for this crop.
5. Never say "the latest image" or "the most recent image". An older,
   clearer satellite pass may have been used deliberately. Say "the
   satellite image used for this analysis", or simply "this
   observation".
6. If coverage state is PARTIAL or LOCAL_ONLY, do not imply the finding
   covers the whole field — in ANY sentence, not just the first. Refer
   to the measured area as "{scope_phrase}". If the state is
   LOCAL_ONLY, say plainly that only part of the field could be
   assessed. Do not quote the coverage percentage; the interface shows
   that separately.
7. If the spatial finding says a comparison could NOT be made, do not
   write that the field looks consistent or that no area stands out.
   Those are claims we did not measure. Say instead that areas within
   the field could not be compared in this observation.
8. Do not describe how the crop looks on the ground. The satellite
   cannot establish that. Describe only what the observation shows.
9. Always recommend checking the field before acting on any treatment.
10. Do not exaggerate. If severity is mild, keep the tone calm.
11. If crop context is supplied, you may use it to frame the finding —
    for example that low cover early in the season can mean the crop has
    not filled in yet, or that a late-season reading may reflect natural
    dry-down. Never use it to explain a finding away: timing context
    does not show that a signal is normal, and a field can be both late
    in its season and genuinely failing.

Return JSON with exactly these three fields:
{{
  "summary": "One or two sentences. What the satellite saw.",
  "explanation": "Three to four sentences. What it means, what might explain it, and what is uncertain.",
  "action": "One or two sentences. What the farmer should do next."
}}

Return only the JSON object. No preamble, no markdown."""

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 500,
        "temperature": 0.4,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an agronomist who writes plainly and never "
                    "overstates what satellite data can prove."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)

    summary     = parsed.get("summary", "").strip()
    explanation = parsed.get("explanation", "").strip()
    action      = parsed.get("action", "").strip()

    if not summary or not explanation or not action:
        raise ValueError("GPT response missing required fields")

    # The action field is included deliberately. A model can obey the
    # location rule throughout summary and explanation and then write
    # "Scout the northwest area for moisture stress" as the action,
    # which is both an invented location and the merge forbidden below.
    combined = (summary + " " + explanation + " " + action).lower()

    # Guard 1 — no area was flagged, so no direction may appear.
    if not attention_area:
        if _contains_area_term(combined):
            raise ValueError("GPT named an area that was not flagged")

    # Guard 2 — an area WAS flagged, so the model may name it, but must
    # not attach it to the field-level signal. Checked sentence by
    # sentence: a location and a signal term in the same sentence is
    # the merge we forbade.
    else:
        # Every condition signal that can reach this path needs terms.
        # vegetation_cover and early_signal previously had none, so
        # `.get(..., ())` returned empty and guard 2 was skipped
        # outright — "Vegetation cover is thin in the northwest area"
        # would have passed unchallenged.
        #
        # early_signal includes "crop condition" because that is what
        # SIGNAL_PLAIN_NAME maps it to, so the model is likely to reach
        # for that phrase rather than "early change".
        #
        # no_warning_signal and not_assessed are absent on purpose.
        # not_assessed never reaches the GPT path, and detection only
        # sets attention_area when severity is non-zero, so a
        # no_warning_signal result arrives with attention_area=None and
        # is covered by guard 1 instead.
        SIGNAL_MERGE_TERMS = {
            "moisture_condition": (
                "moisture",
            ),
            "chlorophyll_condition": (
                "crop condition",
                "chlorophyll",
            ),
            "vegetation_cover": (
                "vegetation cover",
                "plant cover",
                "thin cover",
                "canopy cover",
            ),
            "early_signal": (
                "early signal",
                "early change",
                "crop condition",
            ),
            "general_vegetation_condition": (
                "overall vegetation",
            ),
        }

        # Fail closed. An unrecognised condition_signal means we have no
        # terms to test against, so the merge rule cannot be enforced at
        # all. Rejecting sends the caller to the deterministic path,
        # which never merges by construction — cheaper than shipping an
        # unguarded rewrite.
        if condition_signal not in SIGNAL_MERGE_TERMS:
            raise ValueError(
                "No merge-guard terms for condition signal "
                f"{condition_signal!r}; falling back to the "
                "deterministic path"
            )

        signal_terms = SIGNAL_MERGE_TERMS[condition_signal]

        if signal_terms:
            normalised = combined.replace("!", ".").replace("?", ".")
            for sentence in normalised.split("."):
                has_area = _contains_area_term(sentence)
                has_signal = any(t in sentence for t in signal_terms)
                if has_area and has_signal:
                    raise ValueError(
                        "GPT merged the field-level signal with the spatial "
                        "finding"
                    )

    return summary, explanation, action


# ── Rule-based fallback ──────────────────────────────────────────

def _interpret_rule_based(
    condition_signal, severity, title, hotspot_summary, possible_causes,
    corroborating_signals, recommendation, confidence, assessment_scope,
    assessment_scope_message, spatial_available, crop_context,
    cover_screen_mode
):
    """
    Deterministic interpretation. The default path.

    Note the absence of an attention_area parameter — no branch here
    interpolates a location into a signal statement. Anything spatial
    comes through hotspot_summary as its own sentence.

    No branch says "the latest image": an older, clearer pass may have
    been selected on purpose, and Results.tsx explains which image was
    used and why. No branch describes how the crop looks on the ground
    either — the satellite cannot establish that.

    Every scoped branch ends with the coverage caveat, so the qualifier
    persists to the end of the paragraph rather than appearing once and
    being forgotten.
    """
    scope   = _field_scope(assessment_scope)
    spatial = _spatial_sentence(hotspot_summary)
    causes  = _causes_sentence(possible_causes)
    corrob  = _corroborating_sentence(corroborating_signals)
    caveat  = _scope_caveat(assessment_scope, assessment_scope_message)

    scope_limited = assessment_scope != "whole_field"

    # Could not assess — never treated as healthy, keyed on
    # condition_signal rather than severity. No caveat appended: the
    # branch already says nothing could be assessed.
    if condition_signal == "not_assessed":

        # Pre-planting is a DIFFERENT failure and must be checked first.
        #
        # The image was fine. Coverage was fine. It simply predates the
        # recorded planting date, so it shows the field before this crop
        # went in. Falling through to the generic text below would tell
        # the farmer "there was not enough usable satellite information",
        # which is false, and "try again when another observation
        # becomes available", which would not help — every future
        # observation has the same problem until one is taken after
        # planting. The remedy is a later image or a corrected date, and
        # the wording has to say so.
        if cover_screen_mode == MODE_PRE_PLANTING:
            planting_date = crop_context.get("planting_date")
            observation_date = crop_context.get("observation_date")
            days_before = crop_context.get("days_after_planting")

            when = (
                f" from {observation_date}"
                if observation_date else ""
            )
            planted = (
                f" of {planting_date}"
                if planting_date else ""
            )
            gap = (
                f" — {abs(days_before)} days earlier"
                if isinstance(days_before, int) and days_before < 0
                else ""
            )

            return (
                "This satellite observation was taken before the "
                "recorded planting date.",
                (
                    f"The satellite image used for this analysis{when} "
                    f"was captured before the planting date{planted} "
                    f"recorded for this field{gap}. It therefore shows "
                    f"the field before this crop was planted and cannot "
                    f"describe the condition of the current crop."
                ),
                (
                    "Run the analysis again once a satellite observation "
                    "from after planting is available. If the planting "
                    "date recorded for this field is wrong, correct it "
                    "and run the analysis again."
                ),
            )

        return (
            "This field could not be assessed from the available satellite "
            "data.",
            (
                "There was not enough usable satellite information to judge "
                "the condition of this field. This does not indicate that "
                "the field is healthy or unhealthy — it means a reliable "
                "assessment could not be produced from this observation."
            ),
            (
                "Try again when another usable satellite observation becomes "
                "available."
            ),
        )

    # No warning signal.
    if condition_signal == "no_warning_signal":
        # Scoped like every other summary. Without the qualifier, a
        # field 42% observed still reads as an all-clear for the farm.
        summary = (
            f"The satellite image used for this analysis does not show a "
            f"strong vegetation warning in {scope}."
        )

        if not spatial_available:
            # No within-field comparison was possible, so no claim may
            # be made about areas standing out. hotspot_summary carries
            # the reason. Checked FIRST because it applies at every
            # scope — the old ordering let a partial-coverage field skip
            # this branch entirely and inherit uniformity wording.
            explanation = (
                f"The overall vegetation readings for {scope} do not show "
                f"a strong warning signal.{spatial}{caveat}"
            )

        elif scope_limited:
            explanation = (
                f"Vegetation conditions in {scope} do not show a strong "
                f"warning signal.{spatial}{caveat}"
            )

        else:
            explanation = (
                "Vegetation conditions look fairly consistent overall."
                f"{spatial} No area stands out strongly enough to require "
                "attention right now."
            )

        return (
            summary,
            explanation,
            "Continue your normal field checks and monitor again after "
            "another clear satellite observation.",
        )

    # Vegetation cover — thin or bare.
    # Both cases return MILD severity from the classifier, so the title
    # is what distinguishes them.
    if condition_signal == "vegetation_cover":

        if title == TITLE_VERY_LOW_COVER:
            summary = (
                f"Very little vegetation cover was visible in {scope}."
            )
            # {spatial} was missing here and in the thin-cover branch
            # below, so a real within-field finding was silently dropped
            # whenever the overall signal happened to be cover. It stays
            # a separate sentence, so the location is still not attached
            # to the cover classification.
            #
            # "vegetation cover" rather than "living plant cover": the
            # satellite measures a vegetation signal, it does not
            # establish what is biologically alive on the ground.
            explanation = (
                f"The satellite detected very little vegetation cover in "
                f"{scope}.{spatial}{_cover_timing_clause(cover_screen_mode)}"
                f"{causes}{caveat}"
            )
        else:
            # "looks thin" describes appearance from the ground, which
            # rule 6 of this agent forbids. The satellite measured a
            # vegetation signal; it did not look at the crop.
            summary = f"Vegetation cover is thin in {scope}."
            # The "this can occur early in the season" hedge is only
            # honest without a planting date. With one, either it IS
            # early — in which case say so plainly — or it is not, and
            # offering the excuse anyway would explain away a real
            # finding.
            early_hedge = (
                " This can occur early in the season before plants fill "
                "in."
                if cover_screen_mode == MODE_LEGACY
                else _cover_timing_clause(cover_screen_mode)
            )
            explanation = (
                f"Vegetation cover is currently thin in {scope}."
                f"{early_hedge} Thin vegetation cover can also make "
                f"crop-condition readings less reliable, so this result "
                f"should be interpreted cautiously."
                f"{spatial}{causes}{caveat}"
            )

        return summary, explanation, recommendation

    # Moisture — field-level finding, spatial reported separately.
    if condition_signal == "moisture_condition":
        summary = f"The moisture-related vegetation signal is low in {scope}."
        explanation = (
            f"The satellite detected a low moisture-related vegetation "
            f"reading in {scope}.{spatial}{corrob}{causes}{caveat}"
        )
        return summary, explanation, recommendation

    # Crop condition — field-level finding, spatial reported separately.
    if condition_signal == "chlorophyll_condition":
        summary = f"The crop-condition signal is low in {scope}."
        explanation = (
            f"The satellite detected a lower crop-condition reading in "
            f"{scope}.{spatial}{corrob}{causes}{caveat}"
        )
        return summary, explanation, recommendation

    # Early signal. Deliberately does NOT say the crop may look normal
    # on the ground — that is a claim about ground conditions the
    # satellite cannot support.
    if condition_signal == "early_signal":
        summary = f"An early signal worth watching appeared in {scope}."
        explanation = (
            f"The satellite detected an early change in {scope}, but it is "
            f"not yet a clear warning.{spatial}{corrob}{causes}{caveat}"
        )
        return summary, explanation, recommendation

    # General vegetation.
    if condition_signal == "general_vegetation_condition":
        summary = f"The overall vegetation signal is low in {scope}."
        explanation = (
            f"The satellite detected a lower overall vegetation reading in "
            f"{scope}.{spatial} The image alone cannot identify the cause."
            f"{corrob}{causes}{caveat}"
        )
        return summary, explanation, recommendation

    # Unrecognised signal — stay vague rather than guess.
    summary = "A condition worth checking was found in this observation."
    explanation = (
        f"This observation flagged something worth a closer look.{spatial}"
        f"{corrob}{causes}{caveat}"
    )

    if confidence == "medium" and severity != "none":
        explanation += (
            " Confirm conditions on the ground before taking any corrective "
            "action."
        )

    return summary, explanation, recommendation