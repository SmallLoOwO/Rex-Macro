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
    chill_text_region: Region = field(default_factory=lambda: Region(360, 44, 1220, 37))  # 頂部事件列深色橫幅（實測裁緊：置中 960、只留深色框 y43-82；減 ~40% 像素加速 OCR）
    chat_region: Region = field(default_factory=lambda: Region(0, 110, 460, 280))   # 左上事件/掉落訊息（估計，見到訊息再微調）
    # 採集放棄 NEEDS_HUMAN 附的左側「前/後對比」裁圖：拆成「聊天（寬短）」與「背包（窄高）」兩區，
    # 各自更貼近 Discord 縮圖比例、砍掉右側沒用的粉紅場景（見 2026-07-02 spec 需求 A）。
    # before＝本輪 _pre_scan_ref、after＝放棄當下；左側 UI 是螢幕覆蓋層、不隨鏡頭角度變 → 前後同框
    # 可直接對比「礦是否已被採走」（新 has-found 行 / 背包數量增加＝已採到）。座標實機校準自 logs H010 d3_fire。
    chat_review_region: Region = field(default_factory=lambda: Region(0, 110, 460, 280))     # 左上 has-found 聊天（= chat_region；最新行在底部，勿縮短高度否則漏掉最新 has-found）
    backpack_review_region: Region = field(default_factory=lambda: Region(0, 395, 226, 335)) # 左下 NORMAL 背包「上半」：面板依稀有度排序（Exquisite→Mythic→Surreal→Master→Rare），新採到的礦（count=1）浮最上面；h335 涵蓋到 Surreal 帶 1-2 行 Master，Discord 縮圖才夠大（2026-07-03 需求：舊 h670 全清單縮圖看不清、下半 Rare 橙黃區無關採集比對）
    # buff 會疊加 → 瓶子位置會變，但都在這條「效果列」內；在整條裡搜尋瓶子形狀
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 935, 665, 135))
    boost_edge_threshold: float = 0.40           # 瓶子邊緣比對門檻（校準時調）
    boost_cooldown_s: float = 5.0                # 按 D5 後多久內不重按（等瓶子出現，避免狂按）
    boost_check_interval_s: float = 0.2          # boost 高頻偵測「不空轉」：boost 到期→立刻補，越快偵測瓶子消失越好（提早補無意義且浪費換道具時間，見 2026-07-02 spec #4 方案 A）
    boost_buff_scales: tuple = (1.0,)            # boost 瓶子＝固定尺寸 UI → 單尺度即可（~56ms/次），高頻掃描才不吃 CPU（D4 續用 buff_scales）

    # D4 活動：右鍵刷新事件（不斷換事件 → 多製造 chill 機會）
    # 偵測右下角 D4「冷卻圖示」不在 = 冷卻好 → 就用（避免能用卻沒用）。
    # 缺冷卻圖模板時退回定時模式（activity_reroll_interval_s）當後備。
    activity_reroll_enabled: bool = True
    activity_cooldown_template: str = "assets/d4_cooldown.png"  # D4 冷卻圖示模板（用 capture_template 擷取）
    activity_cooldown_edge_threshold: float = 0.40             # D4 冷卻圖示邊緣比對門檻（校準時調）
    activity_cooldown_grace_s: float = 3.0                     # 按 D4 後等冷卻圖示出現的寬限（避免重複按）
    activity_reroll_interval_s: float = 30.0                   # 後備：無冷卻圖模板時每隔多久刷新一次
    activity_check_interval_s: float = 3.0                     # D4 冷卻偵測節流：比 boost 更疏（D4 冷卻更長，掃更疏即可）
    # 視窗跑位偵測（item ④）：用 Win32 查 Roblox 視窗「前景/位置/大小」，相對啟動時量到的
    # 基準判斷是否跑掉（失焦或被移動/縮放）→ 自動重新聚焦+初始化。用基準相對比較而非寫死
    # 1920x1080，因 DPI 縮放會讓 GetWindowRect 回報縮放後座標（實測此機 125% → 1536x864）。
    window_check_enabled: bool = True
    window_check_interval_s: float = 1.0         # 多久查一次視窗狀態（Win32 很快，節流即可）
    window_pos_tolerance_px: int = 6             # 位置偏移容差（相對基準）
    window_size_tolerance_px: int = 8            # 大小偏移容差（相對基準）
    slot_pixel: tuple = (1011, 845)
    slot_color: int = 0x232323

    # 音訊
    chill_audio_path: str = "assets/chill_reference.wav"  # 單一參考（後備；chill_refs 夾為空時用）
    chill_refs_dir: str = "assets/chill_refs"    # 多參考集資料夾：放各種 chill 實錄裁片（取最高分）。
                                                 # 實測同樣是清楚 chill 對單一參考飄 0.15-0.87、至少 3 種不同音效→單參考必漏。
                                                 # 新 chill 漏抓時：把 logs/snapshots 的 audiochg_*.wav 裁片丟進來即可擴充。
    audio_match_decimate: int = 8                # 比對前抽樣加速倍率。2026-07-04 參考集 6→12 個後
                                                 # k=4 一輪 ~312ms > 0.3s 間隔必積壓 → k=8 ~131ms；
                                                 # 20 個實錄驗證 k=4/k=8 分數差 ≤0.007（距門檻 0.25 很遠）
    audio_match_threshold: float = 0.25          # 交叉相關門檻。多參考取 max：命中任一已知 chill 即觸發。
                                                 # 真 chill 對自己的參考 ~1.0、靜音約 0.01；0.25 遠離雜訊（誤觸再往上調）
    chill_require_ocr: bool = False              # 是否還要 OCR 文字二次確認（OCR 不穩/視窗化時設 False，只靠音訊）
    audio_sample_rate: int = 48000
    audio_window_seconds: float = 1.5
    audio_score_interval_s: float = 0.3            # 交叉相關計算間隔（秒）——太大=偵測延遲，太小=音訊執行緒積壓
    # 音訊變動記錄器：score 越過此觀察門檻（低於觸發門檻）就存音訊+記一筆，供診斷沒觸發的 chill / 累積樣本
    audio_event_record: bool = True              # 是否啟用「音訊明顯變動就記錄」
    audio_event_threshold: float = 0.15          # 觀察門檻（> 雜訊 0.01、< 觸發 0.25）；上升緣才記，不重複洗檔

    # 採集
    marker_color_invariant: bool = True          # 標記用「形狀/邊緣」比對（顏色會變時必須開）
    marker_edge_threshold: float = 0.45          # 邊緣比對門檻（校準時調）
    marker_scales: tuple = (0.6, 0.8, 1.0, 1.2, 1.5)  # 多尺度比對：模板（含 wiki 圖）尺寸對不準時自動試縮放
    buff_scales: tuple = (0.9, 1.0, 1.1)         # buff/冷卻圖示是固定尺寸 UI（boost 瓶子/D4 Used）→ 少尺度即可；marker_scales 的 5 尺度是給會變大小的追蹤框，對固定 UI 是浪費（實測 5→1 尺度快 4x，可再降成 (1.0,)）
    marker_dir: str = "assets/markers"           # 多階級標記模板資料夾（每個階級一張 png；用 fetch_trackers 下載）
    # 混合偵測：HSV 快速定位 + 實機裁圖在小 ROI 做外框形狀確認（拒「有色但非追蹤框形狀」的假陽性）
    tracker_shape_confirm: bool = True           # 開啟形狀確認（需 assets/markers 內有實機裁圖；無則自動退回純 HSV）
    tracker_shape_threshold: float = 0.42        # 外框邊緣相關度門檻（confirmed）；實機真框 edge≥0.43、裝備假陽性≤0.30 中間有 gap，0.42 收「被角色擋到角」的近失綠框(173709)而不誤收裝備（hard_floor 0.30 + colored>0.40 仍守門）
    tracker_shape_scales: tuple = (0.7, 1.0, 1.4)  # 形狀確認用尺度（框置中後尺寸穩定，3 尺度即可）
    tracker_shape_roi_px: int = 160              # 在 HSV 候選周圍裁多大 ROI 做形狀確認
    tracker_shape_hard_floor: float = 0.30       # edge 低於此值直接拒（soft filter 不救）；實測裝備誤判≈0.16/0.25/0.26、真追蹤框≥0.44（2026-06-28 由 0.25→0.30 擋下夜間兩次 borderline 裝備誤射）
    tracker_shape_early_exit: float = 0.60       # sweep 早停：某方位雙幀穩定且 edge≥此值（遠高於裝備上限 0.26）→ 直接確定、免掃完剩餘方位/免轉回 verify（實測真框 0.54-1.00）
    tracker_margin_frac: float = 0.02            # find_tracker 邊緣排除帶（實戰值；vision 函式預設仍 0.10）。H019(1862,418)/H026(1288,1020) 兩次真框都被 0.10 的帶擋掉——D5 到期 FOV 收縮（以中心為錨 ~2.6x 縮放）把框推到邊緣，且 yaw 旋轉不改 y、底緣框 8 方位永遠在帶內。0.02 收得回兩顆（回歸 fixture：edge_clipped/bottom_edge_tracker_scene.png）且對全 fixture 集無新假陽性；邊緣雜訊由 preexist 差分/colored_frac/形狀確認擋
    boost_fov_settle_s: float = 1.5              # 採集中補 D5 後等 FOV 展開的時間（H026 boost 守門；補完必須重抓幀才能偵測/開火）
    aim_center_tolerance_px: int = 25            # 準心對準容差
    mouse_aim_gain: float = 0.2                  # 像素偏移→滑鼠相對位移的縮放（校準時調，避免過衝）
    vertical_extreme_ratio: float = 0.35         # 標記 y 偏離中心超過此比例→頭頂/腳下
    max_aim_rotations: int = 8                   # 水平轉視角上限
    sweep_timeout_s: float = 30.0                # 全方位掃描階段時限（實測 8 方位 ~19s，留 1.5x 餘裕）
    harvest_verify_timeout_s: float = 45.0       # D3 開火+驗證階段時限（sweep 完成後才開始算）。一次 D3 嘗試實測 ~20s（聊天 3-pass OCR 滿版文字 ~10s＋開火序列 1.5s＋輪詢驗證），舊 15s 連一次都裝不下 → RETRY 後 1s 即超時交人工，5 次重試預算形同虛設（H015 根因之一）
    max_harvest_attempts: int = 5
    harvest_verify_window_s: float = 8.0         # D3 後輪詢驗證窗口（H015：框擊中後 2~10s 才消失、聊天成功行更晚到，單幀判定必假陰性）
    harvest_verify_poll_interval_s: float = 0.5  # 輪詢間隔（每輪本身含 find_tracker ~2s，這只是喘息 sleep）
    chat_change_mean_diff: float = 2.0           # 聊天裁圖平均像素差超過此值才重跑 OCR（角色靜止時無新訊息＝近乎逐位元相同）

    # 卡住（用中央遊戲區判斷，避開左下角的狀態小窗，免得小窗變動誤判成「有進度」）
    stuck_timeout_s: float = 60.0
    stuck_frame_diff_threshold: float = 2.0      # 平均像素差低於此視為無變化
    stuck_region: Region = field(default_factory=lambda: Region(560, 200, 800, 520))

    # 狀態小窗（置頂顯示機器人在做什麼；放左下角避開偵測區，採集時自動隱藏）
    hud_enabled: bool = True
    hud_x: int = 12
    hud_y: int = 905
    launch_countdown_s: int = 3           # 啟動倒數秒數（給時間切到 Roblox）；0 = 不倒數直接啟動

    # OCR
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    chill_phrases: tuple = (
        "a chill goes down your spine",
        "your heart skips a beat",
    )
    found_keywords: tuple = ("has found", "found a")
    # 特殊階（ionized / Spectral）聊天標記——這類礦物進「另一個背包」（左側 normal 面板看不到），
    # 只能靠聊天字樣辨識。採集成功時用差分判定是否為特殊階，供 Discord 通知/統計強調。
    special_keywords: tuple = ("ionized", "spectral")
    # 礦坑重置：頂部訊息列出現含這些關鍵字 → 進 RESET_WAIT（停下等你重新定位）
    reset_phrases: tuple = ("reset in", "will reset", "reset")
    reset_check_interval_s: float = 2.0          # 多久 OCR 一次頂部列找重置字樣（OCR 較慢，節流）

    # 記錄 / 診斷
    log_dir: str = "logs"
    log_level: str = "INFO"                      # 改 "DEBUG" 可看每幀偵測細節（音訊分數、標記座標等）
    save_snapshots: bool = True                  # 關鍵事件（chill/失敗/卡住/成功）自動存畫面截圖以利除錯
    heartbeat_interval_s: float = 30.0           # 長時間等待時，每隔多久記一筆「還活著」的心跳

    # 熱鍵（控制權）
    hotkey_emergency_stop: str = "ctrl+q"        # 只暫停（不結束程式、不繼續）：放開所有按鍵，等 Q 繼續
    hotkey_pause: str = "q"                      # 開關 暫停 ↔ 繼續（也用於人工介入/礦坑重置定位後重啟）
    hotkey_quit: str = "f12"                     # 真正結束程式
    antiafk_interval_s: float = 900.0            # 防掛機踢除：暫停中每 N 秒按一次 Space（預設 15 分鐘）

    # Discord（Phase 2）— token 從 .env 讀，不寫死在程式碼
    discord_webhook_url: str = ""
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    discord_poll_interval_s: float = 10.0       # Discord 命令輪詢間隔（秒）

DEFAULT = Config()
