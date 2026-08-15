"""Deterministic normalized messages for manual developer regression checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftEffectFrame,
    GiftEffectLayout,
    GiftMessage,
    HudMessage,
    InteractionKind,
    InteractMessage,
    MessageAuthor,
    MessageBadge,
    MessageBadgeKind,
    ReplySegment,
    SystemMessageLevel,
    TextSegment,
    make_system_message,
)

# Hashed Bilibili CDN paths make the developer fixture independent of a live room.
MOCK_LITTLE_TV_GIFT_ID = 31115
MOCK_LITTLE_TV_IMAGE_URL = "https://s1.hdslb.com/bfs/live/037ff1f5dbf1cb996a39cedc8b67fcdb04b00cdc.png"
MOCK_LITTLE_TV_EFFECT_URL = "https://i0.hdslb.com/bfs/live/2324bda944b2aaaafbc54f30d506b39aa63b53af.mp4"
MOCK_LITTLE_TV_ANIMATION_URL = "https://i0.hdslb.com/bfs/live/2b6e17d10c09072c2007ed462e4d3257e99481cc.gif"
MOCK_LITTLE_TV_EFFECT_LAYOUT = GiftEffectLayout(
    rgb_frame=GiftEffectFrame(0, 0, 750, 1334),
    alpha_frame=GiftEffectFrame(754, 0, 375, 667),
)
MOCK_CASTLE_GIFT_ID = 32132
MOCK_CASTLE_IMAGE_URL = "https://s1.hdslb.com/bfs/live/4ee13c275e13b0a7404bd8af035775db3c721b86.png"
MOCK_CASTLE_EFFECT_URL = "https://i0.hdslb.com/bfs/live/9b5cb18ed9a7134a70b7c2e36113b4c88d5c2437.mp4"
MOCK_CASTLE_ANIMATION_URL = "https://i0.hdslb.com/bfs/live/95cc0087733d3195993db5298718ea5b12a1171d.gif"
MOCK_CASTLE_EFFECT_LAYOUT = GiftEffectLayout(
    rgb_frame=GiftEffectFrame(0, 0, 720, 1280),
    alpha_frame=GiftEffectFrame(724, 0, 360, 640),
)

# Current public Bilibili room-side full-screen resources for the three guard levels.
MOCK_GOVERNOR_GIFT_ID = 10001
MOCK_GOVERNOR_EFFECT_URL = "https://i0.hdslb.com/bfs/live/9d43ca0163de5ce6317a9f475e4217c628d9d081.mp4"
MOCK_ADMIRAL_GIFT_ID = 10002
MOCK_ADMIRAL_EFFECT_URL = "https://i0.hdslb.com/bfs/live/919538c1e28d81270301794b5a8e382d52dafaf5.mp4"
MOCK_CAPTAIN_GIFT_ID = 10003
MOCK_CAPTAIN_EFFECT_URL = "https://i0.hdslb.com/bfs/live/b795b2270087db24ecf41f9a7bdf283b12717e6c.mp4"
MOCK_GUARD_EFFECT_LAYOUT = GiftEffectLayout(
    rgb_frame=GiftEffectFrame(0, 0, 300, 579),
    alpha_frame=GiftEffectFrame(304, 0, 150, 289),
)


class MockScenarioId(StrEnum):
    """Identify one repeatable group of messages in the simulation panel."""

    BASIC = "basic"
    BADGES = "badges"
    PAID_GIFTS = "paid-gifts"
    ADVANCED_GIFT_EFFECTS = "advanced-gift-effects"
    INTERACTIONS = "interactions"
    SYSTEM = "system"
    ALL = "all"


class MockGiftEffectId(StrEnum):
    """Identify one individually triggerable advanced gift-effect fixture."""

    GOVERNOR = "governor"
    ADMIRAL = "admiral"
    CAPTAIN = "captain"
    CASTLE = "castle"


@dataclass(frozen=True, slots=True)
class MockMessageScenario:
    """Describe a named, deterministic group of normalized messages."""

    scenario_id: MockScenarioId
    title: str
    messages: tuple[HudMessage, ...]


@dataclass(frozen=True, slots=True)
class MockGiftEffectOption:
    """Describe one advanced gift effect available to the developer picker."""

    effect_id: MockGiftEffectId
    title: str
    message: GiftMessage


def mock_message_scenarios() -> tuple[MockMessageScenario, ...]:
    """Return the fixed message groups exposed by the developer simulator."""
    scenarios = (
        MockMessageScenario(
            MockScenarioId.BASIC,
            "普通弹幕",
            (
                DanmakuMessage(
                    author=_author(101, "测试观众"),
                    segments=(TextSegment("这是一条普通测试弹幕"),),
                ),
                DanmakuMessage(
                    author=_author(102, "回复观众"),
                    segments=(ReplySegment("@主播 "), TextSegment("回复消息效果测试")),
                ),
            ),
        ),
        MockMessageScenario(
            MockScenarioId.BADGES,
            "勋章与大航海",
            (
                _guard_danmaku("总督用户", 201, 1, "测试总督消息"),
                _guard_danmaku("提督用户", 202, 2, "测试提督消息"),
                _guard_danmaku("舰长用户", 203, 3, "测试舰长消息"),
            ),
        ),
        MockMessageScenario(
            MockScenarioId.PAID_GIFTS,
            "付费礼物",
            (
                _gift("辣条", "赠送", 3, 1000, "小额礼物用户", 301),
                _gift(
                    "鸿运小电视",
                    "送出",
                    1,
                    1000000,
                    "大额礼物用户",
                    302,
                    gift_id=MOCK_LITTLE_TV_GIFT_ID,
                    gift_image_url=MOCK_LITTLE_TV_IMAGE_URL,
                    gift_effect_url=MOCK_LITTLE_TV_EFFECT_URL,
                    gift_animation_url=MOCK_LITTLE_TV_ANIMATION_URL,
                    gift_effect_layout=MOCK_LITTLE_TV_EFFECT_LAYOUT,
                ),
            ),
        ),
        MockMessageScenario(
            MockScenarioId.ADVANCED_GIFT_EFFECTS,
            "高级礼物特效",
            tuple(option.message for option in mock_gift_effect_options()),
        ),
        MockMessageScenario(
            MockScenarioId.INTERACTIONS,
            "互动消息",
            tuple(
                InteractMessage(
                    author=_author(400 + index, f"互动用户{index}"),
                    segments=(TextSegment(interaction.text),),
                    interaction=interaction,
                )
                for index, interaction in enumerate(InteractionKind, start=1)
            ),
        ),
        MockMessageScenario(
            MockScenarioId.SYSTEM,
            "系统消息",
            (
                make_system_message("这是一条系统提示测试消息"),
                make_system_message("这是一条系统错误测试消息", level=SystemMessageLevel.ERROR),
            ),
        ),
    )
    all_messages = tuple(message for scenario in scenarios for message in scenario.messages)
    return (
        *scenarios,
        MockMessageScenario(MockScenarioId.ALL, "完整样例", all_messages),
    )


def mock_message_batch() -> tuple[HudMessage, ...]:
    """Return the standard batch used by the normal developer simulation."""
    return tuple(
        message
        for scenario in mock_message_scenarios()
        if scenario.scenario_id not in {
            MockScenarioId.ADVANCED_GIFT_EFFECTS,
            MockScenarioId.ALL,
        }
        for message in scenario.messages
    )


def mock_gift_effect_options() -> tuple[MockGiftEffectOption, ...]:
    """Return individually triggerable fixtures for advanced gift-effect checks."""
    return (
        MockGiftEffectOption(
            MockGiftEffectId.GOVERNOR,
            "总督开通",
            _gift(
                "总督",
                "开通",
                1,
                19998000,
                "总督礼物用户",
                303,
                guard_level=1,
                gift_id=MOCK_GOVERNOR_GIFT_ID,
                gift_effect_url=MOCK_GOVERNOR_EFFECT_URL,
                gift_effect_layout=MOCK_GUARD_EFFECT_LAYOUT,
            ),
        ),
        MockGiftEffectOption(
            MockGiftEffectId.ADMIRAL,
            "提督开通",
            _gift(
                "提督",
                "开通",
                1,
                1998000,
                "提督礼物用户",
                304,
                guard_level=2,
                gift_id=MOCK_ADMIRAL_GIFT_ID,
                gift_effect_url=MOCK_ADMIRAL_EFFECT_URL,
                gift_effect_layout=MOCK_GUARD_EFFECT_LAYOUT,
            ),
        ),
        MockGiftEffectOption(
            MockGiftEffectId.CAPTAIN,
            "舰长开通",
            _gift(
                "舰长",
                "开通",
                1,
                198000,
                "舰长礼物用户",
                305,
                guard_level=3,
                gift_id=MOCK_CAPTAIN_GIFT_ID,
                gift_effect_url=MOCK_CAPTAIN_EFFECT_URL,
                gift_effect_layout=MOCK_GUARD_EFFECT_LAYOUT,
            ),
        ),
        MockGiftEffectOption(
            MockGiftEffectId.CASTLE,
            "浪漫城堡",
            _gift(
                "浪漫城堡",
                "送出",
                1,
                2233000,
                "城堡测试用户",
                306,
                gift_id=MOCK_CASTLE_GIFT_ID,
                gift_image_url=MOCK_CASTLE_IMAGE_URL,
                gift_effect_url=MOCK_CASTLE_EFFECT_URL,
                gift_animation_url=MOCK_CASTLE_ANIMATION_URL,
                gift_effect_layout=MOCK_CASTLE_EFFECT_LAYOUT,
            ),
        ),
    )


def mock_gift_effect_message(effect_id: str) -> GiftMessage | None:
    """Resolve one picker value to its normalized gift event, if it is supported."""
    try:
        selected_id = MockGiftEffectId(effect_id)
    except ValueError:
        return None
    for option in mock_gift_effect_options():
        if option.effect_id is selected_id:
            return option.message
    return None


def _author(
    uid: int,
    name: str,
    *,
    color: str = "#66CCFF",
    badges: tuple[MessageBadge, ...] = (),
) -> MessageAuthor:
    """Build a stable author used by one simulation scenario."""
    return MessageAuthor(uid=uid, name=name, color=color, badges=badges)


def _guard_danmaku(name: str, uid: int, level: int, text: str) -> DanmakuMessage:
    """Build one danmaku carrying a representative guard-level badge."""
    return DanmakuMessage(
        author=_author(uid, name, color="#FFD700", badges=(_guard_badge(level),)),
        segments=(TextSegment(text),),
    )


def _guard_badge(level: int) -> MessageBadge:
    """Return the stable badge representation for one guard level."""
    if level == 1:
        return MessageBadge(MessageBadgeKind.PRIVILEGE, "🛳︎", "大航海", "#FFD700")
    if level == 2:
        return MessageBadge(MessageBadgeKind.PRIVILEGE, "⛴︎", "大航海", "#C9B6FF")
    if level == 3:
        return MessageBadge(MessageBadgeKind.PRIVILEGE, "⚓︎", "大航海", "#86C8FF")
    raise ValueError(f"unsupported mock guard level: {level}")


def _gift(
    gift_name: str,
    action: str,
    quantity: int,
    unit_price: int,
    user: str,
    uid: int,
    *,
    guard_level: int | None = None,
    gift_id: int = 0,
    gift_image_url: str = "",
    gift_effect_url: str = "",
    gift_animation_url: str = "",
    gift_effect_layout: GiftEffectLayout | None = None,
) -> GiftMessage:
    """Build a paid gold-coin gift with an optional guard badge."""
    badges: tuple[MessageBadge, ...] = ()
    if guard_level is not None:
        badges = (_guard_badge(guard_level),)
    author = _author(uid, user, color="#FFD700", badges=badges)
    return GiftMessage(
        author=author,
        segments=(TextSegment(f"{action} {gift_name} x{quantity}"),),
        action=action,
        gift_name=gift_name,
        quantity=quantity,
        unit_price=unit_price,
        currency=GiftCurrency.GOLD,
        gift_id=gift_id,
        gift_image_url=gift_image_url,
        gift_effect_url=gift_effect_url,
        gift_animation_url=gift_animation_url,
        gift_effect_layout=gift_effect_layout,
    )
