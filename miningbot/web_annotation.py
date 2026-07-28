"""素材標註 schema + helpers（純函式）。

spec §5：每張標註素材是兩個檔——``<name>.png``（裁好的 crop）+ ``<name>.json``
（結構化 metadata）。本模組只負責**建**與**驗證**那份 metadata dict；不讀寫檔。

重要原則（spec §0、§5）：
- 玩家只給症狀（漏判/誤判/...），不給根因——根因屬 docs/incidents.md 範疇。
- 沒問題的素材（confirmed true positive）``symptom`` 留 ``None``，當對照組。
- 不放鬆偵測門檻；純函式優先、I/O 邊界不交叉。
"""
from __future__ import annotations

from typing import Any

# 症狀 enum：玩家可見中文/英文別名 → 標準字串；未認得的字串 → None（素材留空，
# 玩家顯式選「不確定」時才填 unknown）。
_SYMPTOM_MAP: dict[str | None, str | None] = {
    "漏判": "false_negative",
    "FN": "false_negative",
    "false_negative": "false_negative",
    "誤判": "false_positive",
    "FP": "false_positive",
    "false_positive": "false_positive",
    "該拒沒拒": "should_reject_failed",
    "should_reject_failed": "should_reject_failed",
    "不確定": "unknown",
    "unknown": "unknown",
    "": None,
    None: None,
}

# source.kind 只接受這兩個：auto = 玩家介入時自動收集；manual = 玩家事後手動標。
_SOURCE_KINDS: frozenset[str] = frozenset({"auto", "manual"})

# 變體固定清單（spec §5）：遊戲機制只有原色 / Spectral / Ionized。
# 「原色」=無變體；玩家標註時如果選「原色」→ build_annotation 收到 variant=None。
_VARIANTS: list[str] = ["原色", "Spectral", "Ionized"]

# validate_annotation 接受的症狀值（None 或標準 enum）
_SYMPTOM_VALUES: frozenset[str | None] = frozenset(
    {"false_negative", "false_positive", "should_reject_failed", "unknown", None}
)


def normalize_symptom(s: str | None) -> str | None:
    """把玩家可見的症狀文字（「漏判」/「誤判」/FN/FP/...）對應到標準 enum。

    未認得的字串（不是任何別名也不是標準 enum）→ ``None``：避免玩家手打錯字
    變成未知症狀；玩家想要「不確定」必須顯式選「不確定」。
    """
    return _SYMPTOM_MAP.get(s)


# 「這張還沒有玩家標籤」的哨符（失敗佇列那類唯讀頁用）。**不可以用 `None` 代表**
# ——`None` 在標註 schema 裡是「對照組：玩家確認過的真框」，兩者語意相反；混用會讓
# 唯讀頁憑空回一個「與不存在的標註不一致」的 agree 給讀 JSON 的 agent。
NO_LABEL = "__no_label__"

# 玩家標的症狀，換算成「這張圖裡到底有沒有目標」。偵測器 accepted/rejected 只要
# 跟這個對得上就是一致。`unknown` 與 `NO_LABEL` 無從比較 → None。
_SYMPTOM_EXPECTS_TARGET: dict[str | None, bool | None] = {
    None: True,                     # 對照組：玩家確認過的真框（symptom 留空）
    "false_negative": True,         # 「有框，你沒抓到」
    "false_positive": False,        # 「沒框，你卻抓了」
    "should_reject_failed": False,  # 「該拒沒拒」
    "unknown": None,
}


def verdict_agrees(detector: str, symptom: str | None):
    """現行偵測器判定 vs 玩家標的症狀：一致 True／不一致 False／無從比較 None。

    這是標註即時回判決的核心：玩家標完的當下就知道**這張圖是不是真的暴露 bug**，
    還是偵測器其實已經修好了。沒有這個回饋，標註對玩家零回報——三個月只標了 2 張。

    例：玩家標「漏判」（他說有框）而偵測器 `rejected`（它說沒有）→ 兩邊看到的
    不是同一件事 → 不一致，bug 確實還在。
    """
    expects = _SYMPTOM_EXPECTS_TARGET.get(symptom)
    if expects is None:
        return None
    return (detector == "accepted") == expects


def rarity_choices_from_game_data(
    special_ores: list[dict],
) -> tuple[list[str], list[str]]:
    """從 game_data 的礦物清單撈 tier 唯一排序字串；variants 固定四個。

    special_ores 條目可能缺 tier 或 tier=None/空字串——一律略過。
    回傳 (tiers, variants)，variants 永遠是 ``["原色", "Spectral", "Ionized"]``。
    """
    tiers: set[str] = set()
    for entry in special_ores or []:
        if not isinstance(entry, dict):
            continue
        tier = entry.get("tier")
        if isinstance(tier, str) and tier:
            tiers.add(tier)
    return sorted(tiers), list(_VARIANTS)


