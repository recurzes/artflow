"""
Buttons must outlive the process. Every long-lived view is registered at
startup and holds no state of its own.
"""
import discord

from bot.main import ArtflowBot

# Views that are meant to expire: shown only to the user who asked, for a few minutes.
SHORT_LIVED = {"bot.commissions.opening.ArtistPickView"}


def _name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _bot_classes(base: type) -> set[str]:
    """Names of the bot's subclasses of `base`. Names, not classes: every bot
    instance loads its extensions as fresh modules, so the classes differ."""
    found: set[str] = set()
    stack = list(base.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.__module__.startswith("bot."):
            found.add(_name(cls))
    return found


async def test_every_long_lived_view_is_registered_at_startup():
    bot = ArtflowBot()
    await bot.load_cogs()
    registered = {_name(type(view)) for view in bot.persistent_views}

    views = _bot_classes(discord.ui.View) - SHORT_LIVED
    assert views, "expected the cogs to define views"
    assert views <= registered, f"not registered: {views - registered}"


async def test_registered_views_are_stateless_and_fully_persistent():
    bot = ArtflowBot()
    await bot.load_cogs()

    for view in bot.persistent_views:
        assert view.timeout is None
        assert view.is_persistent()  # every component has a custom_id
        # A no-argument constructor means nothing has to be remembered across restarts.
        type(view)()


async def test_every_dynamic_button_is_registered_at_startup():
    bot = ArtflowBot()
    await bot.load_cogs()
    registered = {_name(cls) for cls in bot._connection._view_store._dynamic_items.values()}

    dynamic = _bot_classes(discord.ui.DynamicItem)
    assert dynamic, "expected the cogs to define dynamic items"
    assert dynamic <= registered, f"not registered: {dynamic - registered}"


async def test_custom_ids_are_unique_across_views():
    bot = ArtflowBot()
    await bot.load_cogs()

    seen: dict[str, str] = {}
    for view in bot.persistent_views:
        for item in view.children:
            owner = type(view).__name__
            assert item.custom_id not in seen, (
                f"{item.custom_id} is used by both {seen[item.custom_id]} and {owner}"
            )
            seen[item.custom_id] = owner
