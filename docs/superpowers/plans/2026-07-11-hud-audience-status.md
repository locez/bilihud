# HUD Audience Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact authenticated audience status strip below the BiliHUD header, with a clickable anchored popup that maps each visible ranked user to that user's contribution value.

**Architecture:** Add a pure `live_audience` parser module, reuse `DanmakuClient`'s existing Bilibili session for the two current web API requests, and keep Qt rendering in a focused `audience_widgets` module. `DanmakuWidget` owns only refresh-task lifecycle, room-generation protection, cached snapshot state, and visibility coordination.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, PyQt6, qasync, pytest, ruff, ty.

---

## File Structure

- Create `src/bilihud/live_audience.py`: immutable audience data models and pure Bilibili response parsers.
- Create `tests/test_live_audience.py`: parser, normalization, and hidden-user-count tests.
- Modify `src/bilihud/danmaku_client.py`: current room-info and contribution-rank HTTP requests.
- Modify `tests/test_danmaku_client.py`: request-contract and snapshot assembly tests.
- Create `src/bilihud/audience_widgets.py`: compact status strip and anchored popup.
- Create `tests/test_audience_widgets.py`: Qt rendering, click, empty state, footer, and dismissal tests.
- Modify `src/bilihud/danmaku_widget.py`: layout placement, 30-second task lifecycle, room-generation checks, disconnect cleanup, and gaming-mode visibility.
- Modify `tests/test_danmaku_widget.py`: lifecycle and integration tests.

### Task 1: Add Audience Models And Pure Parsers

**Files:**
- Create: `src/bilihud/live_audience.py`
- Create: `tests/test_live_audience.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/test_live_audience.py` with anonymous fixture data only:

```python
import pytest

from bilihud.live_audience import (
    AudienceSnapshot,
    AudienceUser,
    parse_anchor_uid,
    parse_audience_snapshot,
)


def room_payload(*, popularity=21, watched=9, uid=9001):
    return {
        "code": 0,
        "message": "OK",
        "data": {
            "room_info": {"uid": uid, "online": 18},
            "popularity": {"popularity": popularity},
            "watched_show": {"num": watched},
        },
    }


def rank_payload(*, count=3, items=None):
    return {
        "code": 0,
        "message": "OK",
        "data": {
            "count": count,
            "item": items
            if items is not None
            else [
                {
                    "uid": 1001,
                    "name": "用户A",
                    "score": 1,
                    "rank": 1,
                    "is_mystery": False,
                }
            ],
        },
    }


def test_parse_anchor_uid_reads_room_owner():
    assert parse_anchor_uid(room_payload(uid=9001)) == 9001


def test_parse_audience_snapshot_maps_metrics_users_and_contribution():
    snapshot = parse_audience_snapshot(7450109, room_payload(), rank_payload())

    assert snapshot == AudienceSnapshot(
        room_id=7450109,
        popularity=21,
        watched_count=9,
        online_rank_count=3,
        users=(
            AudienceUser(
                uid=1001,
                name="用户A",
                contribution=1,
                rank=1,
                is_mystery=False,
            ),
        ),
    )
    assert snapshot.hidden_user_count == 2


def test_parse_audience_snapshot_falls_back_to_room_online():
    payload = room_payload()
    payload["data"]["popularity"] = None

    snapshot = parse_audience_snapshot(7450109, payload, rank_payload(count=0, items=[]))

    assert snapshot.popularity == 18


def test_parse_audience_snapshot_skips_invalid_users_and_normalizes_numbers():
    snapshot = parse_audience_snapshot(
        7450109,
        room_payload(popularity="bad", watched=-9),
        rank_payload(
            count="bad",
            items=[
                {"uid": 0, "name": "无效用户", "score": 9, "rank": 1},
                {"uid": 1002, "name": "", "score": 8, "rank": 2},
                {"uid": 1003, "name": "用户B", "score": "4", "rank": "3"},
            ],
        ),
    )

    assert snapshot.popularity == 0
    assert snapshot.watched_count == 0
    assert snapshot.online_rank_count == 1
    assert snapshot.users == (AudienceUser(1003, "用户B", 4, 3, False),)
    assert snapshot.hidden_user_count == 0


def test_parse_audience_snapshot_rejects_api_errors():
    with pytest.raises(ValueError, match="账号未登录"):
        parse_anchor_uid({"code": -101, "message": "账号未登录", "data": None})

    with pytest.raises(ValueError, match="排行榜失败"):
        parse_audience_snapshot(
            7450109,
            room_payload(),
            {"code": -400, "message": "排行榜失败", "data": None},
        )
```

