# 網頁 UI P5：歷史紀錄與標註面板 + 收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成最後子計畫——(1) P4 final-review 標的修復（pinch-zoom 座標協議重設、WebSocket heartbeat、frame-grab race、reentry UX）；(2) 歷史紀錄面板（episode 列表、詳細頁）；(3) 標註工具（正方形 + Rarity 快選 + 症狀標籤）；(4) 自動收集素材（玩家介入成功後寫 tests/fixtures/aim/auto_*.png + .json）。

**Architecture:** P5 加 `miningbot/web_annotation.py`（標註純函式）+ `miningbot/web_history.py`（episode/snapshot/標註三層資料讀取）+ `miningbot/web_server.py` 擴充（/api/history、/api/episode、/api/annotate、GET /history、GET /annotate）+ `miningbot/web_static.py` 擴充（render_history_html、render_annotate_html）+ main.py 自動收集 + 修 P4 Critical（座標協議重設：JS 算 native、parser 變 thin validator）。

**Tech Stack:** Python 3.11+ / FastAPI / pytest / vanilla JS

## Global Constraints

- Python 3.11+
- 不加新依賴
- 座標／門檻／間隔只放 `miningbot/config.py`
- 純函式優先、I/O 邊界不交叉
- 不放寬偵測門檻、不刪事故回歸測試（H001~H060）
- **既有 P1+P2+P3+P4 全套 1398 passed + 9 skipped 不能壞**
- 不修改 `discord_commands.py`、`notify.py`（除非新增的 status 形式）
- 不修改 `reentry_remote.py` / `remote_aim.py` 純函式
- 不修改 P1 web_protocol.py 既有 dataclass（**只加新函式**；P4 Task 1 函式若被 P5 Task 1 修座標協議，可改但保留舊測試的相容路徑或更新 test）
- Commit message 用中文；尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer
- 規格依據：`docs/superpowers/specs/2026-07-26-web-ui-design.md` §5

## 改動範圍預覽

| 檔案 | 改動 |
|---|---|
| `miningbot/web_static.py` | **Task 1**: 修介入面板 JS 改用 client-side native 計算；**Task 7**: 加 render_history_html + render_annotate_html |
| `miningbot/web_protocol.py` | **Task 1**: parse_fire_at_payload / parse_reentry_click_payload 改為 thin validator（接受 native coords，刪 zoom/pan 邏輯） |
| `miningbot/web_server.py` | **Task 2**: heartbeat 改真 pong tracking 或刪；**Task 6**: /api/history、/api/episode/{id}、/api/annotate、GET /history、GET /annotate |
| `miningbot/main.py` | **Task 3**: frame-grab race re-grab + 非 descended verdict 加 web client UX；**Task 5**: 自動收集素材寫入 |
| `miningbot/web_annotation.py`（新） | **Task 4**: 標註純函式（正方形 schema、症狀 normalize、素材 .json schema、Rarity 從 game_data 撈） |
| `miningbot/web_history.py`（新） | **Task 4**: episode/snapshot/標註三層讀取純函式 |
| `tests/test_web_annotation.py`、`tests/test_web_history.py`（新） | 新測試 |
| `tests/test_web_protocol.py`、`tests/test_web_server.py`、`tests/test_web_intervention.py` | 沿用擴充 |

---

## Task 1: 修 P4 Critical pinch-zoom 座標協議重設

**Files:**
- Modify: `miningbot/web_static.py`（render_intervention_html）
- Modify: `miningbot/web_protocol.py`（parse_fire_at_payload / parse_reentry_click_payload）
- Modify: `tests/test_web_protocol.py`（更新 test 對齊新 schema）
- Modify: `tests/test_web_intervention.py`（更新 test）

**背景**：P4 final review 抓到 client/server 之間座標空間 mismatch。JS 送的 `canvas_size = [rect.width, rect.height]` 是 post-transform（含 zoom）；parser 數學假設是 unzoomed。zoom=2 時點擊偏 2x。

**新協議**：client 直接算 native coords：
```js
// JS 用 canvas 內部尺寸（CANVAS_NATIVE）跟顯示尺寸（rect）比例換算
const nativeX = Math.round((clientX - rect.left) * (canvas.width / rect.width));
const nativeY = Math.round((clientY - rect.top) * (canvas.height / rect.height));
// 送 {cmd, flow, harvest_id|attempt_id, x: nativeX, y: nativeY}——不再送 zoom/pan/canvas_size
```

