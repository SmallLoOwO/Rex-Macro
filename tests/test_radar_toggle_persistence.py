"""D2 雷達連續使用開關的跨 session 持久化（2026-07-26 使用者要求）。

需求：Discord `掃描/削洞 [開|關]` 切換後，重啟腳本要記住——不可每次重啟都退回 cfg 預設 False，
否則使用者以為還開著卻沒在用。沿用 keep_ores.json 模式：JSON 檔在 repo 根目錄、
檔案缺／損壞退回 cfg 預設、Discord 指令後即時 save。
"""
import json

from miningbot.config import DEFAULT as cfg
from miningbot.main import Bot


class _Recorder:
    def __init__(self):
        self.records = []

    def info(self, msg, *args):
        self.records.append(("INFO", msg % args if args else msg))

    def warning(self, msg, *args):
        self.records.append(("WARNING", msg % args if args else msg))

    def error(self, msg, *args):
        self.records.append(("ERROR", msg % args if args else msg))


def _bot_with_tmp_path(tmp_path, monkeypatch):
    """Bot 繞過 __init__，radar_toggle 檔指向 tmp_path（不動 repo）。"""
    bot = Bot.__new__(Bot)
    bot.logger = _Recorder()
    path = tmp_path / "radar_toggle.json"
    monkeypatch.setattr(bot, "_radar_toggle_path", lambda: str(path))
    return bot, path


def test_load_returns_cfg_defaults_when_file_missing(tmp_path, monkeypatch):
    """首輪（檔案不存在）→ 用 cfg 預設值，不拋例外。"""
    bot, _ = _bot_with_tmp_path(tmp_path, monkeypatch)
    loaded = bot._load_radar_toggle()
    assert loaded == {"scan": cfg.radar_scan_repeat_enabled,
                      "cave": cfg.radar_cave_skim_enabled}


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    """Discord 改了 → save → 重啟 load → 開關狀態保留。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    bot._radar_toggle = {"scan": True, "cave": False}
    bot._save_radar_toggle()

    # 模擬「重啟」：新建 Bot、載入同一檔
    bot2, _ = _bot_with_tmp_path(tmp_path, monkeypatch)
    loaded = bot2._load_radar_toggle()
    assert loaded == {"scan": True, "cave": False}


def test_load_falls_back_to_cfg_when_json_corrupt(tmp_path, monkeypatch):
    """JSON 損壞 → 退回 cfg 預設，不讓腳本啟動失敗（比照 keep_ores 容錯）。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    path.write_text("{not valid json", encoding="utf-8")
    loaded = bot._load_radar_toggle()
    assert loaded == {"scan": cfg.radar_scan_repeat_enabled,
                      "cave": cfg.radar_cave_skim_enabled}


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path, monkeypatch):
    """只信任 {scan, cave}；其他 key 忽略，缺的 key 用 cfg 預設補。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    path.write_text(json.dumps({"scan": True, "bogus": "x"}), encoding="utf-8")
    loaded = bot._load_radar_toggle()
    assert loaded == {"scan": True, "cave": cfg.radar_cave_skim_enabled}
    assert "bogus" not in loaded


def test_load_rejects_non_bool_values(tmp_path, monkeypatch):
    """非 bool 值（檔案被改壞／手編失誤）→ 該欄位退回 cfg 預設。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    path.write_text(json.dumps({"scan": "yes", "cave": 1}), encoding="utf-8")
    loaded = bot._load_radar_toggle()
    assert loaded == {"scan": cfg.radar_scan_repeat_enabled,
                      "cave": cfg.radar_cave_skim_enabled}


def test_load_logs_when_loaded_differs_from_defaults(tmp_path, monkeypatch):
    """載入值與 cfg 預設不同時要 log——啟動訊息讓使用者看得到「持久化還在生效」。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    path.write_text(json.dumps({"scan": True, "cave": True}), encoding="utf-8")
    bot._load_radar_toggle()
    info_msgs = [r[1] for r in bot.logger.records if r[0] == "INFO"]
    assert any("scan=True" in m and "cave=True" in m for m in info_msgs), \
        f"應 log 載入值，記錄：{info_msgs}"


def test_load_silent_when_file_matches_defaults(tmp_path, monkeypatch):
    """檔案值 == cfg 預設時不必 log（首次 save 後沒切換過的情況）。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    path.write_text(json.dumps({"scan": False, "cave": False}), encoding="utf-8")
    bot._load_radar_toggle()
    info_msgs = [r[1] for r in bot.logger.records if r[0] == "INFO"]
    assert not any("雷達連續使用開關載入" in m for m in info_msgs)


def test_save_failure_does_not_raise(tmp_path, monkeypatch):
    """存檔失敗（路徑不可寫）只 log error，不拋——持久化是 best-effort。"""
    bot, path = _bot_with_tmp_path(tmp_path, monkeypatch)
    # 指向一個不存在的目錄下的檔案 → open(w) 會失敗
    monkeypatch.setattr(bot, "_radar_toggle_path",
                        lambda: str(tmp_path / "no_such_dir" / "radar_toggle.json"))
    bot._radar_toggle = {"scan": True, "cave": False}
    bot._save_radar_toggle()      # 不拋
    errors = [r[1] for r in bot.logger.records if r[0] == "ERROR"]
    assert any("存檔失敗" in m for m in errors), f"應 log 存檔失敗，記錄：{bot.logger.records}"
