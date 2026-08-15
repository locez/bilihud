import asyncio

from bilihud.live.gift_effects import (
    FULL_SCREEN_EFFECT_CONFIG_URL,
    GIFT_DETAIL_URL,
    GiftEffectCatalog,
)


class FakeResponse:
    def __init__(self, payload: object, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False

    async def json(self, content_type=None) -> object:
        return self.payload


class FakeSession:
    def __init__(
        self,
        payload: object,
        metadata_payload: object | None = None,
        special_payload: object | None = None,
    ) -> None:
        self.payload = payload
        self.metadata_payload = metadata_payload
        self.special_payload = special_payload
        self.calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def get(
        self,
        url: str,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append((url, params, headers))
        if url == FULL_SCREEN_EFFECT_CONFIG_URL and self.special_payload is not None:
            payload = self.special_payload
        else:
            payload = self.metadata_payload if url.endswith(".json") else self.payload
        return FakeResponse(self.payload if payload is None else payload)


def test_gift_effect_catalog_resolves_and_caches_official_resources() -> None:
    async def run_test() -> None:
        session = FakeSession(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "config": {
                                "gif": "https://i0.hdslb.com/bfs/live/castle.gif",
                                "full_sc_web": "",
                            },
                            "full_sc_effect": [
                                {
                                    "web_mp4": "https://i0.hdslb.com/bfs/live/castle.mp4",
                                    "web_mp4_json": "https://i0.hdslb.com/bfs/live/castle.json",
                                }
                            ],
                        }
                    ]
                },
            },
            {
                "info": {
                    "rgbFrame": [0, 0, 720, 1280],
                    "aFrame": [724, 0, 360, 640],
                }
            },
        )
        catalog = GiftEffectCatalog(session, 7450109)

        first = await catalog.resolve(32132)
        second = await catalog.resolve(32132)

        assert first is not None
        assert first.gift_id == 32132
        assert first.full_screen_url.endswith("castle.mp4")
        assert first.animation_url.endswith("castle.gif")
        assert first.layout is not None
        assert first.layout.rgb_frame.width == 720
        assert first.layout.alpha_frame.x == 724
        assert second is first
        assert len(session.calls) == 2
        assert session.calls[0][0] == GIFT_DETAIL_URL
        assert session.calls[0][1]["gift_ids"] == "32132"
        assert session.calls[0][2] == {"Referer": "https://live.bilibili.com/7450109"}
        assert session.calls[1][0].endswith("castle.json")

    asyncio.run(run_test())


def test_gift_effect_catalog_discards_untrusted_resource_hosts() -> None:
    async def run_test() -> None:
        session = FakeSession(
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "config": {"gif": "https://example.com/gift.gif"},
                            "full_sc_effect": [{"web_mp4": "https://example.com/gift.mp4"}],
                        }
                    ]
                },
            }
        )

        asset = await GiftEffectCatalog(session, 1).resolve(2)

        assert asset is None

    asyncio.run(run_test())


def test_gift_effect_catalog_resolves_and_caches_guard_special_effects() -> None:
    async def run_test() -> None:
        session = FakeSession(
            {},
            metadata_payload={
                "info": {
                    "rgbFrame": [0, 0, 720, 1280],
                    "aFrame": [724, 0, 360, 640],
                }
            },
            special_payload={
                "code": 0,
                "data": {
                    "conf_list": [
                        {
                            "id": 397,
                            "type": 3,
                            "web_mp4": "https://i0.hdslb.com/bfs/live/captain.mp4",
                            "web_mp4_json": "https://i0.hdslb.com/bfs/live/captain.json",
                        },
                        {
                            "id": 398,
                            "type": 3,
                            "web_mp4": "https://i0.hdslb.com/bfs/live/admiral.mp4",
                            "web_mp4_json": "https://i0.hdslb.com/bfs/live/admiral.json",
                        },
                        {
                            "id": 399,
                            "type": 3,
                            "web_mp4": "https://i0.hdslb.com/bfs/live/governor.mp4",
                            "web_mp4_json": "https://i0.hdslb.com/bfs/live/governor.json",
                        },
                    ]
                },
            },
        )
        catalog = GiftEffectCatalog(session, 7450109)

        first = await catalog.resolve_special_effect(397)
        second = await catalog.resolve_special_effect(397)
        other_effects = [
            await catalog.resolve_special_effect(effect_id)
            for effect_id in (398, 399)
        ]

        assert first is not None
        assert first.full_screen_url.endswith("captain.mp4")
        assert first.layout is not None
        assert first.layout.rgb_frame.height == 1280
        assert second is first
        assert [asset.full_screen_url for asset in other_effects if asset is not None] == [
            "https://i0.hdslb.com/bfs/live/admiral.mp4",
            "https://i0.hdslb.com/bfs/live/governor.mp4",
        ]
        assert [call[0] for call in session.calls] == [
            FULL_SCREEN_EFFECT_CONFIG_URL,
            "https://i0.hdslb.com/bfs/live/captain.json",
            "https://i0.hdslb.com/bfs/live/admiral.json",
            "https://i0.hdslb.com/bfs/live/governor.json",
        ]
        assert session.calls[0][1] == {
            "platform": "pc",
            "room_id": 7450109,
            "area_parent_id": 0,
            "area_id": 0,
            "source": "live",
            "build": 0,
            "base_version": "",
        }
        assert session.calls[0][2] == {"Referer": "https://live.bilibili.com/7450109"}

    asyncio.run(run_test())
