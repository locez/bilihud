"""Deterministic normalized messages for manual developer regression checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .messages import (
    DanmakuMessage,
    GiftCurrency,
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


class MockScenarioId(StrEnum):
    """Identify one repeatable group of messages in the simulation panel."""

    BASIC = "basic"
    BADGES = "badges"
    PAID_GIFTS = "paid-gifts"
    INTERACTIONS = "interactions"
    SYSTEM = "system"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class MockMessageScenario:
    """Describe a named, deterministic group of normalized messages."""

    scenario_id: MockScenarioId
    title: str
    messages: tuple[HudMessage, ...]


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
                _gift("小电视", "送出", 1, 30000, "大额礼物用户", 302),
                _gift("舰长", "开通", 1, 198000, "舰长礼物用户", 303, guard_level=3),
            ),
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
    """Return the complete fixed batch injected by the tray action."""
    for scenario in mock_message_scenarios():
        if scenario.scenario_id is MockScenarioId.ALL:
            return scenario.messages
    raise RuntimeError("complete mock message scenario is missing")


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
    )
