# 每世界回礦黏性層持久化（Per-world Sticky Layer）設計

日期：2026-07-20
狀態：設計定案，待實作計畫
前置：`2026-07-12-remote-reentry-design.md`（遠端回礦；本設計更動其第 3 節「黏性目標層」的跨重啟行為，其餘不動）

## 目標與定位

回礦的「目標層」（點傳送面板哪顆層按鈕）目前只活在 session 記憶體：bot 啟動時把
`Config.reentry_target_layer`（預設 `"Mantle Layer"`）抄進 `Bot._rr_sticky_layer`，使用者
`層 <名>` 指令可改它，**但跨重啟退回 config 預設**。實機痛點：

- Mantle Layer 只存在於某世界；使用者長期在別的世界挖（如 Lucernia 的 Confectent），
  每次重開 bot 都看到目標層被預設成一個「根本不在這個世界」的層，得手動 `層` 一次。
- 使用者「通常長時間挖掘同一個區域」——同一個世界、同一層一挖就是幾小時。

本設計把「使用者設過的層」**按世界持久化到磁碟**，跨重啟自動套用該世界最後設的層。

## 已確認的事實與決策（2026-07-20 問答）

| 問題 | 決策 |
|---|---|
| 跨重啟記幾份 | **每個世界各記一份**（選項 B）。bot 已在被動追蹤現在的世界（`game_data.current_world_name()`），重啟後偵測到世界 X 就用「X 上次設的層」。換世界自動切、不會帶錯層。 |
| 持久化機制 | **專用 JSON map**（`logs/reentry_remote/sticky_layers.json`，與 ledger 同目錄同重導處理）。`層` 指令寫穿式落盤——即使當場沒跑完一場 reentry 也記得住。不掃 ledger（那是「上次用到」非「上次設定」，且當機未收尾場會漏）。 |
| 清除指令 | **不另設**。`層 <新名>` 即覆蓋舊值；要「重設」就再設一次。 |
| 層名驗證 | **不驗證**（沿用 `reentry_remote.py` 既有「純使用者宣告、bot 不驗證」原則）。YAGNI。 |

## 第 1 節：語意

`_rr_sticky_layer`（session 內有效目標層）的來源優先序：

1. **本 session 使用者已用 `層` 釘過** → 用釘的值（使用者意志最高；後續世界偵測變更不再覆寫）。
2. **否則** → 「目前已偵測到的世界」在持久 map 裡的值；查不到回 config 預設 `reentry_target_layer`。

新增 `self._rr_layer_user_pinned: bool = False`（Bot init）。

- `層 <名>` 指令：更新 `_rr_sticky_layer` 與 `ctx.sticky_layer`、設 `_rr_layer_user_pinned = True`、（世界已知時）寫穿 map。
- 世界偵測變更：僅在「**未釘**」時自動套用持久層。

**為何要 `_rr_layer_user_pinned`**：擋住「誤偵測世界把使用者剛設的層甩掉」的腳槍——一旦使用者本 session 明確設過，世界偵測不再覆寫。同時保證「重啟→挖新世界→自動套該世界的層」（新 session pinned=False，首次世界偵測即套用）。新 session 的 pinned 由 init 重置，不會把上個 session 的釘帶過來。

## 第 2 節：資料流

- **Bot init（`__init__`）**：讀 `sticky_layers.json`（容錯：空/缺/壞 → `{}`）進
  `self._rr_sticky_layers: dict[str, str]`。此時世界尚未偵測，`_rr_sticky_layer` 先放
  config 預設 `reentry_target_layer`（與今日相同）。`_rr_layer_user_pinned = False`。
- **世界偵測確認新世界**（`_maybe_detect_world`、`_maybe_detect_world_from_ore_lines`
  兩處「世界剛底定」之後）：呼叫 `_adopt_sticky_for_world(world)`——
  未釘時，`effective_sticky_layer(world, self._rr_sticky_layers, cfg.reentry_target_layer)`
  查值；與現值不同才更新並 `logger.info`。
- **`層 <名>` 指令**（`_rr_apply_reply` 的 `k == "layer"` 分支）：
  1. `self._rr_sticky_layer = reply.layer`；`ctx.sticky_layer = reply.layer`（既有）。
  2. `self._rr_layer_user_pinned = True`。
  3. `world = game_data.current_world_name()`；`new_map = remember_layer(self._rr_sticky_layers, world, reply.layer)`。
     - `new_map is not None`（世界已知、層名非空）→ 更新 `self._rr_sticky_layers`、寫檔、notify「✅ 目標層改為：X（已記住 {world} → X）」。
     - `new_map is None`（世界未偵測到 或 空層名）→ 不寫檔、notify「✅ 目標層改為：X（世界尚未偵測到，僅本次有效；偵測到後請再設一次以記住）」。
- **新 episode 建立**（`_rr_ensure_ctx`）：照舊用 `self._rr_sticky_layer`（已反映上述邏輯），**零改動**。

