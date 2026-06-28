"""Streak-related template variables.

Variables for winning/losing streaks.

Variable naming:
- `streak` - formatted (W3/L2)
- `streak_length` - absolute value (3)
- `streak_type` - direction (win/loss)
- `win_streak` / `loss_streak` - length only if that type
- Prefixed versions: `opponent_*`, `home_team_*`, `away_team_*`
"""

from teamarr.core import TeamStats
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    TemplateScope,
    register_variable,
)


def _get_streak_info(stats: TeamStats | None) -> tuple[str, int, str]:
    """Extract streak info from stats.

    Returns:
        Tuple of (formatted, length, type):
        - formatted: "W3" or "L2"
        - length: 3 (absolute value)
        - type: "win" or "loss"
    """
    if not stats or not stats.streak:
        return "", 0, ""

    formatted = stats.streak  # "W3" or "L2"
    count = stats.streak_count  # signed: 3 or -2

    length = abs(count)
    streak_type = "win" if count > 0 else "loss" if count < 0 else ""

    return formatted, length, streak_type


# =============================================================================
# OUR TEAM'S STREAK
# =============================================================================


@register_variable(
    name="streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's current streak formatted (e.g., 'W3' or 'L2')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    formatted, _, _ = _get_streak_info(ctx.team_stats)
    return formatted


@register_variable(
    name="streak_length",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's streak as absolute value (e.g., '3' for either W3 or L3)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_streak_length(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    _, length, _ = _get_streak_info(ctx.team_stats)
    return str(length) if length > 0 else ""


@register_variable(
    name="streak_type",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's streak direction: 'win' or 'loss'",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_streak_type(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    _, _, streak_type = _get_streak_info(ctx.team_stats)
    return streak_type


@register_variable(
    name="win_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's winning streak length (empty if on losing streak)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_win_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    _, length, streak_type = _get_streak_info(ctx.team_stats)
    return str(length) if streak_type == "win" else ""


@register_variable(
    name="loss_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.BASE_ONLY,
    description="Team's losing streak length (empty if on winning streak)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_loss_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    _, length, streak_type = _get_streak_info(ctx.team_stats)
    return str(length) if streak_type == "loss" else ""


# =============================================================================
# OPPONENT'S STREAK
# =============================================================================


@register_variable(
    name="opponent_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's current streak formatted (e.g., 'W3' or 'L2')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx:
        return ""
    formatted, _, _ = _get_streak_info(game_ctx.opponent_stats)
    return formatted


@register_variable(
    name="opponent_streak_length",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's streak as absolute value (e.g., '3')",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_streak_length(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx:
        return ""
    _, length, _ = _get_streak_info(game_ctx.opponent_stats)
    return str(length) if length > 0 else ""


@register_variable(
    name="opponent_streak_type",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's streak direction: 'win' or 'loss'",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_streak_type(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx:
        return ""
    _, _, streak_type = _get_streak_info(game_ctx.opponent_stats)
    return streak_type


@register_variable(
    name="opponent_win_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's winning streak length (empty if on losing streak)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_win_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx:
        return ""
    _, length, streak_type = _get_streak_info(game_ctx.opponent_stats)
    return str(length) if streak_type == "win" else ""


@register_variable(
    name="opponent_loss_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Opponent's losing streak length (empty if on winning streak)",
    scope=TemplateScope.TEAM_ONLY,
)
def extract_opponent_loss_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    if not game_ctx:
        return ""
    _, length, streak_type = _get_streak_info(game_ctx.opponent_stats)
    return str(length) if streak_type == "loss" else ""


# =============================================================================
# HOME/AWAY TEAM STREAKS (for event-based templates)
# =============================================================================


def _get_home_team_stats(ctx: TemplateContext, game_ctx: GameContext | None) -> TeamStats | None:
    """Get stats for the home team in this game."""
    if not game_ctx or not game_ctx.event:
        return None
    is_home = game_ctx.event.home_team.id == ctx.team_config.team_id
    return ctx.team_stats if is_home else game_ctx.opponent_stats


def _get_away_team_stats(ctx: TemplateContext, game_ctx: GameContext | None) -> TeamStats | None:
    """Get stats for the away team in this game."""
    if not game_ctx or not game_ctx.event:
        return None
    is_home = game_ctx.event.home_team.id == ctx.team_config.team_id
    return game_ctx.opponent_stats if is_home else ctx.team_stats


@register_variable(
    name="home_team_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Home team's current streak formatted (e.g., 'W3' or 'L2')",
)
def extract_home_team_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_home_team_stats(ctx, game_ctx)
    formatted, _, _ = _get_streak_info(stats)
    return formatted


@register_variable(
    name="home_team_streak_length",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Home team's streak as absolute value",
)
def extract_home_team_streak_length(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_home_team_stats(ctx, game_ctx)
    _, length, _ = _get_streak_info(stats)
    return str(length) if length > 0 else ""


@register_variable(
    name="home_team_win_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Home team's winning streak (empty if losing)",
)
def extract_home_team_win_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_home_team_stats(ctx, game_ctx)
    _, length, streak_type = _get_streak_info(stats)
    return str(length) if streak_type == "win" else ""


@register_variable(
    name="home_team_loss_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Home team's losing streak (empty if winning)",
)
def extract_home_team_loss_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_home_team_stats(ctx, game_ctx)
    _, length, streak_type = _get_streak_info(stats)
    return str(length) if streak_type == "loss" else ""


@register_variable(
    name="away_team_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Away team's current streak formatted (e.g., 'W3' or 'L2')",
)
def extract_away_team_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_away_team_stats(ctx, game_ctx)
    formatted, _, _ = _get_streak_info(stats)
    return formatted


@register_variable(
    name="away_team_streak_length",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Away team's streak as absolute value",
)
def extract_away_team_streak_length(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_away_team_stats(ctx, game_ctx)
    _, length, _ = _get_streak_info(stats)
    return str(length) if length > 0 else ""


@register_variable(
    name="away_team_win_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Away team's winning streak (empty if losing)",
)
def extract_away_team_win_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_away_team_stats(ctx, game_ctx)
    _, length, streak_type = _get_streak_info(stats)
    return str(length) if streak_type == "win" else ""


@register_variable(
    name="away_team_loss_streak",
    category=Category.STREAKS,
    suffix_rules=SuffixRules.ALL,
    description="Away team's losing streak (empty if winning)",
)
def extract_away_team_loss_streak(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    stats = _get_away_team_stats(ctx, game_ctx)
    _, length, streak_type = _get_streak_info(stats)
    return str(length) if streak_type == "loss" else ""