- [ ] **Step 2: Run the parser tests and verify RED**

Run:

```bash
uv run pytest tests/test_live_audience.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'bilihud.live_audience'`.

- [ ] **Step 3: Implement the immutable models and parsers**

Create `src/bilihud/live_audience.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AudienceUser:
    uid: int
    name: str
    contribution: int
    rank: int
    is_mystery: bool = False


@dataclass(frozen=True)
class AudienceSnapshot:
    room_id: int
    popularity: int
    watched_count: int
    online_rank_count: int
    users: tuple[AudienceUser, ...]

    @property
    def hidden_user_count(self) -> int:
        return max(0, self.online_rank_count - len(self.users))


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _api_data(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("code") != 0:
        raise ValueError(str(payload.get("message") or payload.get("msg") or "B站接口请求失败"))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("B站接口返回的数据格式无效")
    return data


def parse_anchor_uid(room_payload: dict[str, Any]) -> int:
    data = _api_data(room_payload)
    room_info = data.get("room_info")
    uid = _non_negative_int(room_info.get("uid") if isinstance(room_info, dict) else 0)
    if uid <= 0:
        raise ValueError("未能获取直播间主播 UID")
    return uid


def parse_audience_snapshot(
    room_id: int,
    room_payload: dict[str, Any],
    rank_payload: dict[str, Any],
) -> AudienceSnapshot:
    room_data = _api_data(room_payload)
    rank_data = _api_data(rank_payload)

    room_info = room_data.get("room_info")
    room_info = room_info if isinstance(room_info, dict) else {}
    popularity_info = room_data.get("popularity")
    popularity_info = popularity_info if isinstance(popularity_info, dict) else {}
    watched_info = room_data.get("watched_show")
    watched_info = watched_info if isinstance(watched_info, dict) else {}

    popularity_value = popularity_info.get("popularity")
    if popularity_value is None:
        popularity_value = room_info.get("online")

    raw_items = rank_data.get("item")
    if not isinstance(raw_items, list):
        raw_items = []

    users: list[AudienceUser] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        uid = _non_negative_int(raw_item.get("uid"))
        name = str(raw_item.get("name") or "").strip()
        if uid <= 0 or not name:
            continue
        users.append(
            AudienceUser(
                uid=uid,
                name=name,
                contribution=_non_negative_int(raw_item.get("score")),
                rank=_non_negative_int(raw_item.get("rank")),
                is_mystery=bool(raw_item.get("is_mystery", False)),
            )
        )

    online_rank_count = max(_non_negative_int(rank_data.get("count")), len(users))
    return AudienceSnapshot(
        room_id=room_id,
        popularity=_non_negative_int(popularity_value),
        watched_count=_non_negative_int(watched_info.get("num")),
        online_rank_count=online_rank_count,
        users=tuple(users),
    )
```

- [ ] **Step 4: Run parser tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_live_audience.py -v
uv run ruff check src/bilihud/live_audience.py tests/test_live_audience.py
```

Expected: all parser tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/bilihud/live_audience.py tests/test_live_audience.py
git commit -m "feat: add live audience data model"
```

### Task 2: Fetch The Audience Snapshot Through DanmakuClient

**Files:**
- Modify: `src/bilihud/danmaku_client.py:19-32, 40-52, 150-205`
- Modify: `tests/test_danmaku_client.py:1-105, 205-300`

- [ ] **Step 1: Extend the fake HTTP session and write failing request tests**

Update `FakeHttpSession` in `tests/test_danmaku_client.py` so sequential requests can return different payloads:

```python
class FakeHttpSession:
    def __init__(self, get_payload=None, get_payloads=None, post_payload=None):
        self.get_payload = get_payload or {"code": 0, "data": {"data": []}}
        self.get_payloads = list(get_payloads or [])
        self.post_payload = post_payload or {"code": 0, "message": "0"}
        self.posted_data = None
        self.get_params = None
        self.get_headers = None
        self.get_calls = []
        self.cookie_jar = [FakeCookie("bili_jct", "csrf-token")]

    def get(self, url, params=None, headers=None):
        self.get_url = url
        self.get_params = params
        self.get_headers = headers
        self.get_calls.append((url, params, headers))
        payload = self.get_payloads.pop(0) if self.get_payloads else self.get_payload
        return FakeResponse(payload)

    def post(self, url, data=None):
        self.post_url = url
        self.posted_data = data
        return FakeResponse(self.post_payload)
```

Append these tests:

