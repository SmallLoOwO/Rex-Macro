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
    # 2026-07-29：人確認過的**真陰性**——「這張圖裡真的什麼都沒有」。
    # 先前 schema 逼玩家畫方框才送得出去，於是空幀（tier0 活語料 96/161 是
    # `sweep_empty`）只能跳過，而跳過不留紀錄：事後分不出「看過、確認空」與
    # 「沒人看過」。負樣本正是調參最缺的（可用負樣本實測只有 7 張）。
    "沒東西": "no_target",
    "no_target": "no_target",
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
    {"false_negative", "false_positive", "should_reject_failed",
     "no_target", "unknown", None}
)

# 玩家看到什麼（2026-07-31）。**症狀不再由玩家挑**——玩家只描述畫面，症狀由
# 這張表配上「bot 當下的判定」推出來。
#
# 為什麼改：症狀那五顆按鈕裡，2（誤判）與 3（該拒沒拒）只在 bot 已經接受候選時
# 成立，玩家得先知道 bot 到底接受了沒才選得對——而那件事**快照 label 早就記著**
# （`sweep_accepted_dir4_947_520` / `sweep_empty_dir4`），沒有理由叫玩家猜。
# 使用者原話：「給予的圖片大部分只有 1 與 4，所以我也不知道 2 與 3 的差別」——
# 實測佇列 227 張裡 220 張是 `sweep_empty`（bot 全拒），2/3 根本輪不到。
#
# 順帶保住 2 vs 3 的資訊：`decoy`（有東西但不是礦框）與 `empty`（真的空）在
# bot 拒絕時都是真陰性 `no_target`，但 `observation` 欄位仍原樣存進 json——
# 「像礦的地形」是調門檻最值錢的硬負樣本，跟空幀不是同一種負樣本。
# 2026-08-06 使用者要求移除「不確定」按鈕（幾乎不會用到）。SYMPTOM_BY_OBSERVATION
# 不再含 ``"unsure"`` 鍵——``symptom_from_observation`` 對未認得的 observation 一律
# 回 ``"unknown"``（含舊資料裡的 ``"unsure"``），行為與舊 dict 查出來的值完全相同。
OBSERVATIONS: tuple[str, ...] = ("ore", "decoy", "empty")

SYMPTOM_BY_OBSERVATION: dict[str, dict[str, str | None]] = {
    # 有礦框：bot 接受＝判對（對照組，symptom 留空）；沒接受＝漏判
    "ore": {"accepted": None, "rejected": "false_negative"},
    # 像礦的地形／裝備／UI：bot 接受＝該拒沒拒；沒接受＝bot 判對的真陰性
    "decoy": {"accepted": "should_reject_failed", "rejected": "no_target"},
    # 什麼都沒有：bot 接受＝誤判；沒接受＝真陰性
    "empty": {"accepted": "false_positive", "rejected": "no_target"},
}


def symptom_from_observation(observation: str | None,
                             bot_verdict: str | None) -> str | None:
    """（玩家看到什麼, bot 當下判定）→ 症狀 enum。

    `bot_verdict` 只認 ``"accepted"``；其餘（``"rejected"``／``None``／沒記錄）
    一律走 rejected 那一欄——**沒有證據說 bot 接受過，就不要記一個需要它接受才
    成立的症狀**（誤判／該拒沒拒）。判決真偽由 `/api/annotate` 回應裡的
    `annotation_verdict` 用現行偵測器重跑，這裡不必也不該猜。

    認不得的 observation → ``"unknown"``（等同玩家說不確定），不會靜默變成別的。
    """
    column = SYMPTOM_BY_OBSERVATION.get(observation or "")
    if column is None:
        return "unknown"
    return column["accepted" if bot_verdict == "accepted" else "rejected"]


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
    "no_target": False,             # 「這張真的沒東西」（人確認過的真陰性）
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


