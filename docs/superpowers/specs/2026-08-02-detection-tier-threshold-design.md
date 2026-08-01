# 偵測階級門檻（Detection Minimum Tier）— Design Spec

> 2026-08-02．使用者需求：可以調高偵測系統的最低稀有階級，讓低於門檻的
> 礦（如 Exotic）不觸發面板色檢／救援／採集確認，避免被動挖到的常見 礦
> 被誤判為「已採到稀有 礦」而白交人工。Discord 指令＋網頁設定同步。

## 問題

`classify_found_ore` 把 `rare_ores.json` 裡**所有** HIGH_TIERS 礦都判成
`"rare"`。使用者會在遊戲中調高 chill 觸發階級（例如只讓 Exquisite+ 觸發），
但偵測系統仍把 Exotic 當白名單 → 鎬子被動挖到 Exotic → 面板色檢命中 →
跳過採集流程直接交人工（假陽性）。Exotic 長期下來很常見，每次停下代價大。

## 階級順序

取自 `fetch_ores.py:32` 的 `HIGH_TIERS` tuple（順序即高低）：

```
Exotic < Exquisite < Transcendent < Enigmatic < Unfathomable < Otherworldly < Imaginary < Zenith
```

## 設計

### 核心改動：`classify_found_ore` 加階級閘

`game_data.py` 加模組級變數 `_detection_min_tier`（預設 `None` = 不過濾）。
`classify_found_ore` 在 rare 表精確／模糊命中後，檢查該 礦 tier 是否 ≥
門檻；低於門檻回 `"common"`（非白名單，所有下游自動正確行為）。

效果自動蔓延到全部下游，無需逐處改動：

| 下游 | 低於門檻的 礦行為 |
|---|---|
| `rare_panel_ores`（面板色檢、救援路 B） | 不算「已採到稀有 礦」 |
| `_rescue_chat_ores`（救援路 A 聊天差分） | 不當證據 |
| `_verify_chat_ocr`（採集成功驗證） | 不算成功（正確：chill 只對門檻+） |
| `_harvest_success` 通知標注 | 標「被動挖礦」而非稀有 |

`"common"` 分類的語意 = 「非白名單，可忽略」，與現行 common（Surreal/Mythic
排除清單）在下游完全同路徑。

### 門檻設定：Discord ＋網頁雙向同步

**Discord 指令**（文字，同 `掃描`/`削洞` 慣例）：

- `階級` — 查詢目前門檻
- `階級 Exquisite` — 設定門檻（Exotic 從此不算稀有）
- `階級 Exotic` — 回預設（所有稀有 礦都算）
- 不帶 tier 名／tier 名無效 → 回可用清單＋現值

**網頁設定頁**：在現有設定表單加一個 `<select>` 下拉選單，列所有
HIGH_TIERS，存到 `config_overrides.json`（同 `reentry_mode` 機制）。

**同步**：兩邊都寫 `config_overrides.json`（單一持久化來源）＋即時調
`game_data.set_detection_min_tier()`。啟動時 `_apply_startup_overrides`
讀回 → bot 呼叫 `set_detection_min_tier(cfg.detection_min_tier)`。

### Config

```python
detection_min_tier: str = "Exotic"   # 偵測系統最低稀有階級（classify_found_ore 閘）
```

預設 `"Exotic"` = 現行行為（不過濾），不影響既有測試。

### 模組級 API（game_data.py）

```python
_TIER_ORDER = {tier: i for i, tier in enumerate(HIGH_TIERS)}

_detection_min_tier: str | None = None   # None = 不過濾（測試預設）

def set_detection_min_tier(tier: str | None) -> None: ...
def get_detection_min_tier() -> str | None: ...
```

`classify_found_ore` 在 rare 命中（exact + fuzzy）後加：
```python
if _detection_min_tier and _TIER_ORDER.get(info["tier"], -1) < _TIER_ORDER[_detection_min_tier]:
    return "common", None
```