```python
def test_fetch_audience_snapshot_uses_current_web_api_contract():
    async def run_test():
        client = DanmakuClient(7450109)
        client.session = FakeHttpSession(
            get_payloads=[
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "room_info": {"uid": 9001, "online": 21},
                        "popularity": {"popularity": 21},
                        "watched_show": {"num": 9},
                    },
                },
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "count": 3,
                        "item": [
                            {
                                "uid": 1001,
                                "name": "用户A",
                                "score": 1,
                                "rank": 1,
                                "is_mystery": False,
                            }
                        ],
                    },
                },
            ]
        )

        snapshot = await client.fetch_audience_snapshot()

        assert snapshot.room_id == 7450109
        assert snapshot.popularity == 21
        assert snapshot.watched_count == 9
        assert snapshot.online_rank_count == 3
        assert snapshot.users[0].name == "用户A"
        assert snapshot.users[0].contribution == 1

        room_url, room_params, room_headers = client.session.get_calls[0]
        assert room_url.endswith("/xlive/web-room/v1/index/getInfoByRoom")
        assert room_params == {"room_id": 7450109}
        assert room_headers == {"Referer": "https://live.bilibili.com/7450109"}

        rank_url, rank_params, rank_headers = client.session.get_calls[1]
        assert rank_url.endswith("/xlive/general-interface/v1/rank/queryContributionRank")
        assert rank_params == {
            "ruid": 9001,
            "room_id": 7450109,
            "page": 1,
            "page_size": 100,
            "type": "online_rank",
            "switch": "contribution_rank",
            "platform": "web",
        }
        assert rank_headers == {"Referer": "https://live.bilibili.com/7450109"}

    asyncio.run(run_test())


def test_fetch_audience_snapshot_requires_initialized_session():
    async def run_test():
        client = DanmakuClient(7450109)

        with pytest.raises(RuntimeError, match="弹幕会话未初始化"):
            await client.fetch_audience_snapshot()

    asyncio.run(run_test())


def test_fetch_audience_snapshot_does_not_log_or_return_cookie_values():
    async def run_test():
        client = DanmakuClient(7450109)
        client.session = FakeHttpSession(
            get_payload={"code": -101, "message": "账号未登录", "data": None}
        )

        with pytest.raises(ValueError, match="账号未登录"):
            await client.fetch_audience_snapshot()

    asyncio.run(run_test())
```

- [ ] **Step 2: Run the request tests and verify RED**

Run:

```bash
uv run pytest tests/test_danmaku_client.py::test_fetch_audience_snapshot_uses_current_web_api_contract tests/test_danmaku_client.py::test_fetch_audience_snapshot_requires_initialized_session tests/test_danmaku_client.py::test_fetch_audience_snapshot_does_not_log_or_return_cookie_values -v
```

Expected: tests fail because `DanmakuClient.fetch_audience_snapshot` does not exist.

- [ ] **Step 3: Add endpoint constants, parser imports, and the fetch method**

Add these imports and constants to `src/bilihud/danmaku_client.py`:

```python
from .live_audience import AudienceSnapshot, parse_anchor_uid, parse_audience_snapshot

LIVE_ROOM_INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
LIVE_AUDIENCE_RANK_URL = (
    "https://api.live.bilibili.com/xlive/general-interface/v1/rank/queryContributionRank"
)
```

Add this method to `DanmakuClient` after `send_danmaku()` and before emoticon fetching:

```python
    async def fetch_audience_snapshot(self) -> AudienceSnapshot:
        if not self.session:
            raise RuntimeError("弹幕会话未初始化")

        headers = {"Referer": f"https://live.bilibili.com/{self.room_id}"}
        async with self.session.get(
            LIVE_ROOM_INFO_URL,
            params={"room_id": self.room_id},
            headers=headers,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"直播间信息 HTTP错误: {response.status}")
            room_payload = await response.json(content_type=None)

        anchor_uid = parse_anchor_uid(room_payload)
        rank_params = {
            "ruid": anchor_uid,
            "room_id": self.room_id,
            "page": 1,
            "page_size": 100,
            "type": "online_rank",
            "switch": "contribution_rank",
            "platform": "web",
        }
        async with self.session.get(
            LIVE_AUDIENCE_RANK_URL,
            params=rank_params,
            headers=headers,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"在线榜 HTTP错误: {response.status}")
            rank_payload = await response.json(content_type=None)

        return parse_audience_snapshot(self.room_id, room_payload, rank_payload)
```

- [ ] **Step 4: Run client tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_danmaku_client.py -v
uv run ruff check src/bilihud/danmaku_client.py tests/test_danmaku_client.py
```

Expected: all danmaku-client tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/bilihud/danmaku_client.py tests/test_danmaku_client.py
git commit -m "feat: fetch live audience snapshot"
```

