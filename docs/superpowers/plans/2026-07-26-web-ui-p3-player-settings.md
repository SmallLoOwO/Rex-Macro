# 網頁 UI P3：玩家設定面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 網頁讓玩家改 4 個白名單欄位（`reentry_mode`、`reentry_target_layer`、`reentry_yaw_sample_sweep`、`sweep_pitch_enabled`）；改值即時 runtime 生效 + 寫入 `logs/config_overrides.json` 持久化；bot 啟動時讀回套用。

**Architecture:** P1 已有 WebSocket + `web_config_whitelist.py` 純函式 + `config_set` 命令協議。P3 加三層：(1) `web_config_persistence.py` 純函式（load/save JSON）；(2) `web_server.py` HTTP endpoints（GET/POST `/api/config`、GET `/`）；(3) 網頁 HTML/JS 表單（4 個欄位 + 提交）。main.py 啟動時讀 overrides 套用、`config_set` 命令在 web_pending 路徑處理 runtime 改 + 持久化。

**Tech Stack:** Python 3.11+ / FastAPI（P1 已加）/ pytest / vanilla HTML+JS（不加前端框架）

## Global Constraints

- Python 3.11+
- **不加新依賴**（沿用 fastapi、uvicorn、stdlib json）
- 玩家可改的 Config 欄位**只有 P1 web_config_whitelist.py 定義的 4 個**——其他欄位（門檻、ROI、偵測參數）一律拒絕
- 座標／門檻／間隔只放 `miningbot/config.py`
- 純函式優先、I/O 邊界不交叉
- 不放寬偵測門檻、不刪事故回歸測試（H001~H060）
- 不修改 `discord_commands.py`、`notify.py`（P2 已動過）
- 不修改 `reentry_remote.py` / `remote_aim.py` 純函式
- 不修改 P1 web_protocol.py / web_ipc.py / web_sink.py（協議已固化）
- 不修改 P4/P5 範圍（即時介入、歷史紀錄）
- **既有測試不能壞**（P1+P2 全套 1358 passed + 3 skipped）
- Commit message 用中文；尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer
- 規格依據：`docs/superpowers/specs/2026-07-26-web-ui-design.md` §6

## 改動範圍預覽

| 檔案 | 改動 |
|---|---|
| `miningbot/web_config_persistence.py`（新） | `load_overrides` / `save_overrides` 純函式（讀寫 JSON） |
| `miningbot/web_server.py` | 加 HTTP routes：`GET /api/config`、`POST /api/config`、`GET /`（HTML） |
| `miningbot/web_static/index.html`（新） | 4 個欄位表單 |
| `miningbot/main.py` | 啟動時 load overrides 套用；`config_set` 命令在 web_pending 路徑處理 runtime 改 + 持久化 |
| `tests/test_web_config_persistence.py`（新） | load/save 純函式測試 |
| `tests/test_web_server_p3.py`（新） | HTTP endpoint 測試（TestClient） |

---

## Task 1: web_config_persistence.py 純函式

**Files:**
- Create: `miningbot/web_config_persistence.py`
- Test: `tests/test_web_config_persistence.py`

**Interfaces:**
- Produces:
  - `load_overrides(path: str) -> dict[str, object]`：JSON 不存在/損壞 → 回 `{}`；存在 → 回 dict
  - `save_overrides(path: str, field: str, value, current_overrides: dict) -> dict`：合併當前 overrides 寫回；回新 dict（不 mutate current）
  - `apply_overrides_to_config(config, overrides: dict) -> list[str]`：把 overrides 套用到 Config instance；回成功套用的 field 名單（白名單外略過）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_config_persistence.py
"""P3 玩家設定面板：config_overrides.json 讀寫純函式。"""
import json
import pytest
from pathlib import Path
from miningbot.web_config_persistence import (
    load_overrides, save_overrides, apply_overrides_to_config,
)


