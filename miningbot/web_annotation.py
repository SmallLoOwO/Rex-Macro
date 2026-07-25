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