### Task 3: Build The Compact Status Strip And Anchored Popup

**Files:**
- Create: `src/bilihud/audience_widgets.py`
- Create: `tests/test_audience_widgets.py`

- [ ] **Step 1: Write failing Qt widget tests**

Create `tests/test_audience_widgets.py`:

```python
import os

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from bilihud.audience_widgets import AudiencePopup, AudienceStatusWidget
from bilihud.live_audience import AudienceSnapshot, AudienceUser

_QT_APP = None


def app():
    global _QT_APP
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def snapshot(*, online_count=3, users=None):
    return AudienceSnapshot(
        room_id=7450109,
        popularity=21,
        watched_count=9,
        online_rank_count=online_count,
        users=users
        if users is not None
        else (AudienceUser(1001, "用户A", 1, 1, False),),
    )


def test_status_widget_formats_metrics_and_emits_only_from_online_button():
    app()
    widget = AudienceStatusWidget()
    requested = []
    widget.audience_requested.connect(lambda: requested.append(True))

    assert widget.isHidden()

    widget.set_snapshot(snapshot())

    assert widget.popularity_label.text() == "21 人气"
    assert widget.watched_label.text() == "9 人看过"
    assert widget.online_button.text() == "在线榜 3"
    assert widget.online_button.cursor().shape() == Qt.CursorShape.PointingHandCursor

    widget.online_button.click()
    assert requested == [True]

    widget.clear()
    assert widget.isHidden()


def test_popup_maps_each_username_to_its_contribution():
    app()
    popup = AudiencePopup()
    popup.set_snapshot(
        snapshot(
            users=(
                AudienceUser(1001, "用户A", 1, 1, False),
                AudienceUser(1002, "用户B", 4, 2, False),
            )
        )
    )

    assert popup.summary_label.text() == "可见 2 / 共 3"
    assert popup.tree.topLevelItemCount() == 2
    assert popup.tree.topLevelItem(0).text(0) == "用户A"
    assert popup.tree.topLevelItem(0).text(1) == "1"
    assert popup.tree.topLevelItem(1).text(0) == "用户B"
    assert popup.tree.topLevelItem(1).text(1) == "4"
    assert popup.footer_label.text() == "还有 1 位用户未公开"
    assert popup.footer_label.isHidden() is False


def test_popup_shows_empty_visible_list_without_inventing_users():
    app()
    popup = AudiencePopup()
    popup.set_snapshot(snapshot(online_count=2, users=()))

    assert popup.tree.isHidden()
    assert popup.empty_label.text() == "暂无可见用户"
    assert popup.empty_label.isHidden() is False
    assert popup.footer_label.text() == "还有 2 位用户未公开"


def test_popup_escape_closes_popup():
    qt_app = app()
    popup = AudiencePopup()
    popup.set_snapshot(snapshot())
    popup.show()
    qt_app.processEvents()

    QTest.keyClick(popup, Qt.Key.Key_Escape)
    qt_app.processEvents()

    assert popup.isHidden()


def test_popup_constrains_long_list_to_internal_scroll_area():
    qt_app = app()
    popup = AudiencePopup()
    users = tuple(
        AudienceUser(1000 + index, f"用户{index}", index, index, False)
        for index in range(120)
    )
    popup.set_snapshot(snapshot(online_count=120, users=users))
    popup.show()
    qt_app.processEvents()

    assert popup.tree.topLevelItemCount() == 120
    assert popup.height() <= 260
    assert popup.tree.verticalScrollBar().maximum() > 0
```

- [ ] **Step 2: Run widget tests and verify RED**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_audience_widgets.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'bilihud.audience_widgets'`.

- [ ] **Step 3: Implement the status strip and popup**

Create `src/bilihud/audience_widgets.py`:

```python
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .live_audience import AudienceSnapshot