parser 變 thin validator：
```python
def parse_fire_at_payload(payload: dict) -> dict | None:
    """驗證 cmd/flow/id/x/y；x/y 必須是 int 範圍 [0, 1919] / [0, 1079]。"""
    if payload.get("cmd") != "fire_at": return None
    flow = payload.get("flow")
    if not isinstance(flow, str) or not flow: return None
    # ... id 驗證（同 P4 Task 1）
    x, y = payload.get("x"), payload.get("y")
    if not isinstance(x, int) or not isinstance(y, int): return None
    if not (0 <= x < 1920 and 0 <= y < 1080): return None
    return {"flow": flow, "x": x, "y": y, **id_field}
```

- [ ] **Step 1: 寫測試**——更新 `tests/test_web_protocol.py` 的 TestParseFireAtPayload / TestParseReentryClickPayload：
  - 移除 zoom/pan/canvas_size 用例
  - 加：基本 `{"cmd":"fire_at","flow":"harvest","harvest_id":"007","x":960,"y":540}` → 回 `{"flow":"harvest","x":960,"y":540,"harvest_id":"007"}`
  - 加：`x=1920` 超界回 None；`x=-1` 回 None；`x="abc"` 回 None
  - 加：缺 x/y 回 None

- [ ] **Step 2: 跑測試確認 RED**

- [ ] **Step 3: 重設 parser 為 thin validator**——`miningbot/web_protocol.py`：
  - `parse_fire_at_payload(payload) -> dict | None` 不再吃 canvas_size 參數；只驗證 payload 結構
  - 刪 `_parse_pointer_payload` 內 zoom/pan 邏輯（或保留給其他用途，但 fire_at/reentry_click 不用）
  - `client_to_native_coords` 保留（P1 純函式，不刪）

- [ ] **Step 4: 更新 web_static.py render_intervention_html 的 sendClick**

  把目前算 client_xy + canvas_size + zoom + pan 改成算 native：
  ```js
  function sendClick(clientX, clientY) {
    if (!currentEvent) return;
    const rect = canvas.getBoundingClientRect();
    const nativeX = Math.round((clientX - rect.left) * (canvas.width / rect.width));
    const nativeY = Math.round((clientY - rect.top) * (canvas.height / rect.height));
    const cmd = currentEvent.flow === 'reentry' ? 'reentry_click' : 'fire_at';
    const [flow, epId] = currentEvent.routing_key.split(':', 2);
    const ep_id = flow === 'harvest' ? {harvest_id: epId} : {attempt_id: epId};
    ws.send(JSON.stringify({
      type: 'command',
      payload: {cmd, flow, ...ep_id, x: nativeX, y: nativeY},
    }));
  }
  ```

- [ ] **Step 5: 更新 `tests/test_web_intervention.py` 整合測試**——`test_web_fire_at_full_pipeline` 等改用新 schema（直接 x/y）。

- [ ] **Step 6: 跑全測試 + ruff + lock**

- [ ] **Step 7: Commit**

