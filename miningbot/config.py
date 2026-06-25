import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()  # 從專案根目錄的 .env 載入（放 Discord token 等機密）
except ImportError:
    pass

@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

@dataclass
class Config:
    # 視窗
    window_title: str = "Roblox"
    screen_w: int = 1920
    screen_h: int = 1080

    # 偵測區域（1920x1080、視窗化最大化實測；切全螢幕需整體上移約 30px 標題列高度）
    chill_text_region: Region = field(default_factory=lambda: Region(360, 42, 1440, 52))  # 頂部事件列（chill/事件文字）實測
    chat_region: Region = field(default_factory=lambda: Region(0, 110, 460, 280))   # 左上事件/掉落訊息（估計，見到訊息再微調）
    # buff 會疊加 → 瓶子位置會變，但都在這條「效果列」內；在整條裡搜尋瓶子形狀
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 935, 665, 135))
    boost_edge_threshold: float = 0.40           # 瓶子邊緣比對門檻（校準時調）
    boost_cooldown_s: float = 5.0                # 按 D5 後多久內不重按（等瓶子出現，避免狂按）

    # D4 活動：定時右鍵刷新事件（不斷換事件 → 多製造 chill 機會）
    activity_reroll_enabled: bool = True
    activity_reroll_interval_s: float = 30.0     # 每隔多久刷新一次（抓 D4 冷卻附近）
    window_focus_check_enabled: bool = False     # 失焦復原偵測（未校準前先關，避免誤判狂 refocus）
    window_focus_pixel: tuple = (10, 940)        # 失焦復原偵測點（待校準）
    window_focus_color: int = 0x2B2B2B           # 佔位，校準時量測
    slot_pixel: tuple = (1011, 845)
    slot_color: int = 0x232323

    # 音訊
    chill_audio_path: str = "assets/chill_reference.wav"
    audio_match_threshold: float = 0.55          # 交叉相關門檻，實測調
    audio_sample_rate: int = 48000
    audio_window_seconds: float = 1.5

    # 採集
    marker_color_invariant: bool = True          # 標記用「形狀/邊緣」比對（顏色會變時必須開）
    marker_edge_threshold: float = 0.45          # 邊緣比對門檻（校準時調）
    marker_scales: tuple = (0.6, 0.8, 1.0, 1.2, 1.5)  # 多尺度比對：模板（含 wiki 圖）尺寸對不準時自動試縮放
    marker_dir: str = "assets/markers"           # 多階級標記模板資料夾（每個階級一張 png；用 fetch_trackers 下載）
    aim_center_tolerance_px: int = 25            # 準心對準容差
    mouse_aim_gain: float = 0.2                  # 像素偏移→滑鼠相對位移的縮放（校準時調，避免過衝）
    vertical_extreme_ratio: float = 0.35         # 標記 y 偏離中心超過此比例→頭頂/腳下
    max_aim_rotations: int = 8                   # 水平轉視角上限
    harvest_verify_timeout_s: float = 6.0
    max_harvest_attempts: int = 3

    # 卡住（用中央遊戲區判斷，避開左下角的狀態小窗，免得小窗變動誤判成「有進度」）
    stuck_timeout_s: float = 60.0
    stuck_frame_diff_threshold: float = 2.0      # 平均像素差低於此視為無變化
    stuck_region: Region = field(default_factory=lambda: Region(560, 200, 800, 520))

    # 狀態小窗（置頂顯示機器人在做什麼；放左下角避開偵測區，採集時自動隱藏）
    hud_enabled: bool = True
    hud_x: int = 12
    hud_y: int = 905

    # OCR
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    chill_phrases: tuple = (
        "a chill goes down your spine",
        "your heart skips a beat",
    )
    found_keywords: tuple = ("has found", "found a")

    # 記錄 / 診斷
    log_dir: str = "logs"
    log_level: str = "INFO"                      # 改 "DEBUG" 可看每幀偵測細節（音訊分數、標記座標等）
    save_snapshots: bool = True                  # 關鍵事件（chill/失敗/卡住/成功）自動存畫面截圖以利除錯
    heartbeat_interval_s: float = 30.0           # 長時間等待時，每隔多久記一筆「還活著」的心跳

    # 熱鍵（控制權）
    hotkey_emergency_stop: str = "ctrl+q"        # 緊急停止（不結束程式）：放開所有按鍵，等 Q 重新啟動
    hotkey_pause: str = "q"                      # 手動切換 暫停 ↔ 繼續（也用於緊急停止/人工介入後重啟）
    hotkey_quit: str = "f12"                     # 真正結束程式

    # Discord（Phase 2）— token 從 .env 讀，不寫死在程式碼
    discord_webhook_url: str = ""
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))

DEFAULT = Config()
