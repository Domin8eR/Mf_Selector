"""
Frozen template library for the Insights Engine.

Compact-card format (2026-07-18 migration): every insight renders as ONE
compact sentence (12-22 words, bold only the metric label/decision word)
plus, on expand, 2-5 bullets. No paragraph blocks. Both are filled from
frozen strings via str.format_map() — no LLM calls for page insight cards
(ENABLE_LLM_PAGE_INSIGHT_POLISH = False).

Each template gives 4 alternate compact-sentence phrasings (compact_
variants) so a fund's card doesn't always show the same wording. Which
variant renders is picked deterministically per render by
`variant_index()` below — a hash of entity_id + evaluation_date mod 4 —
not randomly and not always variant 0.

allowed_conclusion_template / forbidden_conclusions / source_tables feed
the canonical follow-up LLM context payload (see models.py
FollowUpPayload) when a user clicks through to Research Chat.
"""

from dataclasses import dataclass, field
import hashlib


@dataclass(frozen=True)
class InsightTemplate:
    template_id: str
    page_type: str
    insight_code: str
    trigger_code: str
    compact_variants: list[str] = field(default_factory=list)
    expanded_bullets: list[str] = field(default_factory=list)
    chip_keys: list[str] = field(default_factory=list)
    follow_up_label: str = "Discuss in Research Chat"
    allowed_conclusion_template: str = ""
    forbidden_conclusions: list[str] = field(default_factory=lambda: [
        "buy recommendation", "sell recommendation",
        "guaranteed outperformance", "personalized investment advice",
    ])
    source_tables: list[str] = field(default_factory=list)
    # Legacy fields — kept so older (pre-migration) template definitions in
    # this file that haven't been converted yet still construct without
    # errors. New templates should not set these.
    headline_template: str = ""
    body_template: str = ""
    required_variables: list[str] = field(default_factory=list)
    fallback_template_id: str | None = None
    severity: str = "neutral"
    priority: int = 100


def variant_index(variables: dict, n: int = 4) -> int:
    """
    Deterministic compact-sentence variant picker: hash(entity_id +
    evaluation_date) mod n. Same fund + same snapshot date always renders
    the same variant (reproducible), but different funds/dates spread
    across all n variants instead of always showing variant 0.
    """
    entity_id = str(
        variables.get("entity_id")
        or variables.get("schemecode")
        or variables.get("fund_name")
        or variables.get("category")
        or ""
    )
    eval_date = str(variables.get("evaluation_date", ""))
    key = f"{entity_id}|{eval_date}".encode("utf-8")
    return int(hashlib.sha256(key).hexdigest(), 16) % n


# ── Section 6: AI Workspace (AIW_*_V1) — compact format, 2026-07-18 ──────────
# Improver definition: rank_delta <= -3 AND current_rank <= 30
# AIW_DAILY_BRIEFING_SUMMARY_V1 (old cross-category rollup) dropped — not in
# the new template set; router.py no longer renders it as a card.

