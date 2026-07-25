"""玩家設定面板：config_overrides.json 讀寫 + 套用 Config（純函式）。

spec §6：玩家在網頁改的 4 個白名單欄位，即時 runtime 生效 + 寫進
`logs/config_overrides.json` 持久化；bot 啟動時讀回套用。

不動 config.py / .env（機密、事故根因記錄）；用獨立 JSON 疊加在 default + env 之上。

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
                   current_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """合併新欄位寫回 JSON；回新 dict（不 mutate current_overrides）。

    current_overrides=None（新預設）= 重讀檔案（消除 caller 維護 in-memory cache 的需求）。
    仍接受 caller 注入 current_overrides（向下相容既有測試）。

    寫檔用 tempfile + os.replace 原子替換，避免寫到一半被中斷導致檔案損壞。
    """
    base = current_overrides if current_overrides is not None else load_overrides(path)
    new_overrides = dict(base)
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
    applied: list[str] = []
    for field, value in overrides.items():
        if not is_web_configurable(field):
            continue
        if not validate_value(field, value):
            continue
        setattr(config, field, value)
        applied.append(field)
    return applied
