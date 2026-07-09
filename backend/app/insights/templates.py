"""
Frozen template library for the Insights Engine.

Every insight is rendered from these templates using str.format_map().
No LLM calls for page insight cards — ENABLE_LLM_PAGE_INSIGHT_POLISH = False.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InsightTemplate:
    template_id: str
    page_type: str
    insight_code: str
    trigger_code: str
    headline_template: str
    body_template: str
    required_variables: list[str] = field(default_factory=list)
    fallback_template_id: str | None = None
    severity: str = "neutral"
    priority: int = 100


# ── Section 6: AI Workspace V1 (AIW_*_V1) ────────────────────────────────────
# Improver definition (Section 12.6): rank_delta <= -3 AND current_rank <= 30

AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1 = InsightTemplate(
    template_id="AIW_RANK_IMPROVERS_COUNT_POSITIVE_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="count_gt_zero",
    headline_template="{count} fund(s) show structural improvement in {category}",
    body_template=(
        "{count} fund(s) in {category} improved their rank by 3 or more places "
        "and are currently positioned in the top 30. "
        "The strongest improver is {top_improver_name} "
        "(moved from rank {prev_rank} to rank {current_rank})."
    ),
    required_variables=["count", "category", "top_improver_name", "prev_rank", "current_rank"],
    severity="positive",
    priority=5,
)

AIW_RANK_IMPROVERS_COUNT_ZERO_V1 = InsightTemplate(
    template_id="AIW_RANK_IMPROVERS_COUNT_ZERO_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="count_zero",
    headline_template="No structural improvement signals in {category}",
    body_template=(
        "No funds in {category} improved their rank by 3 or more places "
        "into the top 30 in the current evaluation period."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=15,
)

AIW_RANK_IMPROVERS_COUNT_SNAPSHOT_MISSING_V1 = InsightTemplate(
    template_id="AIW_RANK_IMPROVERS_COUNT_SNAPSHOT_MISSING_V1",
    page_type="workspace",
    insight_code="rank_improvers_count",
    trigger_code="snapshot_missing",
    headline_template="{category}: Previous ranking snapshot not available",
    body_template=(
        "Rank movement data for {category} requires two ranking snapshots. "
        "Improvement signals will appear after the next ranking run completes."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=20,
)

AIW_BIGGEST_RANK_IMPROVER_POSITIVE_V1 = InsightTemplate(
    template_id="AIW_BIGGEST_RANK_IMPROVER_POSITIVE_V1",
    page_type="workspace",
    insight_code="biggest_rank_improver",
    trigger_code="improver_found",
    headline_template="Biggest structural improver: {fund_name}",
    body_template=(
        "{fund_name} in {category} moved from rank {prev_rank} to rank {current_rank} "
        "(improved {delta} places). Sharpe ratio: {sharpe:.4f}."
    ),
    required_variables=["fund_name", "category", "prev_rank", "current_rank", "delta", "sharpe"],
    severity="positive",
    priority=6,
)

AIW_BIGGEST_RANK_IMPROVER_NONE_V1 = InsightTemplate(
    template_id="AIW_BIGGEST_RANK_IMPROVER_NONE_V1",
    page_type="workspace",
    insight_code="biggest_rank_improver",
    trigger_code="no_improver",
    headline_template="No qualifying rank improvers in {category}",
    body_template=(
        "No fund in {category} meets the structural improvement threshold "
        "(rank improved by 3 or more places into the top 30) in this evaluation period."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=16,
)

AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1 = InsightTemplate(
    template_id="AIW_BIGGEST_RANK_IMPROVER_SNAPSHOT_MISSING_V1",
    page_type="workspace",
    insight_code="biggest_rank_improver",
    trigger_code="snapshot_missing",
    headline_template="{category}: Rank movement data unavailable",
    body_template=(
        "Biggest-improver analysis for {category} requires two ranking snapshots. "
        "This signal will be available after the next scheduled ranking run."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=21,
)

AIW_DAILY_BRIEFING_SUMMARY_V1 = InsightTemplate(
    template_id="AIW_DAILY_BRIEFING_SUMMARY_V1",
    page_type="workspace",
    insight_code="daily_briefing_summary",
    trigger_code="always",
    headline_template="Daily briefing: {evaluation_date}",
    body_template=(
        "Across {category_count} categories evaluated: "
        "{total_improvers} structural improvement signal(s) detected. "
        "{summary_detail}."
    ),
    required_variables=["evaluation_date", "category_count", "total_improvers", "summary_detail"],
    severity="neutral",
    priority=25,
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


# ── Section 7: Category Rankings V1 (CAT_*_V1) ──────────────────────────────
# Improver definition: rank_delta <= -3 AND current_rank <= 30 (same as AIW)
# Deteriorating definition: rank_delta >= +3 AND prev_rank <= 20

CAT_TOP_STRUCTURAL_IMPROVER_FOUND_V1 = InsightTemplate(
    template_id="CAT_TOP_STRUCTURAL_IMPROVER_FOUND_V1",
    page_type="category_rankings",
    insight_code="top_structural_improver",
    trigger_code="improver_found",
    headline_template="{fund_name} leads structural improvement in {category}",
    body_template=(
        "{fund_name} improved {abs_delta} places (from rank {prev_rank} to {current_rank}) "
        "and carries a composite score of {composite_score:.1f}/100. "
        "IR slope is positive ({ir_slope:+.4f}/month), signalling a sustained "
        "improvement trajectory."
    ),
    required_variables=[
        "fund_name", "category", "abs_delta", "prev_rank", "current_rank",
        "composite_score", "ir_slope",
    ],
    severity="positive",
    priority=5,
)

CAT_TOP_STRUCTURAL_IMPROVER_NONE_V1 = InsightTemplate(
    template_id="CAT_TOP_STRUCTURAL_IMPROVER_NONE_V1",
    page_type="category_rankings",
    insight_code="top_structural_improver",
    trigger_code="no_improver",
    headline_template="No structural improvers detected in {category}",
    body_template=(
        "No fund in {category} meets the structural improvement threshold "
        "(rank improved by ≥3 places into the top 30) in the current evaluation period."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=20,
)

CAT_TOP_STRUCTURAL_IMPROVER_PARTIAL_V1 = InsightTemplate(
    template_id="CAT_TOP_STRUCTURAL_IMPROVER_PARTIAL_V1",
    page_type="category_rankings",
    insight_code="top_structural_improver",
    trigger_code="partial_data",
    headline_template="{category}: Partial snapshot data — improvement signals limited",
    body_template=(
        "Fewer than 2 ranking snapshots are available for {category}. "
        "Structural improvement signals will be available after the next evaluation run."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=25,
)

CAT_TOP_RANKED_DETERIORATING_FOUND_V1 = InsightTemplate(
    template_id="CAT_TOP_RANKED_DETERIORATING_FOUND_V1",
    page_type="category_rankings",
    insight_code="top_ranked_deteriorating",
    trigger_code="deterioration_found",
    headline_template="{fund_name} showing signs of deterioration in {category}",
    body_template=(
        "{fund_name} dropped {abs_delta} places to rank {current_rank} "
        "(was rank {prev_rank}). Composite score: {composite_score:.1f}/100. "
        "Monitor closely over the next evaluation window."
    ),
    required_variables=[
        "fund_name", "category", "abs_delta", "prev_rank", "current_rank",
        "composite_score",
    ],
    severity="warning",
    priority=8,
)

CAT_TOP_RANKED_DETERIORATING_NONE_V1 = InsightTemplate(
    template_id="CAT_TOP_RANKED_DETERIORATING_NONE_V1",
    page_type="category_rankings",
    insight_code="top_ranked_deteriorating",
    trigger_code="no_deterioration",
    headline_template="No deterioration signals in top-ranked funds in {category}",
    body_template=(
        "Previously top-20 funds in {category} maintained or improved their positions "
        "in the current evaluation period."
    ),
    required_variables=["category"],
    severity="positive",
    priority=18,
)

CAT_NEW_TOP_30_ENTRANTS_POSITIVE_V1 = InsightTemplate(
    template_id="CAT_NEW_TOP_30_ENTRANTS_POSITIVE_V1",
    page_type="category_rankings",
    insight_code="new_top30_entrants",
    trigger_code="entrants_found",
    headline_template="{entrant_count} new entrant(s) in the top 30 for {category}",
    body_template=(
        "{entrant_names} entered the top 30 in {category} this period. "
        "These funds were previously ranked at positions {prev_ranks}. "
        "They may warrant closer research-grade analysis."
    ),
    required_variables=[
        "entrant_count", "category", "entrant_names", "prev_ranks",
    ],
    severity="neutral",
    priority=12,
)

CAT_NEW_TOP_30_ENTRANTS_ZERO_V1 = InsightTemplate(
    template_id="CAT_NEW_TOP_30_ENTRANTS_ZERO_V1",
    page_type="category_rankings",
    insight_code="new_top30_entrants",
    trigger_code="no_entrants",
    headline_template="No new entrants in the top 30 for {category}",
    body_template=(
        "The top 30 composition in {category} remained stable "
        "relative to the previous evaluation snapshot."
    ),
    required_variables=["category"],
    severity="neutral",
    priority=22,
)

CAT_TIGHT_SCORE_CLUSTER_TRUE_V1 = InsightTemplate(
    template_id="CAT_TIGHT_SCORE_CLUSTER_TRUE_V1",
    page_type="category_rankings",
    insight_code="tight_score_cluster",
    trigger_code="cluster_detected",
    headline_template="Tight score cluster at the top of {category}",
    body_template=(
        "The score gap between rank 1 ({rank1_name}, {rank1_score:.1f}) and "
        "rank 10 ({rank10_name}, {rank10_score:.1f}) is only {score_gap:.1f} points. "
        "Small metric changes could significantly reshuffle the top positions."
    ),
    required_variables=[
        "category", "rank1_name", "rank1_score", "rank10_name",
        "rank10_score", "score_gap",
    ],
    severity="neutral",
    priority=15,
)

CAT_TIGHT_SCORE_CLUSTER_FALSE_V1 = InsightTemplate(
    template_id="CAT_TIGHT_SCORE_CLUSTER_FALSE_V1",
    page_type="category_rankings",
    insight_code="tight_score_cluster",
    trigger_code="clear_separation",
    headline_template="Clear score separation in {category} top 10",
    body_template=(
        "The score gap between rank 1 ({rank1_name}, {rank1_score:.1f}) and "
        "rank 10 ({rank10_name}, {rank10_score:.1f}) is {score_gap:.1f} points, "
        "indicating clear separation between the leaders."
    ),
    required_variables=[
        "category", "rank1_name", "rank1_score", "rank10_name",
        "rank10_score", "score_gap",
    ],
    severity="neutral",
    priority=18,
)

CAT_IMPROVEMENT_BREADTH_POSITIVE_V1 = InsightTemplate(
    template_id="CAT_IMPROVEMENT_BREADTH_POSITIVE_V1",
    page_type="category_rankings",
    insight_code="improvement_breadth",
    trigger_code="majority_improving",
    headline_template="{improving_pct:.0f}% of funds improved in {category}",
    body_template=(
        "{improving_count} of {total_count} ranked funds in {category} "
        "improved their composite score relative to the previous snapshot "
        "({improving_pct:.0f}%). Broad improvement may reflect category-wide tailwinds."
    ),
    required_variables=[
        "category", "improving_count", "total_count", "improving_pct",
    ],
    severity="positive",
    priority=14,
)

CAT_IMPROVEMENT_BREADTH_NEGATIVE_V1 = InsightTemplate(
    template_id="CAT_IMPROVEMENT_BREADTH_NEGATIVE_V1",
    page_type="category_rankings",
    insight_code="improvement_breadth",
    trigger_code="majority_deteriorating",
    headline_template="{deteriorating_pct:.0f}% of funds deteriorated in {category}",
    body_template=(
        "{deteriorating_count} of {total_count} ranked funds in {category} "
        "saw their composite score decline relative to the previous snapshot "
        "({deteriorating_pct:.0f}%). Broad deterioration may indicate category-level headwinds."
    ),
    required_variables=[
        "category", "deteriorating_count", "total_count", "deteriorating_pct",
    ],
    severity="warning",
    priority=10,
)

CAT_IMPROVEMENT_BREADTH_BALANCED_V1 = InsightTemplate(
    template_id="CAT_IMPROVEMENT_BREADTH_BALANCED_V1",
    page_type="category_rankings",
    insight_code="improvement_breadth",
    trigger_code="balanced_breadth",
    headline_template="Mixed signals in {category}: improvement breadth balanced",
    body_template=(
        "{improving_count} funds improved and {deteriorating_count} deteriorated "
        "in {category} this period (out of {total_count} total). "
        "No clear directional trend in the category."
    ),
    required_variables=[
        "category", "improving_count", "deteriorating_count", "total_count",
    ],
    severity="neutral",
    priority=16,
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


# ── Section 10b: Rule Playground V1 (20 specific RULE_*_V1 templates) ────────
# These replace/supplement the generic RULE_* templates above.
# Language rule: no "recommendation", "buy", "sell", "best fund", "top pick".

RULE_WEIGHTS_VALID_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_VALID_V1",
    page_type="rule_playground",
    insight_code="weights_valid",
    trigger_code="weights_sum_eq_100",
    headline_template="Rule weights are valid — total {total_pct:.1f}%",
    body_template=(
        "All {component_count} rule component(s) carry non-negative weights that sum to "
        "{total_pct:.1f}%. The rule engine will use these weights as entered."
    ),
    required_variables=["total_pct", "component_count"],
    severity="positive",
    priority=1,
)

RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_INVALID_TOTAL_HIGH_V1",
    page_type="rule_playground",
    insight_code="weights_invalid_high",
    trigger_code="weights_sum_gt_100",
    headline_template="Rule weights exceed 100% — current total {total_pct:.1f}%",
    body_template=(
        "The {component_count} component weights sum to {total_pct:.1f}%, which exceeds 100%. "
        "Reduce the weights by {excess_pct:.1f} percentage point(s) before running the sandbox "
        "or submitting for approval."
    ),
    required_variables=["total_pct", "component_count", "excess_pct"],
    severity="warning",
    priority=1,
)

RULE_WEIGHTS_INVALID_TOTAL_LOW_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_INVALID_TOTAL_LOW_V1",
    page_type="rule_playground",
    insight_code="weights_invalid_low",
    trigger_code="weights_sum_lt_100",
    headline_template="Rule weights are below 100% — current total {total_pct:.1f}%",
    body_template=(
        "The {component_count} component weights sum to {total_pct:.1f}%, which is "
        "{shortfall_pct:.1f} percentage point(s) short of the required 100%. "
        "Increase one or more weights before running the sandbox."
    ),
    required_variables=["total_pct", "component_count", "shortfall_pct"],
    severity="warning",
    priority=1,
)

RULE_WEIGHTS_INVALID_NEGATIVE_V1 = InsightTemplate(
    template_id="RULE_WEIGHTS_INVALID_NEGATIVE_V1",
    page_type="rule_playground",
    insight_code="weights_invalid_negative",
    trigger_code="any_weight_lt_0",
    headline_template="Negative weights are not allowed",
    body_template=(
        "Component '{offending_component}' has a negative weight ({offending_weight:.1f}%). "
        "All weights must be ≥ 0. Set this component to 0 to exclude it from scoring."
    ),
    required_variables=["offending_component", "offending_weight"],
    severity="warning",
    priority=1,
)

RULE_FORMULA_VALID_V1 = InsightTemplate(
    template_id="RULE_FORMULA_VALID_V1",
    page_type="rule_playground",
    insight_code="formula_valid",
    trigger_code="formula_passes_parse",
    headline_template="Formula is valid — {formula_component}",
    body_template=(
        "The formula expression for '{formula_component}' parsed successfully. "
        "Referenced variables: {parsed_variables}. "
        "Sample evaluation: {sample_result}."
    ),
    required_variables=["formula_component", "parsed_variables", "sample_result"],
    severity="positive",
    priority=2,
)

RULE_FORMULA_INVALID_SYNTAX_V1 = InsightTemplate(
    template_id="RULE_FORMULA_INVALID_SYNTAX_V1",
    page_type="rule_playground",
    insight_code="formula_invalid_syntax",
    trigger_code="formula_syntax_error",
    headline_template="Formula syntax error — {formula_component}",
    body_template=(
        "The formula expression for '{formula_component}' could not be parsed. "
        "Error: {parse_error}. "
        "Check for mismatched parentheses, missing operators, or invalid characters."
    ),
    required_variables=["formula_component", "parse_error"],
    severity="warning",
    priority=2,
)

RULE_FORMULA_INVALID_VARIABLE_V1 = InsightTemplate(
    template_id="RULE_FORMULA_INVALID_VARIABLE_V1",
    page_type="rule_playground",
    insight_code="formula_invalid_variable",
    trigger_code="formula_unknown_variable",
    headline_template="Formula uses unavailable variables — {formula_component}",
    body_template=(
        "The formula for '{formula_component}' references variable(s) not in the "
        "metric vocabulary: {unknown_variables}. "
        "Available variables include: {available_sample}."
    ),
    required_variables=["formula_component", "unknown_variables", "available_sample"],
    severity="warning",
    priority=2,
)

RULE_FORMULA_INVALID_FUNCTION_V1 = InsightTemplate(
    template_id="RULE_FORMULA_INVALID_FUNCTION_V1",
    page_type="rule_playground",
    insight_code="formula_invalid_function",
    trigger_code="formula_unsupported_function",
    headline_template="Formula uses unsupported functions — {formula_component}",
    body_template=(
        "The formula for '{formula_component}' calls function(s) not on the allow-list: "
        "{unsupported_functions}. "
        "Permitted functions: AVG, SLOPE, PERCENTILE_RANK, ZSCORE."
    ),
    required_variables=["formula_component", "unsupported_functions"],
    severity="warning",
    priority=2,
)

RULE_RECENCY_BIAS_WARNING_V1 = InsightTemplate(
    template_id="RULE_RECENCY_BIAS_WARNING_V1",
    page_type="rule_playground",
    insight_code="recency_bias_warning",
    trigger_code="short_window_weight_gt_50",
    headline_template="Recency-bias warning — short-window weight {short_window_pct:.0f}%",
    body_template=(
        "Short-window metrics (window ≤ 12 months: {short_window_components}) carry "
        "{short_window_pct:.0f}% of total weight, exceeding the 50% threshold. "
        "This may cause the ranked list to over-react to recent market moves. "
        "Consider redistributing weight to longer-window metrics."
    ),
    required_variables=["short_window_pct", "short_window_components"],
    severity="warning",
    priority=8,
)

RULE_RECENCY_BIAS_OK_V1 = InsightTemplate(
    template_id="RULE_RECENCY_BIAS_OK_V1",
    page_type="rule_playground",
    insight_code="recency_bias_ok",
    trigger_code="short_window_weight_le_50",
    headline_template="Recency weight is within limit — {short_window_pct:.0f}%",
    body_template=(
        "Short-window metrics carry {short_window_pct:.0f}% of total weight (limit: 50%). "
        "The rule balances near-term signals with longer-window structural metrics."
    ),
    required_variables=["short_window_pct"],
    severity="positive",
    priority=8,
)

RULE_RETURN_HEAVY_WARNING_V1 = InsightTemplate(
    template_id="RULE_RETURN_HEAVY_WARNING_V1",
    page_type="rule_playground",
    insight_code="return_heavy_warning",
    trigger_code="return_weight_gt_50_and_risk_adj_lt_30",
    headline_template="Rule is return-heavy — return weight {return_pct:.0f}%, risk-adjusted {risk_adj_pct:.0f}%",
    body_template=(
        "Absolute-return metrics carry {return_pct:.0f}% of total weight while "
        "risk-adjusted metrics (IR, Sharpe, Sortino) carry only {risk_adj_pct:.0f}%. "
        "This may rank funds that generated returns through higher risk rather than "
        "structural quality. Consider increasing risk-adjusted metric weights."
    ),
    required_variables=["return_pct", "risk_adj_pct"],
    severity="warning",
    priority=10,
)

RULE_RETURN_BALANCED_V1 = InsightTemplate(
    template_id="RULE_RETURN_BALANCED_V1",
    page_type="rule_playground",
    insight_code="return_balanced",
    trigger_code="return_and_risk_adj_balanced",
    headline_template="Return and risk-adjusted weights are balanced",
    body_template=(
        "Return metrics carry {return_pct:.0f}% and risk-adjusted metrics carry "
        "{risk_adj_pct:.0f}% of total weight. The rule blends performance and "
        "structural quality signals adequately."
    ),
    required_variables=["return_pct", "risk_adj_pct"],
    severity="positive",
    priority=10,
)

RULE_HIGH_CHURN_WARNING_V1 = InsightTemplate(
    template_id="RULE_HIGH_CHURN_WARNING_V1",
    page_type="rule_playground",
    insight_code="high_churn_warning",
    trigger_code="top10_turnover_gt_40",
    headline_template="High churn warning — {turnover_pct:.0f}% top-10 turnover",
    body_template=(
        "{turnover_pct:.0f}% of the top-10 positions differ between the sandbox and "
        "the current default ranking (threshold: 40%). "
        "Funds entering top-10 under sandbox: {entering_funds}. "
        "Funds leaving: {leaving_funds}. "
        "High churn may signal excessive sensitivity to the changed weights."
    ),
    required_variables=["turnover_pct", "entering_funds", "leaving_funds"],
    severity="warning",
    priority=12,
)

RULE_CHURN_NORMAL_V1 = InsightTemplate(
    template_id="RULE_CHURN_NORMAL_V1",
    page_type="rule_playground",
    insight_code="churn_normal",
    trigger_code="top10_turnover_le_40",
    headline_template="Churn is within limit — {turnover_pct:.0f}% top-10 turnover",
    body_template=(
        "Only {turnover_pct:.0f}% of the top-10 positions changed relative to the "
        "current default ranking (limit: 40%). The sandbox weights produce stable "
        "structural rankings."
    ),
    required_variables=["turnover_pct"],
    severity="positive",
    priority=12,
)

RULE_CATEGORY_BIAS_WARNING_V1 = InsightTemplate(
    template_id="RULE_CATEGORY_BIAS_WARNING_V1",
    page_type="rule_playground",
    insight_code="category_bias_warning",
    trigger_code="rank_shift_magnitude_2x_across_categories",
    headline_template="Category-bias warning — rank shift {max_shift:.1f}× vs {min_shift:.1f}×",
    body_template=(
        "The sandbox weights produce sharply different rank-movement magnitudes across "
        "fund categories: {high_churn_category} shows average shift of {max_shift:.1f} "
        "places, while {low_churn_category} shows only {min_shift:.1f} places. "
        "The rule may systematically favour or penalise certain categories."
    ),
    required_variables=[
        "high_churn_category", "max_shift", "low_churn_category", "min_shift",
    ],
    severity="warning",
    priority=15,
)

RULE_CATEGORY_BIAS_NONE_V1 = InsightTemplate(
    template_id="RULE_CATEGORY_BIAS_NONE_V1",
    page_type="rule_playground",
    insight_code="category_bias_none",
    trigger_code="rank_shift_magnitude_within_2x",
    headline_template="No major category bias flagged",
    body_template=(
        "Rank-movement magnitude is broadly consistent across the sampled categories "
        "(max/min ratio {shift_ratio:.1f}×). The sandbox weights do not appear to "
        "systematically favour one category over another."
    ),
    required_variables=["shift_ratio"],
    severity="positive",
    priority=15,
)

RULE_TOP_SANDBOX_BENEFICIARY_V1 = InsightTemplate(
    template_id="RULE_TOP_SANDBOX_BENEFICIARY_V1",
    page_type="rule_playground",
    insight_code="top_sandbox_beneficiary",
    trigger_code="largest_positive_rank_change",
    headline_template="Biggest sandbox beneficiary — {fund_name} (+{places} places)",
    body_template=(
        "{fund_name} moves from rank {default_rank} (default) to rank {sandbox_rank} "
        "(sandbox), gaining {places} places. "
        "This fund benefits most from the proposed weight changes."
    ),
    required_variables=["fund_name", "places", "default_rank", "sandbox_rank"],
    severity="neutral",
    priority=17,
)

RULE_TOP_SANDBOX_LOSER_V1 = InsightTemplate(
    template_id="RULE_TOP_SANDBOX_LOSER_V1",
    page_type="rule_playground",
    insight_code="top_sandbox_loser",
    trigger_code="largest_negative_rank_change",
    headline_template="Biggest sandbox decliner — {fund_name} ({places} places)",
    body_template=(
        "{fund_name} moves from rank {default_rank} (default) to rank {sandbox_rank} "
        "(sandbox), declining {places} places. "
        "This fund is most affected by the proposed weight changes."
    ),
    required_variables=["fund_name", "places", "default_rank", "sandbox_rank"],
    severity="neutral",
    priority=17,
)

RULE_READY_FOR_APPROVAL_V1 = InsightTemplate(
    template_id="RULE_READY_FOR_APPROVAL_V1",
    page_type="rule_playground",
    insight_code="ready_for_approval",
    trigger_code="all_checks_pass",
    headline_template="Ready for approval submission",
    body_template=(
        "All pre-submission checks passed: weights sum to 100%, all formulas are valid, "
        "the sandbox run is complete ({fund_count} funds evaluated), and a rationale "
        "text is present. The rule version can be submitted for team approval."
    ),
    required_variables=["fund_count"],
    severity="positive",
    priority=0,
)

RULE_NOT_READY_FOR_APPROVAL_V1 = InsightTemplate(
    template_id="RULE_NOT_READY_FOR_APPROVAL_V1",
    page_type="rule_playground",
    insight_code="not_ready_for_approval",
    trigger_code="any_check_fails",
    headline_template="Not ready for approval — {blocking_check_count} issue(s) to resolve",
    body_template=(
        "The following check(s) must pass before submission: {blocking_checks}. "
        "Address each issue and re-run the sandbox before submitting."
    ),
    required_variables=["blocking_check_count", "blocking_checks"],
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


# ── Section 12.6: Fund Detail V1 (FUND_*_V1) ────────────────────────────────
# Group 1: Holdings availability

FUND_HOLDINGS_AVAIL_FULL_V1 = InsightTemplate(
    template_id="FUND_HOLDINGS_AVAIL_FULL_V1",
    page_type="fund_detail",
    insight_code="holdings_avail_full",
    trigger_code="full_data",
    headline_template="Portfolio holdings: {holding_count} positions as of {as_of_date}",
    body_template=(
        "Full holdings data is available for this fund with {holding_count} positions "
        "as of {as_of_date}. The portfolio is {weight_coverage:.1f}% accounted for "
        "by named holdings; the remainder represents cash or unclassified positions."
    ),
    required_variables=["holding_count", "as_of_date", "weight_coverage"],
    severity="positive",
    priority=10,
)

FUND_HOLDINGS_AVAIL_NONE_V1 = InsightTemplate(
    template_id="FUND_HOLDINGS_AVAIL_NONE_V1",
    page_type="fund_detail",
    insight_code="holdings_avail_none",
    trigger_code="no_data",
    headline_template="Holdings data not available for this fund",
    body_template=(
        "Portfolio holdings data has not been ingested for this fund yet. "
        "Concentration, sector, and overlap analysis will be available after the next "
        "data refresh cycle."
    ),
    required_variables=[],
    severity="neutral",
    priority=30,
)

FUND_HOLDINGS_AVAIL_STALE_V1 = InsightTemplate(
    template_id="FUND_HOLDINGS_AVAIL_STALE_V1",
    page_type="fund_detail",
    insight_code="holdings_avail_stale",
    trigger_code="stale_data",
    headline_template="Holdings data may be outdated (as of {as_of_date})",
    body_template=(
        "The most recent portfolio holdings for this fund are from {as_of_date}, "
        "which is more than 60 days ago. Current sector and concentration analysis "
        "may not reflect the latest portfolio composition."
    ),
    required_variables=["as_of_date"],
    severity="warning",
    priority=20,
)

FUND_HOLDINGS_DATA_FRESH_V1 = InsightTemplate(
    template_id="FUND_HOLDINGS_DATA_FRESH_V1",
    page_type="fund_detail",
    insight_code="holdings_data_fresh",
    trigger_code="fresh_data",
    headline_template="Holdings data current as of {as_of_date}",
    body_template=(
        "Portfolio holdings data is current (as of {as_of_date}, within the last 30 days). "
        "Sector and concentration analysis reflects the latest disclosed composition."
    ),
    required_variables=["as_of_date"],
    severity="positive",
    priority=12,
)

# Group 2: Concentration

FUND_CONC_HIGH_V1 = InsightTemplate(
    template_id="FUND_CONC_HIGH_V1",
    page_type="fund_detail",
    insight_code="conc_high",
    trigger_code="top5_gt_35pct",
    headline_template="High concentration: top 5 holdings are {top5_pct:.1f}% of portfolio",
    body_template=(
        "The top 5 holdings account for {top5_pct:.1f}% of the portfolio — above the "
        "{threshold}% high-concentration threshold. Leading positions include "
        "{top3_names}. This level of concentration amplifies the impact of "
        "individual security outcomes on overall fund performance."
    ),
    required_variables=["top5_pct", "threshold", "top3_names"],
    severity="warning",
    priority=15,
)

FUND_CONC_MODERATE_V1 = InsightTemplate(
    template_id="FUND_CONC_MODERATE_V1",
    page_type="fund_detail",
    insight_code="conc_moderate",
    trigger_code="top5_20_35pct",
    headline_template="Moderate concentration: top 5 at {top5_pct:.1f}%",
    body_template=(
        "Top 5 holdings represent {top5_pct:.1f}% of the portfolio — within the moderate "
        "concentration range ({lower}%–{upper}%). Key positions: {top3_names}."
    ),
    required_variables=["top5_pct", "lower", "upper", "top3_names"],
    severity="neutral",
    priority=18,
)

FUND_CONC_LOW_V1 = InsightTemplate(
    template_id="FUND_CONC_LOW_V1",
    page_type="fund_detail",
    insight_code="conc_low",
    trigger_code="top5_lt_20pct",
    headline_template="Diversified holdings: top 5 at {top5_pct:.1f}%",
    body_template=(
        "Top 5 holdings represent only {top5_pct:.1f}% of the portfolio, indicating "
        "broad diversification across positions. Key holdings include {top3_names}."
    ),
    required_variables=["top5_pct", "top3_names"],
    severity="positive",
    priority=20,
)

FUND_CONC_TOP_NAMES_V1 = InsightTemplate(
    template_id="FUND_CONC_TOP_NAMES_V1",
    page_type="fund_detail",
    insight_code="conc_top_names",
    trigger_code="always",
    headline_template="Top holding: {top1_name} at {top1_pct:.1f}%",
    body_template=(
        "Largest single holding: {top1_name} ({top1_pct:.1f}%). "
        "Top 3 positions: {top3_names} (combined {top3_pct:.1f}%)."
    ),
    required_variables=["top1_name", "top1_pct", "top3_names", "top3_pct"],
    severity="neutral",
    priority=22,
)

# Group 3: Sectors

FUND_SECTOR_CONCENTRATED_V1 = InsightTemplate(
    template_id="FUND_SECTOR_CONCENTRATED_V1",
    page_type="fund_detail",
    insight_code="sector_concentrated",
    trigger_code="sectors_to_80_lte_3",
    headline_template="Sector-concentrated: {sectors_to_80} sectors reach 80% of portfolio",
    body_template=(
        "Only {sectors_to_80} sector(s) are needed to cover 80% of this portfolio, "
        "indicating high sectoral concentration. Dominant sectors: {top_sectors}. "
        "Research candidates in this fund carry concentrated sector exposure."
    ),
    required_variables=["sectors_to_80", "top_sectors"],
    severity="warning",
    priority=14,
)

FUND_SECTOR_DIVERSIFIED_V1 = InsightTemplate(
    template_id="FUND_SECTOR_DIVERSIFIED_V1",
    page_type="fund_detail",
    insight_code="sector_diversified",
    trigger_code="sectors_to_80_gte_6",
    headline_template="Broad sector diversification: {sectors_to_80} sectors to reach 80%",
    body_template=(
        "{sectors_to_80} sectors are needed to cover 80% of the portfolio, "
        "reflecting broad sectoral diversification. Top sector exposures: {top_sectors}."
    ),
    required_variables=["sectors_to_80", "top_sectors"],
    severity="positive",
    priority=18,
)

FUND_SECTOR_FIN_HEAVY_V1 = InsightTemplate(
    template_id="FUND_SECTOR_FIN_HEAVY_V1",
    page_type="fund_detail",
    insight_code="sector_fin_heavy",
    trigger_code="financials_gt_35pct",
    headline_template="Financials sector: {fin_pct:.1f}% of portfolio",
    body_template=(
        "Financial sector holdings represent {fin_pct:.1f}% of the portfolio, "
        "which is above the {threshold}% elevated-exposure threshold. "
        "This fund carries concentrated exposure to financial sector performance and policy."
    ),
    required_variables=["fin_pct", "threshold"],
    severity="warning",
    priority=16,
)

FUND_SECTOR_BALANCED_V1 = InsightTemplate(
    template_id="FUND_SECTOR_BALANCED_V1",
    page_type="fund_detail",
    insight_code="sector_balanced",
    trigger_code="no_single_sector_gt_25pct",
    headline_template="Balanced sector allocation — no sector exceeds {max_sector_pct:.1f}%",
    body_template=(
        "No single sector exceeds {max_sector_pct:.1f}% of the portfolio. "
        "This balanced allocation reduces concentration risk across sector cycles. "
        "Largest sector: {top_sector_name} at {max_sector_pct:.1f}%."
    ),
    required_variables=["max_sector_pct", "top_sector_name"],
    severity="positive",
    priority=19,
)

# Group 4: 3Y Performance

FUND_PERF_IR_STRONG_V1 = InsightTemplate(
    template_id="FUND_PERF_IR_STRONG_V1",
    page_type="fund_detail",
    insight_code="perf_ir_strong",
    trigger_code="ir_3yr_gt_0.5",
    headline_template="Strong 3Y information ratio: {ir_3yr:.2f}",
    body_template=(
        "The 3-year information ratio of {ir_3yr:.2f} places this fund in the top tier "
        "for risk-adjusted excess return consistency. An IR above {threshold} indicates "
        "the fund has delivered active returns with relatively low tracking error over "
        "the evaluation window. Category rank: {rank_in_category} of {total_in_category}."
    ),
    required_variables=["ir_3yr", "threshold", "rank_in_category", "total_in_category"],
    severity="positive",
    priority=8,
)

FUND_PERF_IR_WEAK_V1 = InsightTemplate(
    template_id="FUND_PERF_IR_WEAK_V1",
    page_type="fund_detail",
    insight_code="perf_ir_weak",
    trigger_code="ir_3yr_lt_0.1",
    headline_template="Below-threshold information ratio: {ir_3yr:.2f}",
    body_template=(
        "The 3-year information ratio of {ir_3yr:.2f} is below the {threshold} threshold "
        "for consistent active return generation. This may reflect elevated tracking error "
        "relative to active return, or inconsistency in outperforming the benchmark. "
        "Category rank: {rank_in_category} of {total_in_category}."
    ),
    required_variables=["ir_3yr", "threshold", "rank_in_category", "total_in_category"],
    severity="negative",
    priority=9,
)

FUND_PERF_ALPHA_POSITIVE_V1 = InsightTemplate(
    template_id="FUND_PERF_ALPHA_POSITIVE_V1",
    page_type="fund_detail",
    insight_code="perf_alpha_positive",
    trigger_code="active_3yr_gt_2pct",
    headline_template="Positive 3Y active return: {active_3yr_ret:+.2f}%",
    body_template=(
        "This fund has delivered {active_3yr_ret:+.2f}% active return versus its "
        "benchmark ({benchmark_name}) over 3 years, exceeding the {threshold}% "
        "positive-contribution threshold. The fund return was {fund_3yr_ret:.2f}% "
        "versus the benchmark's implied return."
    ),
    required_variables=["active_3yr_ret", "benchmark_name", "threshold", "fund_3yr_ret"],
    severity="positive",
    priority=10,
)

FUND_PERF_ALPHA_NEGATIVE_V1 = InsightTemplate(
    template_id="FUND_PERF_ALPHA_NEGATIVE_V1",
    page_type="fund_detail",
    insight_code="perf_alpha_negative",
    trigger_code="active_3yr_lt_0pct",
    headline_template="Negative 3Y active return: {active_3yr_ret:+.2f}%",
    body_template=(
        "This fund's 3-year active return of {active_3yr_ret:+.2f}% is negative versus "
        "{benchmark_name}. The fund return was {fund_3yr_ret:.2f}%. "
        "Sustained negative active returns reduce the structural case for an actively "
        "managed position versus a passive alternative."
    ),
    required_variables=["active_3yr_ret", "benchmark_name", "fund_3yr_ret"],
    severity="negative",
    priority=11,
)

FUND_PERF_RANK_TIER_V1 = InsightTemplate(
    template_id="FUND_PERF_RANK_TIER_V1",
    page_type="fund_detail",
    insight_code="perf_rank_tier",
    trigger_code="always",
    headline_template="Category rank: {rank_in_category} of {total_in_category} ({tier})",
    body_template=(
        "This fund ranks {rank_in_category} out of {total_in_category} in {category}, "
        "placing it in the {tier} tier (composite score: {composite_score:.1f}). "
        "Score components — IR₃: {pct_ir:.0f}th percentile, "
        "Sharpe₃: {pct_sharpe:.0f}th percentile."
    ),
    required_variables=[
        "rank_in_category", "total_in_category", "category",
        "tier", "composite_score", "pct_ir", "pct_sharpe",
    ],
    severity="neutral",
    priority=6,
)

# Group 5: Trend

FUND_TREND_IMPROVING_V1 = InsightTemplate(
    template_id="FUND_TREND_IMPROVING_V1",
    page_type="fund_detail",
    insight_code="trend_improving",
    trigger_code="rank_delta_lte_neg3",
    headline_template="Improving trend: rank moved from {prev_rank} to {current_rank}",
    body_template=(
        "This fund has improved {abs_delta} place(s) in the last evaluation period "
        "(from rank {prev_rank} to {current_rank} in {category}). "
        "Composite score: {composite_score:.1f}. This upward movement meets the "
        "structural improvement signal threshold."
    ),
    required_variables=[
        "abs_delta", "prev_rank", "current_rank", "category", "composite_score",
    ],
    severity="positive",
    priority=7,
)

FUND_TREND_DECLINING_V1 = InsightTemplate(
    template_id="FUND_TREND_DECLINING_V1",
    page_type="fund_detail",
    insight_code="trend_declining",
    trigger_code="rank_delta_gte_3",
    headline_template="Declining trend: rank moved from {prev_rank} to {current_rank}",
    body_template=(
        "This fund has dropped {abs_delta} place(s) since the prior evaluation "
        "(from rank {prev_rank} to {current_rank} in {category}). "
        "Composite score: {composite_score:.1f}. Monitor for further changes before "
        "drawing conclusions from a single-period movement."
    ),
    required_variables=[
        "abs_delta", "prev_rank", "current_rank", "category", "composite_score",
    ],
    severity="warning",
    priority=7,
)

FUND_TREND_STABLE_V1 = InsightTemplate(
    template_id="FUND_TREND_STABLE_V1",
    page_type="fund_detail",
    insight_code="trend_stable",
    trigger_code="rank_delta_small",
    headline_template="Stable rank position: {current_rank} in {category}",
    body_template=(
        "Rank position has been stable at {current_rank} in {category} "
        "(delta: {rank_delta:+d} places since prior period). "
        "Composite score: {composite_score:.1f}."
    ),
    required_variables=["current_rank", "category", "rank_delta", "composite_score"],
    severity="neutral",
    priority=12,
)

FUND_TREND_NEW_V1 = InsightTemplate(
    template_id="FUND_TREND_NEW_V1",
    page_type="fund_detail",
    insight_code="trend_new",
    trigger_code="no_prev_rank",
    headline_template="First evaluation period for this fund in {category}",
    body_template=(
        "This is the first ranking snapshot for this fund in {category}. "
        "Rank: {current_rank} of {total_in_category}. "
        "Trend signals will appear after the next evaluation period."
    ),
    required_variables=["category", "current_rank", "total_in_category"],
    severity="neutral",
    priority=15,
)


# ── Section 9 V1: Fund Comparison (CMP_*_V1) ─────────────────────────────────
# 28 templates covering: holdings overlap, sector overlap, category leader,
# IR leadership, recent improvement, laggard flagging, and best-overall.

# ── Holdings overlap 2-fund ───────────────────────────────────────────────────

CMP_HOLDINGS_OVERLAP_VERY_HIGH_2F_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_VERY_HIGH_2F_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_vhigh_2f",
    trigger_code="cmp_holdings_check_2f",
    headline_template="Very high holdings overlap: {weighted_overlap:.1f}% weighted",
    body_template=(
        "Funds {fund_a_name} and {fund_b_name} share {weighted_overlap:.1f}% weighted overlap "
        "({common_count} common securities, Jaccard {jaccard:.1f}%). "
        "This level of similarity substantially reduces the diversification benefit of holding both. "
        "Holding both funds is structurally close to a concentrated single-fund position."
    ),
    required_variables=["fund_a_name", "fund_b_name", "weighted_overlap", "common_count", "jaccard"],
    severity="warning",
    priority=5,
)

CMP_HOLDINGS_OVERLAP_HIGH_2F_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_HIGH_2F_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_high_2f",
    trigger_code="cmp_holdings_check_2f",
    headline_template="High holdings overlap: {weighted_overlap:.1f}% weighted",
    body_template=(
        "Funds {fund_a_name} and {fund_b_name} share {weighted_overlap:.1f}% weighted overlap "
        "({common_count} common securities, Jaccard {jaccard:.1f}%). "
        "This is meaningful portfolio commonality — holding both provides limited incremental "
        "diversification relative to a single-fund position. "
        "Review whether the active positions in each fund justify the dual allocation."
    ),
    required_variables=["fund_a_name", "fund_b_name", "weighted_overlap", "common_count", "jaccard"],
    severity="warning",
    priority=6,
)

CMP_HOLDINGS_OVERLAP_MODERATE_2F_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MODERATE_2F_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_mod_2f",
    trigger_code="cmp_holdings_check_2f",
    headline_template="Moderate holdings overlap: {weighted_overlap:.1f}% weighted",
    body_template=(
        "Funds {fund_a_name} and {fund_b_name} share {weighted_overlap:.1f}% weighted overlap "
        "({common_count} common securities, Jaccard {jaccard:.1f}%). "
        "Some diversification benefit exists — the funds share a meaningful common core "
        "but each holds distinct active positions that may justify a combined allocation."
    ),
    required_variables=["fund_a_name", "fund_b_name", "weighted_overlap", "common_count", "jaccard"],
    severity="neutral",
    priority=7,
)

CMP_HOLDINGS_OVERLAP_LOW_2F_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_LOW_2F_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_low_2f",
    trigger_code="cmp_holdings_check_2f",
    headline_template="Low holdings overlap: {weighted_overlap:.1f}% weighted",
    body_template=(
        "Funds {fund_a_name} and {fund_b_name} share only {weighted_overlap:.1f}% weighted overlap "
        "({common_count} common securities, Jaccard {jaccard:.1f}%). "
        "Strong diversification potential — the portfolios are structurally distinct, "
        "and a combined allocation may offer meaningful exposure breadth."
    ),
    required_variables=["fund_a_name", "fund_b_name", "weighted_overlap", "common_count", "jaccard"],
    severity="positive",
    priority=8,
)

CMP_HOLDINGS_OVERLAP_UNAVAILABLE_2F_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_UNAVAILABLE_2F_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_unavail_2f",
    trigger_code="cmp_holdings_check_2f",
    headline_template="Holdings overlap: data not available",
    body_template=(
        "Portfolio holdings data is not available for one or both of the compared funds. "
        "Holdings overlap, Jaccard similarity, and common-securities analysis cannot be computed. "
        "This analysis will be available after the next data refresh cycle."
    ),
    required_variables=[],
    severity="neutral",
    priority=15,
)

# ── Holdings overlap multi-fund (3-4) ─────────────────────────────────────────

CMP_HOLDINGS_OVERLAP_MULTI_HIGH_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MULTI_HIGH_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_multi_high",
    trigger_code="cmp_holdings_check_multi",
    headline_template="High average pairwise overlap across {num_funds} funds: {avg_pairwise_overlap:.1f}%",
    body_template=(
        "The {num_funds} funds being compared ({fund_names}) show an average pairwise weighted overlap "
        "of {avg_pairwise_overlap:.1f}%. This indicates a high degree of structural similarity "
        "across the group, which substantially reduces the diversification benefit of the combined allocation. "
        "Consider whether this multi-fund structure adds genuine breadth."
    ),
    required_variables=["num_funds", "fund_names", "avg_pairwise_overlap"],
    severity="warning",
    priority=5,
)

CMP_HOLDINGS_OVERLAP_MULTI_MODERATE_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MULTI_MODERATE_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_multi_mod",
    trigger_code="cmp_holdings_check_multi",
    headline_template="Moderate average pairwise overlap across {num_funds} funds: {avg_pairwise_overlap:.1f}%",
    body_template=(
        "The {num_funds} funds being compared ({fund_names}) show an average pairwise weighted overlap "
        "of {avg_pairwise_overlap:.1f}%. Each pair shares a meaningful common core, "
        "but distinct active positions across the group may provide some incremental diversification value."
    ),
    required_variables=["num_funds", "fund_names", "avg_pairwise_overlap"],
    severity="neutral",
    priority=7,
)

CMP_HOLDINGS_OVERLAP_MULTI_LOW_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MULTI_LOW_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_multi_low",
    trigger_code="cmp_holdings_check_multi",
    headline_template="Low average pairwise overlap across {num_funds} funds: {avg_pairwise_overlap:.1f}%",
    body_template=(
        "The {num_funds} funds being compared ({fund_names}) show an average pairwise weighted overlap "
        "of only {avg_pairwise_overlap:.1f}%. The group appears structurally distinct, "
        "suggesting meaningful diversification potential across the combined allocation."
    ),
    required_variables=["num_funds", "fund_names", "avg_pairwise_overlap"],
    severity="positive",
    priority=8,
)

CMP_HOLDINGS_OVERLAP_MULTI_UNAVAILABLE_V1 = InsightTemplate(
    template_id="CMP_HOLDINGS_OVERLAP_MULTI_UNAVAILABLE_V1",
    page_type="fund_comparison",
    insight_code="cmp_hld_overlap_multi_unavail",
    trigger_code="cmp_holdings_check_multi",
    headline_template="Holdings overlap: data not available for one or more funds",
    body_template=(
        "Portfolio holdings data is missing for one or more of the {num_funds} funds being compared "
        "({fund_names}). Pairwise overlap analysis cannot be fully computed. "
        "Results will be available after the next holdings data refresh."
    ),
    required_variables=["num_funds", "fund_names"],
    severity="neutral",
    priority=15,
)

# ── Sector overlap ────────────────────────────────────────────────────────────

CMP_SECTOR_OVERLAP_HIGH_V1 = InsightTemplate(
    template_id="CMP_SECTOR_OVERLAP_HIGH_V1",
    page_type="fund_comparison",
    insight_code="cmp_sector_overlap_high",
    trigger_code="cmp_sector_check",
    headline_template="High sector overlap: {sector_overlap:.1f}% of AUM in common sectors",
    body_template=(
        "The compared funds ({fund_names}) share {sector_overlap:.1f}% of their combined AUM "
        "in common sectors. This high sector co-exposure means combined macro and policy risks "
        "may not be effectively diversified. "
        "Review whether the sector concentration serves a deliberate thematic view."
    ),
    required_variables=["fund_names", "sector_overlap"],
    severity="warning",
    priority=9,
)

CMP_SECTOR_OVERLAP_MODERATE_V1 = InsightTemplate(
    template_id="CMP_SECTOR_OVERLAP_MODERATE_V1",
    page_type="fund_comparison",
    insight_code="cmp_sector_overlap_mod",
    trigger_code="cmp_sector_check",
    headline_template="Moderate sector overlap: {sector_overlap:.1f}% in common sectors",
    body_template=(
        "The compared funds ({fund_names}) share {sector_overlap:.1f}% of their combined AUM "
        "in common sectors. Some sector co-exposure exists, though the funds also differ "
        "in sector allocation, providing partial sector-level diversification."
    ),
    required_variables=["fund_names", "sector_overlap"],
    severity="neutral",
    priority=10,
)

CMP_SECTOR_OVERLAP_LOW_V1 = InsightTemplate(
    template_id="CMP_SECTOR_OVERLAP_LOW_V1",
    page_type="fund_comparison",
    insight_code="cmp_sector_overlap_low",
    trigger_code="cmp_sector_check",
    headline_template="Low sector overlap: {sector_overlap:.1f}% in common sectors",
    body_template=(
        "The compared funds ({fund_names}) share only {sector_overlap:.1f}% of combined AUM "
        "in common sectors. The funds appear to be meaningfully differentiated at the sector level, "
        "which may contribute to macroeconomic and policy-cycle diversification."
    ),
    required_variables=["fund_names", "sector_overlap"],
    severity="positive",
    priority=11,
)

CMP_SECTOR_OVERLAP_UNAVAILABLE_V1 = InsightTemplate(
    template_id="CMP_SECTOR_OVERLAP_UNAVAILABLE_V1",
    page_type="fund_comparison",
    insight_code="cmp_sector_overlap_unavail",
    trigger_code="cmp_sector_check",
    headline_template="Sector overlap: data not available",
    body_template=(
        "Sector allocation data is not available for one or more of the compared funds ({fund_names}). "
        "Sector overlap analysis will be available after holdings data has been refreshed."
    ),
    required_variables=["fund_names"],
    severity="neutral",
    priority=20,
)

# ── Category leader ───────────────────────────────────────────────────────────

CMP_SAME_CATEGORY_CLEAR_LEADER_V1 = InsightTemplate(
    template_id="CMP_SAME_CATEGORY_CLEAR_LEADER_V1",
    page_type="fund_comparison",
    insight_code="cmp_cat_clear_leader",
    trigger_code="cmp_category_check",
    headline_template="Clear structural leader in {category}: {leader_name}",
    body_template=(
        "All compared funds belong to {category}, enabling direct peer comparison. "
        "{leader_name} leads with a composite score gap of {score_gap:.1f} points "
        "and wins on {metrics_won} of the compared metrics. "
        "This margin is sufficient to identify a tentative structural leader — "
        "though rankings can shift with metric updates."
    ),
    required_variables=["leader_name", "category", "score_gap", "metrics_won"],
    severity="positive",
    priority=12,
)

CMP_SAME_CATEGORY_NO_CLEAR_LEADER_V1 = InsightTemplate(
    template_id="CMP_SAME_CATEGORY_NO_CLEAR_LEADER_V1",
    page_type="fund_comparison",
    insight_code="cmp_cat_no_leader",
    trigger_code="cmp_category_check",
    headline_template="No clear leader in {category} — treat {score_gap:.1f}-point gap as narrow",
    body_template=(
        "All compared funds belong to {category}. "
        "The composite score gap between the top- and bottom-ranked fund is only {score_gap:.1f} points — "
        "treat this as a narrow margin. Small metric changes could reshuffle the ranking. "
        "Monitor IR slope and rank delta over upcoming evaluation periods before drawing conclusions."
    ),
    required_variables=["category", "score_gap"],
    severity="neutral",
    priority=13,
)

CMP_DIFFERENT_CATEGORY_NO_LEADER_V1 = InsightTemplate(
    template_id="CMP_DIFFERENT_CATEGORY_NO_LEADER_V1",
    page_type="fund_comparison",
    insight_code="cmp_cat_diff_category",
    trigger_code="cmp_category_check",
    headline_template="Cross-category comparison: {num_categories} categories present",
    body_template=(
        "The compared funds span {num_categories} categories: {categories_str}. "
        "Direct rank comparison across categories is not meaningful — each fund uses "
        "a different benchmark, and composite scores reflect within-category peer rankings. "
        "Interpret relative metrics (IR, active return) with the benchmark differences in mind."
    ),
    required_variables=["categories_str", "num_categories"],
    severity="warning",
    priority=14,
)

# ── IR leadership ─────────────────────────────────────────────────────────────

CMP_IR_LEADER_CLEAR_V1 = InsightTemplate(
    template_id="CMP_IR_LEADER_CLEAR_V1",
    page_type="fund_comparison",
    insight_code="cmp_ir_leader_clear",
    trigger_code="cmp_ir_check",
    headline_template="Clear 3Y IR leader: {leader_name} (IR {leader_ir:.2f}, gap {gap:.2f})",
    body_template=(
        "{leader_name} has the highest 3-year information ratio ({leader_ir:.2f}) "
        "among the compared funds, with a gap of {gap:.2f} over the nearest peer. "
        "This margin indicates a structurally consistent edge in risk-adjusted excess return "
        "relative to the benchmark over the evaluation period."
    ),
    required_variables=["leader_name", "leader_ir", "gap"],
    severity="positive",
    priority=16,
)

CMP_IR_LEADER_CLOSE_V1 = InsightTemplate(
    template_id="CMP_IR_LEADER_CLOSE_V1",
    page_type="fund_comparison",
    insight_code="cmp_ir_leader_close",
    trigger_code="cmp_ir_check",
    headline_template="Narrow 3Y IR difference: {leader_name} leads by {gap:.2f}",
    body_template=(
        "{leader_name} marginally leads on 3-year information ratio ({leader_ir:.2f}), "
        "but the gap of {gap:.2f} over the nearest peer is narrow — treat this as close. "
        "IR slope and recent improvement metrics may be more informative than the point-in-time IR alone."
    ),
    required_variables=["leader_name", "leader_ir", "gap"],
    severity="neutral",
    priority=17,
)

CMP_IR_CONFLICT_RECENT_IMPROVER_V1 = InsightTemplate(
    template_id="CMP_IR_CONFLICT_RECENT_IMPROVER_V1",
    page_type="fund_comparison",
    insight_code="cmp_ir_conflict",
    trigger_code="cmp_ir_check",
    headline_template="IR conflict: {ir_leader_name} leads 3Y IR, but {slope_leader_name} is improving faster",
    body_template=(
        "{ir_leader_name} leads on 3-year information ratio ({ir_leader_val:.2f}), "
        "but {slope_leader_name} shows a stronger positive IR slope ({slope_leader_val:+.4f}/month), "
        "indicating faster recent improvement in risk-adjusted active return. "
        "This structural conflict merits tracking over the next 1-2 evaluation periods before drawing conclusions."
    ),
    required_variables=["ir_leader_name", "slope_leader_name", "ir_leader_val", "slope_leader_val"],
    severity="neutral",
    priority=18,
)

CMP_IR_UNAVAILABLE_V1 = InsightTemplate(
    template_id="CMP_IR_UNAVAILABLE_V1",
    page_type="fund_comparison",
    insight_code="cmp_ir_unavail",
    trigger_code="cmp_ir_check",
    headline_template="3Y IR data not available for one or more compared funds",
    body_template=(
        "Information ratio data is missing for one or more of the compared funds ({fund_names}). "
        "IR comparison cannot be completed. This analysis will be available after metric recalculation."
    ),
    required_variables=["fund_names"],
    severity="neutral",
    priority=25,
)

# ── Recent improvement ────────────────────────────────────────────────────────

CMP_RECENT_IMPROVEMENT_LEADER_CLEAR_V1 = InsightTemplate(
    template_id="CMP_RECENT_IMPROVEMENT_LEADER_CLEAR_V1",
    page_type="fund_comparison",
    insight_code="cmp_improvement_clear",
    trigger_code="cmp_improvement_check",
    headline_template="Clear recent improvement leader: {leader_name}",
    body_template=(
        "{leader_name} leads on recent improvement with an improvement score of {improvement_score:+.4f} "
        "and a gap of {gap:.4f} over the next fund. "
        "This positive trajectory suggests strengthening risk-adjusted performance relative to peers — "
        "a signal worth monitoring as a potential structural improvement indicator."
    ),
    required_variables=["leader_name", "improvement_score", "gap"],
    severity="positive",
    priority=19,
)

CMP_RECENT_IMPROVEMENT_CLOSE_V1 = InsightTemplate(
    template_id="CMP_RECENT_IMPROVEMENT_CLOSE_V1",
    page_type="fund_comparison",
    insight_code="cmp_improvement_close",
    trigger_code="cmp_improvement_check",
    headline_template="Similar recent improvement trajectory across funds",
    body_template=(
        "{leader_name} marginally leads on recent improvement (score {improvement_score:+.4f}), "
        "but the gap of {gap:.4f} to the next fund is narrow — treat as close. "
        "Continue monitoring improvement slope across evaluation periods."
    ),
    required_variables=["leader_name", "improvement_score", "gap"],
    severity="neutral",
    priority=21,
)

CMP_RECENT_IMPROVEMENT_NONE_V1 = InsightTemplate(
    template_id="CMP_RECENT_IMPROVEMENT_NONE_V1",
    page_type="fund_comparison",
    insight_code="cmp_improvement_none",
    trigger_code="cmp_improvement_check",
    headline_template="No positive improvement signal detected in compared funds",
    body_template=(
        "None of the compared funds ({fund_names}) shows a clearly positive recent improvement trajectory. "
        "IR slopes are flat or declining across the comparison set. "
        "This may reflect category-level headwinds rather than fund-specific weakness."
    ),
    required_variables=["fund_names"],
    severity="warning",
    priority=22,
)

# ── Laggard flagging ──────────────────────────────────────────────────────────

CMP_LAGGARD_CLEAR_V1 = InsightTemplate(
    template_id="CMP_LAGGARD_CLEAR_V1",
    page_type="fund_comparison",
    insight_code="cmp_laggard_clear",
    trigger_code="cmp_laggard_check",
    headline_template="Relative laggard identified: {laggard_name}",
    body_template=(
        "{laggard_name} is the weakest fund in this comparison across multiple dimensions: "
        "3Y IR of {laggard_ir_pct:.2f}, IR slope of {laggard_ir_slope:+.4f}/month, "
        "and a rank position {rank_delta:+d} places versus the prior snapshot. "
        "Downside capture: {laggard_downside_capture}. "
        "This combination of signals warrants careful evaluation before continued allocation."
    ),
    required_variables=[
        "laggard_name", "laggard_ir_pct", "laggard_ir_slope",
        "laggard_downside_capture", "rank_delta",
    ],
    severity="warning",
    priority=23,
)

CMP_LAGGARD_SOFT_V1 = InsightTemplate(
    template_id="CMP_LAGGARD_SOFT_V1",
    page_type="fund_comparison",
    insight_code="cmp_laggard_soft",
    trigger_code="cmp_laggard_check",
    headline_template="Soft laggard signal: {laggard_name} shows weak conditions",
    body_template=(
        "{laggard_name} shows weakness on the following dimensions: {weak_conditions}. "
        "This is a soft signal — the fund does not meet the threshold for a clear structural laggard designation, "
        "but warrants monitoring over the next 1-2 evaluation periods."
    ),
    required_variables=["laggard_name", "weak_conditions"],
    severity="warning",
    priority=24,
)

CMP_LAGGARD_NONE_V1 = InsightTemplate(
    template_id="CMP_LAGGARD_NONE_V1",
    page_type="fund_comparison",
    insight_code="cmp_laggard_none",
    trigger_code="cmp_laggard_check",
    headline_template="No clear laggard in this comparison",
    body_template=(
        "None of the compared funds ({fund_names}) shows a sufficient combination of weak signals "
        "to be flagged as a structural laggard. All funds are within an acceptable range "
        "on IR, rank movement, and improvement metrics."
    ),
    required_variables=["fund_names"],
    severity="positive",
    priority=25,
)

# ── Overall best ──────────────────────────────────────────────────────────────

CMP_BEST_CLEAR_V1 = InsightTemplate(
    template_id="CMP_BEST_CLEAR_V1",
    page_type="fund_comparison",
    insight_code="cmp_best_clear",
    trigger_code="cmp_best_check",
    headline_template="Overall research candidate: {winner_name}",
    body_template=(
        "{winner_name} leads this comparison in {category} with a composite score gap "
        "of {score_gap:.1f} points and wins on {metrics_won_count} of the evaluated metrics "
        "(IR, rank, improvement, expense efficiency). "
        "This makes it a structurally stronger research candidate relative to the compared peers — "
        "a structural signal for deeper due diligence, not a directional trading cue."
    ),
    required_variables=["winner_name", "category", "score_gap", "metrics_won_count"],
    severity="positive",
    priority=3,
)

CMP_BEST_NO_CLEAR_WINNER_V1 = InsightTemplate(
    template_id="CMP_BEST_NO_CLEAR_WINNER_V1",
    page_type="fund_comparison",
    insight_code="cmp_best_no_winner",
    trigger_code="cmp_best_check",
    headline_template="No clear winner in this comparison",
    body_template=(
        "The compared funds ({fund_names}) are structurally close across evaluated metrics. "
        "Reason: {reason}. "
        "No single fund dominates across IR, rank, improvement, and expense dimensions. "
        "This comparison does not surface a clear structural improvement signal at this time."
    ),
    required_variables=["fund_names", "reason"],
    severity="neutral",
    priority=4,
)


# ── Section 9.3: AI Workspace Lens V1 (LENS_*_V1) ────────────────────────────
# Axes are always real DB columns — never the original wireframe's "1Y IR" / "2Y IR Slope"
# labels which don't exist as built. x_label / y_label come from METRIC_VOCAB at runtime.

LENS_QUADRANT_EXPLAINER_V1 = InsightTemplate(
    template_id="LENS_QUADRANT_EXPLAINER_V1",
    page_type="workspace",
    insight_code="lens_quadrant_explainer",
    trigger_code="always",
    headline_template="Axis guide: {x_label} (x) vs {y_label} (y) — {category}",
    body_template=(
        "Each point is one fund in {category}. "
        "X-axis: {x_label} — {x_description}. "
        "Y-axis: {y_label} — {y_description}. "
        "Quadrant thresholds: x splits at the category median ({x_label} = {x_median:.3f}); "
        "y splits at {y_threshold} "
        "(positive = structurally improving, negative = declining). "
        "Improving-strong (top-right): x ≥ median AND y ≥ {y_threshold}. "
        "Improving-weak (top-left): x < median AND y ≥ {y_threshold}. "
        "Declining-strong (bottom-right): x ≥ median AND y < {y_threshold}. "
        "Declining-weak (bottom-left): x < median AND y < {y_threshold}."
    ),
    required_variables=[
        "x_label", "y_label", "category",
        "x_description", "y_description",
        "x_median", "y_threshold",
    ],
    severity="neutral",
    priority=1,
)

LENS_CANDIDATES_FOUND_V1 = InsightTemplate(
    template_id="LENS_CANDIDATES_FOUND_V1",
    page_type="workspace",
    insight_code="lens_candidates_found",
    trigger_code="count_gt_zero",
    headline_template="{count} research candidate(s) — {quadrant_label} quadrant",
    body_template=(
        "{count} fund(s) in {category} satisfy the structural filter: {filter_summary}. "
        "Top candidate(s) by {x_label}: {top_candidates}."
    ),
    required_variables=[
        "count", "category", "quadrant_label",
        "filter_summary", "x_label", "top_candidates",
    ],
    severity="positive",
    priority=5,
)

LENS_CANDIDATES_NONE_V1 = InsightTemplate(
    template_id="LENS_CANDIDATES_NONE_V1",
    page_type="workspace",
    insight_code="lens_candidates_none",
    trigger_code="count_zero",
    headline_template="No funds match the {quadrant_label} quadrant in {category}",
    body_template=(
        "The filter '{filter_summary}' returned zero funds in {category}. "
        "Consider loosening the category filter or switching to a different quadrant."
    ),
    required_variables=["quadrant_label", "filter_summary", "category"],
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