tier 不在 `_TIER_ORDER`（未知的 tier）的 礦：`get(tier, -1)` = -1，永遠
< 門檻 → 回 common。安全方向（未知的當低階）。

### 色相閘也跟著門檻走（2026-08-02 使用者補充）

面板偵測有兩條色相路，名字閘之外的第二訊號。提高門檻時兩條都要跟著
縮窄，否則名字閘放行 Exotic、色相閘仍抓 Exotic → 永遠擋零點成立。

**已知量測的 tier→hue 對應**（`config.py:394`、2026-07-31 D11 量測）：

```
Exotic 46｜Exquisite 128｜Transcendent 210｜Mythic 304｜Surreal 166｜低階 0/30/280
```

Enigmatic 以上未量測——靠 `non_low_tier_hues` 反向閘兜住（未知色相當高階）。

**`game_data.py` 加 tier→hue 映射＋有效色相計算**：

```python
TIER_HUES = {"Exotic": 46.0, "Exquisite": 128.0, "Transcendent": 210.0}

def effective_whitelist_hues(min_tier, base_whitelist) -> tuple:
    '''回傳 ≥ min_tier 的量測色相（白名單用）。'''
    min_rank = _TIER_ORDER.get(min_tier, 0)
    return tuple(h for t, h in TIER_HUES.items()
                 if _TIER_ORDER.get(t, 999) >= min_rank)

def effective_low_tier_hues(min_tier, base_low_tier) -> tuple:
    '''回傳 base_low_tier ＋ < min_tier 的量測色相（零點閘用）。'''
    min_rank = _TIER_ORDER.get(min_tier, 0)
    below = tuple(h for t, h in TIER_HUES.items()
                  if _TIER_ORDER.get(t, 999) < min_rank)
    return tuple(dict.fromkeys(base_low_tier + below))  # 去重保序
```

**呼叫端改動**（`main.py`，純函式簽名不動）：

- `_clear_panel_filter` 的 `non_low_tier_hues`：原本傳 `cfg.panel_low_tier_hues`
  → 改傳 `game_data.effective_low_tier_hues(cfg.detection_min_tier, cfg.panel_low_tier_hues)`
- `_panel_rare_ores` 的 `whitelist_hue_hits`：原本傳 `cfg.panel_whitelist_hues`
  → 改傳 `game_data.effective_whitelist_hues(cfg.detection_min_tier, cfg.panel_whitelist_hues)`

**一致性保證**：兩條色相路＋名字閘三者門檻一致 → Exotic 在三條路同時降級、
Exquisite+ 在三條路同時生效。交叉驗 `if ores and not hue_hits` 只在真正
OCR 誤讀時否決，不會因門檻不一致而假性觸發。

**門檻高於 Transcendent 時**：所有量測色相都降級，白名單色相為空。
名字閘仍正確分類（Enigmatic+ 礦在 `rare_ores.json`，classify 判 rare），
但色相交叉驗無法確認 → 救援被否決（保守方向：多交一次人工，安全）。

## 測試

- `classify_found_ore`：門檻 Exotic（預設）→ Exotic 判 rare；門檻 Exquisite
  → Exotic 判 common、Exquisite 判 rare
- 模糊路徑同理（Exotic 模糊命中 → 門檻以上 rare_fuzzy、以下 common）
- `effective_whitelist_hues("Exquisite", ...)` → 不含 46（Exotic）
- `effective_low_tier_hues("Exquisite", ...)` → 含 46（Exotic 降級）
- 門檻 Exotic（預設）→ effective hues 與 base 相同（向後相容）
- Discord `階級 Exquisite` 指令 → set_detection_min_tier 被呼叫＋持久化
- 網頁 POST `detection_min_tier` → setattr + set_detection_min_tier + save_overrides
- `validate_value`：合法 tier True、亂碼 False
- 持久化 round-trip：save → load → set_detection_min_tier
