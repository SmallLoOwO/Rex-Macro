# 網頁 UI P1：IPC 基礎建設 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 WebSocket IPC 基礎建設，讓 bot 主迴圈與網頁 UI 之間能雙向溝通（命令上傳、事件下推、截圖傳輸），為後續 P2~P5 子系統鋪底。

**Architecture:** FastAPI + uvicorn 跑在 daemon thread 內（與 bot 同 process）；web_pending queue 與既有 Discord polling pending queue 平行；race 採 routing key 「先到先贏」；WebSocket client 連線數 0 時切 fallback，30s grace period 防分頁重新整理抖動。

**Tech Stack:** Python 3.11+ / FastAPI / uvicorn / pytest（既有專案 stack）

## Global Constraints

- Python 3.11+（專案 `pyproject.toml` 要求）
- 新依賴 `fastapi` + `uvicorn`，必過 `uv lock --check`
- 座標 / 門檻 / 間隔只放 `miningbot/config.py`
- 純函式優先、I/O 邊界不交叉；race 邏輯放純函式，可單元測試
- 不放寬偵測門檻、不刪事故回歸測試（H001~H060）
- 不修改 `discord_commands.py`、`notify.py` 既有行為（P2 才動 Discord）
- 不修改 `reentry_remote.py` / `remote_aim.py` 純函式
- 實機驗收 = log 確認，不是測試綠（P1 不需實機，整合測試 + fake bot 即可）
- Commit message 用中文；尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer
- 規格依據：`docs/superpowers/specs/2026-07-26-web-ui-design.md` §3、§8、§11

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `pyproject.toml` | 加 fastapi、uvicorn 依賴 |
| `miningbot/config.py` | 加 `web_server_enabled` / `web_server_port` / `web_fallback_grace_s` |
| `miningbot/web_protocol.py` | WebSocket 訊息 dataclass、序列化、座標還原（純函式） |
| `miningbot/web_config_whitelist.py` | 玩家可改欄位白名單 + 值驗證（純函式） |
| `miningbot/web_ipc.py` | race routing key、`PendingReplies`（先到先贏）、`FallbackState`（純函式） |
| `miningbot/web_sink.py` | `WebEventSink`：`EventLog` 事件 → WebSocket 廣播 |
| `miningbot/web_server.py` | FastAPI app、WebSocket endpoint、WebIPC daemon thread |
| `miningbot/main.py` | 啟動 WebIPC thread、主迴圈 safe point 消費 `web_pending`、`EventLog.add_sink(WebEventSink)` |
| `tests/test_web_protocol.py` | dataclass、序列化、座標還原 |
| `tests/test_web_config_whitelist.py` | 白名單與值驗證 |
| `tests/test_web_ipc.py` | routing key、`PendingReplies`、`FallbackState` |
| `tests/test_web_sink.py` | `WebEventSink` 事件 → 廣播 |
| `tests/test_web_server.py` | 整合：fake bot + 測試 WebSocket client |

---

## Task 1: 依賴 + Config + 模組 scaffolding

**Files:**
- Modify: `pyproject.toml`（加 fastapi、uvicorn）
- Modify: `miningbot/config.py`（加 3 個欄位）
- Create: `miningbot/web_protocol.py`（空模組 + docstring）
- Create: `miningbot/web_config_whitelist.py`（空模組）
- Create: `miningbot/web_ipc.py`（空模組）
- Create: `miningbot/web_sink.py`（空模組）
- Create: `miningbot/web_server.py`（空模組）
- Test: `tests/test_web_scaffold.py`

**Interfaces:**
- Produces: `Config.web_server_enabled: bool`、`Config.web_server_port: int`、`Config.web_fallback_grace_s: float`

- [ ] **Step 1: 加依賴到 pyproject.toml**

在 `pyproject.toml` 的 `[project]` → `dependencies` 列表加入：
```toml
"fastapi>=0.110",
"uvicorn>=0.27",
```

跑 `uv sync` 確認能裝起來。

- [ ] **Step 2: 寫失敗測試**

```python
# tests/test_web_scaffold.py
"""web 子系統 scaffolding：依賴可裝、模組可 import、Config 欄位就位。"""
import pytest


def test_fastapi_importable():
    import fastapi
    import uvicorn
    assert fastapi.__version__  # 確保安裝
    assert uvicorn.__version__


@pytest.mark.parametrize("module_name", [
    "miningbot.web_protocol",
    "miningbot.web_config_whitelist",
    "miningbot.web_ipc",
    "miningbot.web_sink",
    "miningbot.web_server",
])
def test_module_importable(module_name):
    __import__(module_name)


def test_config_has_web_fields():
    from miningbot.config import Config
    cfg = Config()
    assert cfg.web_server_enabled is True
    assert cfg.web_server_port == 8765
    assert cfg.web_fallback_grace_s == 30.0
```

- [ ] **Step 3: 跑測試，確認失敗**

```
uv run pytest tests/test_web_scaffold.py -v
```

預期：`test_config_has_web_fields` 跟 `test_module_importable` FAIL（AttributeError / ModuleNotFoundError）。

- [ ] **Step 4: 在 `miningbot/config.py` 加欄位**

在 `Config` dataclass 適當位置（建議在 Discord 相關欄位之前）加：

```python
    # 網頁 UI（2026-07-26 spec；P1：IPC 基礎建設）
    web_server_enabled: bool = True              # 啟用網頁伺服器（綁 127.0.0.1）
    web_server_port: int = 8765                  # 網頁 port（Tailscale Serve 出 HTTPS）
    web_fallback_grace_s: float = 30.0           # WebSocket 0 client 後等多久才切 fallback
```

- [ ] **Step 5: 建空模組（每個檔只放 docstring）**

```python
# miningbot/web_protocol.py
"""WebSocket 訊息協議：dataclass、序列化、座標還原（純函式）。

P1 task 2~3 擴充。"""
```

其他四個檔同理，docstring 寫該模組職責。

- [ ] **Step 6: 跑測試，確認通過**

```
uv run pytest tests/test_web_scaffold.py -v
uv run pytest -q  # 確認沒回歸
uv run ruff check . --no-cache
uv lock --check
```

預期：全綠 + lint 乾淨 + lock 一致。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock miningbot/config.py miningbot/web_protocol.py miningbot/web_config_whitelist.py miningbot/web_ipc.py miningbot/web_sink.py miningbot/web_server.py tests/test_web_scaffold.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 scaffolding——FastAPI/uvicorn 依賴 + Config 三欄位 + 五個空模組

為後續 IPC 基礎建設 task 鋪底。實作規格見
docs/superpowers/specs/2026-07-26-web-ui-design.md §8、§11。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: WebSocket 訊息 dataclass + 序列化

**Files:**
- Modify: `miningbot/web_protocol.py`
- Test: `tests/test_web_protocol.py`

**Interfaces:**
- Produces:
  - `WebMessage`（frozen dataclass：`type`、`payload`）
  - `serialize_message(msg: WebMessage) -> str`（JSON 字串）
  - `parse_message(text: str) -> WebMessage | None`（None = 不合法）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_protocol.py
"""WebSocket 訊息協議：dataclass、序列化、座標還原。"""
import json
import pytest
from miningbot.web_protocol import WebMessage, serialize_message, parse_message


class TestMessageRoundtrip:
    def test_event_message_serializes(self):
        msg = WebMessage(type="event", payload={"event": "NEEDS_HUMAN", "harvest_id": "007"})
        s = serialize_message(msg)
        assert json.loads(s) == {"type": "event", "payload": {"event": "NEEDS_HUMAN", "harvest_id": "007"}}

    def test_command_message_serializes(self):
        msg = WebMessage(type="command", payload={"cmd": "fire_at", "x": 851, "y": 189})
        s = serialize_message(msg)
        parsed = json.loads(s)
        assert parsed["type"] == "command"
        assert parsed["payload"]["cmd"] == "fire_at"

    def test_roundtrip_preserves_message(self):
        msg = WebMessage(type="event", payload={"event": "HARVEST_SUCCESS"})
        assert parse_message(serialize_message(msg)) == msg