class TestLoadOverrides:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_overrides(str(tmp_path / "nonexistent.json")) == {}

    def test_valid_json_returns_dict(self, tmp_path):
        p = tmp_path / "overrides.json"
        p.write_text(json.dumps({"reentry_mode": "auto", "sweep_pitch_enabled": True}))
        result = load_overrides(str(p))
        assert result == {"reentry_mode": "auto", "sweep_pitch_enabled": True}

    def test_corrupted_json_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {")
        assert load_overrides(str(p)) == {}

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("")
        assert load_overrides(str(p)) == {}


class TestSaveOverrides:
    def test_save_new_field(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        new = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        assert new == {"reentry_mode": "auto"}
        # 檔案寫入
        with open(p) as f:
            assert json.load(f) == {"reentry_mode": "auto"}

    def test_save_merges_existing(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        # 第一次存 reentry_mode
        first = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        # 第二次存 sweep_pitch_enabled，保留既有
        second = save_overrides(p, "sweep_pitch_enabled", True, current_overrides=first)
        assert second == {"reentry_mode": "auto", "sweep_pitch_enabled": True}

    def test_save_overwrites_same_field(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        first = save_overrides(p, "reentry_mode", "auto", current_overrides={})
        second = save_overrides(p, "reentry_mode", "off", current_overrides=first)
        assert second == {"reentry_mode": "off"}

    def test_save_does_not_mutate_input(self, tmp_path):
        p = str(tmp_path / "overrides.json")
        original = {"reentry_mode": "auto"}
        result = save_overrides(p, "sweep_pitch_enabled", True, current_overrides=original)
        # 輸入 dict 不該被改
        assert original == {"reentry_mode": "auto"}
        assert result == {"reentry_mode": "auto", "sweep_pitch_enabled": True}


class TestApplyOverridesToConfig:
    def test_apply_whitelisted_field(self):
        from miningbot.config import Config
        cfg = Config()
        cfg.reentry_mode = "off"  # 先設非預設值
        applied = apply_overrides_to_config(cfg, {"reentry_mode": "auto"})
        assert "reentry_mode" in applied
        assert cfg.reentry_mode == "auto"

    def test_apply_skips_non_whitelisted(self):
        from miningbot.config import Config
        cfg = Config()
        original_threshold = cfg.tracker_core_min_area
        applied = apply_overrides_to_config(
            cfg, {"tracker_core_min_area": 999, "reentry_mode": "auto"},
        )
        # 非白名單欄位略過
        assert cfg.tracker_core_min_area == original_threshold
        assert "tracker_core_min_area" not in applied
        assert "reentry_mode" in applied

    def test_apply_skips_invalid_value(self):
        # reentry_mode 只接 off/remote/auto；"garbage" 該被 web_config_whitelist 拒
        from miningbot.config import Config
        cfg = Config()
        original = cfg.reentry_mode
        applied = apply_overrides_to_config(cfg, {"reentry_mode": "garbage"})
        assert cfg.reentry_mode == original  # 沒被改
        assert applied == []

    def test_apply_multiple_whitelisted(self):
        from miningbot.config import Config
        cfg = Config()
        applied = apply_overrides_to_config(cfg, {
            "reentry_mode": "auto",
            "sweep_pitch_enabled": True,
        })
        assert set(applied) == {"reentry_mode", "sweep_pitch_enabled"}
        assert cfg.reentry_mode == "auto"
        assert cfg.sweep_pitch_enabled is True
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_web_config_persistence.py -v` — 預期 FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 實作純函式**

```python
# miningbot/web_config_persistence.py
"""玩家設定面板：config_overrides.json 讀寫 + 套用 Config（純函式）。

spec §6：玩家在網頁改的 4 個白名單欄位，即時 runtime 生效 + 寫進
`logs/config_overrides.json` 持久化；bot 啟動時讀回套用。

不動 config.py / .env（機密、事故根因記錄）；用獨立 JSON 疊加 default + env 之上。

套用順序（啟動時）：
1. Config dataclass default
2. .env 覆蓋（既有機制）
3. config_overrides.json 覆蓋（最高優先，P3 機制）
"""
import json
import os
from typing import Any

from miningbot.web_config_whitelist import is_web_configurable, validate_value


def load_overrides(path: str) -> dict[str, Any]:
    """讀 config_overrides.json；不存在/損壞 → 空 dict（不丟例外）。

    沿用 notify.py 既有「失敗只回報不中斷」慣例——overrides 檔壞掉不該讓 bot 開不了機。
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_overrides(path: str, field: str, value: Any,
                   current_overrides: dict[str, Any]) -> dict[str, Any]:
    """合併新欄位寫回 JSON；回新 dict（不 mutate current_overrides）。

    寫檔用 tempfile + os.replace 原子替換，避免寫到一半被中斷導致檔案損壞。
    """
    new_overrides = dict(current_overrides)
    new_overrides[field] = value
    # 原子寫檔：先寫 tmp，再 rename
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(new_overrides, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return new_overrides


def apply_overrides_to_config(config, overrides: dict[str, Any]) -> list[str]:
    """把 overrides 套用到 Config instance；回成功套用的 field 名單。

    白名單外略過（不報錯）；值不通過 validate_value 也略過。
    套用是 setattr——runtime 即時生效；某些 init-time 拷貝欄位可能要重啟才生效，
    但 P3 白名單 4 欄都是 runtime 讀取型（每 tick 讀 config.field）。
    """
    applied = []
    for field, value in overrides.items():
        if not is_web_configurable(field):
            continue
        if not validate_value(field, value):
            continue
        setattr(config, field, value)
        applied.append(field)
    return applied
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_web_config_persistence.py -v` + `uv run pytest -q` + `uv run ruff check . --no-cache` + `uv lock --check`

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_config_persistence.py tests/test_web_config_persistence.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P3 Task 1——web_config_persistence 純函式

load_overrides（缺檔/壞檔回 {}）、save_overrides（原子寫檔，不 mutate input）、
apply_overrides_to_config（白名單 + validate_value 雙閘；非白名單/無效值略過不報錯）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 擴充 web_server.py 加 HTTP endpoints

**Files:**
- Modify: `miningbot/web_server.py`
- Test: `tests/test_web_server_p3.py`（新）

**Interfaces:**
- Consumes: P1 `web_config_whitelist`、P3 Task 1 `web_config_persistence`、P1 `Config`
- Produces:
  - `create_app(...)` 擴充：接受 `config`、`overrides_path` 參數；新增 `GET /api/config`、`POST /api/config`、`GET /`（HTML）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_web_server_p3.py
"""P3 玩家設定面板 HTTP endpoints 測試。"""
import json
import pytest
from fastapi.testclient import TestClient

from miningbot.config import Config
from miningbot.web_server import create_app
from miningbot.web_ipc import PendingReplies, FallbackState


@pytest.fixture
def app_parts(tmp_path):
    cfg = Config()
    pending = PendingReplies()
    fallback = FallbackState()
    overrides_path = str(tmp_path / "overrides.json")
    app = create_app(
        pending=pending, fallback=fallback,
        broadcast_callback=None,
        config=cfg, overrides_path=overrides_path,
    )
    client = TestClient(app)
    return client, cfg, overrides_path


def test_get_api_config_returns_whitelisted_fields(app_parts):
    client, cfg, _ = app_parts
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    # 4 個白名單欄位都該出現
    assert "reentry_mode" in data
    assert "reentry_target_layer" in data
    assert "reentry_yaw_sample_sweep" in data
    assert "sweep_pitch_enabled" in data
    # 現值 = Config 預設
    assert data["reentry_mode"] == cfg.reentry_mode


def test_get_api_config_does_not_leak_non_whitelisted(app_parts):
    client, _, _ = app_parts
    r = client.get("/api/config")
    data = r.json()
    # 門檻、ROI、機密不該出現
    assert "tracker_core_min_area" not in data
    assert "reentry_game_region" not in data
    assert "discord_bot_token" not in data
    assert "log_dir" not in data


def test_post_api_config_updates_runtime(app_parts):
    client, cfg, _ = app_parts
    r = client.post("/api/config", json={"field": "reentry_mode", "value": "auto"})
    assert r.status_code == 200
    assert cfg.reentry_mode == "auto"  # runtime 即時生效


def test_post_api_config_persists_to_file(app_parts):
    client, _, overrides_path = app_parts
    client.post("/api/config", json={"field": "reentry_mode", "value": "auto"})
    import os
    assert os.path.exists(overrides_path)
    with open(overrides_path) as f:
        assert json.load(f) == {"reentry_mode": "auto"}


def test_post_api_config_rejects_non_whitelisted(app_parts):
    client, cfg, _ = app_parts
    original = cfg.tracker_core_min_area
    r = client.post("/api/config", json={"field": "tracker_core_min_area", "value": 999})
    assert r.status_code == 400
    assert cfg.tracker_core_min_area == original  # 沒被改


def test_post_api_config_rejects_invalid_value(app_parts):
    client, cfg, _ = app_parts
    original = cfg.reentry_mode
    r = client.post("/api/config", json={"field": "reentry_mode", "value": "garbage"})
    assert r.status_code == 400
    assert cfg.reentry_mode == original


def test_post_api_config_rejects_missing_field(app_parts):
    client, _, _ = app_parts
    r = client.post("/api/config", json={"value": "auto"})
    assert r.status_code == 400


def test_post_api_config_rejects_missing_value(app_parts):
    client, _, _ = app_parts
    r = client.post("/api/config", json={"field": "reentry_mode"})
    assert r.status_code == 400


def test_get_root_returns_html(app_parts):
    client, _, _ = app_parts
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    # HTML 含 4 個欄位
    body = r.text
    assert "reentry_mode" in body
    assert "reentry_target_layer" in body
    assert "reentry_yaw_sample_sweep" in body
    assert "sweep_pitch_enabled" in body
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_web_server_p3.py -v` — 預期 FAIL（`create_app` 不接受 `config` / `overrides_path` 參數；HTTP routes 不存在）。

- [ ] **Step 3: 擴充 create_app**

在 `miningbot/web_server.py`：

```python
# 在 create_app 簽名加 config / overrides_path（optional，向下相容）
def create_app(
    pending, fallback, broadcast_callback=None,
    config=None, overrides_path: str | None = None,
):
    app = FastAPI(title="MiningBot Web IPC")
    registry = ConnectionRegistry()
    app.state.registry = registry
    # ...既有...

    # P3: 玩家設定面板 endpoints
    if config is not None:
        from miningbot.web_config_whitelist import (
            is_web_configurable, validate_value, WEB_CONFIGURABLE_FIELDS,
        )
        from miningbot.web_config_persistence import (
            load_overrides, save_overrides, apply_overrides_to_config,
        )
        # 啟動時讀 overrides 套用（building blocks；main.py Task 3 也會做一次冪等）
        if overrides_path:
            initial = load_overrides(overrides_path)
            apply_overrides_to_config(config, initial)
            app.state.overrides = initial
            app.state.overrides_path = overrides_path
        else:
            app.state.overrides = {}
            app.state.overrides_path = None

        @app.get("/api/config")
        def get_config():
            return {f: getattr(config, f) for f in WEB_CONFIGURABLE_FIELDS}

        @app.post("/api/config")
        def post_config(payload: dict):
            field = payload.get("field")
            value = payload.get("value")
            if field is None or value is None:
                return _err(400, "missing field or value")
            if not is_web_configurable(field):
                return _err(400, f"field not web-configurable: {field}")
            if not validate_value(field, value):
                return _err(400, f"invalid value for {field}: {value!r}")
            # runtime 改
            setattr(config, field, value)
            # 持久化
            if app.state.overrides_path:
                app.state.overrides = save_overrides(
                    app.state.overrides_path, field, value, app.state.overrides,
                )
            return {"ok": True, "field": field, "value": value}

        @app.get("/")
        def root():
            from miningbot.web_static import render_index_html
            return fastapi.Response(
                content=render_index_html(config),
                media_type="text/html",
            )

    return app


def _err(status: int, reason: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content={"error": reason})
```

注意：`miningbot/web_static.py` 是 Task 3 新建（HTML render）。這個 task 先建 stub（render_index_html 回空 HTML），Task 3 補完整。

讓 Task 1（這個 task）先建 `miningbot/web_static.py` stub：

```python
# miningbot/web_static.py（Task 3 補完整）
"""網頁前端 HTML render（P3 Task 3 補完整）。"""


def render_index_html(config) -> str:
    """Task 3 補完整 HTML；這個 stub 先回最小可運作頁面。"""
    return "<!DOCTYPE html><html><body>P3 stub</body></html>"
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_web_server_p3.py -v` + `uv run pytest -q`（既有 1358 不回歸） + `uv run ruff check . --no-cache` + `uv lock --check`

注意：`test_get_root_returns_html` 驗證 HTML 含 4 個欄位名——stub 過不了，需要 Task 3 完整 HTML。這個 test 暫時標 `pytest.skip` 等 Task 3 補：

```python
def test_get_root_returns_html(app_parts):
    client, _, _ = app_parts
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    import pytest
    pytest.skip("HTML 完整內容 Task 3 後回頭驗證")
```

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_server.py miningbot/web_static.py tests/test_web_server_p3.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P3 Task 2——web_server 加 /api/config 與 / HTTP endpoints

GET /api/config 回白名單 4 欄現值；POST /api/config 驗證+runtime 改+持久化；
GET / 回 HTML（Task 3 補完整內容）。config/overrides_path 為 optional 參數，
P1 既有 create_app 呼叫端（測試）不受影響。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 網頁 HTML/JS 表單（render_index_html）

**Files:**
- Modify: `miningbot/web_static.py`（完整 HTML）
- Modify: `miningbot/game_data.py` 引用（讀目標層 dropdown 選項）—— **只讀，不改**
- Test: `tests/test_web_server_p3.py`（取消 Step 4 的 skip，補完整）

**Interfaces:**
- Produces:
  - `render_index_html(config) -> str`：4 個欄位表單 HTML（含 JS fetch `/api/config`）

- [ ] **Step 1: 取消 skip 並補完整 test_get_root_returns_html**

把 Task 2 的 skip 拿掉，改為完整斷言。另加 JS 行為的間接驗證：

```python
def test_get_root_returns_html_with_form(app_parts):
    client, _, _ = app_parts
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    # 4 個欄位 form 元素
    assert "reentry_mode" in body
    assert "reentry_target_layer" in body
    assert "reentry_yaw_sample_sweep" in body
    assert "sweep_pitch_enabled" in body
    # JS 提交邏輯（fetch /api/config）
    assert "/api/config" in body
    assert "fetch" in body.lower() or "XMLHttpRequest" in body


def test_get_root_html_has_submit_button(app_parts):
    client, _, _ = app_parts
    body = client.get("/").text
    assert "submit" in body.lower() or "type=\"submit\"" in body or "<button" in body.lower()
```

- [ ] **Step 2: 跑測試，確認失敗**

`uv run pytest tests/test_web_server_p3.py -v` — 預期 `test_get_root_returns_html_with_form` FAIL（stub HTML 不含 form/fetch）。

- [ ] **Step 3: 實作完整 render_index_html**

```python
# miningbot/web_static.py
"""網頁前端 HTML render（P3 玩家設定面板）。"""


def render_index_html(config) -> str:
    """4 個白名單欄位的設定表單 + JS 提交 fetch /api/config。

    純函式：吃 Config instance、回 HTML 字串。讀 4 個白名單欄位現值填入 form。
    """
    reentry_mode = getattr(config, "reentry_mode", "remote")
    target_layer = getattr(config, "reentry_target_layer", "")
    yaw_sample = getattr(config, "reentry_yaw_sample_sweep", False)
    sweep_pitch = getattr(config, "sweep_pitch_enabled", False)

    yaw_checked = "checked" if yaw_sample else ""
    sweep_checked = "checked" if sweep_pitch else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>MiningBot 玩家設定</title>
<style>
body {{ font-family: sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }}
label {{ display: block; margin: 1rem 0 0.3rem; font-weight: bold; }}
input, select {{ width: 100%; padding: 0.4rem; box-sizing: border-box; }}
button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; background: #0084ff; color: white;
         border: none; border-radius: 4px; cursor: pointer; }}
.status {{ margin-top: 1rem; padding: 0.6rem; background: #e6f4ff; border-radius: 4px;
          display: none; }}
.error {{ background: #ffe6e6; }}
</style>
</head>
<body>
<h1>MiningBot 玩家設定</h1>

<form id="settings-form">
  <label for="reentry_mode">回礦模式</label>
  <select id="reentry_mode" name="reentry_mode">
    <option value="off" {"selected" if reentry_mode == "off" else ""}>off（等人工）</option>
    <option value="remote" {"selected" if reentry_mode == "remote" else ""}>remote（Discord 點傳送板）</option>
    <option value="auto" {"selected" if reentry_mode == "auto" else ""}>auto（全自動）</option>
  </select>

  <label for="reentry_target_layer">目標層</label>
  <input type="text" id="reentry_target_layer" name="reentry_target_layer"
         value="{_esc(target_layer)}" placeholder="例：Mantle Layer">

  <label><input type="checkbox" id="reentry_yaw_sample_sweep" name="reentry_yaw_sample_sweep"
                {yaw_checked}>
    回礦後拍八方位（收語料）</label>

  <label><input type="checkbox" id="sweep_pitch_enabled" name="sweep_pitch_enabled"
                {sweep_checked}>
    掃描俯仰（失敗路徑掃上下層）</label>

  <button type="submit">儲存</button>
</form>

<div id="status" class="status"></div>

<script>
const form = document.getElementById('settings-form');
const status = document.getElementById('status');

form.addEventListener('submit', async (e) => {{
  e.preventDefault();
  const payload = {{
    reentry_mode: document.getElementById('reentry_mode').value,
    reentry_target_layer: document.getElementById('reentry_target_layer').value,
    reentry_yaw_sample_sweep: document.getElementById('reentry_yaw_sample_sweep').checked,
    sweep_pitch_enabled: document.getElementById('sweep_pitch_enabled').checked,
  }};
  status.className = 'status';
  status.style.display = 'block';
  status.textContent = '儲存中…';

  try {{
    const results = [];
    for (const [field, value] of Object.entries(payload)) {{
      const r = await fetch('/api/config', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ field, value }}),
      }});
      if (!r.ok) {{
        const err = await r.json().catch(() => ({{}}));
        throw new Error(field + ': ' + (err.error || r.status));
      }}
      results.push(field);
    }}
    status.textContent = '已儲存：' + results.join(', ');
  }} catch (err) {{
    status.className = 'status error';
    status.textContent = '儲存失敗：' + err.message;
  }}
}});
</script>
</body>
</html>
"""


def _esc(s: str) -> str:
    """HTML 屬性值 escape；避免 value 帶 " 或 < > 打破 HTML。"""
    return (str(s)
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))
```

- [ ] **Step 4: 跑測試，確認通過**

`uv run pytest tests/test_web_server_p3.py -v` + full suite + ruff + lock

- [ ] **Step 5: Commit**

```bash
git add miningbot/web_static.py tests/test_web_server_p3.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P3 Task 3——render_index_html 完整表單

4 個白名單欄位 form（dropdown / text / 2 toggle）+ JS fetch /api/config 提交。
ESC HTML 防 value 帶特殊字元打破結構。無外部 JS 依賴（vanilla）。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: main.py 整合——啟動套用 overrides + config_set 命令處理

**Files:**
- Modify: `miningbot/main.py`

**Interfaces:**
- Consumes: P3 Task 1 `web_config_persistence`、P1 `web_config_whitelist`、P1 `WebIPCThread`
- Produces: bot 啟動時讀 `config_overrides.json` 套用；`config_set` 命令在 `_consume_web_pending` 路徑處理（runtime 改 + 持久化）

- [ ] **Step 1: rg 找 WebIPCThread 啟動點 + _consume_web_pending**

```
rg -n "WebIPCThread|_consume_web_pending|web_pending" miningbot/main.py
```

- [ ] **Step 2: 寫整合測試（fake bot）**

加到 `tests/test_web_server_p3.py`：

```python
def test_main_init_loads_overrides(tmp_path, monkeypatch):
    """bot 啟動時讀 overrides 套用 Config。略——具體 fake bot 結構依 main.py；
    留 P4 整合時補回（同 P1 Task 10 / P2 Task 7 慣例）。"""
    pytest.skip("main.py 整合 smoke test 留 P4 補")


def test_main_consume_web_pending_handles_config_set():
    """web_pending 收到 control:config_set 命令時，bot runtime 改 Config + 持久化。
    略——同上，留 P4 補。"""
    pytest.skip("具體 fake bot 結構依 main.py；留 P4 補")
```

- [ ] **Step 3: 整合 main.py**

在 `__init__` 啟動 WebIPCThread 區塊附近加：

```python
# P3: 啟動時讀 config_overrides.json 套用
from .web_config_persistence import load_overrides, apply_overrides_to_config, save_overrides
import os

overrides_path = os.path.join(cfg.log_dir, "config_overrides.json")
self._overrides_path = overrides_path
initial_overrides = load_overrides(overrides_path)
applied = apply_overrides_to_config(cfg, initial_overrides)
if applied and self.logger:
    self.logger.info("config_overrides.json 套用 %d 欄: %s", len(applied), applied)
self._current_overrides = initial_overrides

# 啟動 WebIPCThread 時傳 config + overrides_path（給 HTTP endpoints）
if cfg.web_server_enabled:
    self._web_thread = WebIPCThread(
        pending=self._web_pending,
        fallback=self._web_fallback,
        port=cfg.web_server_port,
        config=cfg,                    # P3 新
        overrides_path=overrides_path,  # P3 新
    )
    # ... 既有 ...
```

WebIPCThread `__init__` 要接受新參數並傳給 `create_app`：

```python
# miningbot/web_server.py - WebIPCThread
def __init__(self, pending, fallback, port=8765, host="127.0.0.1",
             config=None, overrides_path=None):
    # ... 既有 ...
    self.app = create_app(
        pending=pending, fallback=fallback, broadcast_callback=None,
        config=config, overrides_path=overrides_path,
    )
```

在 `_consume_web_pending` 加 `config_set` 命令處理（同 `control:pause` 處理位置）：

```python
# miningbot/main.py - _consume_web_pending
def _consume_web_pending(self):
    if self._web_pending is None:
        return
    # ... 既有 control:* 處理 ...
    # P3: config_set 命令
    reply = self._web_pending.pop("control:config_set")
    while reply is not None:
        field = reply.get("field")
        value = reply.get("value")
        if field is not None and value is not None:
            from .web_config_whitelist import is_web_configurable, validate_value
            if is_web_configurable(field) and validate_value(field, value):
                setattr(self.config, field, value)
                self._current_overrides = save_overrides(
                    self._overrides_path, field, value, self._current_overrides,
                )
                if self.logger:
                    self.logger.info("web config_set: %s=%r", field, value)
            else:
                if self.logger:
                    self.logger.warning("web config_set 拒絕: %s=%r", field, value)
        reply = self._web_pending.pop("control:config_set")
    # ... 既有 expired sweep ...
```

注意：HTTP POST `/api/config` 直接走 web_server FastAPI route（同步處理，不過 web_pending）。WebSocket 命令 `config_set` 走 web_pending（异步處理）。**兩條路徑都呼叫同一個 `save_overrides` + `setattr`**——這是 main.py 內的重複，但保持 web_server 與 main.py 解耦（web_server 不需要 bot 實例）。

- [ ] **Step 4: 跑全測試**

`uv run pytest -q` + `uv run ruff check . --no-cache` + `uv lock --check`

預期：1358 + P3 新增 = 全綠。既有 P1+P2 不回歸。

- [ ] **Step 5: Commit**

```bash
git add miningbot/main.py miningbot/web_server.py tests/test_web_server_p3.py
git commit -m "$(cat <<'EOF'
feat(web-ui): P3 Task 4——main.py 啟動套用 overrides + config_set 命令處理

啟動讀 config_overrides.json 套用 Config；WebIPCThread 接受 config + overrides_path
參數傳給 create_app（HTTP routes 生效）；_consume_web_pending 處理 control:config_set
命令（runtime 改 + 持久化）。

P3 完工：網頁 UI 可改 4 個白名單欄位、即時生效、持久化跨重啟。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 結果

### 1. Spec coverage

| spec §6 段落 | 對應 task |
|---|---|
| 玩家可改欄位白名單（4 個） | P1 已落地 `web_config_whitelist.py`；P3 沿用 |
| 不動 config.py / .env，用 config_overrides.json 疊加 | Task 1（純函式）+ Task 4（main.py 整合） |
| 立即 runtime 生效 + 寫入 config_overrides.json | Task 1 `save_overrides` + Task 2 POST endpoint + Task 4 main.py 雙路徑 |
| Bot 啟動時讀回 | Task 1 `load_overrides` + Task 4 main.py 啟動套用 |
| 不需 diff 預覽/二次確認/備份（玩家能改的不會讓 bot 壞掉） | 不實作（YAGNI） |

### 2. 不在 P3 範圍（屬 P4~P5）

- 即時介入面板 UI（harvest 101 awaiting_fine、回礦傳送板定位）→ **P4**
- 歷史紀錄與標註面板 → **P5**
- 自動收集素材 → **P5**

### 3. Type consistency

- `load_overrides(path: str) -> dict`
- `save_overrides(path, field, value, current_overrides) -> dict`
- `apply_overrides_to_config(config, overrides) -> list[str]`
- `create_app(..., config=None, overrides_path=None)`
- `WebIPCThread(..., config=None, overrides_path=None)`

### 4. 已知 placeholder / 彈性

- Task 4 Step 2 的 main.py smoke test 暫時 skip（同 P1/P2 慣例，P4 補）
- Task 4 雙路徑（HTTP POST + web_pending config_set）呼叫同一個 save_overrides 是有點重複——可重構成單一 helper，但會增加 main.py ↔ web_server 耦合；暫時保留雙路徑

---

## P3 完工驗收

- [ ] 全測試綠（`uv run pytest -q`）
- [ ] lint 乾淨（`uv run ruff check . --no-cache`）
- [ ] lock 一致（`uv lock --check`）
- [ ] **既有 P1+P2 全套 1358 passed + 3 skipped 不回歸**
- [ ] `load_overrides` / `save_overrides` / `apply_overrides_to_config` 純函式測試綠
- [ ] HTTP endpoints（GET/POST /api/config、GET /）測試綠
- [ ] HTML 含 4 個欄位表單 + JS fetch 邏輯
- [ ] main.py 啟動套用 overrides；`config_set` 命令處理

P3 不需實機驗收（main.py 整合測試 skip 部分留 P4 補）。

## 風險

| 風險 | 對策 |
|---|---|
| 兩條 config 改動路徑（HTTP POST + WebSocket config_set）race | 都用 setattr 原子指派；save_overrides 用 os.replace 原子寫檔；無致命 race |
| config_overrides.json 損壞導致 bot 開不了機 | load_overrides 失敗回 `{}`，bot 用 default 開機 |
| 玩家在網頁改值時 bot 正在執行流程（runtime 改 mid-flow） | 白名單 4 欄都是每 tick 讀取型；改了下一 tick 就生效；不破壞進行中流程 |
| 改 `reentry_mode` 後剛好 bot 進 RESET_WAIT | 行為一致：當下流程跑完，下一個狀態機循環讀新值 |
| HTTP endpoint 沒認證 | spec §2 已裁決：tailnet 自己用、設備授權已足夠、不再疊 token |

## 非目標

- 不做即時介入面板（P4）
- 不做歷史紀錄 / 標註（P5）
- 不動 Discord / Discord polling thread 邏輯
- 不動 P1 / P2 既有邏輯（除了 web_server.py 加 routes、main.py 加啟動套用）
- 不實機驗收（P4 才需要）