# 遊戲官方階梯（2026-07-31 使用者指正：**Exotic 才是最低階**，先前排在 Exquisite
# 之後）。這件事資料本身排不出來——tier 的 rarity 區間彼此重疊，取最小值說
# Exquisite 低（111,112 vs 180,000）、取最大值說 Exotic 低（15,001,500 vs
# 7,500,000），沒有一個統計量能還原官方階梯。玩家知道遊戲怎麼排，就寫死。
# 不在這張表裡的 tier（遊戲更新新增）排在最後，彼此按最小 rarity 排。
_TIER_LADDER: tuple[str, ...] = (
    "Exotic", "Exquisite", "Transcendent", "Enigmatic",
    "Unfathomable", "Otherworldly", "Imaginary",
)


def rarity_choices_from_game_data(
    special_ores: list[dict],
) -> tuple[list[str], list[str]]:
    """從 game_data 的礦物清單撈 tier，**按稀有度由低到高**排；variants 固定三個。

    先前用 ``sorted(tiers)``＝字母序，玩家看到的是
    ``Enigmatic, Exotic, Exquisite, Imaginary, ...``——跟遊戲裡的階級毫無關係，
    標註時等於在一排無序名詞裡找字。現在照 `_TIER_LADDER` 的官方階梯排。

    special_ores 條目可能缺 tier 或 tier=None/空字串——一律略過。
    回傳 (tiers, variants)，variants 永遠是 ``["原色", "Spectral", "Ionized"]``。
    """
    mins: dict[str, float] = {}
    for entry in special_ores or []:
        if not isinstance(entry, dict):
            continue
        tier = entry.get("tier")
        if not (isinstance(tier, str) and tier):
            continue
        rarity = entry.get("rarity")
        prev = mins.get(tier, float("inf"))
        if isinstance(rarity, (int, float)) and not isinstance(rarity, bool):
            prev = min(prev, float(rarity))
        mins[tier] = prev

    def _key(tier: str):
        try:
            return (_TIER_LADDER.index(tier), 0.0, tier)
        except ValueError:            # 階梯外的新 tier：排最後，內部按入門價
            return (len(_TIER_LADDER), mins[tier], tier)

    return sorted(mins, key=_key), list(_VARIANTS)


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

    必須有：``image`` (str) / ``source`` (dict, kind ∈ {"auto","manual"})。

    ``annotation`` (dict, type="square" + cx/cy/size:int)：除 ``no_target`` 之外
    必須帶。``no_target`` 標的是「整張圖裡什麼都沒有」，玩家不該被逼畫一個假框
    才送得出去；這時 ``annotation`` 允許缺，存檔走 corpus/negatives 而非 fixtures。

    選填：``tier`` / ``variant`` / ``mineral`` / ``observation`` /
    ``related_incident`` 存在時非 None 必須是 str；``symptom`` 非 None 必須是
    _SYMPTOM_VALUES 之一。

    ``observation``（2026-07-31）＝玩家原話「我看到什麼」（ore/decoy/empty/
    unsure）。症狀是它推出來的（`symptom_from_observation`），但推導**不可逆**
    ——`decoy` 與 `empty` 在 bot 拒絕時都推成 `no_target`，而「像礦的地形」正是
    調門檻最值錢的硬負樣本。存原話才留得住這個差別。
    """
    if not isinstance(ann, dict):
        return False

    # required: image
    if not isinstance(ann.get("image"), str):
        return False

    # required: source.kind
    src = ann.get("source")
    if not isinstance(src, dict):
        return False
    if src.get("kind") not in _SOURCE_KINDS:
        return False

    # optional strings: tier / variant / mineral / observation / related_incident
    for k in ("tier", "variant", "mineral", "observation", "related_incident"):
        v = ann.get(k)
        if v is not None and not isinstance(v, str):
            return False

    # symptom: None 或標準 enum
    if ann.get("symptom") not in _SYMPTOM_VALUES:
        return False

    # annotation: no_target 允許缺；其餘必須是 square schema
    if ann.get("symptom") == "no_target":
        return True
    a = ann.get("annotation")
    if not isinstance(a, dict):
        return False
    if a.get("type") != "square":
        return False
    for k in ("cx", "cy", "size"):
        v = a.get(k)
        if isinstance(v, bool) or not isinstance(v, int):
            return False

    return True