class TestParseValidation:
    def test_parse_invalid_json_returns_none(self):
        assert parse_message("not json") is None

    def test_parse_missing_type_returns_none(self):
        assert parse_message('{"payload": {}}') is None

    def test_parse_missing_payload_returns_none(self):
        assert parse_message('{"type": "event"}') is None

    def test_parse_payload_not_dict_returns_none(self):
        assert parse_message('{"type": "event", "payload": "string"}') is None

    def test_parse_type_not_string_returns_none(self):
        assert parse_message('{"type": 123, "payload": {}}') is None
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_protocol.py -v
```

預期：FAIL（import error / 屬性錯）。

- [ ] **Step 3: 實作 `WebMessage` + 序列化**

```python
# miningbot/web_protocol.py
"""WebSocket 訊息協議：dataclass、序列化、座標還原（純函式）。

訊息分兩種 type：
- "event"（bot → web）：NEEDS_HUMAN / HARVEST_SUCCESS / REENTRY_START / 狀態變動 等
- "command"（web → bot）：fire_at / reentry_click / config_set / pause / request_frame 等

座標系：所有 (x,y) 都是**遊戲原生解析度**（1920×1080）；client 端用 CSS scale 顯示，
點擊座標 server 端用 client_to_native_coords 還原（Task 3）。
"""
import json
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class WebMessage:
    """WebSocket 訊息。type 必為 "event" 或 "command"；payload 是 dict。

    frozen=True：訊息不可變，避免 consumer 改到 producer 還在用的實例。
    """
    type: str
    payload: dict


def serialize_message(msg: WebMessage) -> str:
    """WebMessage → JSON 字串（ WebSocket text frame 傳輸用）。"""
    return json.dumps(asdict(msg), ensure_ascii=False)


def parse_message(text: str) -> WebMessage | None:
    """JSON 字串 → WebMessage；不合法回 None（不丟例外，避免網路層吃壞資料炸掉）。

    缺 type / 缺 payload / type 不是字串 / payload 不是 dict 一律 None。
    """
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    t = d.get("type")
    p = d.get("payload")
    if not isinstance(t, str) or not isinstance(p, dict):
        return None
    return WebMessage(type=t, payload=p)
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_protocol.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_protocol.py tests/test_web_protocol.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 2——WebSocket 訊息 dataclass + 序列化純函式

WebMessage(type, payload) frozen dataclass；parse_message 防禦性回 None。
支援 event（bot→web）與 command（web→bot）雙向。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 座標還原（pinch-zoom 數學）

**Files:**
- Modify: `miningbot/web_protocol.py`
- Test: `tests/test_web_protocol.py`（加新 class）

**Interfaces:**
- Produces:
  - `client_to_native_coords(client_xy, canvas_size, native_size, pan_offset=(0,0), zoom=1.0) -> tuple[int, int]`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_web_protocol.py` 末尾：

```python
from miningbot.web_protocol import client_to_native_coords