```bash
git add miningbot/web_static.py miningbot/web_protocol.py tests/test_web_protocol.py tests/test_web_intervention.py
git commit -m "$(cat <<'EOF'
fix(web-ui): P5 Task 1——修 P4 Critical pinch-zoom 座標協議重設

JS 改用 client-side 直接算 native coords（(clientX-rect.left) * canvas.width/rect.width）；
parser 變 thin validator（只驗 cmd/flow/id/x/y 結構與範圍）。
舊 client_to_native_coords 純函式保留（其他場景可能用）。
解 P4 final review 抓到的 zoom=2 點擊偏 2x 座標空間 mismatch。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 修 P4 Important WebSocket heartbeat + reentry UX

**Files:**
- Modify: `miningbot/web_server.py`（heartbeat 改真 pong tracking 或刪）
- Modify: `miningbot/web_static.py`（render_intervention_html 加 client-side pong 回覆）
- Modify: `miningbot/main.py`（_reentry_await_player_click 非 descended verdict 加 web prompt）

**背景**：P4 final review 標的：
- (a) heartbeat 是 text message 不是 protocol-level ping frame；send_text 只在 TCP 全斷才拋；不真守 half-open
- (b) `_reentry_await_player_click` 非 descended verdict 卡玩家（無 embed 卡可反應）

**修法**：
- (a) **刪 app-level heartbeat task**——uvicorn 預設 20s 協議級 ping 已足夠；docstring 改「依賴 uvicorn protocol-level ping」。Config `websocket_ping_interval_s` 欄位標 deprecated 但保留（不刪避免破壞 P4 既有呼叫端）。
- (b) **`_reentry_await_player_click` verdict 非 descended 時推 INTERVENTION_RESULT event 給 web client**，client UI 顯示「未成功，再點一次或重骰」訊息 + 重新等 reply（最多 3 次）。

- [ ] **Step 1: 寫測試**——test_web_server.py 加 test 確認 heartbeat task 已移除（或行為改）；test_web_intervention.py 加 test 確認 INTERVENTION_RESULT 事件送的邏輯（用 mocked _rr_click_and_verify 回 still_surface 觸發）

- [ ] **Step 2: 修 web_server.py heartbeat**——刪 `asyncio.create_task(_send_pings())` 整段；改 docstring 說明依賴 uvicorn protocol ping

- [ ] **Step 3: 修 main.py `_reentry_await_player_click`**——加 verdict retry loop；非 descended 時推 INTERVENTION_RESULT 給 client；3 次失敗 fall through Discord

- [ ] **Step 4: 跑全測試 + ruff + lock**

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(web-ui): P5 Task 2——修 P4 heartbeat + reentry 非 descended verdict UX

heartbeat 改依賴 uvicorn 協議級 ping（app-level text ping 不能守 half-open）；
_reentry_await_player_click 加 verdict retry loop（3 次）+ INTERVENTION_RESULT 事件
讓 client 顯示「再點一次」提示，避免玩家卡死。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: 修 P4 Important frame-grab race

**Files:**
- Modify: `miningbot/main.py`（`_execute_remote_fire_from_web` + `_rr_click_from_web`）

**背景**：P4 final review 標的：60-120s 等 reply 期間，tracker 可能消失／傳送板關閉／礦坑重置；reply 到時 bot 用過時 snapshot 的座標開火。

**修法（minimum viable）**：reply 到時 **re-grab 當下 frame**，做 minimum sanity check（例如 `_mine_resetting` 已是 True 就 abort；FOV state0/state1 不一致就 reject reply 走 fallback）。完整 re-verify target visibility（ tracker 還在不在）是更複雜的工作，留實機驗收後再評估。

- [ ] **Step 1: 寫測試**——test_web_intervention.py 加 mocked test 確認 `_mine_resetting=True` 時 reply 被 reject

- [ ] **Step 2: 修 `_execute_remote_fire_from_web` + `_rr_click_from_web`**——reply pop 後加：
  ```python
  if getattr(self, "_mine_resetting", False):
      self.logger.info("web reply 在 礦坑重置中，reject")
      return False
  ```

- [ ] **Step 3: 跑全測試**

- [ ] **Step 4: Commit**

---

## Task 4: web_annotation.py + web_history.py 純函式

**Files:**
- Create: `miningbot/web_annotation.py`
- Create: `miningbot/web_history.py`
- Create: `tests/test_web_annotation.py`
- Create: `tests/test_web_history.py`

**Interfaces:**
- `web_annotation.py`:
  - `build_annotation(image, annotation, tier, variant, mineral, source, symptom, related_incident) -> dict`：建素材 .json schema
  - `normalize_symptom(s) -> str | None`： symptom 文字（「漏判」/「誤判」/FN/FP）→ 標準 enum
  - `rarity_choices_from_game_data() -> list[tuple[str, list[str]]]`：從 `game_data.SPECIAL_ORES` tier 撈 + 變體（Spectral/Ionized）
- `web_history.py`:
  - `load_episodes(snapshot_index_path, harvest_log_path) -> list[dict]`：episode 列表（id/類型/結果/時間）
  - `load_episode_detail(episode_id, snapshot_index_path) -> dict`：episode 詳細（事件流/snapshots/標註）
  - `list_annotations_for_episode(episode_id, fixtures_dir) -> list[dict]`：該 episode 已標註素材

- [ ] **Step 1-5**: TDD + commit

---

## Task 5: 自動收集素材

**Files:**
- Modify: `miningbot/main.py`（`_execute_remote_fire_from_web` + `_rr_click_from_web` 成功路徑加素材寫入）

**邏輯**：
- harvest verify 通過 → 寫 `tests/fixtures/aim/auto_<hid>_success.png`（cell crop）+ `.json`（{cx, cy, size, tier, source:"auto", symptom:null}）
- verify 失敗 → 寫 `tests/fixtures/aim/auto_<hid>_fail.png` + .json（symptom:"unknown"）
- reentry plan_click_verdict descended → 寫 `tests/fixtures/reentry/teleport_board/auto_<ep>_success.png` + .json

- [ ] **Step 1-5**: TDD + commit

---

## Task 6: HTTP endpoints（/api/history, /api/episode/{id}, /api/annotate）

**Files:**
- Modify: `miningbot/web_server.py`

- `GET /api/history` → episode 列表
- `GET /api/episode/{id}` → 詳細
- `POST /api/annotate` → 寫入素材（標註工具提交）
- `GET /history` → render_history_html
- `GET /annotate?episode={id}&snapshot={label}` → render_annotate_html

- [ ] **Step 1-5**: TDD + commit

---

## Task 7: 網頁 UI（render_history_html + render_annotate_html）

**Files:**
- Modify: `miningbot/web_static.py`

- `render_history_html(episodes: list) -> str`：列表 + 篩選
- `render_annotate_html(episode_id, snapshot_path, rarity_choices) -> str`：標註工具（pinch-zoom + 正方形拖曳 + Rarity 快選 + 症狀標籤 + 匯出按鈕）

- [ ] **Step 1-5**: TDD + commit

---

## Task 8: 整合測試 + 最終驗收 smoke

**Files:**
- Modify: 各 test 檔

- 整合測試：episode 列表、詳細頁、標註 POST
- 自動收集素材：玩家介入 mock → 素材寫入正確
- P4 pinch-zoom 協議：舊測試調整 + 新測試覆蓋 native 算法

- [ ] **Step 1-5**: TDD + commit

---

## Self-Review 結果

### 1. Spec coverage

| spec §5 段落 | 對應 task |
|---|---|
| 三層資料模型（episode / snapshot / 標註） | Task 4 |
| UI 三區塊（列表 / 詳細 / 標註工具） | Task 6/7 |
| 素材格式（PNG + JSON，2 檔） | Task 4 schema + Task 5 寫入 |
| 自動收集 | Task 5 |
| 症狀標籤 + Rarity 快選 | Task 4 normalize + Task 7 UI |
| 素材庫結構 | Task 5 寫入路徑 |

### 2. P4 final review findings 處理

| Finding | Task |
|---|---|
| Critical pinch-zoom 座標協議 | Task 1 |
| Important heartbeat 不真守 half-open | Task 2 |
| Important frame-grab race | Task 3 |
| Important reentry 非 descended UX | Task 2 |
| Minor Manhattan threshold 5px | Task 7（標註 UI 一併調） |

### 3. 非目標

- 不實機驗收（玩家從手機連網頁 pinch-zoom 點選 → verify）—— P5 後單獨安排
- 不做素材庫跨語料訓練 / 兩側夾調門檻（AI agent 工作）

---

## P5 完工驗收

- [ ] 全測試綠
- [ ] lint + lock 一致
- [ ] 既有 P1-P4 全套不回歸
- [ ] P4 Critical pinch-zoom 修復 + 新 test 鎖住 native 算法
- [ ] 自動收集素材寫入測試綠
- [ ] 標註工具 POST 測試綠

## 風險

| 風險 | 對策 |
|---|---|
| Task 1 座標協議重設破壞 P4 既有測試 | 同步更新 test_web_protocol.py + test_web_intervention.py |
| Task 4/6/7 範圍大（多新檔 + 跟 game_data 整合） | minimum viable：先純函式 + endpoint + minimal UI；詳細 UI 修 polish |
| 自動收集素材 race（玩家介入期間 snapshot 寫入衝突） | 用 snapshot worker 既有 queue；不另開 thread |

## 非目標

- 不實機驗收（單獨安排）
- 不做 AI agent 自動分析素材