def cell_crop_box(frame_w: int, frame_h: int, cx: int, cy: int,
                  cols: int = 6, rows: int = 4) -> tuple[int, int, int, int]:
    """以 (cx, cy) 為中心裁一塊「粗格大小」的框；回 (x0, y0, x1, y1)。

    素材的 PNG 必須是**檢測函式吃的格式**（spec §5：「裁好的 crop（檢測函式輸入
    格式）」），對 `aim/` 而言就是 320×270 的粗格裁圖——`detect_tracker_core`
    實機吃的正是這個尺寸，既有 fixture（`101_core_green_c1.png` 等）也都是。
    存全幀或存一個貼著框邊的小圖都不能直接餵給它：前者尺寸不對，後者看不到
    旁邊的地形，而 `aim/README.md` 的兩側夾正是靠「框心 vs 亮綠地形」的面積差
    ——沒有周邊脈絡就無從判斷。

    cols/rows 預設 6×4 是 main.py 自動收集路徑既有的切法
    （`cfg.screen_w // 6`、`cfg.screen_h // 4` → 1920/1080 下即 320×270），
    這裡改吃畫面尺寸而不是 Config，讓網頁路徑不必抓 cfg 也能算。

    邊界行為刻意與 main.py 既有寫法逐字一致（先 max(0, ...) 再
    min(邊界, x0 + 寬)）：貼著畫面右／下緣時裁圖會**比一格窄**，而不是把
    起點往回推。兩條路徑必須產出同形狀的素材，否則同一批 fixture 尺寸不一。
    """
    cw = max(1, frame_w // cols)
    ch = max(1, frame_h // rows)
    x0 = max(0, int(cx) - cw // 2)
    y0 = max(0, int(cy) - ch // 2)
    x1 = min(frame_w, x0 + cw)
    y1 = min(frame_h, y0 + ch)
    return x0, y0, x1, y1


def build_annotation(
    image: str,
    annotation: dict,
    tier: str | None,
    variant: str | None,
    mineral: str | None,
    source: dict,
    symptom: str | None,
    related_incident: str | None,
) -> dict:
    """建素材 .json 的 canonical dict（spec §5 schema）。

    symptom 會透過 normalize_symptom 正規化——玩家從 UI 選「漏判」也會被轉成
    ``"false_negative"``；未認得的字串變成 ``None``。

    不做深 copy：annotation / source dict 直接放進結果；caller 不要事後改 input
    污染結果（測試已驗證 input 不會被本函式 mutate）。
    """
    return {
        "image": image,
        "annotation": dict(annotation) if isinstance(annotation, dict) else annotation,
        "tier": tier,
        "variant": variant,
        "mineral": mineral,
        "source": dict(source) if isinstance(source, dict) else source,
        "symptom": normalize_symptom(symptom),
        "related_incident": related_incident,
    }


def validate_annotation(ann: Any) -> bool:
    """驗證 annotation dict schema（required keys + 型別）。

    必須有：``image`` (str) / ``annotation`` (dict, type="square" + cx/cy/size:int)
    / ``source`` (dict, kind ∈ {"auto","manual"})。

    選填：``tier`` / ``variant`` / ``mineral`` / ``symptom`` / ``related_incident``
    存在時非 None 必須是 str；``symptom`` 非 None 必須是 _SYMPTOM_VALUES 之一。
    """
    if not isinstance(ann, dict):
        return False

    # required: image
    if not isinstance(ann.get("image"), str):
        return False

    # required: annotation square schema
    a = ann.get("annotation")
    if not isinstance(a, dict):
        return False
    if a.get("type") != "square":
        return False
    for k in ("cx", "cy", "size"):
        v = a.get(k)
        # bool 是 int 子類別但語意不該被當座標；明確排除
        if isinstance(v, bool) or not isinstance(v, int):
            return False

    # required: source.kind
    src = ann.get("source")
    if not isinstance(src, dict):
        return False
    if src.get("kind") not in _SOURCE_KINDS:
        return False

    # optional strings: tier / variant / mineral / related_incident
    for k in ("tier", "variant", "mineral", "related_incident"):
        v = ann.get(k)
        if v is not None and not isinstance(v, str):
            return False

    # symptom: None 或標準 enum
    if ann.get("symptom") not in _SYMPTOM_VALUES:
        return False

    return True