寫檔慣例照 `_rr_ledger_append`：`os.makedirs(os.path.dirname(path), exist_ok=True)` 再 `open(path, "w", encoding="utf-8")`；讀檔照 ledger 讀法 `open(path, "rb")` 配 `try/except OSError`。與 ledger 同目錄 → MSIX 重導問題沿用既有解（見 memory `reference_msix_log_location`）。

## 第 3 節：純函式（`reentry_remote.py`，TDD，I/O 在 main）

比照 `reentry_remote.py` 既有風格（純決策可單測、I/O 在 `Bot`）。全部不碰磁碟：

- `effective_sticky_layer(world: str | None, mapping: dict[str, str], fallback: str) -> str`
  — `mapping.get(world, fallback)`；`world is None` → `fallback`。
- `remember_layer(mapping: dict[str, str], world: str | None, layer: str) -> dict[str, str] | None`
  — 功能性、**不改輸入 mapping**。`world` 為 None 或 `layer` 空字串 → 回 `None`（呼叫端據此不寫檔）；
  否則回 `{**mapping, world: layer}`（已存在 → 覆蓋）。
- `parse_sticky_layers(raw_text: str | None) -> dict[str, str]` — `json.loads`；`None`/空字串/壞 JSON
  → `{}`（容錯比照 `next_episode_id`）。頂層非 dict → `{}`。
- `serialize_sticky_layers(mapping: dict[str, str]) -> str` — `json.dumps(mapping, ensure_ascii=False, sort_keys=True)`（中文層名可讀、鍵有序利於 diff）。

## 第 4 節：config

一條新欄，與 ledger 同目錄：

```python
reentry_remote_sticky_layers_path: str = "logs/reentry_remote/sticky_layers.json"
# 每世界回礦黏性層 map（{世界: 層名}）；`層` 指令寫穿、bot init 讀回。
# 容錯：空/缺/壞 → {}，回退到 reentry_target_layer。與 reentry_remote_ledger 同目錄
# （MSIX 重導同處理）。reentry_target_layer 保留為「世界未在 map 中 / 未偵測到」的 fallback。
```

`reentry_target_layer`（`"Mantle Layer"`）**保留不刪**——它是「該世界從沒設過」與「世界還沒偵測到」時的初值，維持今日行為。

## 第 5 節：邊界與不改動項

- **從沒設過的世界** → 回 config 預設（= 今日行為）。第一次挖新世界 `層` 一次即永久記住。
- **世界未知時下 `層`** → 只 session 有效、不寫檔、notify 明示。不做延後持久化（YAGNI；實務上 reentry/採礦時世界早已偵測到）。
- **誤偵測世界**：未釘時會把持久層套成「錯世界的值」——但 `_adopt_sticky_for_world` 只在值不同時更新＋log，且使用者一旦 `層` 即釘住、不再被覆寫。可接受。
- **embed「目標層」顯示**取自 `_rr_sticky_layer`（`build_reentry_embed` 既有路徑），自動反映，UI 零改動。
- **`reentry.py`（全自動路徑）不動**——本設計只影響遠端回礦的黏性層來源；全自動路徑仍讀 `cfg.reentry_target_layer`（該路徑目前 calibration-gated 且未上線）。
- **不驗證層名**是否真屬於該世界（既有原則）。
- **不新增清除指令**（`層 <新名>` 即覆蓋）。

## 第 6 節：測試（純，無 fixture）

`tests/test_reentry_remote.py`（或既有對應測試檔）新增：

- `effective_sticky_layer`：命中（map 有該世界）／miss→fallback／`world=None`→fallback。
- `remember_layer`：新增世界／更新已存在（覆蓋）／`world=None`→None／空層名→None／不改動輸入 mapping。
- `parse_sticky_layers`：`None`→{}、空字串→{}、壞 JSON→{}、頂層非 dict→{}、含中文值、與 `serialize_sticky_layers` round-trip。
- main 層指令路徑：若既有 `_rr_apply_reply` 測試則擴充（monkeypatch 檔案寫入、斷言 map 更新＋`_rr_layer_user_pinned`）；否則補一隻涵蓋「世界已知→寫檔」與「世界未知→不寫檔」兩分支。

## 第 7 節：實作落點（供實作計畫參考）

| 檔案 | 變更 |
|---|---|
| `miningbot/reentry_remote.py` | 新增 4 個純函式（第 3 節）。 |
| `miningbot/config.py` | 新增 `reentry_remote_sticky_layers_path`（第 4 節）。 |
| `miningbot/main.py` `Bot.__init__` | 載入 map 進 `self._rr_sticky_layers`；新增 `self._rr_layer_user_pinned = False`。`_rr_sticky_layer` 初始化維持 `cfg.reentry_target_layer`。 |
| `miningbot/main.py` `_maybe_detect_world` / `_maybe_detect_world_from_ore_lines` | 世界底定後呼叫新增的 `_adopt_sticky_for_world(world)`。 |
| `miningbot/main.py` `_rr_apply_reply`（`k == "layer"` 分支） | 設 pinned、`remember_layer`、寫檔、notify 文案隨世界已知與否分岐。 |
| `tests/` | 第 6 節純函式＋層指令整合測試。 |