class AudienceStatusWidget(QWidget):
    audience_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.popularity_label = QLabel()
        self.watched_label = QLabel()
        first_separator = QLabel("·")
        second_separator = QLabel("·")
        self.online_button = QToolButton()
        self.online_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.online_button.setToolTip("查看在线榜用户")
        self.online_button.clicked.connect(lambda _checked=False: self.audience_requested.emit())

        neutral_style = "color: rgba(255, 255, 255, 170); font-size: 11px;"
        separator_style = "color: rgba(255, 255, 255, 80); font-size: 11px;"
        self.popularity_label.setStyleSheet(neutral_style)
        self.watched_label.setStyleSheet(neutral_style)
        first_separator.setStyleSheet(separator_style)
        second_separator.setStyleSheet(separator_style)
        self.online_button.setStyleSheet(
            """
            QToolButton {
                color: #67c7ff;
                background: transparent;
                border: none;
                border-bottom: 1px dotted rgba(103, 199, 255, 160);
                padding: 0;
                font-size: 11px;
                font-weight: 600;
            }
            QToolButton:hover { color: #9bdcff; }
            """
        )

        layout.addWidget(self.popularity_label)
        layout.addWidget(first_separator)
        layout.addWidget(self.watched_label)
        layout.addWidget(second_separator)
        layout.addWidget(self.online_button)
        layout.addStretch()
        self.hide()

    def set_snapshot(self, snapshot: AudienceSnapshot) -> None:
        self.popularity_label.setText(f"{snapshot.popularity} 人气")
        self.watched_label.setText(f"{snapshot.watched_count} 人看过")
        self.online_button.setText(f"在线榜 {snapshot.online_rank_count}")
        self.show()

    def clear(self) -> None:
        self.popularity_label.clear()
        self.watched_label.clear()
        self.online_button.setText("在线榜 0")
        self.hide()


