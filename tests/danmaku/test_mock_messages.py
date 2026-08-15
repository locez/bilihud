from bilihud.danmaku.messages import (
    DanmakuMessage,
    GiftCurrency,
    GiftMessage,
    MessageBadgeKind,
    SystemMessage,
    SystemMessageLevel,
)
from bilihud.danmaku.mock import (
    MOCK_ADMIRAL_EFFECT_URL,
    MOCK_ADMIRAL_GIFT_ID,
    MOCK_CAPTAIN_EFFECT_URL,
    MOCK_CAPTAIN_GIFT_ID,
    MOCK_CASTLE_EFFECT_LAYOUT,
    MOCK_CASTLE_EFFECT_URL,
    MOCK_CASTLE_GIFT_ID,
    MOCK_GOVERNOR_EFFECT_URL,
    MOCK_GOVERNOR_GIFT_ID,
    MOCK_GUARD_EFFECT_LAYOUT,
    MOCK_LITTLE_TV_EFFECT_LAYOUT,
    MOCK_LITTLE_TV_EFFECT_URL,
    MOCK_LITTLE_TV_GIFT_ID,
    MockGiftEffectId,
    MockScenarioId,
    mock_gift_effect_message,
    mock_gift_effect_options,
    mock_message_batch,
    mock_message_scenarios,
)


def test_mock_message_batch_is_deterministic_and_covers_domain_variants():
    first = mock_message_batch()
    second = mock_message_batch()

    assert first == second
    assert any(isinstance(message, DanmakuMessage) for message in first)
    assert any(isinstance(message, GiftMessage) for message in first)
    assert any(isinstance(message, SystemMessage) for message in first)


def test_mock_message_batch_keeps_advanced_effects_out_of_standard_simulation():
    messages = mock_message_batch()
    gifts = [message for message in messages if isinstance(message, GiftMessage)]
    guard_messages = [message for message in messages if isinstance(message, DanmakuMessage)]

    assert [(gift.gift_name, gift.unit_price, gift.currency, gift.total_price) for gift in gifts] == [
        ("辣条", 1000, GiftCurrency.GOLD, 3000),
        ("鸿运小电视", 1000000, GiftCurrency.GOLD, 1000000),
    ]
    little_tv = next(gift for gift in gifts if gift.gift_id == MOCK_LITTLE_TV_GIFT_ID)
    assert little_tv.gift_effect_url == MOCK_LITTLE_TV_EFFECT_URL
    assert little_tv.gift_effect_layout == MOCK_LITTLE_TV_EFFECT_LAYOUT
    assert [
        message.author.badges[0].text
        for message in guard_messages
        if message.author.badges and message.author.badges[0].kind is MessageBadgeKind.PRIVILEGE
    ] == ["🛳︎", "⛴︎", "⚓︎"]


def test_advanced_gift_effects_are_selectable_one_at_a_time():
    options = mock_gift_effect_options()

    assert [option.effect_id for option in options] == [
        MockGiftEffectId.GOVERNOR,
        MockGiftEffectId.ADMIRAL,
        MockGiftEffectId.CAPTAIN,
        MockGiftEffectId.CASTLE,
    ]
    assert [option.title for option in options] == ["总督开通", "提督开通", "舰长开通", "浪漫城堡"]
    assert [mock_gift_effect_message(option.effect_id.value) for option in options] == [
        option.message for option in options
    ]

    guard_effects = {
        option.message.gift_id: option.message.gift_effect_url
        for option in options
        if option.effect_id is not MockGiftEffectId.CASTLE
    }
    assert guard_effects == {
        MOCK_GOVERNOR_GIFT_ID: MOCK_GOVERNOR_EFFECT_URL,
        MOCK_ADMIRAL_GIFT_ID: MOCK_ADMIRAL_EFFECT_URL,
        MOCK_CAPTAIN_GIFT_ID: MOCK_CAPTAIN_EFFECT_URL,
    }
    assert all(
        option.message.gift_effect_layout == MOCK_GUARD_EFFECT_LAYOUT
        for option in options
        if option.effect_id is not MockGiftEffectId.CASTLE
    )
    castle = mock_gift_effect_message(MockGiftEffectId.CASTLE.value)
    assert castle is not None
    assert castle.gift_id == MOCK_CASTLE_GIFT_ID
    assert castle.gift_effect_url == MOCK_CASTLE_EFFECT_URL
    assert castle.gift_animation_url.endswith(".gif")
    assert castle.gift_effect_layout == MOCK_CASTLE_EFFECT_LAYOUT
    assert mock_gift_effect_message("unknown") is None


def test_mock_message_scenarios_include_system_info_and_error_messages():
    scenarios = mock_message_scenarios()

    assert [scenario.scenario_id for scenario in scenarios] == [
        MockScenarioId.BASIC,
        MockScenarioId.BADGES,
        MockScenarioId.PAID_GIFTS,
        MockScenarioId.ADVANCED_GIFT_EFFECTS,
        MockScenarioId.INTERACTIONS,
        MockScenarioId.SYSTEM,
        MockScenarioId.ALL,
    ]
    advanced = next(
        scenario for scenario in scenarios if scenario.scenario_id is MockScenarioId.ADVANCED_GIFT_EFFECTS
    )
    assert len(advanced.messages) == len(mock_gift_effect_options())
    system_messages = [
        message
        for message in next(
            scenario for scenario in scenarios if scenario.scenario_id is MockScenarioId.SYSTEM
        ).messages
        if isinstance(message, SystemMessage)
    ]
    assert [message.level for message in system_messages] == [
        SystemMessageLevel.INFO,
        SystemMessageLevel.ERROR,
    ]
