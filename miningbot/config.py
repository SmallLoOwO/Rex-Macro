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

    # 偵測區域（視窗內相對座標，校準後覆寫）
    chill_text_region: Region = field(default_factory=lambda: Region(660, 20, 600, 60))
    chat_region: Region = field(default_factory=lambda: Region(0, 90, 440, 260))
    boost_indicator_region: Region = field(default_factory=lambda: Region(1380, 940, 430, 90))
    window_focus_pixel: tuple = (10, 940)        # 失焦復原偵測點
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
    aim_center_tolerance_px: int = 25            # 準心對準容差
    mouse_aim_gain: float = 0.2                  # 像素偏移→滑鼠相對位移的縮放（校準時調，避免過衝）
    vertical_extreme_ratio: float = 0.35         # 標記 y 偏離中心超過此比例→頭頂/腳下
    max_aim_rotations: int = 8                   # 水平轉視角上限
    harvest_verify_timeout_s: float = 6.0
    max_harvest_attempts: int = 3

    # 卡住
    stuck_timeout_s: float = 60.0
    stuck_frame_diff_threshold: float = 2.0      # 平均像素差低於此視為無變化

    # OCR
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    chill_phrases: tuple = (
        "a chill goes down your spine",
        "your heart skips a beat",
    )
    found_keywords: tuple = ("has found", "found a")

    # 熱鍵
    hotkey_pause: str = "f8"
    hotkey_resume_human: str = "f9"
    hotkey_quit: str = "f12"

    # Discord（Phase 2）— token 從 .env 讀，不寫死在程式碼
    discord_webhook_url: str = ""
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))

DEFAULT = Config()