class TestClientToNativeCoords:
    def test_no_zoom_no_pan(self):
        # canvas 跟原生同尺寸，點哪是哪
        assert client_to_native_coords(
            client_xy=(960, 540),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (960, 540)

    def test_canvas_half_size(self):
        # canvas 顯示 960×540（縮小 2x），點 (480, 270) → 原生 (960, 540)
        assert client_to_native_coords(
            client_xy=(480, 270),
            canvas_size=(960, 540),
            native_size=(1920, 1080),
        ) == (960, 540)

    def test_with_pan_offset(self):
        # 玩家 pinch-zoom 後平移了 canvas 內容（pan_offset 是 canvas 視口左上角相對原點的位移）
        # 點 canvas (100, 100)、pan_offset (50, 50)、canvas 跟原生同尺寸
        # → 原生座標 (100+50, 100+50) = (150, 150)
        assert client_to_native_coords(
            client_xy=(100, 100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
            pan_offset=(50, 50),
        ) == (150, 150)

    def test_with_explicit_zoom(self):
        # canvas 顯示原圖 zoom=2（顯示更大），點 canvas (100, 100) →
        # canvas_size 仍 1920×1080，但原圖被 zoom 2x 後只顯示 1/2 區域
        # (100, 100) / zoom=2 → (50, 50) 原生；加 pan_offset (0,0) → (50, 50)
        assert client_to_native_coords(
            client_xy=(100, 100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
            zoom=2.0,
        ) == (50, 50)

    def test_combined_zoom_and_pan(self):
        # canvas 顯示 960×540、zoom 2x、pan_offset (10, 10)
        # 玩家點 canvas (200, 100)
        # step1：把 canvas 座標還原到「未 zoom 的 canvas 座標」= (200, 100) / 2 = (100, 50)
        # step2：把「未 zoom 的 canvas 座標」映射到 native = (100, 50) * (1920/960, 1080/540) = (200, 100)
        # step3：加 pan_offset（在 native 空間加）= (200+10, 100+10) = (210, 110)
        # 簡化：演算法先除 zoom、再 scale、再加 pan
        assert client_to_native_coords(
            client_xy=(200, 100),
            canvas_size=(960, 540),
            native_size=(1920, 1080),
            pan_offset=(10, 10),
            zoom=2.0,
        ) == (210, 110)

    def test_clamps_to_native_bounds(self):
        # 點出界：clamp 到 [0, native_w-1] / [0, native_h-1]
        assert client_to_native_coords(
            client_xy=(-100, -100),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (0, 0)
        assert client_to_native_coords(
            client_xy=(10000, 10000),
            canvas_size=(1920, 1080),
            native_size=(1920, 1080),
        ) == (1919, 1079)
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_protocol.py::TestClientToNativeCoords -v
```

預期：FAIL（function 不存在）。

- [ ] **Step 3: 實作 `client_to_native_coords`**

加到 `miningbot/web_protocol.py`：

```python
def client_to_native_coords(
    client_xy: tuple[float, float],
    canvas_size: tuple[int, int],
    native_size: tuple[int, int],
    pan_offset: tuple[float, float] = (0.0, 0.0),
    zoom: float = 1.0,
) -> tuple[int, int]:
    """把玩家在 canvas 上點的座標還原成遊戲原生解析度座標。

    參數：
    - client_xy：玩家點擊的 canvas 座標（像素）
    - canvas_size：canvas 在瀏覽器中顯示的尺寸（CSS 像素）
    - native_size：遊戲原生解析度（1920×1080）
    - pan_offset：玩家 pinch-zoom 後平移的量（在 native 空間的位移；預設 (0,0)）
    - zoom：玩家 pinch-zoom 的倍數（1.0 = fit canvas；2.0 = 放大 2x）

    順序：先除 zoom（退到未 zoom 座標）→ scale 到 native → 加 pan_offset → clamp。

    pan_offset 的定義是「玩家把原圖往哪個方向拖了多少 native 像素」——client 端
    會在 event handler 裡追蹤，並跟 client_xy 一起送 server。本函式純數學，
    不處理 client 端手勢。

    clamp 到 [0, native_w-1] / [0, native_h-1]：避免玩家平移出界送了負值或超界。
    """
    cx, cy = client_xy
    cw, ch = canvas_size
    nw, nh = native_size
    px, py = pan_offset

    # 先除 zoom：zoom 是「顯示放大」，反向除掉
    unzoomed_x = cx / zoom
    unzoomed_y = cy / zoom

    # canvas → native 比例縮放
    scale_x = nw / cw
    scale_y = nh / ch
    native_x = unzoomed_x * scale_x + px
    native_y = unzoomed_y * scale_y + py

    # clamp
    native_x = max(0, min(native_x, nw - 1))
    native_y = max(0, min(native_y, nh - 1))
    return (int(native_x), int(native_y))
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_protocol.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_protocol.py tests/test_web_protocol.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 3——pinch-zoom 座標還原純函式

client_to_native_coords 處理 zoom + pan + clamp；client 點擊座標即時轉遊戲原生。
支援 pinch-zoom + 拖曳平移的手勢組合。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Config 白名單驗證

**Files:**
- Modify: `miningbot/web_config_whitelist.py`
- Test: `tests/test_web_config_whitelist.py`

**Interfaces:**
- Produces:
  - `WEB_CONFIGURABLE_FIELDS: frozenset[str]`
  - `is_web_configurable(field: str) -> bool`
  - `validate_value(field: str, value) -> bool`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_config_whitelist.py
"""玩家可在網頁改的 Config 欄位白名單。

門檻、ROI、偵測參數完全不在此——AI agent 改 code，不在網頁。"""
import pytest
from miningbot.web_config_whitelist import (
    WEB_CONFIGURABLE_FIELDS,
    is_web_configurable,
    validate_value,
)


class TestWhitelist:
    def test_four_player_facing_fields_in_whitelist(self):
        # spec §6：就這四個
        assert WEB_CONFIGURABLE_FIELDS == frozenset({
            "reentry_mode",
            "reentry_target_layer",
            "reentry_yaw_sample_sweep",
            "sweep_pitch_enabled",
        })

    @pytest.mark.parametrize("field", [
        "reentry_mode", "reentry_target_layer",
        "reentry_yaw_sample_sweep", "sweep_pitch_enabled",
    ])
    def test_whitelisted_field_passes(self, field):
        assert is_web_configurable(field) is True

    @pytest.mark.parametrize("field", [
        "tracker_core_min_area",      # 偵測門檻
        "reentry_game_region",        # ROI
        "discord_bot_token",          # 機密
        "log_dir",                    # 系統路徑
        "reentry_teleport_diff",      # 偵測門檻
        "",        "nonexistent_field",
    ])
    def test_non_whitelisted_field_rejected(self, field):
        assert is_web_configurable(field) is False


class TestValidateValue:
    @pytest.mark.parametrize("value", ["off", "remote", "auto"])
    def test_reentry_mode_valid_values(self, value):
        assert validate_value("reentry_mode", value) is True

    @pytest.mark.parametrize("value", ["garbage", "", "OFF", "Remote", 123, None, True])
    def test_reentry_mode_invalid_values(self, value):
        assert validate_value("reentry_mode", value) is False

    @pytest.mark.parametrize("value", ["Mantle Layer", "Core Layer", ""])
    def test_reentry_target_layer_accepts_string(self, value):
        # 層名是任意字串，由 game_data 提供選項；空字串也允許（fallback）
        assert validate_value("reentry_target_layer", value) is True

    @pytest.mark.parametrize("value", [123, None, True, ["list"]])
    def test_reentry_target_layer_rejects_non_string(self, value):
        assert validate_value("reentry_target_layer", value) is False

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_fields_accept_bool(self, value):
        assert validate_value("reentry_yaw_sample_sweep", value) is True
        assert validate_value("sweep_pitch_enabled", value) is True

    @pytest.mark.parametrize("value", [0, 1, "true", None, "yes"])
    def test_bool_fields_reject_non_bool(self, value):
        assert validate_value("reentry_yaw_sample_sweep", value) is False
        assert validate_value("sweep_pitch_enabled", value) is False

    def test_non_whitelisted_field_always_invalid(self):
        assert validate_value("tracker_core_min_area", 80) is False
        assert validate_value("nonexistent", "x") is False
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_config_whitelist.py -v
```

預期：FAIL（constant / function 不存在）。

- [ ] **Step 3: 實作**

```python
# miningbot/web_config_whitelist.py
"""玩家可在網頁改的 Config 欄位白名單 + 值型別驗證。

spec §6：玩家只動 4 個「遊戲 play style」欄位，門檻 / ROI / 偵測參數完全不暴露。
AI agent 改這些是直接 edit config.py（Claude session 內），跟網頁無關。
"""
from typing import Any


WEB_CONFIGURABLE_FIELDS: frozenset[str] = frozenset({
    "reentry_mode",
    "reentry_target_layer",
    "reentry_yaw_sample_sweep",
    "sweep_pitch_enabled",
})

_REENTRY_MODE_VALUES = frozenset({"off", "remote", "auto"})


def is_web_configurable(field: str) -> bool:
    """欄位是否在玩家可改白名單內。"""
    return field in WEB_CONFIGURABLE_FIELDS


def validate_value(field: str, value: Any) -> bool:
    """欄位+值組合是否合法。

    非白名單欄位一律 False（即使值看起來對）。
    白名單欄位的值驗證規則：
    - reentry_mode：只能是 "off"/"remote"/"auto"
    - reentry_target_layer：任意字串（含空字串 fallback）
    - 兩個 toggle：嚴格 bool（不收 0/1/"true"）
    """
    if not is_web_configurable(field):
        return False
    if field == "reentry_mode":
        return value in _REENTRY_MODE_VALUES
    if field == "reentry_target_layer":
        return isinstance(value, str)
    # 兩個 bool toggle
    # 注意：isinstance(True, int) 是 True，所以反過來要先檢查 bool
    return isinstance(value, bool)
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_config_whitelist.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_config_whitelist.py tests/test_web_config_whitelist.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 4——Config 白名單驗證純函式

玩家只動 reentry_mode / reentry_target_layer / reentry_yaw_sample_sweep /
sweep_pitch_enabled 四個欄位；門檻、ROI、偵測參數完全不收。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: race routing key + PendingReplies（先到先贏）

**Files:**
- Modify: `miningbot/web_ipc.py`
- Test: `tests/test_web_ipc.py`

**Interfaces:**
- Produces:
  - `routing_key(flow: str, episode_id: str) -> str`（例：`"harvest:007"`）
  - `reply_matches(key_a: str, key_b: str) -> bool`
  - `class PendingReplies`：`push(key, reply)` / `pop(key) -> reply | None` / `pop_any_expired(now, ttl_s) -> list`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_ipc.py
"""race routing key 與 PendingReplies（先到先贏規則）。"""
import pytest
from miningbot.web_ipc import routing_key, reply_matches, PendingReplies


class TestRoutingKey:
    def test_harvest_episode(self):
        assert routing_key("harvest", "007") == "harvest:007"

    def test_reentry_attempt(self):
        assert routing_key("reentry", "attempt_3") == "reentry:attempt_3"

    def test_empty_episode_id_still_formatted(self):
        # 防禦性：不該出現，但格式仍可建
        assert routing_key("harvest", "") == "harvest:"


class TestReplyMatches:
    def test_same_key_matches(self):
        assert reply_matches("harvest:007", "harvest:007") is True

    def test_different_episode_same_flow_no_match(self):
        # bot 等 harvest:007，送來 harvest:008 → 不匹配
        assert reply_matches("harvest:008", "harvest:007") is False

    def test_different_flow_no_match(self):
        assert reply_matches("reentry:attempt_3", "harvest:007") is False


class TestPendingRepliesFirstWins:
    def test_first_push_wins(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100, "y": 200})
        q.push("harvest:007", {"x": 999, "y": 999})  # 太晚，丟棄
        reply = q.pop("harvest:007")
        assert reply == {"x": 100, "y": 200}

    def test_second_push_for_same_key_returns_none_immediately(self):
        # spec §8：同 key 第二個 reply 進來，立刻丟棄（不排隊）
        q = PendingReplies()
        assert q.push("harvest:007", {"x": 100, "y": 200}) is True   # 第一個收下
        assert q.push("harvest:007", {"x": 999, "y": 999}) is False  # 第二個拒絕

    def test_pop_returns_none_when_empty(self):
        q = PendingReplies()
        assert q.pop("harvest:007") is None

    def test_pop_clears_slot(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100, "y": 200})
        assert q.pop("harvest:007") == {"x": 100, "y": 200}
        # 再 pop 一次也空
        assert q.pop("harvest:007") is None
        # pop 後可再 push 新 reply
        assert q.push("harvest:007", {"x": 300, "y": 400}) is True

    def test_different_keys_independent(self):
        q = PendingReplies()
        q.push("harvest:007", {"x": 100})
        q.push("reentry:attempt_3", {"x": 200})
        assert q.pop("harvest:007") == {"x": 100}
        assert q.pop("reentry:attempt_3") == {"x": 200}

    def test_pop_any_expired_removes_old_replies(self):
        # 用 monotonic clock injection 測過期
        q = PendingReplies()
        q._now = lambda: 0.0  # 注入時鐘
        q.push("harvest:007", {"x": 100}, ttl_s=30.0)
        q._now = lambda: 100.0  # 時間推 100s
        expired = q.pop_any_expired()
        assert len(expired) == 1
        assert expired[0][0] == "harvest:007"
        assert expired[0][1] == {"x": 100}
        # 過期後 slot 清空
        assert q.pop("harvest:007") is None

    def test_pop_any_expired_keeps_fresh(self):
        q = PendingReplies()
        q._now = lambda: 0.0
        q.push("harvest:007", {"x": 100}, ttl_s=30.0)
        q._now = lambda: 10.0  # 還新鮮
        assert q.pop_any_expired() == []
        assert q.pop("harvest:007") == {"x": 100}
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_ipc.py -v
```

預期：FAIL。

- [ ] **Step 3: 實作 routing key + PendingReplies**

```python
# miningbot/web_ipc.py
"""race routing key、PendingReplies（先到先贏）、FallbackState（Task 6）。

spec §8 race 規則：bot 等玩家介入時，第一個進來的 reply（web 或 discord 任一）
鎖定，其他同 routing key 的 reply 立刻丟棄。「先到先贏，後到丟棄」。
"""
import time
from typing import Any, Callable


def routing_key(flow: str, episode_id: str) -> str:
    """flow + episode_id 組成 routing key。

    例：routing_key("harvest", "007") → "harvest:007"
        routing_key("reentry", "attempt_3") → "reentry:attempt_3"
    """
    return f"{flow}:{episode_id}"


def reply_matches(key_a: str, key_b: str) -> bool:
    """兩個 routing key 是否匹配（嚴格相等）。"""
    return key_a == key_b


class PendingReplies:
    """等待消費的 reply 佇列（先到先贏）。

    - push(key, reply)：同 key 第一個收下（回 True）；同 key 後續立刻丟棄（回 False）
    - pop(key)：取出該 key 的 reply（取出後 slot 清空，可 push 新 reply）；無則 None
    - pop_any_expired()：清掉所有過期 reply，回 [(key, reply), ...]

    時間透過 `_now` 注入（測試可替換）；production 用 time.monotonic。
    reply 結構由呼叫端決定（dict / dataclass 都行）。

    執行緒安全：本類別的 push/pop 由 WebIPC thread（單一 consumer 視角）呼叫，
    bot 主迴圈另一個 thread 只透過 pop(key) 讀取。為了 thread-safe，所有動作
    都在 instance lock 內做。WebIPC thread push、bot thread pop 是經典 SPSC，
    lock 仍加保守邊際。
    """

    def __init__(self):
        self._slots: dict[str, tuple[Any, float, float]] = {}  # key → (reply, push_time, ttl)
        self._lock = __import__("threading").Lock()
        self._now: Callable[[], float] = time.monotonic

    def push(self, key: str, reply: Any, ttl_s: float = 60.0) -> bool:
        """同 key 第一個收下；後到的立刻拒絕（spec §8「先到先贏，後到丟棄」）。

        回 True = 收下；False = 拒絕（已有人或 slot 未清）。
        """
        with self._lock:
            if key in self._slots:
                return False
            self._slots[key] = (reply, self._now(), ttl_s)
            return True

    def pop(self, key: str) -> Any | None:
        """取出該 key 的 reply（清空 slot）；無則 None。"""
        with self._lock:
            entry = self._slots.pop(key, None)
            return entry[0] if entry is not None else None

    def pop_any_expired(self) -> list[tuple[str, Any]]:
        """清掉所有過期 reply；回 [(key, reply), ...]。"""
        now = self._now()
        expired = []
        with self._lock:
            for key in list(self._slots.keys()):
                reply, pushed_at, ttl = self._slots[key]
                if now - pushed_at >= ttl:
                    expired.append((key, reply))
                    del self._slots[key]
        return expired
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_ipc.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_ipc.py tests/test_web_ipc.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 5——race routing key + PendingReplies（先到先贏）

bot 等玩家介入時，第一個進來的 reply 鎖定；同 routing_key 後到的立刻丟棄。
pop_any_expired 支援 client 斷線後 reply 自動清掉。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: FallbackState + grace period

**Files:**
- Modify: `miningbot/web_ipc.py`
- Test: `tests/test_web_ipc.py`（加新 class）

**Interfaces:**
- Produces:
  - `class FallbackState`：`client_connected(now)` / `client_disconnected(now)` / `is_fallback(now, grace_s) -> bool` / `client_count -> int`

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_web_ipc.py`：

```python
from miningbot.web_ipc import FallbackState


class TestFallbackState:
    def test_initial_state_is_fallback(self):
        # 啟動時 0 client → fallback
        s = FallbackState()
        s._now = lambda: 0.0
        assert s.is_fallback(now=0.0, grace_s=30.0) is True

    def test_client_connected_exits_fallback(self):
        s = FallbackState()
        s.client_connected(now=0.0)
        assert s.is_fallback(now=0.0, grace_s=30.0) is False
        assert s.client_count == 1

    def test_disconnect_starts_grace_not_immediate_fallback(self):
        s = FallbackState()
        s.client_connected(now=0.0)
        s.client_disconnected(now=10.0)
        # grace 還沒過
        assert s.is_fallback(now=20.0, grace_s=30.0) is False
        assert s.client_count == 0

    def test_grace_expires_into_fallback(self):
        s = FallbackState()
        s.client_connected(now=0.0)
        s.client_disconnected(now=10.0)
        # grace 30s 從 disconnect 起算 → 10+30=40s 過期
        assert s.is_fallback(now=40.0, grace_s=30.0) is True

    def test_reconnect_during_grace_resets(self):
        s = FallbackState()
        s.client_connected(now=0.0)
        s.client_disconnected(now=10.0)
        s.client_connected(now=20.0)  # grace 內重連
        assert s.is_fallback(now=25.0, grace_s=30.0) is False
        assert s.client_count == 1

    def test_multiple_clients_only_last_disconnect_triggers_grace(self):
        s = FallbackState()
        s.client_connected(now=0.0)
        s.client_connected(now=1.0)  # 兩個 client
        s.client_disconnected(now=10.0)  # 走一個，還有一個
        assert s.is_fallback(now=100.0, grace_s=30.0) is False
        assert s.client_count == 1
        s.client_disconnected(now=110.0)  # 全走
        assert s.is_fallback(now=115.0, grace_s=30.0) is False  # grace 內
        assert s.is_fallback(now=150.0, grace_s=30.0) is True

    def test_client_count_never_negative(self):
        s = FallbackState()
        # 沒連過就 disconnect 不該讓 count 變負
        s.client_disconnected(now=0.0)
        assert s.client_count == 0
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_ipc.py::TestFallbackState -v
```

預期：FAIL。

- [ ] **Step 3: 實作 FallbackState**

加到 `miningbot/web_ipc.py`：

```python
class FallbackState:
    """WebSocket client 連線數 + grace period → fallback 模式開關。

    spec §8：連線 0 → ≥1 立刻脫離 fallback；≥1 → 0 起算 grace period
    （預設 30s，防玩家分頁重新整理抖動）；grace 過後切回 fallback。

    client_count 由 WebSocket endpoint 的 connect/disconnect callback 維護。
    is_fallback 由 bot 主迴圈在 NEEDS_HUMAN / awaiting_fine / 點傳送板 等
    「準備發 Discord 訊息」前查詢。
    """

    def __init__(self):
        self._client_count = 0
        self._last_disconnect_at: float | None = None
        self._lock = __import__("threading").Lock()
        self._now: Callable[[], float] = time.monotonic

    @property
    def client_count(self) -> int:
        with self._lock:
            return self._client_count

    def client_connected(self, now: float | None = None) -> None:
        """WebSocket on_connect 呼叫。連上即清 grace（不論之前是否倒數中）。"""
        with self._lock:
            self._client_count += 1
            self._last_disconnect_at = None

    def client_disconnected(self, now: float | None = None) -> None:
        """WebSocket on_disconnect 呼叫。最後一個 client 走才起算 grace。"""
        with self._lock:
            if self._client_count > 0:
                self._client_count -= 1
            if self._client_count == 0:
                self._last_disconnect_at = now if now is not None else self._now()

    def is_fallback(self, now: float | None = None, grace_s: float = 30.0) -> bool:
        """目前是否該走 fallback（無 web 連線有效）。"""
        with self._lock:
            if self._client_count > 0:
                return False
            if self._last_disconnect_at is None:
                # 從未連過 → fallback
                return True
            current = now if now is not None else self._now()
            return (current - self._last_disconnect_at) >= grace_s
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_ipc.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_ipc.py tests/test_web_ipc.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 6——FallbackState + 30s grace period

WebSocket client 連線數追蹤；最後一個 client 斷線起算 grace period，
防玩家分頁重新整理抖動切回 Discord fallback 模式。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: WebEventSink（事件 → 廣播）

**Files:**
- Modify: `miningbot/web_sink.py`
- Test: `tests/test_web_sink.py`

**Interfaces:**
- Consumes: `EventLog` 的事件 record（既有）
- Produces:
  - `class WebEventSink`：`__init__(broadcast_callback)`、`__call__(rec) -> None`
  - `format_event_for_web(rec) -> WebMessage | None`（哪些事件要送、內容長相）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_sink.py
"""WebEventSink：EventLog 事件 → WebSocket 廣播純函式。"""
import pytest
from miningbot.web_sink import WebEventSink, format_event_for_web


class TestFormatEventForWeb:
    def test_needs_human_event_formats(self):
        # 模擬 EventLog record（看 miningbot.events 結構）
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "稀有礦未自動命中", "harvest_id": "007"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.type == "event"
        assert msg.payload["event"] == "NEEDS_HUMAN"
        assert msg.payload["harvest_id"] == "007"
        assert msg.payload["flow"] == "harvest"

    def test_harvest_success_formats(self):
        rec = type("Rec", (), {
            "type": "HARVEST_SUCCESS",
            "meta": {"mineral": "Mythic Tin", "harvest_id": "007"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["event"] == "HARVEST_SUCCESS"
        assert msg.payload["mineral"] == "Mythic Tin"

    def test_reentry_start_formats_with_attempt(self):
        rec = type("Rec", (), {
            "type": "REENTRY_START",
            "meta": {"attempts": 2},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["flow"] == "reentry"
        assert msg.payload["attempt"] == 2

    def test_unknown_event_returns_none(self):
        # 不在白名單的事件（PAUSED / RESUMED / 心跳）不送，避免洗 web client
        rec = type("Rec", (), {"type": "PAUSED", "meta": {}})()
        assert format_event_for_web(rec) is None

    def test_event_meta_carried_through(self):
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007", "rotation_hint": "（試試方位 3）"},
        })()
        msg = format_event_for_web(rec)
        assert msg is not None
        assert msg.payload["reason"] == "X"
        assert msg.payload["rotation_hint"] == "（試試方位 3）"


class TestWebEventSinkCall:
    def test_sink_calls_broadcast_for_relevant_event(self):
        calls = []
        sink = WebEventSink(broadcast_callback=lambda msg: calls.append(msg))
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007"},
        })()
        sink(rec)
        assert len(calls) == 1
        assert calls[0].payload["event"] == "NEEDS_HUMAN"

    def test_sink_skips_irrelevant_event(self):
        calls = []
        sink = WebEventSink(broadcast_callback=lambda msg: calls.append(msg))
        rec = type("Rec", (), {"type": "PAUSED", "meta": {}})()
        sink(rec)
        assert calls == []

    def test_sink_broadcast_exception_does_not_raise(self):
        # 廣播失敗（client 斷線等）不該炸主迴圈
        def explode(msg):
            raise RuntimeError("client gone")
        sink = WebEventSink(broadcast_callback=explode)
        rec = type("Rec", (), {
            "type": "NEEDS_HUMAN",
            "meta": {"reason": "X", "harvest_id": "007"},
        })()
        sink(rec)  # 不該丟例外
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_sink.py -v
```

預期：FAIL。

- [ ] **Step 3: 實作 WebEventSink + format_event_for_web**

```python
# miningbot/web_sink.py
"""WebEventSink：把 EventLog 事件廣播給所有 WebSocket client。

跟 notify.py 的 DiscordSink 平行——同一份事件來源，兩個 sink 各自消化。
不影響 Discord 通知路徑。
"""
import logging
from typing import Callable

from miningbot.web_protocol import WebMessage


_log = logging.getLogger(__name__)


# 哪些事件要送 web client（同 Discord notify 的 _TEMPLATES 概念，但 web 不洗版，
# 可以更寬鬆。先放跟 Discord 一樣的「玩家該知道」集合）。
# flow 從事件 type 推導：harvest 系（NEEDS_HUMAN 在採集流程中觸發）/ reentry 系。
_RELEVANT_EVENTS = frozenset({
    "RARE_FOUND",
    "TRACKER_FOUND",
    "HARVEST_SUCCESS",
    "NEEDS_HUMAN",
    "SPAWN_CHILL",
    "MINE_RESET",
    "REENTRY_START",
    "REENTRY_SUCCESS",
})

_HARVEST_EVENTS = frozenset({
    "RARE_FOUND", "TRACKER_FOUND", "HARVEST_SUCCESS", "NEEDS_HUMAN", "SPAWN_CHILL",
})
_REENTRY_EVENTS = frozenset({"MINE_RESET", "REENTRY_START", "REENTRY_SUCCESS"})


def format_event_for_web(rec) -> WebMessage | None:
    """EventLog record → WebMessage；不需通知的事件回 None。

    flow 推導：HARVEST 系 → "harvest"；REENTRY 系 → "reentry"。
    NEEDS_HUMAN 預設 harvest（採集流程最常見）；reentry 的 NEEDS_HUMAN 未來可用
    meta["flow"] 覆寫（保留擴充點，目前不實作）。

    沿用 notify.py format_message 的精神：只挑玩家該知道的，避免洗 web client。
    """
    rtype = getattr(rec, "type", None)
    if rtype not in _RELEVANT_EVENTS:
        return None
    meta = getattr(rec, "meta", {}) or {}
    flow = "reentry" if rtype in _REENTRY_EVENTS else "harvest"
    payload = {"event": rtype, "flow": flow}
    payload.update(meta)
    return WebMessage(type="event", payload=payload)


class WebEventSink:
    """EventLog sink：把事件廣播給所有 WebSocket client。

    broadcast_callback 由 WebIPC thread 注入——實際廣播動作（iterate 連線、send）
    在 thread 內做，避免主迴圈接觸 WebSocket。

    廣播例外只 log 不丟——比照 notify.make_discord_sink 的「失敗只回報，不中斷」。
    """

    def __init__(self, broadcast_callback: Callable[[WebMessage], None]):
        self._broadcast = broadcast_callback

    def __call__(self, rec) -> None:
        msg = format_event_for_web(rec)
        if msg is None:
            return
        try:
            self._broadcast(msg)
        except Exception as e:
            # 廣播失敗（client 斷線、連線例外）只記 log，不傳染主迴圈
            _log.warning("WebEventSink broadcast 失敗: %s", e)
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_sink.py -v
```

預期：全綠。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_sink.py tests/test_web_sink.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 7——WebEventSink 把事件廣播給所有 WebSocket client

跟 DiscordSink 平行；同一份事件來源兩個 sink 各自消化。廣播失敗只 log 不丟，
比照 notify.make_discord_sink 既有「失敗只回報」慣例。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: FastAPI server + WebSocket endpoint（連線 + 命令 push）

**Files:**
- Modify: `miningbot/web_server.py`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `PendingReplies`、`FallbackState`、`parse_message`（來自先前 task）
- Produces:
  - `create_app(pending, fallback, broadcast_callback) -> fastapi.FastAPI`
  - `class WebIPCThread`：`start()` / `stop()` / `simulate_client_command(msg_dict)`（測試用）

**注意：** 這個 task 範圍只做「連線建立 + 命令 parse + push queue + client count 維護」；
事件廣播與截圖 push 在 Task 9 做。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_server.py
"""WebIPC server 整合測試：WebSocket 連線 + 命令 push + client count。"""
import json
import pytest
from fastapi.testclient import TestClient

from miningbot.web_ipc import PendingReplies, FallbackState
from miningbot.web_server import create_app


@pytest.fixture
def app_parts():
    pending = PendingReplies()
    fallback = FallbackState()
    broadcast_calls = []
    broadcast_callback = lambda msg: broadcast_calls.append(msg)
    app = create_app(pending, fallback, broadcast_callback)
    return app, pending, fallback, broadcast_calls


def test_health_endpoint(app_parts):
    app, *_ = app_parts
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_websocket_connect_increments_client_count(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        assert fallback.client_count == 1
    assert fallback.client_count == 0


def test_websocket_command_pushes_to_pending(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        client.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "fire_at", "flow": "harvest",
                        "harvest_id": "007", "x": 851, "y": 189},
        }))
        # 給 server 一點時間處理
        import time; time.sleep(0.05)
    # 連線斷了之後 pending 應該有 reply（routing key harvest:007）
    reply = pending.pop("harvest:007")
    assert reply is not None
    assert reply["cmd"] == "fire_at"
    assert reply["x"] == 851


def test_websocket_invalid_message_does_not_crash(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        client.send_text("not json")  # 壞訊息
        client.send_text(json.dumps({"missing": "type"}))  # 缺欄位
        # 連線仍活著
        client.send_text(json.dumps({
            "type": "command",
            "payload": {"cmd": "pause"},
        }))
        import time; time.sleep(0.05)
    # 壞訊息沒進 queue，正常的進了
    # pause 沒有 routing key（不是 fire/click）→ 用 None episode 推導為 "control" key
    # 這裡先驗證不 crash；routing key 細節看主迴圈整合 task


def test_websocket_disconnect_decrements_client_count(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        assert fallback.client_count == 1
    assert fallback.client_count == 0


def test_multiple_clients_counted(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"), \
         client.websocket_connect("/ws"):
        assert fallback.client_count == 2
    assert fallback.client_count == 0
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_server.py -v
```

預期：FAIL（`create_app` 不存在）。

- [ ] **Step 3: 實作 create_app**

```python
# miningbot/web_server.py
"""WebIPC server：FastAPI app + WebSocket endpoint。

WebIPC thread（Task 10 整合進 main.py）跑 uvicorn server；client 連線維護
FallbackState.client_count；命令透過 parse_message 解析後 push 進 PendingReplies。

事件廣播與截圖 push 在 Task 9 加。
"""
import logging
from typing import Callable

import fastapi
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from miningbot.web_protocol import WebMessage, parse_message, serialize_message
from miningbot.web_ipc import PendingReplies, FallbackState


_log = logging.getLogger(__name__)


def create_app(
    pending: PendingReplies,
    fallback: FallbackState,
    broadcast_callback: Callable[[WebMessage], None],
) -> FastAPI:
    """建 FastAPI app。

    broadcast_callback：事件到達時呼叫（WebEventSink 用同一個 callback）。
    本 task 不實作廣播，callback 在 Task 9 才接到 WebSocket 連線池。
    """
    app = FastAPI(title="MiningBot Web IPC")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
        try:
            while True:
                text = await websocket.receive_text()
                msg = parse_message(text)
                if msg is None:
                    # 壞訊息不 crash，記 log
                    _log.warning("web: 收到不合法訊息，忽略: %r", text[:200])
                    continue
                if msg.type == "command":
                    _handle_command(msg.payload, pending)
                # event type 由 server 發、client 收；client 不該送 event，忽略
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning("web: WebSocket 連線例外: %s", e)
        finally:
            fallback.client_disconnected()

    return app


def _handle_command(payload: dict, pending: PendingReplies) -> None:
    """把 command payload 推進 PendingReplies（用 flow + id 算 routing key）。

    payload 結構（spec §8）：
    - fire_at / reentry_click：必有 flow + harvest_id（或 attempt_id）+ (x, y)
    - config_set：必有 field + value（白名單驗證在 main.py 整合時做）
    - pause / resume / request_frame：控制類，無 routing key，用 "control:*"

    若 payload 缺 routing key 必要欄位，記 log 不 push（防護）。
    """
    cmd = payload.get("cmd")
    if cmd in ("fire_at", "reentry_click"):
        flow = payload.get("flow")
        ep_id = payload.get("harvest_id") or payload.get("attempt_id")
        if not flow or not ep_id:
            _log.warning("web: %s 缺 flow/episode_id，丟棄: %r", cmd, payload)
            return
        key = f"{flow}:{ep_id}"
    else:
        # 控制類：直接用 cmd 名當 key（不参與 race，主迴圈 safe point 直接讀）
        key = f"control:{cmd}"
    pending.push(key, payload)
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_server.py -v
```

預期：全綠。`time.sleep(0.05)` 給 server 時間處理 command（async endpoint）。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_server.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 8——FastAPI server + WebSocket endpoint

client 連線維護 FallbackState；命令 parse 後 push 進 PendingReplies。
壞訊息只 log 不 crash；控制類命令（pause/resume/request_frame）用 control:* routing key。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 事件廣播 + 截圖 push + fallback 切換整合

**Files:**
- Modify: `miningbot/web_server.py`
- Test: `tests/test_web_server.py`（加新測試）

**Interfaces:**
- Produces:
  - `class ConnectionRegistry`：`add(ws)` / `remove(ws)` / `broadcast(msg: WebMessage)` / `broadcast_binary(data: bytes)`
  - `create_app` 擴充：WebSocket endpoint 註冊/移除連線；broadcast_callback 注入 registry.broadcast

- [ ] **Step 1: 寫失敗測試**

加到 `tests/test_web_server.py`：

```python
import asyncio
from miningbot.web_protocol import WebMessage


def test_event_broadcast_reaches_connected_client(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # 給連線建立時間
        import time; time.sleep(0.05)
        # 模擬 bot 推一個事件
        app.state.broadcast(WebMessage(type="event", payload={"event": "NEEDS_HUMAN"}))
        received = ws.receive_text()
        msg = json.loads(received)
        assert msg["type"] == "event"
        assert msg["payload"]["event"] == "NEEDS_HUMAN"


def test_broadcast_only_reaches_current_clients(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    # 沒連線，broadcast 不該炸
    app.state.broadcast(WebMessage(type="event", payload={"event": "X"}))
    # 連一個、broadcast、收
    with client.websocket_connect("/ws") as ws:
        import time; time.sleep(0.05)
        app.state.broadcast(WebMessage(type="event", payload={"event": "Y"}))
        received = ws.receive_text()
        assert json.loads(received)["payload"]["event"] == "Y"


def test_broadcast_failure_does_not_raise(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        import time; time.sleep(0.05)
    # 連線已斷；broadcast 不該丟例外
    app.state.broadcast(WebMessage(type="event", payload={"event": "Z"}))


def test_fallback_true_when_no_clients(app_parts):
    app, pending, fallback, _ = app_parts
    client = TestClient(app)
    assert fallback.is_fallback(now=None, grace_s=0.0) is True  # grace=0 立刻 fallback
    with client.websocket_connect("/ws"):
        assert fallback.is_fallback(now=None, grace_s=0.0) is False
    assert fallback.is_fallback(now=None, grace_s=0.0) is True
```

- [ ] **Step 2: 跑測試，確認失敗**

```
uv run pytest tests/test_web_server.py -v
```

預期：FAIL（`app.state.broadcast` 不存在）。

- [ ] **Step 3: 擴充 server，加 ConnectionRegistry 與 broadcast**

修改 `miningbot/web_server.py`：

```python
# 在檔頭加 import
import asyncio
from contextlib import suppress


class ConnectionRegistry:
    """當下 WebSocket 連線池；thread-safe（WebIPC thread 跟事件 sink 都會呼叫）。

    broadcast 是 async（WebSocket send_text 是 async）；但事件 sink 是同步呼叫。
    解法：用 asyncio.run_coroutine_threadsafe 把廣播丟到 server 的 event loop，
    或同步 collect send coroutine 在下次 loop tick 跑。

    採用：維護 WebSocket 物件清單；broadcast 用 asyncio.run_coroutine_threadsafe
    把「逐一 send_text」的 coroutine 丟進 server 的 event loop。
    """

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = __import__("threading").Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """WebIPC thread 啟動後注入 event loop（broadcast 用）。"""
        self._loop = loop

    def add(self, ws: WebSocket) -> None:
        with self._lock:
            self._connections.add(ws)

    def remove(self, ws: WebSocket) -> None:
        with self._lock:
            self._connections.discard(ws)

    def broadcast(self, msg: WebMessage) -> None:
        """同步呼叫介面（事件 sink 用）；內部丟進 event loop 跑。"""
        if self._loop is None:
            return  # server 還沒跑起來
        text = serialize_message(msg)
        asyncio.run_coroutine_threadsafe(self._broadcast_async(text), self._loop)

    async def _broadcast_async(self, text: str) -> None:
        with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception as e:
                _log.warning("web: broadcast send 失敗（連線可能已斷）: %s", e)
                self.remove(ws)

    def broadcast_binary(self, data: bytes) -> None:
        """截圖 push 用（Task 10 在 main.py 裡接）。"""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast_binary_async(data), self._loop)

    async def _broadcast_binary_async(self, data: bytes) -> None:
        with self._lock:
            conns = list(self._connections)
        for ws in conns:
            try:
                await ws.send_bytes(data)
            except Exception as e:
                _log.warning("web: binary broadcast 失敗: %s", e)
                self.remove(ws)
```

修改 `create_app`：

```python
def create_app(pending, fallback, broadcast_callback) -> FastAPI:
    app = FastAPI(title="MiningBot Web IPC")
    registry = ConnectionRegistry()
    app.state.registry = registry
    # broadcast_callback（給 WebEventSink 用）指到 registry.broadcast
    # 但 broadcast_callback 參數保留，測試可注入自訂；沒注入就用 registry.broadcast
    if broadcast_callback is None:
        broadcast_callback = registry.broadcast
    app.state.broadcast = broadcast_callback  # 測試直接呼叫

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        await websocket.accept()
        fallback.client_connected()
        registry.add(websocket)
        try:
            while True:
                text = await websocket.receive_text()
                msg = parse_message(text)
                if msg is None:
                    _log.warning("web: 收到不合法訊息，忽略: %r", text[:200])
                    continue
                if msg.type == "command":
                    _handle_command(msg.payload, pending)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            _log.warning("web: WebSocket 連線例外: %s", e)
        finally:
            registry.remove(websocket)
            fallback.client_disconnected()

    return app
```

更新 fixture（fixture 預設用 registry broadcast）：

```python
# tests/test_web_server.py fixture 改：
@pytest.fixture
def app_parts():
    pending = PendingReplies()
    fallback = FallbackState()
    app = create_app(pending, fallback, broadcast_callback=None)
    # 模擬 WebIPC thread 已注入 loop：用 TestClient 的 event loop
    # TestClient 跑 app 時 loop 在內部，需手動設
    registry = app.state.registry
    # 用一個新 loop 跑 broadcast（測試中 run_coroutine_threadsafe 需要 loop）
    loop = asyncio.new_event_loop()
    registry.set_loop(loop)
    # 跑 loop 在背景 thread
    import threading
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield app, pending, fallback, []
    loop.call_soon_threadsafe(loop.stop)
```

- [ ] **Step 4: 跑測試，確認通過**

```
uv run pytest tests/test_web_server.py -v
```

預期：全綠。`time.sleep` 給 asyncio 處理廣播。

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_server.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 9——事件廣播給所有 WebSocket client

ConnectionRegistry 維護連線池；broadcast 用 asyncio.run_coroutine_threadsafe
跨 thread（事件 sink 同步呼叫 → server event loop 跑）。廣播失敗（連線已斷）
只 log 不丟，並把壞連線移出 registry。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: main.py 整合（thread 啟動 + safe point 消費 + sink 註冊）

**Files:**
- Modify: `miningbot/main.py`（啟動 WebIPC thread、safe point 消費 `web_pending`、`EventLog.add_sink(WebEventSink)`）

**Interfaces:**
- Consumes: `create_app`、`PendingReplies`、`FallbackState`、`WebEventSink`（來自 P1 先前 task）
- Produces: bot 啟動跑 web server；bot 主迴圈 safe point 可消費 web_pending

**注意：** 這個 task 是整合性，需要先讀 `main.py` 既有結構，找：
- bot 啟動 Discord polling thread 的位置（WebIPC thread 比照辦理）
- bot 主迴圈 safe point（消費 Discord pending 的地方）
- `EventLog.add_sink` 既有呼叫位置

- [ ] **Step 1: 讀 main.py 找整合點**

```
rg -n "discord.*thread|_discord_polling|pending.*queue|EventLog|add_sink" miningbot/main.py
```

記錄三個位置：
- A: Discord polling thread 啟動（在 `__init__` 或 `run` 方法）
- B: 主迴圈 safe point 消費 Discord pending（每 tick 或狀態切換間）
- C: `EventLog.add_sink` 呼叫（Discord sink 註冊處）

- [ ] **Step 2: 寫失敗測試**

由於 main.py 是大檔，整合測試用 fake bot 模式。加到 `tests/test_web_server.py`：

```python
def test_webipc_thread_starts_and_serves_websocket(app_parts, monkeypatch):
    """WebIPC thread 啟動後能接受 WebSocket 連線（用 uvicorn 跑實際 port）。"""
    import threading
    import socket
    from miningbot.web_server import WebIPCThread

    pending = PendingReplies()
    fallback = FallbackState()
    thread = WebIPCThread(pending=pending, fallback=fallback, port=0)  # 0 = 隨機 port
    thread.start()
    try:
        # 等 thread 起來
        import time; time.sleep(0.5)
        assert thread.is_alive()
        assert thread.actual_port > 0
        # 連連線測試
        client = TestClient(thread.app)
        with client.websocket_connect("/ws"):
            assert fallback.client_count == 1
    finally:
        thread.stop()
        thread.join(timeout=2.0)


def test_main_loop_consumes_web_pending_at_safe_point(monkeypatch):
    """bot 主迴圈 safe point 會 pop web_pending 並執行對應動作。

    用一個 minimal fake bot 驗證迴圈邏輯，不啟動完整 bot。
    """
    # 這個測試需要看 main.py 的迴圈結構來設計 fake bot
    # 暫時放 skip，等 Step 3 確認 main.py 迴圈結構後補具體測試
    pytest.skip("具體 fake bot 設計依 main.py 結構；Step 3 後回頭補")
```

- [ ] **Step 3: 跑測試，確認第一個 PASS / 第二個 skip**

```
uv run pytest tests/test_web_server.py::test_webipc_thread_starts_and_serves_websocket tests/test_web_server.py::test_main_loop_consumes_web_pending_at_safe_point -v
```

預期：第一個 FAIL（`WebIPCThread` 不存在）；第二個 skip。

- [ ] **Step 4: 實作 WebIPCThread class**

加到 `miningbot/web_server.py`：

```python
import threading
import uvicorn


class WebIPCThread:
    """WebIPC daemon thread：跑 uvicorn server。

    port=0：作業系統隨機分配；actual_port 在 server 啟動後填。
    bot 啟動時 start()，關機時 stop()。
    """

    def __init__(
        self,
        pending: PendingReplies,
        fallback: FallbackState,
        port: int = 8765,
        host: str = "127.0.0.1",
    ):
        self.pending = pending
        self.fallback = fallback
        self.port = port
        self.host = host
        self._thread: threading.Thread | None = None
        self._server: uvicorn.Server | None = None
        self.actual_port: int = 0
        self.app = create_app(pending, fallback, broadcast_callback=None)

    def start(self) -> None:
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",  # uvicorn 預設 info 太吵
        )
        self._server = uvicorn.Server(config)
        # 注入 registry 的 event loop（在 server 跑起來後）
        # 用 startup event hook
        original_lifespan = config.lifespan

        async def _patched_lifespan(scope, receive, send):
            await original_lifespan(scope, receive, send)
            # server 起來後，loop 已經在跑
            loop = asyncio.get_event_loop()
            self.app.state.registry.set_loop(loop)
            # 取實際 port（port=0 從 server.servers[0].sockets[0]）
            for srv in self._server.servers:
                for sock in srv.sockets:
                    self.actual_port = sock.getsockname()[1]
                    break

        config.lifespan = _patched_lifespan

        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="web-ipc"
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
```

- [ ] **Step 5: 整合進 main.py**

**這一步需要根據 Step 1 找到的 main.py 實際結構做調整**。以下為範本，執行者需對齊既有命名：

```python
# miningbot/main.py

# 在 __init__ 或 setup 階段（與 Discord polling thread 啟動同處）加：
if cfg.web_server_enabled:
    from miningbot.web_server import WebIPCThread
    from miningbot.web_ipc import PendingReplies, FallbackState
    from miningbot.web_sink import WebEventSink

    self._web_pending = PendingReplies()
    self._web_fallback = FallbackState()
    self._web_thread = WebIPCThread(
        pending=self._web_pending,
        fallback=self._web_fallback,
        port=cfg.web_server_port,
    )
    self._web_thread.start()
    # 註冊 WebEventSink 跟 DiscordSink 平行
    self._events.add_sink(WebEventSink(
        broadcast_callback=lambda msg: self._web_thread.app.state.broadcast(msg)
    ))
    self.logger.info("WebIPC server 啟動：http://127.0.0.1:%d", self._web_thread.actual_port)
else:
    self._web_pending = None
    self._web_fallback = None
    self._web_thread = None

# 在主迴圈 safe point（消費 Discord pending 的旁邊）加：
def _consume_web_pending(self):
    if self._web_pending is None:
        return
    # 處理控制類命令（pause/resume/request_frame）
    for cmd in ("pause", "resume", "request_frame"):
        reply = self._web_pending.pop(f"control:{cmd}")
        if reply is not None:
            self._handle_web_control(cmd, reply)
    # 處理 fire_at / reentry_click（routing key 對齊當下 episode）
    # 由各狀態處理器（NEEDS_HUMAN / awaiting_fine / reentry 開場鏈）在它們的
    # tick 內呼叫 self._web_pending.pop(self._current_routing_key()) 自取
    # 清過期 reply 避免累積
    expired = self._web_pending.pop_any_expired()
    if expired:
        self.logger.info("web: 清掉過期 reply %d 筆", len(expired))

# 關機時 stop thread（如果 main.py 有 shutdown hook）：
if self._web_thread is not None:
    self._web_thread.stop()
```

注意：每個狀態處理器（NEEDS_HUMAN / awaiting_fine / reentry 開場鏈）需要在它們的
tick 邏輯裡加「先檢查 web_pending 有沒有當前 routing key 的 reply」——這部分是 P4
（即時介入面板）做的工作，P1 只鋪好 `_consume_web_pending` 框架，回傳的 reply 由
P4 接到對應狀態路徑。

- [ ] **Step 6: 跑全測試，確認通過**

```
uv run pytest tests/test_web_server.py -v
uv run pytest -q
uv run ruff check . --no-cache
uv lock --check
```

預期：全綠 + lint 乾淨。

- [ ] **Step 7: Commit**

```bash
git add miningbot/web_server.py miningbot/main.py tests/test_web_server.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P1 Task 10——main.py 整合 WebIPC thread

啟動 uvicorn server（綁 127.0.0.1）；EventLog 註冊 WebEventSink 跟 DiscordSink
平行；主迴圈 safe point 消費 web_pending（控制類立即處理、fire/click 由各狀態
處理器在 P4 自取）；自動清過期 reply。

P1 完工：IPC 基礎建設到位，可進 P2~P5。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 結果

### 1. Spec coverage（spec 對照）

| spec 段落 | 對應 task |
|---|---|
| §3 三條資料流（事件 / 命令 / 截圖） | Task 7（事件）、Task 8（命令）、Task 9（截圖 broadcast_binary 框架，main.py 整合時用） |
| §8 IPC 拓撲（WebIPC thread + pending queue + EventLog sink） | Task 7 + Task 8 + Task 10 |
| §8 三條資料流的協議 | Task 2（WebMessage）+ Task 8（命令協議）+ Task 9（事件廣播） |
| §8 race 規則（先到先贏、routing key） | Task 5 |
| §8 fallback 切換規則（30s grace） | Task 6 + Task 9（fallback.is_fallback 整合進 server） |
| §8 Bot 端整合（最小侵入） | Task 10 |
| §11 Config 變動 | Task 1 |
| §6 玩家可改欄位白名單（ spec §6） | Task 4 |

### 2. 不在 P1 範圍（屬 P2~P5）

- Discord 訊息角色精簡（edit_message / PING / 結案編輯）→ **P2**
- 玩家設定面板 UI（網頁前端表單）→ **P3**
- 即時介入面板 UI（pinch-zoom canvas、tap）+ 各狀態處理器接 web_pending → **P4**
- 歷史紀錄與標註面板 + 自動收集素材 + `tests/fixtures/aim/auto_*` 寫入 → **P5**
- 網頁前端（HTML/JS）任何 UI → P3~P5（P1 只鋪 WebSocket 協議）

### 3. Type consistency

- `WebMessage(type, payload)` 在所有 task 一致
- `PendingReplies.push/pop/pop_any_expired` 在 Task 5 定義、Task 8/9/10 使用
- `FallbackState.client_connected/disconnected/is_fallback/client_count` 在 Task 6 定義、Task 8/9/10 使用
- `routing_key` 在 Task 5 定義；Task 8 `_handle_command` 用字串模板 `f"{flow}:{ep_id}"` 直接組（不必跟 `routing_key()` 共用，但語義一致；P4 整合時可選擇重構）

### 4. 已知 placeholder / 不完整

- Task 10 Step 5 的 main.py 整合需要實作者對齊既有命名（先 `rg` 才寫），plan 已標明
- Task 10 Step 2 的 `test_main_loop_consumes_web_pending_at_safe_point` 暫時 skip，理由是 main.py 迴圈結構需實際讀過才能寫 fake bot。**建議**：P1 驗收時，若此測試還是 skip，要在 P4 整合時補回（因為 P4 才會讓狀態處理器實際吃 reply）

---

## P1 完工驗收（結案標準）

- [ ] 全測試綠（`uv run pytest -q`）
- [ ] lint 乾淨（`uv run ruff check . --no-cache`）
- [ ] lock 一致（`uv lock --check`）
- [ ] `WebIPCThread` 啟動後能接受 WebSocket 連線（測試綠即可，不需實機）
- [ ] `EventLog` 事件能透過 `WebEventSink` 廣播給所有連線 client
- [ ] bot 主迴圈 safe point 能消費 `web_pending` 控制類命令（pause/resume/request_frame）
- [ ] fallback 切換邏輯正確（連線 0 → ≥1 → 0 + grace expire）
- [ ] race 規則正確（先到先贏，後到丟棄）

P1 不需實機驗收（沒有玩家面向 UI）；整合測試 + fake bot 即可結案。

## 風險

| 風險 | 對策 |
|---|---|
| uvicorn 在 Windows daemon thread 內可能有 event loop 怪事 | Task 10 整合測試要實際跑過；若有問題，改用 `asyncio.run` 在主執行緒跑（會逼 bot 迴圈改 async） |
| `asyncio.run_coroutine_threadsafe` 跨 thread 廣播失敗靜默 | log warning；P1 不要求廣播可靠度 100%，P4 才嚴格驗收 |
| FastAPI 與既有 stdlib urllib 風格不一致 | 接受——這是新模組，不影響既有 notify.py |
| `TestClient` 的 event loop 跟 WebIPCThread 的 loop 不同 | Task 9 fixture 用獨立 loop + thread 跑 broadcast；整合進 main.py 後回歸單一 loop |

## 非目標

- 不做玩家面向 UI（HTML/JS）
- 不動 Discord 既有邏輯（P2 才動）
- 不接 bot 各狀態處理器（P4 才做）
- 不寫素材 / 標註（P5 才做）
- 不實機驗收（P4 才需要）
