from bilihud.domain.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftMessage,
    MessageBadgeKind,
    SystemMessage,
    SystemMessageLevel,
)
from bilihud.mock_messages import MockScenarioId, mock_message_batch, mock_message_scenarios


def test_mock_message_batch_is_deterministic_and_covers_domain_variants():
    first = mock_message_batch()
    second = mock_message_batch()

    assert first == second
    assert any(isinstance(message, DanmakuMessage) for message in first)
    assert any(isinstance(message, GiftMessage) for message in first)
    assert any(isinstance(message, SystemMessage) for message in first)


def test_mock_message_batch_covers_paid_gifts_and_guard_levels():
    messages = mock_message_batch()
    gifts = [message for message in messages if isinstance(message, GiftMessage)]
    guard_messages = [message for message in messages if isinstance(message, DanmakuMessage)]

    assert [(gift.gift_name, gift.unit_price, gift.currency, gift.total_price) for gift in gifts] == [
        ("辣条", 1000, GiftCurrency.GOLD, 3000),
        ("小电视", 30000, GiftCurrency.GOLD, 30000),
        ("舰长", 198000, GiftCurrency.GOLD, 198000),
    ]
    assert [
        message.author.badges[0].text
        for message in guard_messages
        if message.author.badges and message.author.badges[0].kind is MessageBadgeKind.PRIVILEGE
    ] == ["🛳︎", "⛴︎", "⚓︎"]


def test_mock_message_scenarios_include_system_info_and_error_messages():
    scenarios = mock_message_scenarios()

    assert [scenario.scenario_id for scenario in scenarios] == [
        MockScenarioId.BASIC,
        MockScenarioId.BADGES,
        MockScenarioId.PAID_GIFTS,
        MockScenarioId.INTERACTIONS,
        MockScenarioId.SYSTEM,
        MockScenarioId.ALL,
    ]
    system_messages = [
        message
        for message in scenarios[4].messages
        if isinstance(message, SystemMessage)
    ]
    assert [message.level for message in system_messages] == [
        SystemMessageLevel.INFO,
        SystemMessageLevel.ERROR,
    ]
