"""Playoff and season type template variables.

Variables for identifying game type (playoff, preseason, regular season).
All comparisons use canonical season_type constants from core; providers are
responsible for mapping their native values to these constants before the
Event reaches the template layer.
"""

from teamarr.core import SEASON_POSTSEASON, SEASON_PRESEASON, SEASON_REGULAR
from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.variables.registry import (
    Category,
    SuffixRules,
    register_variable,
)


def _get_season_type(game_ctx: GameContext | None) -> str:
    """Get canonical season_type from event (one of SEASON_* or '')."""
    if not game_ctx or not game_ctx.event:
        return ""
    return game_ctx.event.season_type or ""


@register_variable(
    name="season_type",
    category=Category.PLAYOFFS,
    suffix_rules=SuffixRules.ALL,
    description="Season type ('regular', 'postseason', 'preseason', 'offseason')",
)
def extract_season_type(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return _get_season_type(game_ctx)


@register_variable(
    name="is_playoff",
    category=Category.PLAYOFFS,
    suffix_rules=SuffixRules.ALL,
    description="'true' if playoff/postseason game",
)
def extract_is_playoff(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return "true" if _get_season_type(game_ctx) == SEASON_POSTSEASON else ""


@register_variable(
    name="is_preseason",
    category=Category.PLAYOFFS,
    suffix_rules=SuffixRules.ALL,
    description="'true' if preseason/exhibition game",
)
def extract_is_preseason(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return "true" if _get_season_type(game_ctx) == SEASON_PRESEASON else ""


@register_variable(
    name="is_regular_season",
    category=Category.PLAYOFFS,
    suffix_rules=SuffixRules.ALL,
    description="'true' if regular season game",
)
def extract_is_regular_season(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return "true" if _get_season_type(game_ctx) == SEASON_REGULAR else ""