class AudiencePopup(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("audiencePopup")
        self.setMinimumWidth(220)
        self.setMaximumHeight(260)
        self.setStyleSheet(
            """
            QFrame#audiencePopup {
                background: rgba(32, 36, 42, 245);
                border: 1px solid rgba(255, 255, 255, 45);
                border-radius: 6px;
            }
            QLabel { color: rgba(255, 255, 255, 210); font-size: 11px; }
            QTreeWidget {
                color: rgba(255, 255, 255, 220);
                background: transparent;
                border: none;
                outline: none;
                font-size: 11px;
            }
            QHeaderView::section {
                color: rgba(255, 255, 255, 120);
                background: transparent;
                border: none;
                padding: 3px 4px;
                font-size: 10px;
            }
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(9, 8, 9, 8)
        outer.setSpacing(5)

        header = QHBoxLayout()
        title = QLabel("在线榜")
        title.setStyleSheet("font-weight: 700; color: white;")
        self.summary_label = QLabel()
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.summary_label.setStyleSheet("color: rgba(255, 255, 255, 120); font-size: 10px;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.summary_label)
        outer.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["用户名", "贡献值"])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.tree)

        self.empty_label = QLabel("暂无可见用户")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: rgba(255, 255, 255, 110); padding: 12px;")
        outer.addWidget(self.empty_label)

        self.footer_label = QLabel()
        self.footer_label.setStyleSheet("color: rgba(255, 255, 255, 110); font-size: 10px;")
        outer.addWidget(self.footer_label)
        self.hide()

    def set_snapshot(self, snapshot: AudienceSnapshot) -> None:
        self.summary_label.setText(f"可见 {len(snapshot.users)} / 共 {snapshot.online_rank_count}")
        self.tree.clear()
        for user in snapshot.users:
            item = QTreeWidgetItem([user.name, str(user.contribution)])
            item.setToolTip(0, user.name)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)

        has_users = bool(snapshot.users)
        self.tree.setVisible(has_users)
        self.empty_label.setVisible(not has_users)

        hidden_count = snapshot.hidden_user_count
        self.footer_label.setText(f"还有 {hidden_count} 位用户未公开")
        self.footer_label.setVisible(hidden_count > 0)

    def show_below(self, anchor: QWidget, host: QWidget) -> None:
        self.adjustSize()
        host_left = host.mapToGlobal(QPoint(0, 0)).x()
        host_right = host_left + host.width()
        anchor_bottom_right = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + 4))
        x = max(host_left, min(anchor_bottom_right.x() - self.width(), host_right - self.width()))
        y = anchor_bottom_right.y()

        screen = anchor.screen()
        if screen is not None and y + self.height() > screen.availableGeometry().bottom():
            y = anchor.mapToGlobal(QPoint(0, -self.height() - 4)).y()

        self.move(x, y)
        self.show()
        self.raise_()
```

- [ ] **Step 4: Run widget tests and verify GREEN**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_audience_widgets.py -v
uv run ruff check src/bilihud/audience_widgets.py tests/test_audience_widgets.py
```

Expected: all audience-widget tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/bilihud/audience_widgets.py tests/test_audience_widgets.py
git commit -m "feat: add HUD audience widgets"
```

### Task 4: Integrate Refresh Lifecycle Into DanmakuWidget

**Files:**
- Modify: `src/bilihud/danmaku_widget.py:1-42, 706-755, 877-1040, 1247-1380, 1513-1618`
- Modify: `tests/test_danmaku_widget.py:1-20, 385-466`

- [ ] **Step 1: Write failing lifecycle tests**

Add imports to `tests/test_danmaku_widget.py`:

```python
import pytest

from bilihud.live_audience import AudienceSnapshot, AudienceUser
```

Append these tests:

```python
def audience_snapshot(room_id=7450109):
    return AudienceSnapshot(
        room_id=room_id,
        popularity=21,
        watched_count=9,
        online_rank_count=3,
        users=(AudienceUser(1001, "用户A", 1, 1, False),),
    )


def test_refresh_audience_once_applies_only_current_room_and_generation():
    class Client:
        room_id = 7450109

        async def fetch_audience_snapshot(self):
            return audience_snapshot()

    class Status:
        def set_snapshot(self, snapshot):
            applied.append(snapshot)

        def setVisible(self, visible):
            visibility.append(visible)

    class Popup:
        def set_snapshot(self, snapshot):
            popup_applied.append(snapshot)

    async def run_test():
        client = Client()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.danmaku_client = client
        widget.room_id = 7450109
        widget._audience_generation = 4
        widget._audience_snapshot = None
        widget.is_gaming_mode = False
        widget.audience_status = Status()
        widget.audience_popup = Popup()

        updated = await widget._refresh_audience_once(client, 4)
        stale = await widget._refresh_audience_once(client, 3)

        assert updated is True
        assert stale is False
        assert widget._audience_snapshot == audience_snapshot()
        assert applied == [audience_snapshot()]
        assert popup_applied == [audience_snapshot()]
        assert visibility == [True]

    applied = []
    popup_applied = []
    visibility = []
    asyncio.run(run_test())


def test_refresh_audience_once_keeps_last_snapshot_after_failure():
    previous = audience_snapshot()

    class Client:
        room_id = 7450109

        async def fetch_audience_snapshot(self):
            raise RuntimeError("temporary failure")

    async def run_test():
        client = Client()
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget.danmaku_client = client
        widget.room_id = 7450109
        widget._audience_generation = 2
        widget._audience_snapshot = previous

        updated = await widget._refresh_audience_once(client, 2)

        assert updated is False
        assert widget._audience_snapshot is previous

    asyncio.run(run_test())


def test_stop_audience_refresh_cancels_task_and_clears_widgets():
    class Status:
        def clear(self):
            calls.append("status-clear")

    class Popup:
        def hide(self):
            calls.append("popup-hide")

    async def run_test():
        started = asyncio.Event()

        async def forever():
            started.set()
            await asyncio.Event().wait()

        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
        widget._audience_generation = 1
        widget._audience_snapshot = audience_snapshot()
        widget.audience_status = Status()
        widget.audience_popup = Popup()
        widget._audience_refresh_task = asyncio.create_task(forever())
        await started.wait()

        await widget._stop_audience_refresh()

        assert widget._audience_refresh_task is None
        assert widget._audience_snapshot is None
        assert calls == ["popup-hide", "status-clear"]

    calls = []
    asyncio.run(run_test())


def test_sync_audience_visibility_hides_status_and_popup_in_gaming_mode():
    class Status:
        def setVisible(self, visible):
            calls.append(("visible", visible))

    class Popup:
        def hide(self):
            calls.append(("popup", False))

    widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)
    widget._audience_snapshot = audience_snapshot()
    widget.is_gaming_mode = True
    widget.audience_status = Status()
    widget.audience_popup = Popup()

    widget._sync_audience_visibility()

    assert calls == [("visible", False), ("popup", False)]


def test_audience_refresh_loop_waits_thirty_seconds(monkeypatch):
    class Client:
        room_id = 7450109

    async def run_test():
        widget = danmaku_widget.DanmakuWidget.__new__(danmaku_widget.DanmakuWidget)

        async def refresh_once(client, generation):
            calls.append(("refresh", client.room_id, generation))
            return True

        async def fake_sleep(delay):
            calls.append(("sleep", delay))
            raise asyncio.CancelledError

        widget._refresh_audience_once = refresh_once
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await widget._audience_refresh_loop(Client(), 7)

    calls = []
    asyncio.run(run_test())

    assert calls == [
        ("refresh", 7450109, 7),
        ("sleep", danmaku_widget.AUDIENCE_REFRESH_INTERVAL_SECONDS),
    ]
    assert danmaku_widget.AUDIENCE_REFRESH_INTERVAL_SECONDS == 30.0
```

Update the existing stale-client connection test so its fake widget supplies audience lifecycle hooks:

```python
        async def start_audience_refresh(client):
            events.append(("audience-start", client.room_id))

        widget._start_audience_refresh = start_audience_refresh
```

Add this assertion after the connection completes:

```python
        assert events[-2:] == ["connected", ("audience-start", 7450109)]
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_danmaku_widget.py::test_refresh_audience_once_applies_only_current_room_and_generation tests/test_danmaku_widget.py::test_refresh_audience_once_keeps_last_snapshot_after_failure tests/test_danmaku_widget.py::test_stop_audience_refresh_cancels_task_and_clears_widgets tests/test_danmaku_widget.py::test_sync_audience_visibility_hides_status_and_popup_in_gaming_mode tests/test_danmaku_widget.py::test_audience_refresh_loop_waits_thirty_seconds tests/test_danmaku_widget.py::test_connect_to_room_replaces_stale_same_room_client -v
```

Expected: tests fail because the audience lifecycle methods do not exist and the connection does not start audience refresh.

- [ ] **Step 3: Add imports, constants, and initial audience state**

Add to `src/bilihud/danmaku_widget.py`:

```python
import logging

from .audience_widgets import AudiencePopup, AudienceStatusWidget
from .live_audience import AudienceSnapshot

logger = logging.getLogger(__name__)
AUDIENCE_REFRESH_INTERVAL_SECONDS = 30.0
```

Add these fields in `DanmakuWidget.__init__` before `init_ui()`:

```python
        self._audience_refresh_task: asyncio.Task[None] | None = None
        self._audience_generation = 0
        self._audience_snapshot: AudienceSnapshot | None = None
```

- [ ] **Step 4: Place the status strip and popup below the existing header**

In `DanmakuWidget.init_ui()`, create the components after the header controls are assembled:

```python
        self.audience_status = AudienceStatusWidget(self)
        self.audience_popup = AudiencePopup(self)
        self.audience_status.audience_requested.connect(self.open_audience_popup)
```

Change main-layout assembly to:

```python
        self.main_layout.addWidget(self.header_widget)
        self.main_layout.addWidget(self.audience_status)
        self.main_layout.addWidget(self.danmaku_list)
        self.main_layout.addWidget(self.input_area)
```

Add the popup-opening method:

```python
    def open_audience_popup(self) -> None:
        if self.is_gaming_mode or self._audience_snapshot is None:
            return
        self.audience_popup.set_snapshot(self._audience_snapshot)
        self.audience_popup.show_below(self.audience_status.online_button, self)
```

- [ ] **Step 5: Implement refresh, generation, and cleanup methods**

Add these methods near the existing danmaku-client lifecycle methods:

```python
    async def _refresh_audience_once(self, client: DanmakuClient, generation: int) -> bool:
        try:
            snapshot = await client.fetch_audience_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Failed to refresh audience snapshot for room %s: %s", client.room_id, exc)
            return False

        if (
            generation != self._audience_generation
            or self.danmaku_client is not client
            or self.room_id != snapshot.room_id
        ):
            return False

        self._audience_snapshot = snapshot
        self.audience_popup.set_snapshot(snapshot)
        self.audience_status.set_snapshot(snapshot)
        self._sync_audience_visibility()
        return True

    async def _audience_refresh_loop(self, client: DanmakuClient, generation: int) -> None:
        while True:
            await self._refresh_audience_once(client, generation)
            await asyncio.sleep(AUDIENCE_REFRESH_INTERVAL_SECONDS)

    async def _start_audience_refresh(self, client: DanmakuClient) -> None:
        await self._stop_audience_refresh()
        self._audience_generation += 1
        generation = self._audience_generation
        self._audience_refresh_task = asyncio.create_task(
            self._audience_refresh_loop(client, generation)
        )

    async def _stop_audience_refresh(self) -> None:
        self._audience_generation += 1
        task = self._audience_refresh_task
        self._audience_refresh_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._audience_snapshot = None
        self.audience_popup.hide()
        self.audience_status.clear()

    def _sync_audience_visibility(self) -> None:
        visible = not self.is_gaming_mode and self._audience_snapshot is not None
        self.audience_status.setVisible(visible)
        if not visible:
            self.audience_popup.hide()
```

- [ ] **Step 6: Wire refresh into connect, disconnect, and gaming mode**

At the end of a successful `_connect_to_room_id()` call, after `_set_connected_ui()`:

```python
        await self._start_audience_refresh(self.danmaku_client)
```

If the active same-room connection returns early, ensure a missing refresh task is restarted:

```python
            if self._audience_refresh_task is None:
                await self._start_audience_refresh(self.danmaku_client)
```

Replace `_disconnect_current_room()` with lifecycle-aware cleanup that restores refresh if stopping the client fails:

```python
    async def _disconnect_current_room(self):
        self.connect_button.setEnabled(False)
        client = self.danmaku_client
        await self._stop_audience_refresh()
        try:
            if client is not None:
                await client.stop()
        except Exception as exc:
            if client is not None:
                await self._start_audience_refresh(client)
            self._set_connected_ui()
            self.add_system_message(f"断开失败: {exc}", "error")
            print(f"Disconnect failed: {exc}")
            raise
        self.danmaku_client = None
        self._set_disconnected_ui()
```

In `set_gaming_mode()`, after the normal/gaming UI visibility branch and before native window handling, call:

```python
        self._sync_audience_visibility()
```

- [ ] **Step 7: Run lifecycle and widget integration tests and verify GREEN**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_danmaku_widget.py tests/test_audience_widgets.py -v
uv run ruff check src/bilihud/danmaku_widget.py tests/test_danmaku_widget.py
```

Expected: all widget and lifecycle tests pass and Ruff reports no errors.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/bilihud/danmaku_widget.py tests/test_danmaku_widget.py
git commit -m "feat: show audience status in HUD"
```

### Task 5: Verify The Complete Feature And Capture The UI

**Files:**
- Verify: `src/bilihud/live_audience.py`
- Verify: `src/bilihud/danmaku_client.py`
- Verify: `src/bilihud/audience_widgets.py`
- Verify: `src/bilihud/danmaku_widget.py`
- Verify: `tests/test_live_audience.py`
- Verify: `tests/test_danmaku_client.py`
- Verify: `tests/test_audience_widgets.py`
- Verify: `tests/test_danmaku_widget.py`

- [ ] **Step 1: Run the focused feature suite**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest \
  tests/test_live_audience.py \
  tests/test_danmaku_client.py \
  tests/test_audience_widgets.py \
  tests/test_danmaku_widget.py \
  -q
```

Expected: all focused tests pass with zero failures.

- [ ] **Step 2: Run the complete test suite**

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

Expected: the entire repository test suite passes with zero failures.

- [ ] **Step 3: Run lint and type checks**

```bash
uv run ruff check src tests
uv run ty check
```

Expected: both commands exit successfully with no new diagnostics.

- [ ] **Step 4: Capture an offscreen screenshot at the default HUD width**

Run:

```bash
QT_QPA_PLATFORM=offscreen uv run python -c '
from PyQt6.QtWidgets import QApplication
from bilihud.danmaku_widget import DanmakuWidget
from bilihud.live_audience import AudienceSnapshot, AudienceUser
app = QApplication([])
widget = DanmakuWidget(7450109)
widget.resize(300, 450)
snapshot = AudienceSnapshot(7450109, 21, 9, 3, (AudienceUser(1001, "用户A", 1, 1),))
widget._audience_snapshot = snapshot
widget.audience_status.set_snapshot(snapshot)
widget.show()
widget.open_audience_popup()
app.processEvents()
widget.grab().save("/tmp/bilihud-audience-status.png")
widget.audience_popup.grab().save("/tmp/bilihud-audience-popup.png")
'
```

Inspect both files. Verify:

- all status text fits at 280 pixels without overlap;
- `在线榜 3` is visibly interactive but restrained;
- popup columns align and remain within the intended HUD width;
- the anonymous sample username elides if necessary;
- the hidden-user footer is readable;
- no real user identity appears in test fixtures, screenshots, docs, or logs.

- [ ] **Step 5: Re-test gaming-mode visibility manually in offscreen Qt**

Add a temporary assertion in an interactive Python session or use the lifecycle test fixture to confirm:

```python
widget.is_gaming_mode = True
widget._sync_audience_visibility()
assert widget.audience_status.isHidden()
assert widget.audience_popup.isHidden()
```

Remove any temporary interactive-only code before committing.

- [ ] **Step 6: Review the final diff for scope and credential safety**

```bash
git diff --check
git diff --stat HEAD~4..HEAD
rg -n "SESSDATA|bili_jct|csrf-token" src tests docs
rg -n "用户A|用户B" tests docs/superpowers
```

Expected:

- `git diff --check` reports no whitespace errors;
- the diff contains only the audience feature and its tests;
- credential names may appear only in existing authentication/test code, never with real values;
- all audience examples use anonymous placeholders such as `用户A` and `用户B`.

- [ ] **Step 7: Commit any verification-only corrections**

If verification required tracked corrections, commit only those corrections:

```bash
git add src tests docs
git commit -m "test: verify HUD audience status"
```

If verification required no tracked corrections, do not create an empty commit.