AIW_RANK_IMPROVERS_COUNT_V1 = InsightTemplate(
    template_id="AIW_RANK_IMPROVERS_COUNT_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="count_gt_zero",
    compact_variants=[
        "**{category}:** {count} funds improved by more than 2 ranks.",
        "**{category}:** {count} top-30 funds moved up meaningfully.",
        "**{category}:** {count} funds gained 3+ ranks in the latest snapshot.",
        "**{category}:** {count} rank improvers are now inside the top 30.",
    ],
    expanded_bullets=[
        "**Category:** {category}",
        "**Improver rule:** rank improved by at least 3 places.",
        "**Top-30 filter:** only funds currently ranked 30 or better are counted.",
        "**Snapshot:** {evaluation_date}",
    ],
    chip_keys=["count", "category", "evaluation_date"],
    follow_up_label="Open filtered Category Rankings",
    allowed_conclusion_template=(
        "{count} fund(s) in {category} improved rank by 3+ places into the top 30 "
        "as of {evaluation_date}."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="positive",
    priority=5,
)

AIW_RANK_IMPROVERS_COUNT_SNAPSHOT_MISSING_V1 = InsightTemplate(
    template_id="AIW_RANK_IMPROVERS_COUNT_SNAPSHOT_MISSING_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="snapshot_missing",
    compact_variants=[
        "**{category}:** previous ranking snapshot not available yet.",
        "**{category}:** rank movement needs two snapshots to compare.",
        "**{category}:** improvement signal pending the next ranking run.",
        "**{category}:** no prior snapshot to measure rank change against.",
    ],
    expanded_bullets=[
        "**Category:** {category}",
        "**Requirement:** two ranking snapshots are needed to compute rank movement.",
        "**Next step:** signal appears after the next scheduled ranking run.",
    ],
    chip_keys=["category"],
    follow_up_label="Open Category Rankings",
    allowed_conclusion_template=(
        "Rank movement data for {category} is not yet available — only one snapshot exists."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=20,
)

AIW_BIGGEST_RANK_IMPROVER_V1 = InsightTemplate(
    template_id="AIW_BIGGEST_RANK_IMPROVER_V1",
    page_type="workspace",
    insight_code="biggest_rank_improver",
    trigger_code="improver_found",
    compact_variants=[
        "**Biggest mover:** {fund_name} improved {rank_improvement_abs} places to rank {current_rank}.",
        "**Top improver:** {fund_name} moved from {previous_rank} to {current_rank}.",
        "**Rank jump:** {fund_name} gained {rank_improvement_abs} places and entered the top 30.",
        "**Largest gain:** {fund_name}, up {rank_improvement_abs} places in {category}.",
    ],
    expanded_bullets=[
        "**Previous rank:** {previous_rank}",
        "**Current rank:** {current_rank}",
        "**Rank improvement:** {rank_improvement_abs} places",
        "**Category:** {category}",
    ],
    chip_keys=["current_rank", "rank_improvement_abs", "category"],
    follow_up_label="Open Fund Detail",
    allowed_conclusion_template=(
        "{fund_name} improved from rank {previous_rank} to {current_rank} in {category} "
        "(up {rank_improvement_abs} places)."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="positive",
    priority=6,
)

AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1 = InsightTemplate(
    template_id="AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1",
    page_type="workspace",
    insight_code="biggest_rank_improver",
    trigger_code="snapshot_missing",
    compact_variants=[
        "**{category}:** rank movement data unavailable for a biggest-mover call.",
        "**{category}:** biggest improver needs two ranking snapshots.",
        "**{category}:** no prior snapshot to compare rank movement against.",
        "**{category}:** biggest-mover signal pending next ranking run.",
    ],
    expanded_bullets=[
        "**Category:** {category}",
        "**Requirement:** two ranking snapshots are needed.",
        "**Next step:** available after the next scheduled ranking run.",
    ],
    chip_keys=["category"],
    follow_up_label="Open Category Rankings",
    allowed_conclusion_template=(
        "Biggest-improver analysis for {category} is not yet available — only one snapshot exists."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=21,
)

AIW_NO_MEANINGFUL_IMPROVERS_V1 = InsightTemplate(
    template_id="AIW_NO_MEANINGFUL_IMPROVERS_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="no_improver",
    compact_variants=[
        "**{category}:** no top-30 fund improved by 3+ ranks.",
        "**{category}:** no meaningful top-30 rank improver today.",
        "**{category}:** rankings were broadly stable in the latest snapshot.",
        "**{category}:** no new rank-improvement signal crossed the threshold.",
    ],
    expanded_bullets=[
        "**Rule checked:** current rank <= 30 and rank improvement >= 3 places.",
        "**Result:** no matching fund in the latest snapshot.",
        "**Next check:** compare the full rank-movement table if needed.",
    ],
    chip_keys=["category"],
    follow_up_label="Open rank movement view",
    allowed_conclusion_template=(
        "No fund in {category} met the 3+ place rank-improvement threshold in this snapshot."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=16,
)


# ── Section 6: AI Workspace legacy (AIW_*) ────────────────────────────────────

AIW_DAILY_MOVERS = InsightTemplate(
    template_id="AIW_DAILY_MOVERS",
    page_type="workspace",
    insight_code="daily_movers",
    trigger_code="always",
    headline_template="{category}: {improvers_count} improving, {decliners_count} declining",
    body_template=(
        "In {category}, {improvers_count} funds improved their rank and "
        "{decliners_count} declined. Top improver: {top_improver_name} "
        "(rank {top_improver_rank}, moved {top_improver_delta} places)."
    ),
    required_variables=[
        "category", "improvers_count", "decliners_count",
        "top_improver_name", "top_improver_rank", "top_improver_delta",
    ],
    severity="neutral",
    priority=10,
)

AIW_TOP_STRUCTURAL_IMPROVER = InsightTemplate(
    template_id="AIW_TOP_STRUCTURAL_IMPROVER",
    page_type="workspace",
    insight_code="top_structural_improver",
    trigger_code="rank_delta_negative_and_ir_positive",
    headline_template="Structural improvement signal: {fund_name}",
    body_template=(
        "{fund_name} in {category} improved {rank_delta} places to rank "
        "{current_rank} with a positive information ratio trend. "
        "3Y active return: {active_3yr_ret:.2%}."
    ),
    required_variables=[
        "fund_name", "category", "rank_delta", "current_rank", "active_3yr_ret",
    ],
    severity="positive",
    priority=5,
)

AIW_DETERIORATING_LEADER = InsightTemplate(
    template_id="AIW_DETERIORATING_LEADER",
    page_type="workspace",
    insight_code="deteriorating_leader",
    trigger_code="top10_rank_worsened_and_ir_negative",
    headline_template="Watch: {fund_name} showing signs of deterioration",
    body_template=(
        "{fund_name} in {category} dropped {rank_delta} places to rank "
        "{current_rank}. Information ratio is negative ({ir_3yr:.2f}), "
        "suggesting weakening risk-adjusted performance."
    ),
    required_variables=[
        "fund_name", "category", "rank_delta", "current_rank", "ir_3yr",
    ],
    severity="warning",
    priority=8,
)

AIW_NO_RANK_DATA = InsightTemplate(
    template_id="AIW_NO_RANK_DATA",
    page_type="workspace",
    insight_code="no_rank_data",
    trigger_code="no_prev_rank",
    headline_template="{category}: First ranking run — no movement data yet",
    body_template=(
        "This is the first ranking evaluation for {category}. "
        "Rank movement signals will appear after the next daily refresh. "
        "{total_in_category} funds ranked."
    ),
    required_variables=["category", "total_in_category"],
    severity="neutral",
    priority=20,
)


# ── Section 7: Category Rankings (CAT_*_V1) — compact format, 2026-07-18 ────
# CAT_TOP_STRUCTURAL_IMPROVER_PARTIAL_V1, CAT_TOP_RANKED_DETERIORATING_*_V1,
# CAT_IMPROVEMENT_BREADTH_*_V1 dropped — not in the new template set. The
# breadth calculation in InsightRuleEngine stays (other logic may still use
# it); it's just not rendered as a card anymore.

CAT_TOP_STRUCTURAL_IMPROVER_V1 = InsightTemplate(
    template_id="CAT_TOP_STRUCTURAL_IMPROVER_V1",
    page_type="category_rankings",
    insight_code="top_structural_improver",
    trigger_code="improver_found",
    compact_variants=[
        "**Top improver:** {fund_name} gained {rank_improvement_abs} places to rank {current_rank}.",
        "**Strongest rank move:** {fund_name}, up {rank_improvement_abs} places in {category}.",
        "**Improvement signal:** {fund_name} moved to rank {current_rank} with positive 3Y IR slope.",
        "**Rank momentum:** {fund_name} improved {rank_improvement_abs} places over 6 months.",
    ],
    expanded_bullets=[
        "**Rank change:** +{rank_improvement_abs} places over 6 months.",
        "**Current rank:** {current_rank}",
        "**3Y IR slope:** {ir_slope_3y}",
        "**Outperformance ratio:** {outperformance_ratio_3y_pct}%",
    ],
    chip_keys=["current_rank", "rank_improvement_abs", "ir_slope_3y"],
    follow_up_label="Open Explain Rank",
    allowed_conclusion_template=(
        "{fund_name} improved {rank_improvement_abs} places to rank {current_rank} in {category}, "
        "with a positive 3Y IR slope of {ir_slope_3y}."
    ),
    source_tables=["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
    severity="positive",
    priority=5,
)

CAT_NO_CLEAR_IMPROVER_V1 = InsightTemplate(
    template_id="CAT_NO_CLEAR_IMPROVER_V1",
    page_type="category_rankings",
    insight_code="top_structural_improver",
    trigger_code="no_improver",
    compact_variants=[
        "**No clear improver:** no top-30 fund crossed the improvement threshold.",
        "**Stable category:** no strong rank-improvement signal in this snapshot.",
        "**No standout move:** rank changes did not meet the configured threshold.",
        "**No new signal:** improvement rules did not flag a category leader.",
    ],
    expanded_bullets=[
        "**Rule checked:** rank improvement >= 5 places and positive 3Y IR slope.",
        "**Result:** no matching fund.",
        "**Action:** inspect rank history or loosen thresholds if needed.",
    ],
    chip_keys=["category"],
    follow_up_label="Open rank movement chart",
    allowed_conclusion_template=(
        "No fund in {category} met the structural-improver threshold (rank improvement >= 5 "
        "places with positive 3Y IR slope) in this snapshot."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=20,
)

CAT_TOP_RANKED_WEAKENING_V1 = InsightTemplate(
    template_id="CAT_TOP_RANKED_WEAKENING_V1",
    page_type="category_rankings",
    insight_code="top_ranked_weakening",
    trigger_code="weakening_found",
    compact_variants=[
        "**Watchlist:** {fund_name} is top 10, but rank and 3Y IR trend are weakening.",
        "**Weakening top rank:** {fund_name} remains top 10 but slipped {rank_decline_abs} places.",
        "**Monitor:** {fund_name} is still highly ranked, but 3Y IR slope is negative.",
        "**Top-10 caution:** {fund_name} has rank slippage and weaker IR trend.",
    ],
    expanded_bullets=[
        "**Current rank:** {current_rank}",
        "**Rank decline:** {rank_decline_abs} places over 6 months.",
        "**3Y IR slope:** {ir_slope_3y}",
        "**Interpretation:** still highly ranked, but trend is weakening.",
    ],
    chip_keys=["current_rank", "rank_decline_abs", "ir_slope_3y"],
    follow_up_label="Open rank history and rolling IR",
    allowed_conclusion_template=(
        "{fund_name} remains ranked in the top 10 of {category} but slipped {rank_decline_abs} "
        "places with a negative 3Y IR slope ({ir_slope_3y}) — a weakening trend worth monitoring."
    ),
    source_tables=["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
    severity="warning",
    priority=8,
)

CAT_NEW_TOP_30_ENTRANTS_V1 = InsightTemplate(
    template_id="CAT_NEW_TOP_30_ENTRANTS_V1",
    page_type="category_rankings",
    insight_code="new_top30_entrants",
    trigger_code="entrants_found",
    compact_variants=[
        "**New entrants:** {count} funds moved into the top 30.",
        "**Top-30 changes:** {count} funds entered the leading group.",
        "**Fresh candidates:** {count} funds crossed into the top 30.",
        "**Rank upgrade:** {count} funds are newly inside the top 30.",
    ],
    expanded_bullets=[
        "**Rule:** previous rank > 30 and current rank <= 30.",
        "**Count:** {count} funds.",
        "**Category:** {category}",
        "**Action:** review entrants before comparing them.",
    ],
    chip_keys=["count", "category"],
    follow_up_label="Open filtered new-entrants table",
    allowed_conclusion_template=(
        "{count} fund(s) newly entered the top 30 of {category} (previously ranked below 30)."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=12,
)

CAT_TIGHT_SCORE_CLUSTER_V1 = InsightTemplate(
    template_id="CAT_TIGHT_SCORE_CLUSTER_V1",
    page_type="category_rankings",
    insight_code="tight_score_cluster",
    trigger_code="cluster_detected",
    compact_variants=[
        "**Tight cluster:** top 10 funds differ by only {score_gap_rank_1_to_10} score points.",
        "**Close race:** rank 1-10 are separated by {score_gap_rank_1_to_10} points.",
        "**Ranking caution:** top scores are tightly packed in {category}.",
        "**Small score gap:** exact order among top funds should not be overread.",
    ],
    expanded_bullets=[
        "**Score gap:** {score_gap_rank_1_to_10} points between rank 1 and rank 10.",
        "**Interpretation:** top funds are closely matched.",
        "**Action:** compare metric drivers before selecting a research candidate.",
    ],
    chip_keys=["score_gap_rank_1_to_10", "category"],
    follow_up_label="Open top-10 comparison",
    allowed_conclusion_template=(
        "The top 10 funds in {category} are tightly clustered — only {score_gap_rank_1_to_10} "
        "score points separate rank 1 from rank 10, so exact order should not be overread."
    ),
    source_tables=["selfmade_ranking_snapshot"],
    severity="neutral",
    priority=15,
)


# ── Section 7 legacy: Category Rankings (CAT_*) ───────────────────────────────

CAT_TOP_IMPROVER = InsightTemplate(
    template_id="CAT_TOP_IMPROVER",
    page_type="category_rankings",
    insight_code="top_improver",
    trigger_code="best_rank_delta_with_positive_ir_slope",
    headline_template="Top structural improver: {fund_name}",
    body_template=(
        "{fund_name} improved {rank_delta} places to rank {current_rank}/{total_in_category}. "
        "IR slope is positive ({ir_slope:.4f}/mo), indicating sustained improvement. "
        "Composite score: {composite_score:.1f}."
    ),
    required_variables=[
        "fund_name", "rank_delta", "current_rank", "total_in_category",
        "ir_slope", "composite_score",
    ],
    fallback_template_id="CAT_TOP_IMPROVER_NO_SLOPE",
    severity="positive",
    priority=10,
)

CAT_TOP_IMPROVER_NO_SLOPE = InsightTemplate(
    template_id="CAT_TOP_IMPROVER_NO_SLOPE",
    page_type="category_rankings",
    insight_code="top_improver",
    trigger_code="best_rank_delta_no_slope",
    headline_template="Top rank improver: {fund_name}",
    body_template=(
        "{fund_name} improved {rank_delta} places to rank {current_rank}/{total_in_category}. "
        "Composite score: {composite_score:.1f}. IR slope data not yet available."
    ),
    required_variables=[
        "fund_name", "rank_delta", "current_rank", "total_in_category",
        "composite_score",
    ],
    severity="positive",
    priority=12,
)

CAT_DETERIORATING_TOP = InsightTemplate(
    template_id="CAT_DETERIORATING_TOP",
    page_type="category_rankings",
    insight_code="deteriorating_top",
    trigger_code="top10_worsened_negative_ir",
    headline_template="Ranked fund showing weakness: {fund_name}",
    body_template=(
        "{fund_name} (rank {current_rank}) dropped {rank_delta} places. "
        "IR: {ir_3yr:.2f}. This may signal emerging structural weakness. "
        "Monitor over coming weeks."
    ),
    required_variables=[
        "fund_name", "current_rank", "rank_delta", "ir_3yr",
    ],
    severity="warning",
    priority=15,
)

CAT_NEW_TOP30_ENTRANTS = InsightTemplate(
    template_id="CAT_NEW_TOP30_ENTRANTS",
    page_type="category_rankings",
    insight_code="new_top30_entrants",
    trigger_code="entered_top_30",
    headline_template="{entrant_count} new entrant(s) in top 30",
    body_template=(
        "{entrant_names} entered the top 30 in {category}. "
        "Previous ranks: {prev_ranks}. These funds may be worth closer analysis."
    ),
    required_variables=["entrant_count", "entrant_names", "category", "prev_ranks"],
    severity="neutral",
    priority=18,
)

CAT_TIGHT_CLUSTER = InsightTemplate(
    template_id="CAT_TIGHT_CLUSTER",
    page_type="category_rankings",
    insight_code="tight_cluster",
    trigger_code="score_gap_lt_5",
    headline_template="Tight score cluster in top 10",
    body_template=(
        "The composite score gap between rank 1 ({rank1_name}, {rank1_score:.1f}) and "
        "rank 10 ({rank10_name}, {rank10_score:.1f}) is only {score_gap:.1f} points. "
        "Small changes in any metric could significantly reshuffle the top ranks."
    ),
    required_variables=[
        "rank1_name", "rank1_score", "rank10_name", "rank10_score", "score_gap",
    ],
    severity="neutral",
    priority=20,
)

CAT_IMPROVEMENT_BREADTH = InsightTemplate(
    template_id="CAT_IMPROVEMENT_BREADTH",
    page_type="category_rankings",
    insight_code="improvement_breadth",
    trigger_code="breadth_comparison",
    headline_template="{category}: {improving_pct:.0f}% of funds improving",
    body_template=(
        "In {category}, {improving_count} of {total_count} ranked funds "
        "improved their position ({improving_pct:.0f}%), while {deteriorating_count} "
        "deteriorated. Broad improvement breadth can indicate category-wide tailwinds."
    ),
    required_variables=[
        "category", "improving_count", "total_count", "improving_pct",
        "deteriorating_count",
    ],
    severity="neutral",
    priority=22,
)


# ── Section 8: Fund Detail (FUND_*) ─────────────────────────────────────────

FUND_HOLDINGS_CONCENTRATION = InsightTemplate(
    template_id="FUND_HOLDINGS_CONCENTRATION",
    page_type="fund_detail",
    insight_code="holdings_concentration",
    trigger_code="top5_concentration_check",
    headline_template="Top 5 holdings: {top5_pct:.1f}% of portfolio",
    body_template=(
        "The fund's top 5 holdings ({top5_names}) account for {top5_pct:.1f}% "
        "of the portfolio. {concentration_label}."
    ),
    required_variables=["top5_names", "top5_pct", "concentration_label"],
    severity="neutral",
    priority=30,
)

FUND_SECTOR_CONCENTRATION = InsightTemplate(
    template_id="FUND_SECTOR_CONCENTRATION",
    page_type="fund_detail",
    insight_code="sector_concentration",
    trigger_code="sectors_to_80_check",
    headline_template="Sector exposure: {sectors_to_80} sectors cover 80% of AUM",
    body_template=(
        "Top 3 sectors: {top3_sectors}. {sectors_to_80} sectors are needed "
        "to reach 80% of AUM. {sector_label}."
    ),
    required_variables=["top3_sectors", "sectors_to_80", "sector_label"],
    severity="neutral",
    priority=32,
)

FUND_RISK_ADJUSTED_PERF = InsightTemplate(
    template_id="FUND_RISK_ADJUSTED_PERF",
    page_type="fund_detail",
    insight_code="risk_adjusted_performance",
    trigger_code="sharpe_and_ir_check",
    headline_template="3Y risk-adjusted: {perf_label}",
    body_template=(
        "Sharpe ratio (3Y): {sharpe_3yr:.2f} (pctile: {pct_sharpe:.0f}). "
        "Information ratio (3Y): {ir_3yr}. "
        "Jensen's alpha (3Y): {alpha_3yr}. {perf_commentary}."
    ),
    required_variables=[
        "perf_label", "sharpe_3yr", "pct_sharpe", "ir_3yr", "alpha_3yr",
        "perf_commentary",
    ],
    severity="neutral",
    priority=25,
)

FUND_TREND = InsightTemplate(
    template_id="FUND_TREND",
    page_type="fund_detail",
    insight_code="trend_classification",
    trigger_code="rank_movement_check",
    headline_template="Trend: {trend_label}",
    body_template=(
        "Current rank: {current_rank}/{total_in_category} in {category}. "
        "{trend_detail}. Composite score: {composite_score:.1f}."
    ),
    required_variables=[
        "trend_label", "current_rank", "total_in_category",
        "category", "trend_detail", "composite_score",
    ],
    severity="neutral",
    priority=28,
)


# ── Section 9: Fund Comparison (CMP_*) ──────────────────────────────────────

CMP_HOLDINGS_OVERLAP = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP",
    page_type="fund_comparison",
    insight_code="holdings_overlap",
    trigger_code="overlap_check",
    headline_template="Holdings overlap: {weighted_overlap:.1f}%",
    body_template=(
        "Weighted holdings overlap is {weighted_overlap:.1f}% "
        "({common_count} common holdings out of ~{unique_count} unique). "
        "Jaccard similarity: {jaccard:.1f}%. {overlap_label}."
    ),
    required_variables=[
        "weighted_overlap", "common_count", "unique_count",
        "jaccard", "overlap_label",
    ],
    severity="neutral",
    priority=10,
)

CMP_SECTOR_OVERLAP = InsightTemplate(
    template_id="CMP_SECTOR_OVERLAP",
    page_type="fund_comparison",
    insight_code="sector_overlap",
    trigger_code="sector_overlap_check",
    headline_template="Sector overlap: {sector_overlap:.1f}%",
    body_template=(
        "The compared funds share {common_sectors} common sectors covering "
        "{sector_overlap:.1f}% of combined exposure. {sector_commentary}."
    ),
    required_variables=[
        "sector_overlap", "common_sectors", "sector_commentary",
    ],
    severity="neutral",
    priority=12,
)

CMP_SAME_CATEGORY = InsightTemplate(
    template_id="CMP_SAME_CATEGORY",
    page_type="fund_comparison",
    insight_code="category_match",
    trigger_code="category_check",
    headline_template="All funds in same category: {category}",
    body_template=(
        "All compared funds belong to {category}. Direct rank comparison "
        "is meaningful. Score spread: {score_spread:.1f} points."
    ),
    required_variables=["category", "score_spread"],
    severity="neutral",
    priority=15,
)

CMP_DIFFERENT_CATEGORY = InsightTemplate(
    template_id="CMP_DIFFERENT_CATEGORY",
    page_type="fund_comparison",
    insight_code="category_match",
    trigger_code="different_categories",
    headline_template="Funds span {category_count} categories",
    body_template=(
        "The compared funds span {category_count} categories: {categories}. "
        "Cross-category comparisons use different benchmarks — interpret with care."
    ),
    required_variables=["category_count", "categories"],
    severity="warning",
    priority=14,
)

CMP_IR_LEADER = InsightTemplate(
    template_id="CMP_IR_LEADER",
    page_type="fund_comparison",
    insight_code="ir_leader",
    trigger_code="ir_comparison",
    headline_template="IR leader: {leader_name} ({leader_ir:.2f})",
    body_template=(
        "{leader_name} has the highest information ratio ({leader_ir:.2f}) "
        "among compared funds. {ir_gap_label}."
    ),
    required_variables=["leader_name", "leader_ir", "ir_gap_label"],
    severity="positive",
    priority=18,
)

CMP_RECENT_IMPROVER = InsightTemplate(
    template_id="CMP_RECENT_IMPROVER",
    page_type="fund_comparison",
    insight_code="recent_improver",
    trigger_code="improvement_check",
    headline_template="Recent improvement leader: {improver_name}",
    body_template=(
        "{improver_name} shows the strongest recent improvement "
        "(rank delta: {rank_delta}, composite: {composite_score:.1f}). "
        "{improvement_detail}."
    ),
    required_variables=[
        "improver_name", "rank_delta", "composite_score", "improvement_detail",
    ],
    severity="positive",
    priority=20,
)

CMP_LAGGARD = InsightTemplate(
    template_id="CMP_LAGGARD",
    page_type="fund_comparison",
    insight_code="laggard",
    trigger_code="laggard_check",
    headline_template="Relative laggard: {laggard_name}",
    body_template=(
        "{laggard_name} has the lowest composite score ({laggard_score:.1f}) "
        "among compared funds. {laggard_detail}."
    ),
    required_variables=[
        "laggard_name", "laggard_score", "laggard_detail",
    ],
    severity="warning",
    priority=22,
)

CMP_BEST_OF = InsightTemplate(
    template_id="CMP_BEST_OF",
    page_type="fund_comparison",
    insight_code="best_of_summary",
    trigger_code="always",
    headline_template="Comparison summary",
    body_template=(
        "Highest composite: {best_composite_name} ({best_composite_score:.1f}). "
        "Best 1Y: {best_1yr_name}. Best 3Y: {best_3yr_name}. "
        "Best risk-adjusted: {best_risk_adj_name}."
    ),
    required_variables=[
        "best_composite_name", "best_composite_score",
        "best_1yr_name", "best_3yr_name", "best_risk_adj_name",
    ],
    severity="neutral",
    priority=25,
)


# ── Section 10: Rule Playground (RULE_*) ─────────────────────────────────────

RULE_WEIGHT_VALIDATION = InsightTemplate(
    template_id="RULE_WEIGHT_VALIDATION",
    page_type="rule_playground",
    insight_code="weight_validation",
    trigger_code="weight_sum_check",
    headline_template="Weight validation: {validation_status}",
    body_template=(
        "Total weight: {total_weight:.0f}%. {validation_message}."
    ),
    required_variables=["validation_status", "total_weight", "validation_message"],
    severity="neutral",
    priority=5,
)

RULE_RECENCY_BIAS = InsightTemplate(
    template_id="RULE_RECENCY_BIAS",
    page_type="rule_playground",
    insight_code="recency_bias",
    trigger_code="short_window_gt_50",
    headline_template="Recency bias detected",
    body_template=(
        "Short-window metrics (1Y return, etc.) account for {short_pct:.0f}% "
        "of total weight. This may cause excessive sensitivity to recent "
        "market conditions. Consider increasing longer-term metric weights."
    ),
    required_variables=["short_pct"],
    severity="warning",
    priority=8,
)

RULE_RETURN_HEAVY = InsightTemplate(
    template_id="RULE_RETURN_HEAVY",
    page_type="rule_playground",
    insight_code="return_heavy",
    trigger_code="return_weight_gt_50",
    headline_template="Return-heavy weighting",
    body_template=(
        "Return metrics account for {return_pct:.0f}% of total weight, "
        "while risk-adjusted metrics are only {risk_adj_pct:.0f}%. "
        "This may under-weight quality signals like IR and Sharpe."
    ),
    required_variables=["return_pct", "risk_adj_pct"],
    severity="warning",
    priority=10,
)

RULE_CHURN_WARNING = InsightTemplate(
    template_id="RULE_CHURN_WARNING",
    page_type="rule_playground",
    insight_code="churn_warning",
    trigger_code="churn_gt_threshold",
    headline_template="High rank churn detected: {churn_pct:.0f}%",
    body_template=(
        "{churn_pct:.0f}% of top-10 positions changed vs. the current ruleset. "
        "New entrants: {new_entrants}. Dropped: {dropped}. "
        "High churn may indicate over-sensitivity to the changed weights."
    ),
    required_variables=["churn_pct", "new_entrants", "dropped"],
    severity="warning",
    priority=12,
)

RULE_CATEGORY_BIAS = InsightTemplate(
    template_id="RULE_CATEGORY_BIAS",
    page_type="rule_playground",
    insight_code="category_bias",
    trigger_code="category_concentration_check",
    headline_template="Category concentration in results",
    body_template=(
        "{dominant_category} accounts for {dominant_pct:.0f}% of the top 10 "
        "results. This weighting may systematically favour certain fund types."
    ),
    required_variables=["dominant_category", "dominant_pct"],
    severity="neutral",
    priority=15,
)

RULE_APPROVAL_READINESS = InsightTemplate(
    template_id="RULE_APPROVAL_READINESS",
    page_type="rule_playground",
    insight_code="approval_readiness",
    trigger_code="readiness_check",
    headline_template="Approval readiness: {readiness_label}",
    body_template=(
        "{readiness_detail}. {action_suggestion}."
    ),
    required_variables=["readiness_label", "readiness_detail", "action_suggestion"],
    severity="neutral",
    priority=3,
)

RULE_SCORE_LEADER_GAP = InsightTemplate(
    template_id="RULE_SCORE_LEADER_GAP",
    page_type="rule_playground",
    insight_code="score_leader_gap",
    trigger_code="leader_gap_check",
    headline_template="Score leader gap: {gap:.1f} points",
    body_template=(
        "The gap between rank 1 ({rank1_name}, {rank1_score:.1f}) and "
        "rank 2 ({rank2_name}, {rank2_score:.1f}) is {gap:.1f} points. "
        "{gap_commentary}."
    ),
    required_variables=[
        "rank1_name", "rank1_score", "rank2_name", "rank2_score",
        "gap", "gap_commentary",
    ],
    severity="neutral",
    priority=18,
)


# ── Section 10: Rule Playground (RULE_*_V1) — compact format, 2026-07-18 ────
# RULE_FORMULA_VALID/INVALID_SYNTAX/VARIABLE/FUNCTION_V1 dropped — formula
# validation renders directly via the Formula Validation checklist UI, not
# as an insight card. RULE_CATEGORY_BIAS_*_V1 and RULE_TOP_SANDBOX_
# BENEFICIARY/LOSER_V1 dropped as cards too — the calculations stay cheap
# and available (SandboxRunSummary still carries beneficiary/loser fields),
# surfaced via the sandbox-vs-default results table's movement arrows
# instead of a separate card.

RULE_WEIGHTS_VALID_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_VALID_V1",
    page_type="rule_playground",
    insight_code="weights_valid",
    trigger_code="weights_sum_eq_100",
    compact_variants=[
        "**Rule status:** valid. Weights add to 100%.",
        "**Weights:** valid at 100%.",
        "**Rule check:** weights are balanced and valid.",
        "**Ready check:** weights pass validation.",
    ],
    expanded_bullets=[
        "**Total weight:** {total_weight_pct}%",
        "**Negative weights:** none",
        "**Duplicate metrics:** {duplicate_metric_status}",
        "**Next step:** run sandbox impact.",
    ],
    chip_keys=["total_weight_pct"],
    follow_up_label="Run sandbox",
    allowed_conclusion_template="The current rule weights sum to {total_weight_pct}% and are valid.",
    source_tables=[],
    severity="positive",
    priority=1,
)

RULE_WEIGHTS_INVALID_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_INVALID_V1",
    page_type="rule_playground",
    insight_code="weights_valid",
    trigger_code="weights_invalid",
    compact_variants=[
        "**Rule status:** invalid. Weights total {total_weight_pct}%.",
        "**Fix needed:** weights must add to 100%, not {total_weight_pct}%.",
        "**Weight error:** adjust by {weight_gap_pct} percentage points.",
        "**Not ready:** weight validation failed.",
    ],
    expanded_bullets=[
        "**Current total:** {total_weight_pct}%",
        "**Required total:** 100%",
        "**Gap:** {weight_gap_pct} percentage points",
        "**Action:** edit weights before sandbox submission.",
    ],
    chip_keys=["total_weight_pct", "weight_gap_pct"],
    follow_up_label="Focus weight editor",
    allowed_conclusion_template=(
        "The current rule weights total {total_weight_pct}%, not the required 100% "
        "(gap of {weight_gap_pct} percentage points)."
    ),
    source_tables=[],
    severity="warning",
    priority=1,
)

RULE_RECENCY_BIAS_WARNING_V1 = InsightTemplate(
    template_id="RULE_RECENCY_BIAS_WARNING_V1",
    page_type="rule_playground",
    insight_code="recency_bias",
    trigger_code="short_window_weight_gt_50",
    compact_variants=[
        "**Recency bias:** {short_window_weight_pct}% weight is on 1Y or shorter metrics.",
        "**Short-window tilt:** {short_window_weight_pct}% of the rule uses recent metrics.",
        "**Bias check:** high dependence on short-term metrics.",
        "**Rule caution:** recent performance may dominate the ranking.",
    ],
    expanded_bullets=[
        "**Short-window weight:** {short_window_weight_pct}%",
        "**Threshold:** 50%",
        "**Risk:** rankings may overreact to recent performance.",
        "**Action:** add 3Y or 5Y stabilizers if desired.",
    ],
    chip_keys=["short_window_weight_pct"],
    follow_up_label="Suggest alternative weight mix",
    allowed_conclusion_template=(
        "{short_window_weight_pct}% of this rule's weight is on short-window (<=1Y) metrics, "
        "above the 50% recency-bias threshold."
    ),
    source_tables=[],
    severity="warning",
    priority=8,
)

RULE_RETURN_HEAVY_WARNING_V1 = InsightTemplate(
    template_id="RULE_RETURN_HEAVY_WARNING_V1",
    page_type="rule_playground",
    insight_code="return_heavy",
    trigger_code="return_weight_gt_50_and_risk_adj_lt_30",
    compact_variants=[
        "**Return-heavy:** {absolute_return_weight_pct}% weight is on return metrics.",
        "**Risk balance:** rule is tilted toward raw returns.",
        "**Rule caution:** risk-adjusted metrics have low weight.",
        "**Metric mix:** returns dominate the rule design.",
    ],
    expanded_bullets=[
        "**Return weight:** {absolute_return_weight_pct}%",
        "**Risk-adjusted weight:** {risk_adjusted_weight_pct}%",
        "**Concern:** rankings may reward volatile winners.",
        "**Action:** consider IR, Sortino or downside capture weight.",
    ],
    chip_keys=["absolute_return_weight_pct", "risk_adjusted_weight_pct"],
    follow_up_label="Open metric mix editor",
    allowed_conclusion_template=(
        "This rule weights absolute return at {absolute_return_weight_pct}% versus only "
        "{risk_adjusted_weight_pct}% on risk-adjusted metrics — return-heavy design."
    ),
    source_tables=[],
    severity="warning",
    priority=10,
)

RULE_HIGH_CHURN_WARNING_V1 = InsightTemplate(
    template_id="RULE_HIGH_CHURN_WARNING_V1",
    page_type="rule_playground",
    insight_code="high_churn",
    trigger_code="top10_turnover_gt_40",
    compact_variants=[
        "**Churn warning:** {top10_turnover_count} of top 10 funds change.",
        "**High turnover:** sandbox replaces {top10_turnover_count} top-10 funds.",
        "**Rule impact:** top-10 list changes materially.",
        "**Stability check:** sandbox rule creates high rank churn.",
    ],
    expanded_bullets=[
        "**Top-10 turnover:** {top10_turnover_pct}%",
        "**Funds replaced:** {top10_turnover_count}",
        "**Average rank change:** {average_rank_change}",
        "**Action:** review whether churn is acceptable.",
    ],
    chip_keys=["top10_turnover_pct", "top10_turnover_count"],
    follow_up_label="Open sandbox vs default comparison",
    allowed_conclusion_template=(
        "This sandbox rule replaces {top10_turnover_count} of the top 10 funds "
        "({top10_turnover_pct}% turnover) versus the current default ranking."
    ),
    source_tables=[],
    severity="warning",
    priority=12,
)

RULE_READY_FOR_APPROVAL_V1 = InsightTemplate(
    template_id="RULE_READY_FOR_APPROVAL_V1",
    page_type="rule_playground",
    insight_code="approval_readiness",
    trigger_code="all_checks_pass",
    compact_variants=[
        "**Approval status:** ready to submit.",
        "**Rule status:** ready for approval workflow.",
        "**Ready:** validations passed and sandbox is complete.",
        "**Submit-ready:** rule can move to approval review.",
    ],
    expanded_bullets=[
        "**Weights:** valid",
        "**Formula:** valid",
        "**Sandbox:** complete",
        "**Approval note:** present",
    ],
    chip_keys=[],
    follow_up_label="Submit for approval",
    allowed_conclusion_template="This rule version has passed all pre-submission checks and is ready for approval.",
    source_tables=[],
    severity="positive",
    priority=0,
)

RULE_NOT_READY_FOR_APPROVAL_V1 = InsightTemplate(
    template_id="RULE_NOT_READY_FOR_APPROVAL_V1",
    page_type="rule_playground",
    insight_code="approval_readiness",
    trigger_code="any_check_fails",
    compact_variants=[
        "**Not ready:** {blocking_issue_count} issue(s) must be fixed.",
        "**Approval blocked:** resolve {blocking_issue_count} issue(s) first.",
        "**Rule status:** not ready for approval.",
        "**Fix required:** validation or sandbox checks are incomplete.",
    ],
    expanded_bullets=[
        "**Blocking issues:** {blocking_issue_count}",
        "**Weight status:** {weight_status}",
        "**Formula status:** {formula_status}",
        "**Sandbox status:** {sandbox_status}",
    ],
    chip_keys=["blocking_issue_count"],
    follow_up_label="Open blocking issue list",
    allowed_conclusion_template=(
        "This rule version is not ready for approval — {blocking_issue_count} blocking "
        "issue(s) remain."
    ),
    source_tables=[],
    severity="warning",
    priority=0,
)


# ── Section 11: Research Chat (CHAT_*) ───────────────────────────────────────

CHAT_EXPLAIN_RANKING = InsightTemplate(
    template_id="CHAT_EXPLAIN_RANKING",
    page_type="research_chat",
    insight_code="explain_ranking",
    trigger_code="user_asks_why_ranked",
    headline_template="Explain ranking for {fund_name}",
    body_template=(
        "The user is asking about {fund_name}'s rank ({current_rank}/{total_in_category} "
        "in {category}). Key factors: composite score {composite_score:.1f}, "
        "3Y return pctile {pct_3yr_ret:.0f}, IR pctile {pct_ir_3yr:.0f}."
    ),
    required_variables=[
        "fund_name", "current_rank", "total_in_category", "category",
        "composite_score", "pct_3yr_ret", "pct_ir_3yr",
    ],
    severity="neutral",
    priority=5,
)

CHAT_EXPLAIN_COMPARISON = InsightTemplate(
    template_id="CHAT_EXPLAIN_COMPARISON",
    page_type="research_chat",
    insight_code="explain_comparison",
    trigger_code="user_asks_about_comparison",
    headline_template="Comparison context for research chat",
    body_template=(
        "The user wants to discuss a comparison between {fund_names}. "
        "Overlap: {weighted_overlap:.1f}%. IR leader: {ir_leader}. "
        "Highest composite: {best_composite_name}."
    ),
    required_variables=[
        "fund_names", "weighted_overlap", "ir_leader", "best_composite_name",
    ],
    severity="neutral",
    priority=5,
)

CHAT_EXPLAIN_TREND = InsightTemplate(
    template_id="CHAT_EXPLAIN_TREND",
    page_type="research_chat",
    insight_code="explain_trend",
    trigger_code="user_asks_about_trend",
    headline_template="Trend context for {fund_name}",
    body_template=(
        "The user wants to understand {fund_name}'s performance trend. "
        "Rank: {current_rank}/{total_in_category}. Trend: {trend_label}. "
        "{trend_detail}."
    ),
    required_variables=[
        "fund_name", "current_rank", "total_in_category",
        "trend_label", "trend_detail",
    ],
    severity="neutral",
    priority=5,
)


# ── Section 12.6: Fund Detail (FUND_*_V1) — compact format, 2026-07-18 ──────
# FUND_CONC_*_V1/FUND_CONC_TOP_NAMES_V1 → folded into FUND_TOP_HOLDINGS_V1.
# FUND_SECTOR_FIN_HEAVY/BALANCED_V1 → folded into FUND_TOP_SECTORS_V1 /
# FUND_SECTORS_TO_80_V1. FUND_PERF_ALPHA_*/RANK_TIER_V1 → folded into
# FUND_3Y_PERFORMANCE_STRONG/MIXED_V1's expanded bullets. Data-freshness
# (old FRESH/STALE cards) folded into FUND_TOP_HOLDINGS_V1's as_of_date bullet
# per the POC rule — no standalone data-confidence card.
#
# Preserved fallbacks (existing trigger logic, new compact+expandable format):
# zero holdings, zero/fewer-than-3 sectors, insufficient 3Y history,
# insufficient trend data. A fund with missing data must never show nothing.

# — Group 1: Holdings —

FUND_HOLDINGS_AVAIL_NONE_V1 = InsightTemplate(
    template_id="FUND_HOLDINGS_AVAIL_NONE_V1",
    page_type="fund_detail",
    insight_code="holdings_avail_none",
    trigger_code="no_data",
    compact_variants=[
        "**Holdings:** not yet available for this fund.",
        "**Portfolio data:** not ingested for this fund yet.",
        "**Holdings status:** unavailable pending the next data refresh.",
        "**No holdings data:** concentration and sector views are unavailable.",
    ],
    expanded_bullets=[
        "**Status:** portfolio holdings have not been ingested for this fund.",
        "**Affected views:** concentration, sector, and overlap analysis.",
        "**Next step:** check back after the next data refresh cycle.",
    ],
    chip_keys=[],
    follow_up_label="Ask about data availability",
    allowed_conclusion_template="Portfolio holdings data is not yet available for this fund.",
    source_tables=["selfmade_portfolio_holding"],
    severity="neutral",
    priority=30,
)

FUND_TOP_HOLDINGS_V1 = InsightTemplate(
    template_id="FUND_TOP_HOLDINGS_V1",
    page_type="fund_detail",
    insight_code="top_holdings",
    trigger_code="holdings_gte_5",
    compact_variants=[
        "**Top holdings:** top 5 account for {top_5_weight_pct}% of AUM.",
        "**Top book:** {top_5_weight_pct}% of AUM is in the five largest holdings.",
        "**Largest positions:** top 5 holdings make up {top_5_weight_pct}% of the portfolio.",
        "**Holding concentration:** five largest holdings total {top_5_weight_pct}%.",
    ],
    expanded_bullets=[
        "**1:** {holding_1_name} — {holding_1_weight_pct}%",
        "**2:** {holding_2_name} — {holding_2_weight_pct}%",
        "**3:** {holding_3_name} — {holding_3_weight_pct}%",
        "**4:** {holding_4_name} — {holding_4_weight_pct}%",
        "**5:** {holding_5_name} — {holding_5_weight_pct}% (as of {as_of_date})",
    ],
    chip_keys=["top_5_weight_pct", "holding_count", "as_of_date"],
    follow_up_label="Open holdings table",
    allowed_conclusion_template=(
        "The top 5 holdings account for {top_5_weight_pct}% of AUM as of {as_of_date}, "
        "led by {holding_1_name} at {holding_1_weight_pct}%."
    ),
    source_tables=["selfmade_portfolio_holding", "selfmade_security_master"],
    severity="neutral",
    priority=10,
)

FUND_TOP_HOLDINGS_LESS_THAN_5_V1 = InsightTemplate(
    template_id="FUND_TOP_HOLDINGS_LESS_THAN_5_V1",
    page_type="fund_detail",
    insight_code="top_holdings",
    trigger_code="holdings_1_to_4",
    compact_variants=[
        "**Holdings shown:** only {holding_count} holdings are available for this fund.",
        "**Limited holdings data:** {holding_count} holdings available in the latest file.",
        "**Partial view:** latest holdings data has {holding_count} rows.",
        "**Holdings coverage:** fewer than 5 holdings are available.",
    ],
    expanded_bullets=[
        "**Available holdings:** {holding_count}",
        "**Latest holding date:** {as_of_date}",
        "**Action:** verify portfolio disclosure if this seems incomplete.",
    ],
    chip_keys=["holding_count", "as_of_date"],
    follow_up_label="Open source holdings file",
    allowed_conclusion_template=(
        "Only {holding_count} holdings are available for this fund as of {as_of_date} — "
        "fewer than the usual 5+ disclosed positions."
    ),
    source_tables=["selfmade_portfolio_holding"],
    severity="neutral",
    priority=28,
)

# — Group 2: Sectors —

FUND_SECTORS_UNAVAILABLE_V1 = InsightTemplate(
    template_id="FUND_SECTORS_UNAVAILABLE_V1",
    page_type="fund_detail",
    insight_code="top_sectors",
    trigger_code="sectors_lt_3",
    compact_variants=[
        "**Sector data:** fewer than 3 sectors are classified for this fund.",
        "**Sector view:** limited — {sector_count} sector(s) classified.",
        "**Sector coverage:** insufficient to show a top-3 breakdown.",
        "**Sector data:** not enough classified sectors for this fund yet.",
    ],
    expanded_bullets=[
        "**Sectors classified:** {sector_count}",
        "**Reason:** holdings may be unclassified or too few to break down by sector.",
        "**Action:** check holdings table directly if this seems incomplete.",
    ],
    chip_keys=["sector_count"],
    follow_up_label="Open holdings table",
    allowed_conclusion_template=(
        "Only {sector_count} sector(s) are classified for this fund — not enough for a "
        "top-3 sector breakdown."
    ),
    source_tables=["selfmade_portfolio_holding", "selfmade_security_master"],
    severity="neutral",
    priority=29,
)

FUND_TOP_SECTORS_V1 = InsightTemplate(
    template_id="FUND_TOP_SECTORS_V1",
    page_type="fund_detail",
    insight_code="top_sectors",
    trigger_code="sectors_gte_3",
    compact_variants=[
        "**Top sectors:** {sector_1} {sector_1_weight_pct}%, {sector_2} {sector_2_weight_pct}%, {sector_3} {sector_3_weight_pct}%.",
        "**Sector mix:** led by {sector_1}, {sector_2}, and {sector_3}.",
        "**Largest sectors:** {sector_1}, {sector_2}, and {sector_3} drive exposure.",
        "**Sector leaders:** {sector_1} is the largest exposure at {sector_1_weight_pct}%.",
    ],
    expanded_bullets=[
        "**{sector_1}:** {sector_1_weight_pct}%",
        "**{sector_2}:** {sector_2_weight_pct}%",
        "**{sector_3}:** {sector_3_weight_pct}%",
        "**Top 3 total:** {top_3_sector_weight_pct}%",
    ],
    chip_keys=["sector_1", "sector_1_weight_pct", "top_3_sector_weight_pct"],
    follow_up_label="Open sector exposure chart",
    allowed_conclusion_template=(
        "This fund's largest sector exposures are {sector_1} ({sector_1_weight_pct}%), "
        "{sector_2} ({sector_2_weight_pct}%), and {sector_3} ({sector_3_weight_pct}%)."
    ),
    source_tables=["selfmade_portfolio_holding", "selfmade_security_master"],
    severity="neutral",
    priority=19,
)

FUND_SECTORS_TO_80_V1 = InsightTemplate(
    template_id="FUND_SECTORS_TO_80_V1",
    page_type="fund_detail",
    insight_code="sectors_to_80",
    trigger_code="sectors_gte_3",
    compact_variants=[
        "**Sector spread:** {sectors_to_80} sectors make up {cumulative_sector_weight_pct}% of AUM.",
        "**Diversification check:** it takes {sectors_to_80} sectors to cross 80% AUM.",
        "**Sector concentration:** top {sectors_to_80} sectors reach {cumulative_sector_weight_pct}% of AUM.",
        "**80% build-up:** {sectors_to_80} sectors explain most of the portfolio.",
    ],
    expanded_bullets=[
        "**Sectors to 80%:** {sectors_to_80}",
        "**Cumulative weight:** {cumulative_sector_weight_pct}%",
        "**Profile:** {sector_profile_label}",
        "**Largest sector:** {sector_1} at {sector_1_weight_pct}%",
    ],
    chip_keys=["sectors_to_80", "sector_profile_label"],
    follow_up_label="Open sector table sorted by weight",
    allowed_conclusion_template=(
        "{sectors_to_80} sectors account for {cumulative_sector_weight_pct}% of AUM — a "
        "{sector_profile_label} sector profile."
    ),
    source_tables=["selfmade_portfolio_holding", "selfmade_security_master"],
    severity="neutral",
    priority=14,
)

# — Group 3: 3Y Information Ratio (percentile-based, 3-way split) —

FUND_3Y_IR_INSUFFICIENT_HISTORY_V1 = InsightTemplate(
    template_id="FUND_3Y_IR_INSUFFICIENT_HISTORY_V1",
    page_type="fund_detail",
    insight_code="3y_ir",
    trigger_code="ir_missing",
    compact_variants=[
        "**3Y IR:** not available — insufficient 3-year return history.",
        "**Risk-adjusted signal:** unavailable until 3 years of history accrue.",
        "**3Y IR check:** this fund doesn't have enough history yet.",
        "**Performance quality:** 3Y IR requires a longer track record.",
    ],
    expanded_bullets=[
        "**Status:** insufficient 3-year return history for this fund.",
        "**Requirement:** 3 years of fund and benchmark NAV history.",
        "**Alternative:** check 1-year metrics if available.",
    ],
    chip_keys=[],
    follow_up_label="Open available metrics",
    allowed_conclusion_template=(
        "This fund does not yet have enough return history to compute a 3-year information ratio."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="neutral",
    priority=27,
)

FUND_3Y_IR_TOP_TIER_V1 = InsightTemplate(
    template_id="FUND_3Y_IR_TOP_TIER_V1",
    page_type="fund_detail",
    insight_code="3y_ir",
    trigger_code="ir_percentile_gte_70",
    compact_variants=[
        "**3Y IR:** {ir_3y}. Top-tier risk-adjusted consistency.",
        "**3Y IR:** {ir_3y}, placing the fund in the stronger category bucket.",
        "**Risk-adjusted signal:** 3Y IR is strong at {ir_3y}.",
        "**3Y performance quality:** strong IR at {ir_3y}.",
    ],
    expanded_bullets=[
        "**3Y IR:** {ir_3y}",
        "**Category percentile:** {ir_3y_percentile}th",
        "**Rule bucket:** strong",
        "**Tooltip:** a category percentile of 70 or higher usually indicates positive active returns with controlled tracking error relative to peers.",
    ],
    chip_keys=["ir_3y", "ir_3y_percentile"],
    follow_up_label='Ask "Why is the 3Y IR strong?"',
    allowed_conclusion_template=(
        "This fund's 3Y information ratio of {ir_3y} is in the {ir_3y_percentile}th percentile "
        "of its category — a top-tier risk-adjusted consistency signal."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot", "selfmade_ranking_contribution"],
    severity="positive",
    priority=8,
)

FUND_3Y_IR_ACCEPTABLE_V1 = InsightTemplate(
    template_id="FUND_3Y_IR_ACCEPTABLE_V1",
    page_type="fund_detail",
    insight_code="3y_ir",
    trigger_code="ir_percentile_40_70",
    compact_variants=[
        "**3Y IR:** {ir_3y}. Acceptable, but not a clear leader.",
        "**3Y IR:** {ir_3y}, broadly middle-of-pack for the category.",
        "**Risk-adjusted signal:** 3Y IR is acceptable at {ir_3y}.",
        "**3Y IR check:** fair, but not top-tier.",
    ],
    expanded_bullets=[
        "**3Y IR:** {ir_3y}",
        "**Category percentile:** {ir_3y_percentile}th",
        "**Rule bucket:** acceptable",
        "**Action:** check Sortino, downside capture and improvement trend.",
    ],
    chip_keys=["ir_3y", "ir_3y_percentile"],
    follow_up_label="Open 3Y metrics panel",
    allowed_conclusion_template=(
        "This fund's 3Y information ratio of {ir_3y} is in the {ir_3y_percentile}th percentile "
        "of its category — acceptable, but not a category leader."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot", "selfmade_ranking_contribution"],
    severity="neutral",
    priority=9,
)

FUND_3Y_IR_WEAK_V1 = InsightTemplate(
    template_id="FUND_3Y_IR_WEAK_V1",
    page_type="fund_detail",
    insight_code="3y_ir",
    trigger_code="ir_percentile_lt_40",
    compact_variants=[
        "**3Y IR:** {ir_3y}. Weak versus category peers.",
        "**Risk-adjusted concern:** 3Y IR is low at {ir_3y}.",
        "**3Y IR check:** below the category comfort zone.",
        "**Performance quality:** 3Y IR is weaker than most peers.",
    ],
    expanded_bullets=[
        "**3Y IR:** {ir_3y}",
        "**Category percentile:** {ir_3y_percentile}th",
        "**Rule bucket:** weak",
        "**Action:** inspect tracking error and excess-return consistency.",
    ],
    chip_keys=["ir_3y", "ir_3y_percentile"],
    follow_up_label="Open rolling IR chart",
    allowed_conclusion_template=(
        "This fund's 3Y information ratio of {ir_3y} is in the {ir_3y_percentile}th percentile "
        "of its category — weak versus peers."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot", "selfmade_ranking_contribution"],
    severity="negative",
    priority=9,
)

# — Group 4: 3Y overall performance scorecard —

# FUND_3Y_PERFORMANCE_INSUFFICIENT_SORTINO_V1 (2026-07-21): the STRONG/MIXED
# gate needs real Sortino data as one of its 3 dimensions. sortino_ratio_3yr is
# only populated for a real subset of funds (78 of 3454) — for the rest, this
# fires instead of MIXED, which previously silently defaulted a missing
# Sortino to a neutral score and always reported it as the "concern" dragging
# every fund down to Mixed, even when IR and active return were both strong.
# Same insufficient-data pattern as FUND_3Y_IR_INSUFFICIENT_HISTORY_V1 —
# named for the specific missing dimension rather than a generic "no data".
FUND_3Y_PERFORMANCE_INSUFFICIENT_SORTINO_V1 = InsightTemplate(
    template_id="FUND_3Y_PERFORMANCE_INSUFFICIENT_SORTINO_V1",
    page_type="fund_detail",
    insight_code="3y_performance",
    trigger_code="sortino_missing",
    compact_variants=[
        "**3Y view:** can't fully classify — Sortino data unavailable for this fund.",
        "**3Y scorecard:** incomplete — no Sortino ratio on file for this fund.",
        "**3Y quality:** IR and active return are available, but Sortino is not.",
        "**3Y signal:** partial — Sortino data is missing, not weak.",
    ],
    expanded_bullets=[
        "**3Y IR:** {ir_3y}",
        "**Sortino:** not available for this fund",
        "**Outperformance ratio:** {outperformance_ratio_3y_pct}%",
        "**Why:** a full Strong/Mixed classification needs all 3 metrics populated; Sortino is missing, not weak.",
    ],
    chip_keys=["ir_3y", "outperformance_ratio_3y_pct"],
    follow_up_label="Open available 3Y metrics",
    allowed_conclusion_template=(
        "This fund's 3-year performance cannot be fully classified — Sortino ratio data "
        "is not available for this fund, though IR ({ir_3y}) and outperformance ratio "
        "({outperformance_ratio_3y_pct}%) are."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="neutral",
    priority=13,
)

FUND_3Y_PERFORMANCE_STRONG_V1 = InsightTemplate(
    template_id="FUND_3Y_PERFORMANCE_STRONG_V1",
    page_type="fund_detail",
    insight_code="3y_performance",
    trigger_code="good_3y",
    compact_variants=[
        "**3Y view:** strong risk-adjusted performance across key metrics.",
        "**3Y signal:** positive across IR, Sortino and consistency.",
        "**3Y quality:** fund screens well on risk-adjusted metrics.",
        "**3Y scorecard:** strong overall risk-adjusted profile.",
    ],
    expanded_bullets=[
        "**3Y IR:** {ir_3y}",
        "**Sortino:** {sortino_3y}",
        "**Outperformance ratio:** {outperformance_ratio_3y_pct}%",
        "**Category rank:** {rank_in_category} of {total_in_category}",
    ],
    chip_keys=["ir_3y", "sortino_3y", "outperformance_ratio_3y_pct"],
    follow_up_label="Open full metric scorecard",
    allowed_conclusion_template=(
        "This fund screens strong on 3-year risk-adjusted metrics: IR {ir_3y}, Sortino "
        "{sortino_3y}, and a {outperformance_ratio_3y_pct}% outperformance ratio."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="positive",
    priority=7,
)

FUND_3Y_PERFORMANCE_MIXED_V1 = InsightTemplate(
    template_id="FUND_3Y_PERFORMANCE_MIXED_V1",
    page_type="fund_detail",
    insight_code="3y_performance",
    trigger_code="mixed_3y",
    compact_variants=[
        "**3Y view:** mixed. Some metrics are good, others need checking.",
        "**3Y signal:** not one-sided; review the metric breakdown.",
        "**3Y quality:** mixed evidence across risk and return.",
        "**3Y scorecard:** no clean strong or weak classification.",
    ],
    expanded_bullets=[
        "**Positive:** {positive_metric_summary}",
        "**Concern:** {negative_metric_summary}",
        "**Action:** compare rolling IR, Sortino and downside capture together.",
    ],
    chip_keys=["ir_3y", "sortino_3y"],
    follow_up_label="Open metric comparison panel",
    allowed_conclusion_template=(
        "This fund's 3-year performance is mixed — {positive_metric_summary}, but "
        "{negative_metric_summary}."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="neutral",
    priority=13,
)

# — Group 5: Trend —

FUND_TREND_INSUFFICIENT_DATA_V1 = InsightTemplate(
    template_id="FUND_TREND_INSUFFICIENT_DATA_V1",
    page_type="fund_detail",
    insight_code="trend",
    trigger_code="trend_data_missing",
    compact_variants=[
        "**Trend:** not available — insufficient monthly IR history.",
        "**Momentum signal:** unavailable until more monthly data accrues.",
        "**Trend check:** this fund doesn't have enough rolling IR points yet.",
        "**Trend status:** requires at least 6 months of rolling IR.",
    ],
    expanded_bullets=[
        "**Status:** fewer than 6 monthly IR observations available.",
        "**Requirement:** 6+ months of rolling information ratio history.",
        "**Alternative:** check the category rank-history chart instead.",
    ],
    chip_keys=[],
    follow_up_label="Open rank history chart",
    allowed_conclusion_template=(
        "This fund does not yet have enough monthly rolling-IR history to compute a trend signal."
    ),
    source_tables=["ratio_3year_monthlyret"],
    severity="neutral",
    priority=26,
)

FUND_TREND_IMPROVING_V1 = InsightTemplate(
    template_id="FUND_TREND_IMPROVING_V1",
    page_type="fund_detail",
    insight_code="trend",
    trigger_code="improving",
    compact_variants=[
        "**Trend:** improving. Rank, IR slope and recent IR all support the signal.",
        "**Improvement:** positive 3Y IR slope with rank gain of {rank_improvement_abs} places.",
        "**Trend signal:** improving across rank and rolling IR.",
        "**Momentum:** fund is improving under the current rule set.",
    ],
    expanded_bullets=[
        "**Rank change:** +{rank_improvement_abs} places",
        "**3Y IR slope:** {ir_slope_3y}",
        "**Improvement metric:** {improvement_metric}",
        "**Recent vs prior IR:** {latest_6m_avg_rolling_ir} vs {previous_6m_avg_rolling_ir}",
    ],
    chip_keys=["rank_improvement_abs", "ir_slope_3y", "improvement_metric"],
    follow_up_label='Ask "What is driving improvement?"',
    allowed_conclusion_template="The fund is improving under the current rule set.",
    forbidden_conclusions=[
        "buy recommendation", "guaranteed outperformance",
        "manager skill attribution unless document evidence exists",
    ],
    source_tables=["ratio_3year_monthlyret", "selfmade_ranking_snapshot"],
    severity="positive",
    priority=7,
)

FUND_TREND_WEAKENING_V1 = InsightTemplate(
    template_id="FUND_TREND_WEAKENING_V1",
    page_type="fund_detail",
    insight_code="trend",
    trigger_code="weakening",
    compact_variants=[
        "**Trend:** weakening. Rank and 3Y IR slope have both moved the wrong way.",
        "**Weakening signal:** rank slipped {rank_decline_abs} places with negative IR slope.",
        "**Trend check:** weakening under the current rule set.",
        "**Momentum:** recent trend is deteriorating.",
    ],
    expanded_bullets=[
        "**Rank decline:** {rank_decline_abs} places",
        "**3Y IR slope:** {ir_slope_3y}",
        "**Improvement metric:** {improvement_metric}",
        "**Recent vs prior IR:** {latest_6m_avg_rolling_ir} vs {previous_6m_avg_rolling_ir}",
    ],
    chip_keys=["rank_decline_abs", "ir_slope_3y", "improvement_metric"],
    follow_up_label="Open rank history and rolling IR",
    allowed_conclusion_template="The fund is weakening under the current rule set.",
    source_tables=["ratio_3year_monthlyret", "selfmade_ranking_snapshot"],
    severity="warning",
    priority=7,
)

FUND_TREND_MIXED_V1 = InsightTemplate(
    template_id="FUND_TREND_MIXED_V1",
    page_type="fund_detail",
    insight_code="trend",
    trigger_code="mixed",
    compact_variants=[
        "**Trend:** mixed. Improvement is not yet confirmed across metrics.",
        "**Mixed signal:** one indicator improved, but others have not confirmed it.",
        "**Trend check:** inconclusive; review rank and rolling IR together.",
        "**Momentum:** not clear enough for a strong trend label.",
    ],
    expanded_bullets=[
        "**Positive indicator:** {positive_trend_indicator}",
        "**Offsetting indicator:** {negative_trend_indicator}",
        "**Action:** inspect rolling IR and rank movement before concluding.",
    ],
    chip_keys=["ir_slope_3y", "rank_delta_6m"],
    follow_up_label="Open trend diagnostics",
    allowed_conclusion_template=(
        "This fund's trend signal is mixed — {positive_trend_indicator}, but {negative_trend_indicator}."
    ),
    source_tables=["ratio_3year_monthlyret", "selfmade_ranking_snapshot"],
    severity="neutral",
    priority=13,
)


# ── Section 9: Fund Comparison (CMP_*_V1) — compact format, 2026-07-18 ──────
# Sector overlap, IR-unavailable, and the separate "overall best" templates
# are dropped (not in the new template set — category-leader below already
# covers "who's ahead"). CMP_HOLDINGS_OVERLAP_UNAVAILABLE_V1 is the one
# PRESERVEd fallback (holdings missing for a fund), covering both the 2-fund
# and multi-fund cases in one template.

CMP_HOLDINGS_OVERLAP_UNAVAILABLE_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_UNAVAILABLE_V1",
    page_type="fund_comparison",
    insight_code="holdings_overlap",
    trigger_code="holdings_missing",
    compact_variants=[
        "**Overlap:** holdings data unavailable for one or more compared funds.",
        "**Holdings overlap:** cannot be computed — portfolio data is missing.",
        "**Portfolio similarity:** unavailable until holdings data is refreshed.",
        "**Common book:** overlap analysis needs holdings for every selected fund.",
    ],
    expanded_bullets=[
        "**Status:** portfolio holdings missing for at least one compared fund.",
        "**Affected:** overlap %, common-holdings count, sector overlap.",
        "**Next step:** available after the next holdings data refresh.",
    ],
    chip_keys=[],
    follow_up_label="Ask about data availability",
    allowed_conclusion_template="Holdings overlap could not be computed — portfolio data is missing for one or more compared funds.",
    source_tables=["selfmade_portfolio_holding"],
    severity="neutral",
    priority=25,
)

CMP_HOLDINGS_OVERLAP_TWO_FUNDS_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_TWO_FUNDS_V1",
    page_type="fund_comparison",
    insight_code="holdings_overlap",
    trigger_code="two_funds",
    compact_variants=[
        "**Overlap:** {weighted_overlap_pct}% weighted overlap across {common_holdings_count} common holdings.",
        "**Holdings overlap:** {weighted_overlap_pct}% between {fund_a} and {fund_b}.",
        "**Portfolio similarity:** {common_holdings_count} common holdings; {weighted_overlap_pct}% weighted overlap.",
        "**Common book:** {fund_a} and {fund_b} overlap by {weighted_overlap_pct}%.",
    ],
    expanded_bullets=[
        "**Common holdings:** {common_holdings_count}",
        "**Weighted overlap:** {weighted_overlap_pct}%",
        "**Jaccard overlap:** {jaccard_overlap_pct}%",
        "**Overlap band:** {overlap_band}",
    ],
    chip_keys=["weighted_overlap_pct", "common_holdings_count", "overlap_band"],
    follow_up_label="Open common holdings table",
    allowed_conclusion_template=(
        "{fund_a} and {fund_b} share {weighted_overlap_pct}% weighted portfolio overlap "
        "({common_holdings_count} common holdings) — {overlap_band} overlap."
    ),
    source_tables=["selfmade_portfolio_holding"],
    severity="neutral",
    priority=10,
)

CMP_HOLDINGS_OVERLAP_MULTI_FUND_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MULTI_FUND_V1",
    page_type="fund_comparison",
    insight_code="holdings_overlap",
    trigger_code="multi_fund",
    compact_variants=[
        "**Average overlap:** {avg_pairwise_overlap_pct}% across compared funds.",
        "**Portfolio similarity:** average pairwise overlap is {avg_pairwise_overlap_pct}%.",
        "**Overlap range:** {min_pair_overlap_pct}% to {max_pair_overlap_pct}% across fund pairs.",
        "**Common holdings:** {common_to_all_count} holdings are shared by all selected funds.",
    ],
    expanded_bullets=[
        "**Average pairwise overlap:** {avg_pairwise_overlap_pct}%",
        "**Highest overlap:** {max_pair_name} at {max_pair_overlap_pct}%",
        "**Lowest overlap:** {min_pair_name} at {min_pair_overlap_pct}%",
        "**Common to all:** {common_to_all_count} holdings",
    ],
    chip_keys=["avg_pairwise_overlap_pct", "common_to_all_count"],
    follow_up_label="Open overlap matrix",
    allowed_conclusion_template=(
        "The compared funds have an average pairwise weighted overlap of {avg_pairwise_overlap_pct}%, "
        "ranging from {min_pair_overlap_pct}% to {max_pair_overlap_pct}%."
    ),
    source_tables=["selfmade_portfolio_holding"],
    severity="neutral",
    priority=10,
)

CMP_CLEAR_LEADER_V1 = InsightTemplate(
    template_id="CMP_CLEAR_LEADER_V1",
    page_type="fund_comparison",
    insight_code="clear_leader",
    trigger_code="leader_found",
    compact_variants=[
        "**Clear leader:** {leader_fund} leads under the current rule set.",
        "**Rule-ranked leader:** {leader_fund} is ahead by {score_gap} score points.",
        "**Comparison winner:** {leader_fund} leads on {metric_win_summary}.",
        "**Stronger candidate:** {leader_fund} leads the comparison today.",
    ],
    expanded_bullets=[
        "**Score gap:** {score_gap} points",
        "**Metric wins:** {metric_win_summary}",
        "**Current rank:** {leader_current_rank}",
        "**Category:** {category}",
    ],
    chip_keys=["leader_fund", "score_gap", "category"],
    follow_up_label="Open detailed metric comparison",
    allowed_conclusion_template=(
        "{leader_fund} is the current rule-ranked leader of this comparison in {category}, "
        "ahead by {score_gap} composite-score points and winning on {metric_win_summary}."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot"],
    severity="positive",
    priority=3,
)

CMP_NO_CLEAR_LEADER_V1 = InsightTemplate(
    template_id="CMP_NO_CLEAR_LEADER_V1",
    page_type="fund_comparison",
    insight_code="clear_leader",
    trigger_code="no_leader",
    compact_variants=[
        "**No clear leader:** score gap is small and metrics are split.",
        "**Close comparison:** no fund is clearly ahead under the current rule set.",
        "**Mixed leadership:** different funds lead on different metrics.",
        "**No single winner:** review metric drivers before deciding research priority.",
    ],
    expanded_bullets=[
        "**Top score gap:** {score_gap} points",
        "**Leader on 3Y IR:** {ir_leader}",
        "**Leader on trend:** {trend_leader}",
        "**Leader on overlap differentiation:** {differentiated_fund}",
    ],
    chip_keys=["score_gap", "ir_leader", "trend_leader"],
    follow_up_label="Open metric-by-metric comparison",
    allowed_conclusion_template=(
        "No fund clearly leads this comparison — the score gap ({score_gap} points) is narrow "
        "and different funds lead on different metrics (IR: {ir_leader}, trend: {trend_leader})."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot"],
    severity="neutral",
    priority=4,
)

CMP_BETTER_3Y_IR_V1 = InsightTemplate(
    template_id="CMP_BETTER_3Y_IR_V1",
    page_type="fund_comparison",
    insight_code="better_3y_ir",
    trigger_code="ir_leader_found",
    compact_variants=[
        "**3Y IR leader:** {ir_leader} at {leader_ir_3y}.",
        "**Best 3Y IR:** {ir_leader} leads with {leader_ir_3y}.",
        "**Risk-adjusted leader:** {ir_leader} has the strongest 3Y IR.",
        "**3Y IR comparison:** {ir_leader} is ahead of peers.",
    ],
    expanded_bullets=[
        "**Leader:** {ir_leader}",
        "**3Y IR:** {leader_ir_3y}",
        "**Next best:** {second_fund} at {second_ir_3y}",
        "**Gap:** {ir_gap}",
    ],
    chip_keys=["ir_leader", "leader_ir_3y", "ir_gap"],
    follow_up_label="Open 3Y IR and rolling IR history",
    allowed_conclusion_template=(
        "{ir_leader} has the strongest 3-year information ratio in this comparison ({leader_ir_3y}, "
        "a gap of {ir_gap} over the next-best fund)."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="positive",
    priority=16,
)

CMP_3Y_IR_CONFLICT_V1 = InsightTemplate(
    template_id="CMP_3Y_IR_CONFLICT_V1",
    page_type="fund_comparison",
    insight_code="better_3y_ir",
    trigger_code="ir_trend_conflict",
    compact_variants=[
        "**Split signal:** {ir_leader} leads 3Y IR, but {trend_leader} has better recent improvement.",
        "**IR vs trend:** {ir_leader} wins 3Y IR; {trend_leader} wins improvement.",
        "**Mixed comparison:** long-term IR and recent trend point to different funds.",
        "**Not one-sided:** {ir_leader} has stronger 3Y IR; {trend_leader} is improving faster.",
    ],
    expanded_bullets=[
        "**3Y IR leader:** {ir_leader} at {leader_ir_3y}",
        "**Trend leader:** {trend_leader}",
        "**Trend reason:** {trend_reason}",
        "**Action:** compare rolling IR before drawing a conclusion.",
    ],
    chip_keys=["ir_leader", "trend_leader", "leader_ir_3y"],
    follow_up_label="Open rolling IR and trend comparison",
    allowed_conclusion_template=(
        "{ir_leader} leads on 3-year information ratio ({leader_ir_3y}), but {trend_leader} shows "
        "stronger recent improvement ({trend_reason}) — these point to different funds, not one clear winner."
    ),
    source_tables=["selfmade_scheme_metrics"],
    severity="neutral",
    priority=17,
)

CMP_RECENT_IMPROVEMENT_LEADER_V1 = InsightTemplate(
    template_id="CMP_RECENT_IMPROVEMENT_LEADER_V1",
    page_type="fund_comparison",
    insight_code="recent_improvement",
    trigger_code="improvement_leader_found",
    compact_variants=[
        "**Improvement leader:** {trend_leader} has the strongest recent improvement signal.",
        "**Recent trend:** {trend_leader} leads on rank movement and IR slope.",
        "**Momentum leader:** {trend_leader} is improving fastest among the compared funds.",
        "**Trend edge:** {trend_leader} has the best recent improvement score.",
    ],
    expanded_bullets=[
        "**Rank change:** +{rank_improvement_abs} places",
        "**3Y IR slope:** {ir_slope_3y}",
        "**Improvement metric:** {improvement_metric}",
        "**Recent IR change:** {recent_ir_change}",
    ],
    chip_keys=["trend_leader", "rank_improvement_abs", "ir_slope_3y"],
    follow_up_label="Open improvement decomposition",
    allowed_conclusion_template=(
        "{trend_leader} shows the strongest recent-improvement signal in this comparison "
        "(rank +{rank_improvement_abs}, 3Y IR slope {ir_slope_3y})."
    ),
    source_tables=["ratio_3year_monthlyret", "selfmade_ranking_snapshot"],
    severity="positive",
    priority=19,
)

CMP_LAGGARD_V1 = InsightTemplate(
    template_id="CMP_LAGGARD_V1",
    page_type="fund_comparison",
    insight_code="laggard",
    trigger_code="laggard_found",
    compact_variants=[
        "**Laggard:** {laggard_fund} trails on key risk-adjusted metrics.",
        "**Weakest profile:** {laggard_fund} has the lowest 3Y IR and weaker trend.",
        "**Comparison caution:** {laggard_fund} is behind on risk-adjusted performance.",
        "**Lagging signal:** {laggard_fund} trails peers on the current metric set.",
    ],
    expanded_bullets=[
        "**3Y IR:** {laggard_ir_3y}",
        "**3Y IR percentile:** {laggard_ir_percentile}th",
        "**IR slope:** {laggard_ir_slope_3y}",
        "**Rank change:** {laggard_rank_delta}",
    ],
    chip_keys=["laggard_fund", "laggard_ir_3y", "laggard_ir_slope_3y"],
    follow_up_label="Open laggard diagnostics",
    allowed_conclusion_template=(
        "{laggard_fund} is the relative laggard in this comparison — 3Y IR {laggard_ir_3y}, "
        "IR slope {laggard_ir_slope_3y}, rank change {laggard_rank_delta}."
    ),
    source_tables=["selfmade_scheme_metrics", "selfmade_ranking_snapshot"],
    severity="warning",
    priority=23,
)


# ── Section 9.3: AI Workspace Lens V1 (LENS_*_V1) — compact format, 2026-07-21 ─
# Axes are always real DB columns — never the original wireframe's "1Y IR" / "2Y IR Slope"
# labels which don't exist as built. x_label / y_label come from METRIC_VOCAB at runtime.
# x_direction_phrase / y_axis_meaning / x_threshold_phrase / y_threshold_phrase are
# pre-formatted by the caller (app.routers.metrics / app.routers.workspaces) from real
# facts — never hardcoded per category — so the template itself stays a dumb fill-in.

LENS_QUADRANT_EXPLAINER_V1 = InsightTemplate(
    template_id="LENS_QUADRANT_EXPLAINER_V1",
    page_type="workspace",
    insight_code="lens_quadrant_explainer",
    trigger_code="always",
    compact_variants=[
        "**Axis guide:** {x_label} (right) vs {y_label} (up) — {fund_count} funds in {category}.",
        "**How to read this chart:** {x_label} across, {y_label} up — {category} ({fund_count} funds).",
        "**Chart legend:** each dot is a {category} fund, plotted by {x_label} and {y_label}.",
        "**Quadrant map:** {fund_count} {category} funds split by {x_label} and {y_label}.",
    ],
    expanded_bullets=[
        "Each dot = one **{category}** fund ({fund_count} total).",
        "Further right = {x_direction_phrase} (**{x_label}**).",
        "{y_axis_meaning}",
        "**Dashed lines** split funds into 4 groups using {x_threshold_phrase} and {y_threshold_phrase}.",
    ],
    chip_keys=["fund_count", "category", "x_label", "y_label"],
    follow_up_label="Discuss this chart in Research Chat",
    allowed_conclusion_template=(
        "This scatter groups {fund_count} {category} funds into 4 quadrants using "
        "{x_label} and {y_label} only."
    ),
    source_tables=["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
    severity="neutral",
    priority=1,
)

LENS_CANDIDATES_FOUND_V1 = InsightTemplate(
    template_id="LENS_CANDIDATES_FOUND_V1",
    page_type="workspace",
    insight_code="lens_candidates_found",
    trigger_code="count_gt_zero",
    compact_variants=[
        "**{count} research candidate(s)** found in the {quadrant_label} quadrant of {category}.",
        "**{quadrant_label} quadrant:** {count} {category} funds qualify.",
        "**{count} funds** match {quadrant_label} in {category}.",
        "**Filtered results:** {count} {category} funds sit in {quadrant_label}.",
    ],
    expanded_bullets=[
        "**Filter:** {filter_summary}",
        "**Category:** {category}",
        "**Top by {x_label}:** {top_candidates}",
    ],
    chip_keys=["count", "category", "quadrant_label"],
    follow_up_label="Open filtered results table",
    allowed_conclusion_template=(
        "{count} fund(s) in {category} fall in the {quadrant_label} quadrant "
        "based on {filter_summary}."
    ),
    source_tables=["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
    severity="positive",
    priority=5,
)

LENS_CANDIDATES_NONE_V1 = InsightTemplate(
    template_id="LENS_CANDIDATES_NONE_V1",
    page_type="workspace",
    insight_code="lens_candidates_none",
    trigger_code="count_zero",
    compact_variants=[
        "**No funds** match {quadrant_label} in {category}.",
        "**Zero results:** {quadrant_label} quadrant is empty for {category}.",
        "**No candidates:** nothing in {category} falls into {quadrant_label}.",
        "**Empty quadrant:** {quadrant_label} has no {category} funds right now.",
    ],
    expanded_bullets=[
        "**Filter:** {filter_summary}",
        "**Category:** {category}",
        "**Try:** loosen the filter or switch quadrants.",
    ],
    chip_keys=["category", "quadrant_label"],
    follow_up_label="Adjust filter",
    allowed_conclusion_template=(
        "No {category} funds currently fall in the {quadrant_label} quadrant "
        "based on {filter_summary}."
    ),
    source_tables=["selfmade_ranking_snapshot", "selfmade_scheme_metrics"],
    severity="neutral",
    priority=10,
)


# ── Template Registry ────────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, InsightTemplate] = {}

for _name, _obj in list(globals().items()):
    if isinstance(_obj, InsightTemplate):
        TEMPLATE_REGISTRY[_obj.template_id] = _obj


def get_template(template_id: str) -> InsightTemplate | None:
    return TEMPLATE_REGISTRY.get(template_id)
