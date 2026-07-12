# Preserve HUD Connection During Live Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the live-start callback path that can reconnect or replace the HUD danmaku client while preserving automatic HUD connection when live control opens.

**Architecture:** `DanmakuWidget` remains the sole owner of the HUD connection lifecycle. `LiveControlDialog` performs only live API and OBS operations; it no longer receives or calls a HUD connection callback. Existing source-level regression tests are inverted to enforce this ownership boundary.

**Tech Stack:** Python 3.10+, PyQt6, qasync, pytest

---

### Task 1: Remove HUD Connection Management From Live Start

**Files:**
- Modify: `tests/test_danmaku_widget.py:387-473`
- Modify: `src/bilihud/live_control_dialog.py:1-818`
- Modify: `src/bilihud/danmaku_widget.py:1805-1809`

- [ ] **Step 1: Write the failing regression test**

In `tests/test_danmaku_widget.py`, rename the open-dialog test and remove the assertion that wires the start-live callback:

```python
def test_live_control_uses_anchor_room_and_connects_hud_when_opened_source():
    source = Path("src/bilihud/danmaku_widget.py").read_text(encoding="utf-8")

    assert "get_anchor_live_room_id" in source
    assert "async def open_live_control(self):" in source
    assert "anchor_room_id = await self._ensure_live_control_room()" in source
    assert "self._live_control_dialog.set_room_id(anchor_room_id)" in source
    assert "self._live_control_dialog.set_room_id(self.room_id)" not in source
    assert "await self._connect_to_room_id(anchor_room_id)" in source
    assert "set_ensure_hud_room_callback" not in source
```

Replace `test_live_control_start_live_ensures_hud_room_before_starting` with:

```python
def test_live_control_start_live_does_not_manage_hud_connection():
    source = Path("src/bilihud/live_control_dialog.py").read_text(encoding="utf-8")

    assert "_ensure_hud_room_callback" not in source
    assert "set_ensure_hud_room_callback" not in source
    assert "_ensure_hud_room" not in source
```

- [ ] **Step 2: Run the regression tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra test pytest -q \
  tests/test_danmaku_widget.py::test_live_control_uses_anchor_room_and_connects_hud_when_opened_source \
  tests/test_danmaku_widget.py::test_live_control_start_live_does_not_manage_hud_connection
```

Expected: both tests fail because the current code still contains `set_ensure_hud_room_callback`, `_ensure_hud_room_callback`, and `_ensure_hud_room`.

- [ ] **Step 3: Remove the live-control callback contract**

In `src/bilihud/live_control_dialog.py`, remove the unused callback imports:

```python
from collections.abc import Awaitable, Callable
```

Remove this initialization from `LiveControlDialog.__init__()`:

```python
self._ensure_hud_room_callback: Callable[[int], Awaitable[None]] | None = None
```

Remove the setter:

```python
def set_ensure_hud_room_callback(self, callback: Callable[[int], Awaitable[None]]) -> None:
    self._ensure_hud_room_callback = callback
```

Remove the HUD ensure call and its action-generation check from `handle_start_live()`:

```python
await self._ensure_hud_room(room_id)
if not self._is_current_action(action_generation, session):
    return
```

Remove the helper:

```python
async def _ensure_hud_room(self, room_id: int) -> None:
    if self._ensure_hud_room_callback is not None:
        await self._ensure_hud_room_callback(room_id)
```

In `src/bilihud/danmaku_widget.py`, keep dialog creation and live status wiring but remove the callback registration so the block becomes:

```python
if not hasattr(self, '_live_control_dialog'):
    self._live_control_dialog = LiveControlDialog(self)
    self._live_control_dialog.live_status_changed.connect(self.set_live_status_indicator)
self._live_control_dialog.set_room_id(anchor_room_id)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra test pytest -q \
  tests/test_danmaku_widget.py::test_live_control_uses_anchor_room_and_connects_hud_when_opened_source \
  tests/test_danmaku_widget.py::test_live_control_start_live_does_not_manage_hud_connection \
  tests/test_danmaku_widget.py::test_connect_to_room_replaces_stale_same_room_client
```

Expected: `3 passed`.

- [ ] **Step 5: Run static checks for the removed contract**

Run:

```bash
rg -n "ensure_hud_room|set_ensure_hud_room_callback" src tests
```

Expected: no matches and exit status 1.

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra test ruff check \
  src/bilihud/live_control_dialog.py \
  src/bilihud/danmaku_widget.py \
  tests/test_danmaku_widget.py
```

Expected: `All checks passed!`.

- [ ] **Step 6: Run the full test suite**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --extra test pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the bug fix**

```bash
git add src/bilihud/live_control_dialog.py src/bilihud/danmaku_widget.py tests/test_danmaku_widget.py
git commit -m "fix: preserve HUD connection when starting live"
```
