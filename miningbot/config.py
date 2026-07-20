import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()  # 從專案根目錄的 .env 載入（放 Discord token 等機密）
except ImportError:
    pass


def default_log_dir() -> str:
    """執行期資料預設放本機 AppData，避免 repo/OneDrive 同步大量快照。"""
    override = os.getenv("REX_MININGBOT_LOG_DIR")
    if override:
        return os.path.expandvars(os.path.expanduser(override))
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, "RexMacro", "logs")
    return "logs"


def resolve_log_dir(path: str, project_root: str | None = None) -> str:
    """Resolve runtime logs to one stable absolute directory."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(root, expanded))


def resolve_runtime_log_path(path: str, log_dir: str,
                             project_root: str | None = None) -> str:
    """Resolve legacy ``logs/...`` settings under the active log root."""
    expanded = os.path.expandvars(os.path.expanduser(path))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    normalized = os.path.normpath(expanded)
    head, tail = os.path.split(normalized)
    while head and os.path.basename(head):
        parent, name = os.path.split(head)
        if not parent:
            if os.path.normcase(name) == os.path.normcase("logs"):
                return os.path.normpath(os.path.join(log_dir, tail))
            break
        tail = os.path.join(name, tail)
        head = parent
    if os.path.normcase(normalized) == os.path.normcase("logs"):
        return os.path.normpath(log_dir)
    return resolve_log_dir(normalized, project_root)


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
    backpack_review_region: Region = field(default_factory=lambda: Region(0, 345, 226, 335)) # 左下 NORMAL 背包「上半」：面板依稀有度排序（Exquisite→Mythic→Surreal→Master→Rare），新採到的礦（count=1）浮最上面；h335 涵蓋到 Surreal 帶 1-2 行 Master，Discord 縮圖才夠大（2026-07-03 需求：舊 h670 全清單縮圖看不清、下半 Rare 橙黃區無關採集比對）。y395→345（2026-07-12）：工作列調回顯示後左側面板同底部 UI 整條上移 ~50px（舊裁圖 NORMAL 標題被切掉、新版面兩幀實測標題 y≈345-385）
    # buff 會疊加 → 瓶子位置會變，但都在這條「效果列」內；在整條裡搜尋瓶子形狀
    # 右緣縮到永久計數圖示左緣(x=1740)、下緣延到 1080（2026-07-08 遊戲更新新增常駐計數圖示，
    # 舊區涵蓋到它 → 舊「瓶子在=生效中」邏輯永遠判生效、永遠不補 D5；見 boost_active.png 說明）
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 935, 590, 145))
    boost_edge_threshold: float = 0.40           # 瓶子邊緣比對門檻（校準時調）
    boost_cooldown_s: float = 5.0                # 按 D5 後多久內不重按（等瓶子出現，避免狂按）
    boost_check_interval_s: float = 0.2          # boost 高頻偵測「不空轉」：boost 到期→立刻補，越快偵測瓶子消失越好（提早補無意義且浪費換道具時間，見 2026-07-02 spec #4 方案 A）
    boost_buff_scales: tuple = (1.0,)            # boost 瓶子＝固定尺寸 UI → 單尺度即可（~56ms/次），高頻掃描才不吃 CPU（D4 續用 buff_scales）
    # boost 使用次數計數器（2026-07-19）：右下角藥水圖示紅字＝session 內使用次數
    # （重進歸零）；boost FOV 縮小隨它累積（作用中變大/到期變小），是 FOV 漂移的
    # 狀態變數。區域依 07-17~07-19 歷史快照校準（vision.read_boost_use_count）。
    boost_count_region: Region = field(default_factory=lambda: Region(1720, 940, 90, 90))
    boost_count_digit_max_mismatch: float = 0.08  # 數字模板像素不一致比例上限（兩側夾：類內 ≤0.026 vs 類間最近 0.177）
    boost_count_ledger: str = "logs/boost_fov/count.jsonl"  # 使用確認/對帳/前後幀對 append-only jsonl（FOV 曲線離線分析）
    boost_fov_pair_every_n: int = 10             # 螢幕計數每前進 N 存一組補瓶前後幀（JPEG 對；0=關）——
                                                 # 到期(縮)→補瓶(展開)同場景自比＝無姿勢/場景雜訊的 FOV 量測點

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
    # D1（鎬子）是否已裝備——舊寫死單點 slot_pixel/slot_color（對照原巨集 IF PIXEL FOUND
    # 2302755=0x232323）在工作列調回顯示後失準（底部 UI 整條上移約 50px、單點落到場景上）。
    # 2026-07-10 起改「區域顏色」：hotbar 選中的槽位底色會轉綠 → 量 slot 1 內部區域的綠色主導
    # 程度（vision.slot_selected）。slot_pixel/slot_color 保留給 calibrate 說明字串，偵測已不用。
    slot_pixel: tuple = (1011, 845)              # 已停用（見 d1_slot_region）
    slot_color: int = 0x232323                   # 已停用（原巨集 0x232323 灰＝未拿鎬子）
    d1_slot_region: Region = field(default_factory=lambda: Region(798, 948, 54, 58))  # slot 1（鎬子）內部；實機 taskbar 可見版面
    d1_selected_greenness_min: float = 5.0       # greenness=平均G-平均(R+B)/2 ≥ 此值＝槽位選中(裝備中)；實測 選中≈+9.8~+11.5、未選中≈-1.4~0 → 5.0 兩側夾

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
    # 重置完成鈴聲擷取（第一階段：RESET_WAIT 期間只錄候選片段、不比對）
    # 設計：docs/superpowers/specs/2026-07-09-reset-chime-capture-design.md
    reset_chime_capture: bool = True             # 總開關；校準拿到樣本後可關
    reset_chime_capacity_arm_pct: float = 10.0   # 錄音窗開啟錨（H045 使用者裁決 2026-07-17）：RESET_WAIT/
                                                 # REENTRY 期間容量 OCR 讀到 ≤ 此值＝重置真的完成、開始錄。
                                                 # 時間錨被否決——banner 到真重置完成的耗時不定（凍結可拖
                                                 # 1~2.5 分）。兩側夾：重置前/凍結舊幀 78~100% vs 重置後 0%
    reset_chime_capture_max_s: float = 120.0     # 錄音窗上限（自容量歸零觀測起算；窗跨 RESET_WAIT/REENTRY
                                                 # 需要收口——等 Discord 指令可達數十分鐘，遊戲音效會把
                                                 # max_clips 洗滿）
    reset_chime_spike_factor: float = 3.0        # rms/baseline 達此倍數即觸發（安靜後一記鈴聲＝相對尖峰）
    reset_chime_baseline_alpha: float = 0.9      # 基準線 EMA 係數（越大越慢跟隨；實機再調）
    reset_chime_min_floor: float = 50.0          # 絕對 RMS 下限，防純靜音除以極小值誤觸（int16 值域，實機看 heartbeat log 校）
    reset_chime_window_s: float = 4.0            # 存檔片段總長（秒）
    reset_chime_post_roll_s: float = 1.5         # 觸發後再收多久才存（讓鈴聲落片段中段）
    reset_chime_warmup_s: float = 2.0            # 暖機：頭幾秒只建基準線不觸發
    reset_chime_max_clips: int = 20              # 單輪 RESET_WAIT 存檔上限（防洗版）

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
    tracker_shape_roi_px: int = 320              # 在 HSV 候選周圍裁多大 ROI 做形狀確認
                                                 # H040（2026-07-11）：160→320。harvest 070 實錄
                                                 # 207×208px 粗紅方框裝不進 160 ROI → 模板×尺度
                                                 # 超 ROI 被跳過 → 8 方位全空誤交人工。
                                                 # 模板 213px×尺度 1.4≈298 也要裝得下 → 320。
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
    d3_cooldown_s: float = 10.0                  # Starts at the actual hold-click; shared by normal and remote fire.
    max_harvest_attempts: int = 5
    harvest_verify_window_s: float = 8.0         # D3 後輪詢驗證窗口（H015：框擊中後 2~10s 才消失、聊天成功行更晚到，單幀判定必假陰性）
    harvest_verify_poll_interval_s: float = 0.5  # 輪詢間隔（每輪本身含 find_tracker ~2s，這只是喘息 sleep）
    verify_roi_radius_px: int = 180              # verify 輪詢 gone 檢查的 ROI 半徑：涵蓋雙幀穩定 8px 誤差
                                                  # ＋輕微視角/FOV 殘餘漂移；大位移（D5 到期縮放）由
                                                  # 「ROI miss → 全幀後備」兜住（見 find_tracker_near 註解）
    harvest_extra_targets_max: int = 2        # 同一 episode 成功後最多續採顆數（迴圈保險；072 實錄 1 顆）
    harvest_extra_target_min_dist_px: int = 100  # 續採候選離上發開火座標最小距離（兩側夾：真第二框 551px、剛採掉淡出框漂移 ≤8px）
    # D2 掃描成功確認（HANDOFF F）：掃描後 OCR 左下 Local 標籤。彈窗吃掉 click → 白掃
    # 8 方位 ~19s＋可能誤交人工。模式循 RapidOCR 觀察期慣例：
    #   off=不跑；observe=只記 log 收誤判數據（不重試）；enforce=失敗重聚焦重掃一次
    scan_confirm_mode: str = "off"               # 校準 region 後先切 observe，2-3 天裁決再 enforce
    scan_confirm_region: Region = field(default_factory=lambda: Region(20, 850, 200, 60))  # 左下 Local 標籤（估值，校準時調——照 chat_review_region 慣例從 logs/snapshots 全幀圖裁）
    chat_change_mean_diff: float = 2.0           # 聊天裁圖平均像素差超過此值才重跑 OCR（角色靜止時無新訊息＝近乎逐位元相同）

    # 驗證式旋轉（2026-07-05 視角回歸 45° 偏移對策）：每次 ,/. 送鍵後以前後幀確認「真的轉了」。
    # 被吃（pickup 動畫/焦點被搶）→ 重新聚焦後重送；重試用盡不計入 net_rotations——計數＝實際
    # 角度，restore 才必回原角（挖礦視角 90° 倍數對齊，差 45° 直接影響效率）。
    # 「被吃」判定保守（兩訊號都近零才重送，見 harvester.rotation_looks_eaten）。
    rotation_verify_region: Region = field(default_factory=lambda: Region(560, 160, 800, 320))  # 中央偏上場景帶：避開左側聊天/頂部事件列等覆蓋 UI（不隨旋轉動）、少吃角色 idle 晃動
    rotation_settle_s: float = 0.35              # 送鍵後等畫面轉完再截 after 幀（沿用 sweep 既有節奏）
    rotation_eaten_mean_diff: float = 2.0        # 平均差 ≤ 此值（與 stuck/chat 同尺度＝「近乎沒變」）
    rotation_eaten_changed_frac: float = 0.02    # 且有感變化像素佔比 ≤ 此值才判被吃（角色 idle 實測遠低於旋轉的大面積變化）
    rotation_changed_pixel_thresh: int = 12      # 單像素任一 channel 差 > 此值才算「有感變化」
    rotation_max_retries: int = 2                # 被吃後重送上限（每次重送前先 _focus_roblox）
    pitch_eaten_mean_diff: float = 8.0           # 俯仰拖曳被吃判定（2026-07-11 實機兩側夾：被吃 ≤3.29、真生效 ≥32.5）
    pitch_eaten_changed_frac: float = 0.15       # 同上（被吃 ≤0.045、真生效 ≥0.63）。地表粒子特效讓無效拖曳
                                                 # 也有 0.022~0.045，旋轉門檻 0.02 會誤判生效；俯仰歸位冪等、
                                                 # 誤判被吃重做無害 → 門檻可比旋轉激進。旋轉門檻不可共用不可動。

    # 卡住（用中央遊戲區判斷，避開左下角的狀態小窗，免得小窗變動誤判成「有進度」）
    stuck_timeout_s: float = 60.0
    stuck_frame_diff_threshold: float = 2.0      # 平均像素差低於此視為無變化
    stuck_region: Region = field(default_factory=lambda: Region(560, 200, 800, 520))

    # 狀態小窗（置頂顯示機器人在做什麼；放左下角避開偵測區，採集時自動隱藏）
    hud_enabled: bool = True
    hud_x: int = 12
    hud_y: int = 860                      # 905→860（2026-07-12）：工作列調回顯示後頂緣 y≈1015，
                                          # 905 時倒數畫面（5 行 ~145px）底緣被工作列蓋到；860 連倒數也放得下
    launch_countdown_s: int = 0           # 啟動倒數秒數（給時間切到 Roblox）；0 = 不倒數直接啟動
                                          # 3→0（2026-07-12 需求）：啟動環境檢查本身夠長，倒數多餘；
                                          # 要找回倒數改回 >0 即可（HUD _countdown_tick 分支仍在）

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
    # 容量飽和監看（輔助信號，2026-07-12 起不再觸發 RESET_WAIT）：頂部「Capacity: NNN%」段
    # （2026-07-11 實機 4 張快照實測 4/4）。Capacity 由玩家挖礦累積——bot 自己填的，
    # 礦坑遠未填滿時就顯示飽和（Mine Capacity 300% 升級下顯示 100% ≠ 重置臨近），
    # 提早停挖容量永遠不再累積＝死鎖（2026-07-12 實錄卡死 1h47m）。故現在只當「加速
    # banner 輪詢＋記一次飽和 INFO」的輔助信號；唯一停機條件是 reset 橫幅。
    capacity_region: Region = field(default_factory=lambda: Region(715, 92, 200, 45))
        # 頂部「Capacity: NNN%」段（2026-07-11 實機 4 張快照實測 4/4）
    depth_region: Region = field(default_factory=lambda: Region(890, 92, 210, 45))
        # 頂部「Depth: Surface / NNNm」段（H046 開場狀態錨；2026-07-17 實機 3 張快照
        # Surface/488m/25790m 實測 3/3，fixtures tests/fixtures/reentry/h046_depth_*.png）
    capacity_reset_threshold: float = 100.0   # ≥此值連續 2 次＝容量飽和：只記一次 INFO＋維持加速輪詢，
                                              # 不再觸發 RESET_WAIT（2026-07-12 死鎖實錄：Mine Capacity 300%
                                              # 升級下顯示 100% ≠ 重置臨近，提早停挖＝死鎖）
    capacity_fast_from: float = 99.0          # ≥此值 banner worker 輪詢加速（容量飽和期間高頻監看橫幅）
    capacity_fast_interval_s: float = 0.5     # 加速後間隔（平時沿用 reset_check_interval_s=2.0）

    # 記錄 / 診斷
    log_dir: str = field(default_factory=default_log_dir)
    log_level: str = "INFO"                      # 改 "DEBUG" 可看每幀偵測細節（音訊分數、標記座標等）
    save_snapshots: bool = True                  # 關鍵事件（chill/失敗/卡住/成功）自動存畫面截圖以利除錯
    sweep_empty_snapshot: bool = True            # sweep 全 8 方位皆空→交人工時，存每個方位的全幀（診斷用）：
                                                 # 這類交人工的真框常是薄/暗/被遮、shape-edge 低到被 hard_rej
                                                 # （2026-07-07 harvest 044-064 實錄），但過去只存觸發幀、看不到
                                                 # sweep 各方位實況→無從判斷是真漏抓還是礦已被挖走、也無法裁模板補救
    heartbeat_interval_s: float = 30.0           # 長時間等待時，每隔多久記一筆「還活著」的心跳
    snapshot_retention_enabled: bool = True      # 啟動時清理過舊/過量快照（實測 632MB 且在 OneDrive 同步夾）
    snapshot_max_age_days: int = 30              # review/events/reentry 等診斷的全域最長保留期
    snapshot_max_total_mb: int = 1024            # 全部 snapshots 總量上限，超過從最舊開始刪
    snapshot_trace_max_age_days: int = 7          # trace 高頻且低價值，較早回收
    snapshot_trace_max_total_mb: int = 256
    snapshot_queue_max: int = 16                  # 1080p BGR 約 6MB/張；限制最壞記憶體占用
    snapshot_queue_critical_reserve: int = 4      # 保留給 rare/review/reentry，trace 不得吃滿
    snapshot_shutdown_drain_s: float = 5.0        # Bounded shutdown wait for queued snapshot writes.
    discord_sink_queue_max: int = 64              # 網路斷線時避免事件無界堆積
    perf_log_interval_s: float = 60.0             # 主迴圈延遲分位數寫 heartbeat.log 的間隔
    perf_sample_window: int = 300                 # 每個階段保留最近 N 筆樣本

    # 重置自動回礦（auto re-entry；docs/superpowers/specs/2026-07-08-mine-reentry-design.md）
    reentry_mode: str = "remote"                # "off"=RESET_WAIT 等人工（今日行為）/"remote"=Discord 指位（2026-07-12 spec）/"auto"=全自動（2026-07-08 spec，面板模板校準完成前勿開）
    reentry_surface_button_xy: tuple = (1855, 965)  # 右下「Go to surface」UI 按鈕中心（2026-07-12 實機 RESET_WAIT 幀量測：按鈕 x1804-1907/y914-1017；taskbar 可見版面，工作列隱藏需重量——同 d1_slot_region 家族）
    reentry_reset_settle_s: float = 5.0         # banner reset 字樣消失後沉澱多久才開始
    reentry_max_attempts: int = 5               # reroll 上限，用盡 → NEEDS_HUMAN
    reentry_attempt_timeout_s: float = 60.0     # 單輪（按回到地表→點擊驗證）時限
    reentry_teleport_wait_s: float = 6.0        # 按回到地表/層按鈕後等場景切換上限
    reentry_teleport_diff: float = 12.0         # 幀平均差超過此值＝傳送發生。兩側夾數據（2026-07-13
                                                 # 實機）：虛空無變化噪音 ≤0.3、UI 動畫噪音 ~4.4、真傳送
                                                 # 穩定值 ≥19、地表→地表換重生點最低 26.8。舊值 25 會漏判
                                                 # 真傳送（夜間地表穩定值 19 < 25）→ 降到 12（>4.4 噪音、<19 真傳送）
    reentry_evac_on_banner: bool = False        # RESET_WAIT 進場即撤離（H043 對策）總開關。H045 起預設
                                                 # 關：撤離＝重置那一刻人在地表，遊戲不記錄坑內位置，
                                                 # 臨時挖到的稀有礦回不去原位（使用者 2026-07-17 裁決：
                                                 # 留坑內記位置，虛空/凍結交 H044 探測預算慢慢爬出）。
                                                 # 若實機證明虛空卡死率不可接受，開回 True 即回 H043 行為
    reentry_evac_settle_s: float = 0.5          # RESET_WAIT 進場撤離：focus 後沉澱再點「回到地表」
                                                 # （輸入被吃家族既有教訓——焦點剛切回就送點擊會被吃）
    reentry_click_retries: int = 3              # 單次撤離/開場的「回到地表」點擊重試上限（虛空下偶發
                                                 # 成功前都有真實滑鼠移動事件；重試前 move_to 中央再移回按鈕）
    reentry_game_region: Region = field(default_factory=lambda: Region(1100, 200, 690, 650))
    # ↑ H044 遊戲專屬觀測區（右側場景帶 x1100-1790/y200-850）：避開頂部橫幅、左側聊天/NORMAL
    #   面板、右側按鈕欄（x≥1800）、左下 HUD，也避開使用者常放覆蓋視窗的中央區。傳送驗證量此區。
    #   ⚠ 此區必須保持無覆蓋視窗；改座標須重裁 tests/fixtures/reentry/h044_*.png。
    reentry_teleport_frac: float = 0.05         # 傳送雙訊號之二（frames_changed_frac ≥ 此值＝傳送）。
    #   兩側夾（H044）：真傳送 0.9966 / 活著靜止 ≤0.0004 / 凍結 0.0000。mean 會被夜空大片黑稀釋，
    #   frac 補位；與 reentry_teleport_diff 取 OR。
    reentry_open_retry_wait_s: float = 20.0     # 開場探測：判「未傳送」後隔多久再點一次（H044 凍結中
    #   點擊無反應，點擊本身就是探針；被動凍結偵測已被量測否決——活著靜止畫面與凍結像素不可分）
    reentry_open_budget_s: float = 300.0        # 開場探測總預算（自 episode 首擊起算；實測凍結 1~2.5
    #   分鐘，300s 蓋過最壞觀測 2 倍）。用盡→通知一次附截圖，等 重骰/跳過/回礦
    reentry_open_capacity_max_pct: float = 10.0  # 開場容量閘（H045，僅 reset 觸發）：拍照前容量 OCR 須
    #   ≤ 此值。兩側夾：凍結舊幀 Capacity 78%（2026-07-14 ep3 實機幀）/ 重置進行中（地表）
    #   56~71%（RR#2 01:33~01:34 實讀）vs 真重置完成後 0~1%（H046 0%、H053 RR#7 連續 17 次 1%）。
    #   凍結中傳送驗證可能在凍結開始前真過了——容量歸零是「重置真的完成且畫面是活的」第二訊號。
    #   H046：容量 OCR 與俯仰結果解耦（頂部 Capacity 列不管俯仰有沒有生效都讀得到）。
    #   H053（2026-07-20 RR#7）：舊預設 0.0 太嚴——真重置完成後容量 OCR 穩定讀到 1%（非 0%），
    #   1.0 > 0.0 恆成立→開場閘永遠回 capacity、預算 300s 耗盡卡死。改 10.0＝與
    #   reset_chime_capacity_arm_pct 同概念（同一幀鈴聲路徑早已用「1% ≤ 10%」接受），兩側各 ≥10x 餘裕。
    reentry_frozen_mean_max: float = 0.02       # 凍結探針（H046）：俯仰拖曳前後幀 mean ≤ 此值「且」frac ≤
    reentry_frozen_frac_max: float = 0.0002     #   下值才判凍結。兩側夾：凍結 0.00/0.0000（逐位元相同）vs
    #   活著靜止 0.09/0.0004 vs 夜間地表拖曳最小 0.93/0.018（2026-07-17 ep1）。⚠ 不可改用
    #   pitch_eaten_*（那是「拖曳生效」門檻 8.0/0.15）——H046 就是誤用它把活人鎖 300s
    reentry_pitch_clamp_px: int = 1500          # 俯仰歸位：向下拖到夾限的量（過量無妨，飽和即可）
    reentry_pitch_back_px: int = 370            # 回拉量（R 視窗校準出、寫回這裡）
    reentry_attempt_warn_every: int = 5         # 人工重骰每 N 次提醒可跳過/調視角（0=關；attempt 無上限不變）
    # --- H048 俯仰拖曳人式分段（2026-07-18 實機兩側量測）---
    pitch_drag_hold_budget_px: int = 150        # 單次右鍵 hold 的注入上限。指標加速實測 40→78/80→174/
    #   120→271/180→416（~2.0-2.3x），150px 實走 ~345px < 中央到標題列/工作列 ~500px——
    #   游標永不甩出遊戲視口（甩到標題列＝右鍵放開會彈系統選單、吞掉後續輸入）
    pitch_drag_hold_settle_s: float = 0.8       # 兩次 hold 間沉澱。兩側夾：間隔 0.15~0.2s 的下一段右鍵
    #   被吃（回拉段長期失效、歸位實停在下夾限）、0.55s 以上生效——取 0.8 留餘裕
    reentry_panel_dir: str = "assets/surface"   # 面板偵測模板資料夾（實機裁圖）
    reentry_panel_threshold: float = 0.45       # 面板邊緣比對門檻（高信心才進下一步）
    reentry_panel_scales: tuple = (0.5, 0.7, 1.0, 1.4, 2.0)  # 距離變化大→尺度比 marker 寬
    reentry_target_layer: str = "Mantle Layer"  # 目標層按鈕文字（校準時依實際要挖的層改）
    reentry_decoy_buttons: tuple = ("Back to pre-reset location", "Basalt Layer",
                                    "Diorite Layer", "Obsidian Layer", "Core Layer")
    reentry_button_min_ratio: float = 0.75      # 層按鈕模糊比對下限（且須嚴格贏過 decoy）
    reentry_nav_timeout_s: float = 15.0         # click-to-move 單段到位上限
    reentry_move_stable_ticks: int = 3          # 連續 N tick 幀差近零＝角色停下
    reentry_move_diff: float = 2.0              # 「近零」門檻（與 stuck/chat 同尺度）
    reentry_mine_max_brightness: float = 60.0   # 礦內判定：stuck_region 平均亮度上限（校準時定）
    # R 鍵手動取樣（校準素材收集；也可用於裁追蹤框模板/補 OCR fixture）
    hotkey_sample: str = "r"
    manual_snapshot_dir: str = "logs/snapshots/manual"
    sample_pitch_step_px: int = 40              # R 視窗上/下微調一次的拖曳量
    sampler_pitch_focus_settle_s: float = 0.5   # 俯仰鈕：聚焦回遊戲→拖曳前的沉澱。2026-07-11 實機：
                                                 # 三次「聚焦成功」但拖曳全沒生效——焦點剛切回就送
                                                 # 右鍵拖曳會被吃（與旋轉鍵被吃同家族），settle 後再拖

    # --- 失敗路徑俯仰掃描（2026-07-11 spec：標準層 8 方位全空才掃上/下層）---
    sweep_pitch_enabled: bool = False           # 校準完成前保持 False（比照 reentry 慣例）
    sweep_pitch_step_px: int = 0                # 一層 nudge 拖曳量（R 視窗校準；0=未校準＝停用；
                                                 #   正=向下拖。遊戲拖曳方向若相反，校準時設負值即可）
    sweep_pitch_clamp_px: int = 1500            # pitch_reset 飽和拖曳量（沿用 reentry 初值；礦內校準可調）
    sweep_pitch_center_back_px: int = 370       # 挖礦標準角：夾限飽和後回拉量（校準 挖礦/CLI 寫回；0=未校準＝停用）。
                                                 #   370＝2026-07-20 使用者確認：本世界挖礦角＝地表角，沿用
                                                 #   reentry_pitch_back_px；換世界若挖礦角不同須 `校準 挖礦` 另校

    # --- Discord 遠端瞄準（2026-07-11 spec：giveup 附近失候選編號圖，回訊息即指揮）---
    remote_aim_enabled: bool = True             # 關掉＝giveup 附圖/回覆解析全部回到今天行為
    remote_aim_max_candidates: int = 9          # 附圖候選編號上限（防洗版）
    remote_aim_refind_radius_px: int = 160      # fire 前重找 ROI 半徑（同 shape_roi 半徑量級）
    remote_aim_budget_s: float = 120.0          # 單次 fire 全流程預算（對齊+重掃+驗證）
    remote_aim_snapshot_wait_s: float = 3.0     # Total wait budget before rendering or directly sending async snapshots.
    harvest_target_recovery_max: int = 1        # At most one recovery at an accepted/fired absolute direction.
    harvest_target_recovery_radius_px: int = 240  # Expanded ROI around the historical target coordinate.

    # --- Discord 遠端回礦（2026-07-12 spec：重置後發八方位圖，回訊息兩段式指位點傳送面板）---
    reentry_remote_fine_cols: int = 6           # 細網格欄數（放大圖上）
    reentry_remote_fine_rows: int = 6           # 細網格列數；6×6 映射回原幀一格 ≈53×45px（±27px）
    reentry_remote_zoom_scale: int = 3          # 粗格 320×270 → 放大 960×810 再疊細網格
    reentry_remote_drift_diff: float = 12.0     # 點擊前漂移守門：粗格區域幀平均差 ≥ 此值 → 不點、重發放大圖（H026 家族）
    reentry_remote_auto_resume: bool = False    # True=幀差+礦內亮度雙過即自動開挖；False=一律等「好」放行（亮度簽名校準前的安全預設）
    reentry_remote_ledger: str = "logs/reentry_remote/ledger.jsonl"   # append-only ground-truth 帳本
    reentry_remote_sticky_layers_path: str = "logs/reentry_remote/sticky_layers.json"
    # 每世界回礦黏性層 map（{世界: 層名}）；`層` 指令寫穿、bot init 讀回。
    # 容錯：空/缺/壞 → {}，回退到 reentry_target_layer。與 reentry_remote_ledger 同目錄
    # （MSIX 重導同處理）。reentry_target_layer 保留為「世界未在 map／未偵測到」的 fallback。

    # REENTRY 鏡頭遠近（2026-07-12 spec：遠/近指令＋夾限飽和絕對歸位）
    reentry_zoom_step_default: int = 4          # `遠`/`近` 省略步數時的預設
    reentry_zoom_max_steps: int = 12            # 單指令步數上限（防手滑打 99；超過 clamp 不拒收）
    zoom_reset_saturate_presses: int = 30       # 歸位飽和段按 I 次數（須大於最大可能累積步數）
    zoom_reset_pullback_steps: int = 4          # 歸位回拉 K 步；0＝未校準＝遠/近指令整組停用。
                                                # 2026-07-20 使用者實機校準：連點 I 進第一人稱後
                                                # O×4＝標準挖礦距離（07-19 初校 O×2 偏近，07-20 實機改 4）。boost FOV 隨使用次數累積漂移
                                                # （作用中變大/到期變小、重進伺服器才重製），鏡頭距離
                                                # 是唯一可歸一的相機自由度——啟動/回礦 sweep 前/回
                                                # MINING/暫停恢復都做一次歸位（_zoom_normalize）。
    zoom_eaten_mean_diff: float = 8.0           # zoom 送鍵被吃判定（初值抄 pitch_eaten_*；獨立門檻，
    zoom_eaten_changed_frac: float = 0.15       # 不可共用旋轉門檻——歸位冪等、誤判重做無害，方向安全性與旋轉相反）

    # 熱鍵（控制權）
    hotkey_emergency_stop: str = "ctrl+q"        # 只暫停（不結束程式、不繼續）：放開所有按鍵，等 Q 繼續
    hotkey_pause: str = "q"                      # 開關 暫停 ↔ 繼續（也用於人工介入/礦坑重置定位後重啟；
                                                 # 啟動環境檢查期間按 Q＝跳過剩餘檢查直接開挖——原 F8 專用鍵
                                                 # 與 Roblox 內建功能衝突而廢棄，2026-07-10）
    hotkey_quit: str = "f12"                     # 真正結束程式
    antiafk_interval_s: float = 900.0            # 防掛機踢除：暫停中每 N 秒按一次 Space（預設 15 分鐘）

    # Discord（Phase 2）— token 從 .env 讀，不寫死在程式碼
    discord_webhook_url: str = ""
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    discord_poll_interval_s: float = 1.0        # Discord 命令/反應輪詢間隔（秒；單卡 reaction 摘要已把每輪 GET 壓到 1 次）
    discord_repin_quiet_s: float = 4.0          # 釘底防抖安靜窗（秒）：頻道最後一則新訊息後安靜滿此秒數，才把遙控器/回礦卡刪舊貼新到頻道底（輪詢 1s ≈ 4 輪安靜；2026-07-19 spec）

    # 選單前置切換（Movement Mode）＋聊天框前置檢查
    # docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md
    movement_mode_options: tuple = ("Default (Keyboard)", "Keyboard + Mouse", "Click to Move")
    movement_mode_mining: str = "Default (Keyboard)"    # 挖礦用（兩個鍵鼠模式皆可，使用者確認取此值）
    movement_mode_reentry: str = "Click to Move"        # REENTRY 導航用（click-to-move 依賴此模式）
    menu_panel_region: Region = field(default_factory=lambda: Region(460, 130, 1000, 880))
        # Esc 選單面板整塊（分頁列 People/Settings/... ＋ 內容列表），OCR 找標籤/值/箭頭都在此裁圖裡做
        # （2026-07-08 實機驗證：People(576,156) Settings(774,156) Gallery(976,156) 等分頁文字，
        # Movement Mode 標籤(571,503)／值(1153,503) 皆落在此區內）
    menu_movement_label_region: Region = field(default_factory=lambda: Region(500, 478, 300, 50))
    menu_movement_value_region: Region = field(default_factory=lambda: Region(1000, 478, 350, 50))
    menu_movement_row_y: int = 503       # 固定列快速路徑；辨識不確定時回退全面板 OCR
    menu_arrow_right_x: int = 1425       # 值列右箭頭 x（y 用該列 label 的 y；2026-07-08 實測 1423~1425）
    menu_value_column_x_range: tuple = (1000, 1350)   # 值文字欄 x 範圍（中心約 1153，三個值都置中對齊）
    menu_row_y_tolerance_px: int = 18    # 同一列判定的 y 容差（label 與 value 實測同列時 y 差 0~1px）
    menu_scroll_xy: tuple = (960, 500)   # 捲動前滑鼠停駐座標（面板中央）
    menu_scroll_amount: int = -3         # 每次捲動的滾輪格數（負=向下捲；WHEEL_DELTA=120/格）。
        # 方向依 Windows 滾輪慣例推斷、未經真實遊戲驗證——實機校準時若捲反了對調正負（見最後 Task）。
    menu_scroll_max_screens: int = 8     # 捲動找標籤上限（屏數）；Movement Mode 實測不捲動就找得到，
        # 此上限只是「遊戲改版把它挪到更下面」的防呆餘裕
    menu_arrow_click_max: int = 3        # 右箭頭最多點幾次（三值循環，最多 3 次必回到任意目標值）
    menu_arrow_settle_s: float = 0.3     # 點右箭頭後等值更新
    menu_open_settle_s: float = 0.3      # Esc/點分頁/點圖示後等畫面反應
    menu_close_settle_s: float = 0.3     # Esc 關閉後等選單收合
    menu_fuzzy_min_ratio: float = 0.6    # 標籤/值模糊比對下限（比照 reentry_button_min_ratio 精神）
    menu_retry_max: int = 1              # 整鏈失敗後重試次數（不含首次嘗試）
    menu_budget_s: float = 90.0          # Movement Mode 整鏈時間預算；超過即中止走失敗路徑
        # （實測成功 71~82s、失敗曾燒 170s；2026-07-10 spec 第 4 節）

    chat_icon_xy: tuple = (174, 71)      # 左上聊天圖示（收合時點它展開；2026-07-08 實測座標）
    chat_icon_state_region: Region = field(default_factory=lambda: Region(154, 51, 40, 40))
        # 左上聊天圖示狀態判定框（H047：開＝實心白泡泡、關＝空心白邊；40x40 含整個圖示；
        # 任何狀態都看得到，不像輸入列 placeholder 會被自動隱藏——取代舊版輸入列 OCR 信號）
    chat_icon_probe: tuple = (6, 21, 18, 28)
        # 泡泡內部補丁（crop 相對 x0,y0,x1,y1；位於泡泡左下內部，避開中央文字筆劃與右上未讀徽章）
    chat_icon_open_min_gray: float = 180.0    # >= 判開（實心白泡泡）
        # 實測補丁灰階平均：開 238..255（n=42）、關 81..87（n=19 含未讀徽章「11」樣本）→ 兩側夾
    chat_icon_closed_max_gray: float = 130.0  # <= 判關（空心、內部暗）；中間 unknown，呼叫端絕不點擊
    chat_open_settle_s: float = 0.8      # 點聊天圖示後等展開動畫（menu_open_settle_s 0.3 偏緊）
    chat_open_max_retries: int = 2       # 首次點擊複檢仍關 → 重新聚焦再點的重試次數

    player_list_region: Region = field(default_factory=lambda: Region(1490, 110, 425, 150))
        # 右上角玩家列表（Tab toggle）標題列＋第一列。2026-07-09 由實機截圖量測：
        # client 座標 header y≈118-145；grab 全螢幕比 client area 低 ~29px → 區域開高吸收偏移。
        # fixtures: tests/fixtures/player_list/（open/open2/closed）
    player_list_phrases: tuple = ("players", "blocks mined")

DEFAULT = Config()
