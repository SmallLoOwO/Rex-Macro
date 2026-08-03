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

    # 偵測區域基準版面＝**Roblox 全螢幕**（client rect 0,0-1920,1080；2026-07-28 實測校準）。
    # 之前的基準是「視窗化最大化＋工作列可見」＝client 只有 1920×1001、原點 (0,29)。
    # 2026-07-28 切全螢幕後由新舊實機幀兩側量測（舊 01:07 rare_found vs 新全螢幕幀），
    # 位移是**純平移、無縮放**（同一 UI 元素的 run 長度不變）：
    #   ・頂端錨定 UI（事件橫幅／Capacity-Depth 列／聊天／聊天圖示）整體 **上移 29px**
    #     （量測：Capacity 白字列 108-125 → 79-96；橫幅深色框 43-82 → 14-53）
    #   ・底端錨定 UI（快捷欄／效果列／NORMAL 面板／右側按鈕欄／Go to surface）整體 **下移 50px**
    #     （量測：Go to surface 白字 953-956/971-986 → 1003-1006/1021-1036；右側圖示欄四段全 +50）
    #   ・水平方向完全不變（螢幕寬度沒變、UI 置中或靠邊）
    # 換回視窗化就是反向（頂 +29 / 底 -50）。世界場景區（stuck/rotation_verify/reentry_game）
    # 不需動：視口變高 1001→1080 只是多看到一點場景，這幾區仍落在純場景帶內。
    chill_text_region: Region = field(default_factory=lambda: Region(360, 15, 1220, 37))  # 頂部事件列深色橫幅（實測裁緊：置中 960、只留深色框；全螢幕 y14-53，視窗化時為 y43-82）
    # ⚠ 全螢幕特有陷阱（2026-07-28 實測）：游標停在畫面頂端 ~80px 內，Roblox 會顯示
    #   視窗標題列（"Roblox" ＋ 還原/關閉鈕）蓋住這一區 → 這裡 OCR 出來是字串 'Roblox'，
    #   chill 與**礦坑重置橫幅**（唯一停機條件）雙雙看不見。游標離開頂端就自動收起，
    #   但停著就一直蓋著 → input_control.click_at 已收口：點在頂端帶就把游標移回中央
    #   （見 input_control.TOP_OVERLAY_STRIP_PX）。看到 banner OCR 讀到 'Roblox' 先查游標在哪。
    # 下緣蓋到左上礦物面板（標頭 "NORMAL"，091 另有右側圖層面板）→ 每次聊天 OCR 的最後一行
    # 都是面板文字。**不可用縮短高度解決**（H055 實機量測）：面板是疊在最新聊天行**之上**——
    # 082 裁圖面板上緣 y=227 橫穿最新 has-found 行字身（y=225..234），094 最新（淡出中）聊天行
    # 更落在 "NORMAL" 白字帶（y=240..258）內 → 停在面板上方必切掉真聊天行。
    # 對策在 OCR 側：ocr._strip_ui_residue() 於比對進入點剝掉尾端殘留行。
    # 全螢幕版面下（2026-07-28）NORMAL 面板頂緣落在 y≈388、聊天裁圖下緣 361 → 兩者**不再重疊**，
    # 但 _strip_ui_residue 保留：換回視窗化或面板加長時重疊會回來，剝除本身對無殘留的裁圖無害。
    chat_region: Region = field(default_factory=lambda: Region(0, 81, 460, 280))   # 左上事件/掉落訊息（全螢幕 y81；視窗化時為 y110）
    # 左側 NORMAL 礦石面板：不透明 UI，蓋住的世界畫面本來就看不到也點不到 → 追蹤框偵測一律排除。
    # H068 量測（141 dir6 vs dir7 同場不同視角逐像素差分，靜態像素比例 >0.7）：x 11~281、
    # y 386~1068。取 x≤240 只含 NORMAL 面板本體，右側 Shamrock 製作面板不納入（非恆存，
    # 多吃 40px 世界畫面不划算）；y 380 起、吃到底。不排除的話面板文字會出 colored=0.86 /
    # edge=0.33 的候選，正好落在 H068 軟收路徑內 → 對 UI 開一發 D3。
    ore_panel_region: Region = field(default_factory=lambda: Region(0, 380, 240, 700))
    # 採集放棄 NEEDS_HUMAN 附的左側「前/後對比」裁圖：拆成「聊天（寬短）」與「背包（窄高）」兩區，
    # 各自更貼近 Discord 縮圖比例、砍掉右側沒用的粉紅場景（見 2026-07-02 spec 需求 A）。
    # before＝本輪 _pre_scan_ref、after＝放棄當下；左側 UI 是螢幕覆蓋層、不隨鏡頭角度變 → 前後同框
    # 可直接對比「礦是否已被採走」（新 has-found 行 / 背包數量增加＝已採到）。座標實機校準自 logs H010 d3_fire。
    chat_review_region: Region = field(default_factory=lambda: Region(0, 81, 460, 280))     # 左上 has-found 聊天（= chat_region；最新行在底部，勿縮短高度否則漏掉最新 has-found）
    backpack_review_region: Region = field(default_factory=lambda: Region(0, 395, 226, 335)) # 左下 NORMAL 背包「上半」：面板依稀有度排序（Exquisite→Mythic→Surreal→Master→Rare），新採到的礦（count=1）浮最上面；h335 涵蓋到 Surreal 帶 1-2 行 Master，Discord 縮圖才夠大（2026-07-03 需求：舊 h670 全清單縮圖看不清、下半 Rare 橙黃區無關採集比對）。y395→345（2026-07-12）：工作列調回顯示後左側面板同底部 UI 整條上移 ~50px（舊裁圖 NORMAL 標題被切掉、新版面兩幀實測標題 y≈345-385）。345→395（2026-07-28 切全螢幕）：面板是底端錨定，同底部 UI 整條下移 50px（實測標題 y≈388-425）
    # buff 會疊加 → 瓶子位置會變，但都在這條「效果列」內；在整條裡搜尋瓶子形狀
    # 右緣縮到永久計數圖示左緣(x=1740)、下緣延到 1080（2026-07-08 遊戲更新新增常駐計數圖示，
    # 舊區涵蓋到它 → 舊「瓶子在=生效中」邏輯永遠判生效、永遠不補 D5；見 boost_active.png 說明）
    # 2026-07-28 全螢幕：y935→985（底端錨定 +50）。高度 145→95 是因為舊區的 1030-1080 那段
    # 本來就是工作列（不是遊戲畫面），全螢幕下效果列徽章實佔 y≈1003-1073，985-1080 完整涵蓋。
    boost_indicator_region: Region = field(default_factory=lambda: Region(1150, 985, 590, 95))
    boost_edge_threshold: float = 0.55           # 瓶子邊緣比對門檻；H073：0.40 在全螢幕校準後讓使用次數 icon 偽陽性。兩側夾（tests/fixtures/boost 全五張實測）：真 boost 下界 active_61=0.619，誤收上界 h168_sweep_no_boost=0.419 → 0.55（正側餘裕僅 0.069，調高前先加真 boost 樣本）
    boost_cooldown_s: float = 5.0                # 按 D5 後多久內不重按（等瓶子出現，避免狂按）
    boost_check_interval_s: float = 0.2          # boost 高頻偵測「不空轉」：boost 到期→立刻補，越快偵測瓶子消失越好（提早補無意義且浪費換道具時間，見 2026-07-02 spec #4 方案 A）
    boost_buff_scales: tuple = (1.0,)            # boost 瓶子＝固定尺寸 UI → 單尺度即可（~56ms/次），高頻掃描才不吃 CPU（D4 續用 buff_scales）
    # boost 使用次數計數器（2026-07-19）：右下角藥水圖示紅字＝session 內使用次數
    # （重進歸零）；boost FOV 縮小隨它累積（作用中變大/到期變小），是 FOV 漂移的
    # 狀態變數。區域依 07-17~07-19 歷史快照校準（vision.read_boost_use_count）。
    boost_count_region: Region = field(default_factory=lambda: Region(1720, 990, 90, 90))
        # 2026-07-28 全螢幕：y940→990（底端錨定 +50）。⚠ 這顆圖示是 session 計數（重進歸零），
        # 切全螢幕＝重進 → 校準當下畫面上沒有它，位置是照 +50 平移推得、待下次補瓶時實機複驗。
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

    # D2 雷達連續使用（2026-07-25）：比照 D4/D5「冷卻好就再按」，用來持續清洞穴方塊。
    # 就緒判定＝效果列**沒有**對應徽章（vision.find_effect_slots + OCR，同 D4 的
    # cooldown_ready 語意）；徽章實測 t+0.4s 出現、~30s 後隨冷卻消失。
    # 兩個能力冷卻**各自獨立**（wiki：左鍵 30s／Z 30s／右鍵 25s 三條分開）。
    # ⚠ scan（左鍵）預設關：它與採集流程的 harvester.execute_scan 搶同一條 30s 冷卻，
    #   開著會讓 chill 觸發採集時掃不出追蹤框 → 白掃 8 方位。Z 不與任何流程衝突。
    radar_scan_repeat_enabled: bool = False      # D2 左鍵 Cyberscan 自動重複（會搶採集冷卻）
    radar_cave_skim_enabled: bool = False        # D2 Z Cave Skim 自動重複（削洞穴方塊）
    radar_check_interval_s: float = 3.0          # 徽章偵測節流（同 activity_check_interval_s 量級）
    radar_grace_s: float = 4.0                   # 按下後等徽章出現的寬限（實測 t+0.4s 出現，留餘裕）
    radar_repeat_interval_s: float = 34.0        # 後備定時：OCR 引擎不可用時改用（實測徽章 31s 在、34s 沒）
    # 採集掃描前等 D2 左鍵冷卻（2026-07-25）：連續使用開著時 Cyberscan 可能剛被自動用掉，
    # 此時 execute_scan 按下去沒作用 → 白掃 8 方位 ~19s＋可能誤交人工。改成**先等冷卻結束
    # 再掃**（使用者指定的解法）：多等 ≤30s 換一次有效掃描，遠優於白掃。
    # 逾時不卡死：照常往下掃（保守，寧可白掃一次也不要卡在採集入口）。
    radar_scan_wait_max_s: float = 36.0          # 等待上限（冷卻 30s + 餘裕）
    radar_scan_wait_poll_s: float = 1.0          # 等待期間重讀徽章的間隔
    # Boost 沒到期警報（2026-07-25 使用者要求）：MINING 且未暫停時 boost 連續 > 此秒數沒重上
    # = 遊戲時間可能凍結（Roblox 失焦／偵測誤判）。boost 自然 ~50s 到期，給 ~1.5 倍餘裕。
    # 不同於 STUCK（靠 frame diff 抓不到——frame 還在動就 pass），這條直接看 boost 是否到期。
    boost_stall_warn_s: float = 90.0
    # 視窗跑位偵測（item ④）：用 Win32 查 Roblox 視窗「前景/位置/大小」，相對啟動時量到的
    # 基準判斷是否跑掉（失焦或被移動/縮放）→ 自動重新聚焦+初始化。用基準相對比較而非寫死
    # 1920x1080，因 DPI 縮放會讓 GetWindowRect 回報縮放後座標（實測此機 125% → 1536x864）。
    window_check_enabled: bool = True
    window_check_interval_s: float = 1.0         # 多久查一次視窗狀態（Win32 很快，節流即可）
    window_pos_tolerance_px: int = 6             # 位置偏移容差（相對基準）
    window_size_tolerance_px: int = 8            # 大小偏移容差（相對基準）
    # D1（鎬子）是否已裝備——舊寫死單點 slot_pixel=(1011,845)/slot_color=0x232323（對照原巨集
    # IF PIXEL FOUND 2302755）在工作列調回顯示後失準（底部 UI 整條上移約 50px、單點落到場景上）。
    # 2026-07-10 起改「區域顏色」：hotbar 選中的槽位底色會轉綠 → 量 slot 1 內部區域的綠色主導
    # 程度（vision.slot_selected）。兩個舊欄位 2026-07-30 刪除（全 repo 零讀取）。
    d1_slot_region: Region = field(default_factory=lambda: Region(798, 998, 54, 58))  # slot 1（鎬子）內部；2026-07-28 全螢幕版面（y948→998，底端錨定 +50）
    d1_selected_greenness_min: float = 5.0       # greenness=平均G-平均(R+B)/2 ≥ 此值＝槽位選中(裝備中)；實測 選中≈+9.8~+11.5、未選中≈-1.4~0 → 5.0 兩側夾
    d2_slot_region: Region = field(default_factory=lambda: Region(864, 998, 54, 58))  # slot 2（掃描器）內部；2026-07-29 全螢幕校準（slot1 x798-852、pitch 66 → slot2 x864-918；H065）
    d2_selected_greenness_min: float = 5.0       # 同 d1 慣例；實測 slot2 選中≈+10.5、未選中≈+1.5（掃描器圖示帶微綠，但 up/d3/down 三個不同場景幀量出來分毫不差＝UI 固定屬性）→ 5.0 兩側夾（H065）

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
    chill_ref_negative_ceiling: float = 0.22     # 收新參考前的假觸發守門：若該參考會讓任一已知
                                                 # 非 chill 錄音分數 ≥ 此值就拒收。2026-07-21 兩側夾：
                                                 # 週期性非 chill 音效(每 ~15 分一次的 s18 族)對安全參考
                                                 # 集最高 0.180；H040 的裁片會把它推到 0.507、078 推到
                                                 # 0.273、077 推到 0.245 → 全數拒收。0.18~0.22 任一值都
                                                 # 選出同一組參考（結論對取值不敏感），取 0.22 留邊際。
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
    # H068（2026-07-31，harvest 129/133/141 玩家標註）：框被角色/裝備擋住一角時 edge 掉到
    # 0.33~0.41，卡在 0.42 下方 → 八方位全空誤交人工。edge 單軸已無 gap（裝備最高 0.36），
    # 但同一批幀裡「edge 偏低」的真框 colored 一律 ≥0.86，裝備只有 0.56/0.73 → 補一條
    # 二維軟收路徑：edge ≥ soft_edge **且** colored ≥ soft_colored 也算 confirmed。
    tracker_shape_soft_edge: float = 0.35        # 軟收 edge 下限；兩側夾：真框 0.36×3/0.40/0.41 vs colored≥0.80 的誤收候選最高 0.33（H026 粉紅岩層 colored=1.00，另 0.31/0.30/0.29/0.28）→ 留 0.02 margin。**0.33 那顆真框（133 dir4 (979,550)）與粉紅岩層同分，軟收救不回，記在 D09**
    tracker_shape_soft_colored: float = 0.80     # 軟收 colored 下限；兩側夾：低 edge 真框 0.86×4/1.00 vs edge≥0.35 的非框最高 0.56（裝備）／0.73（角色，edge 0.33）→ 留 0.07 margin。礦石面板文字同為 0.86/0.33，靠 ore_panel_region 排除而非門檻
    tracker_shape_early_exit: float = 0.60       # sweep 早停：某方位雙幀穩定且 edge≥此值（遠高於裝備上限 0.26）→ 直接確定、免掃完剩餘方位/免轉回 verify（實測真框 0.54-1.00）
    # H057（2026-07-20 harvest 097）超大輪廓救援：綠框貼受光綠牆被 RETR_EXTERNAL 接成
    # 一條爆 area/bbox 閘的大輪廓（bbox 493x85、area 14620），真框在形狀確認前就出局
    # → 全八方位掃描全空誤交人工。confirmed 全滅時在爆閘輪廓 bbox 內用高 V 子 mask
    # 二次分割，救回的候選只走形狀 confirmed 路徑（不放寬任何全域門檻）。
    tracker_rescue_v_min: int = 150              # 二次分割亮度下限；兩側夾：受光牆帶 V=72~76（必擋）vs 框芯 V=222（必收），dir4 實測 V 100~180 都能救回真框，取中值
    tracker_rescue_area_min: int = 120           # 救援 blob 面積下限；真框亮芯碎片實測 area 552~600（V=150 時），120 擋掉更小的牆面亮點雜訊
    tracker_rescue_max_candidates: int = 12      # 每幀救援候選上限（依 area 大者優先）；控形狀確認開銷（實測正常場景救援候選 5~15、最多 65）
    tracker_rescue_dedup_px: int = 60            # 救援候選去重半徑（同一框的碎片合併；與 remote_aim_dedup_radius_px 同語意）
    sweep_per_dir_reference: bool = True         # D06：掃描前先轉一圈，每個方位各拍一張 preexist reference。
        # 舊版八方位共用起始方位那一張，而差分是逐像素同座標比 → 轉 45° 後比的是別的地方的牆，
        # 玩家標註的漏抓 9 張可測有 6 張死在 ref_fill（1.00/0.78/0.70/0.22/0.16）。
        # 代價＝每次 chill episode 多轉一圈（~19s，在 D2 掃描之前，不吃追蹤框壽命）。
        # 三條便宜替代路都已實機否決（亮度閘/像素相似度/不套差分），見 docs/open-detection-issues.md D06。
        # 轉一圈的重現性實測 dx=dy=0.0px（ep133 兩次 sweep 同方位相位相關）。
        # 關掉＝回到今日行為（旋轉被吃時也會自動退回）。**待實機驗證**：離線無法驗——
        # 語料裡沒有任何「掃描前的各方位幀」。
    tracker_margin_frac: float = 0.02            # find_tracker 邊緣排除帶（實戰值；vision 函式預設仍 0.10）。H019(1862,418)/H026(1288,1020) 兩次真框都被 0.10 的帶擋掉——D5 到期 FOV 收縮（以中心為錨 ~2.6x 縮放）把框推到邊緣，且 yaw 旋轉不改 y、底緣框 8 方位永遠在帶內。0.02 收得回兩顆（回歸 fixture：edge_clipped/bottom_edge_tracker_scene.png）且對全 fixture 集無新假陽性；邊緣雜訊由 preexist 差分/colored_frac/形狀確認擋
    boost_fov_settle_s: float = 1.5              # 採集中補 D5 後等 FOV 展開的時間（H026 boost 守門；補完必須重抓幀才能偵測/開火）
    aim_center_tolerance_px: int = 25            # 準心對準容差
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
    scan_confirm_mode: str = "enforce"           # harvest 168 實機驗證：off 使掃描被吃時全盲白掃 → 預設 enforce（重試後仍 False 則 abort，不白掃 8 方位）
    # 掃描成功＝右下角效果列出現雷達徽章「Local」（2026-07-25 實機校準，取代原先的左下估值——
    # 舊值 Region(20,850,200,60) 方位就錯，離線重放 22 幀 TP=0：它讀到的是左側常駐礦物面板
    # 文字 'Dyvantium 1 / Equalizosity 1'）。徽章 t+0.4s 出現、~30s 後消失（同冷卻）。
    # 這裡放**整條效果列**而非單格：徽章疊加時位置會變（見 vision.find_effect_slots），
    # 由 _confirm_scan 逐格 OCR。右緣停在常駐計數圖示左緣 x=1740，與 boost_indicator_region 同。
    # ⚠ 整條一次 OCR 不可行：psm=6 假設單一均勻文字塊，590px 帶多圖示實測讀成 'oy A\nBa' 亂碼。
    scan_confirm_region: Region = field(default_factory=lambda: Region(1150, 990, 650, 90))
        # 2026-07-28 全螢幕：y940→990（底端錨定 +50）；高度 100→90 是切掉舊區壓在工作列上的那段。
        # 右緣 1740→1800（同日實測）：效果列是**右錨定**、格距 64px、最右格右緣 x=1798。
        # 常駐 boost 次數圖示佔最右格（1740-1798），但它是 session 計數、重進遊戲會消失——
        # 此時第一個徽章就落在最右格。實測剛切全螢幕（＝剛重進）觸發 D2 掃描，'Local' 徽章
        # 出現在 1740-1798，舊右緣 1740 完全讀不到 → 掃描確認恆失敗。這一區只做逐格 OCR
        # 找 'Local'/'Cave Skim' 字樣，收進計數圖示格無害（OCR 讀出來是雜訊字）。
        # ⚠ boost_indicator_region 右緣**維持 1740**：它是形狀比對，收進計數圖示會恆判「瓶子在」。
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
    hud_y: int = 910                      # 905→860（2026-07-12，工作列可見）→910（2026-07-28，全螢幕）：
                                          # 9925cd9 校準偵測區域時漏改這個——HUD 是獨立 Win32 視窗，錨點是
                                          # 「螢幕底部可用邊界」不是遊戲畫面，windowed 時工作列擋在 y≈1015、
                                          # fullscreen 工作列不再擋，邊界下移到螢幕底 1080，同一顆 +50 平移
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
    capacity_region: Region = field(default_factory=lambda: Region(715, 63, 200, 45))
        # 頂部「Capacity: NNN%」段（2026-07-11 實機 4 張快照實測 4/4）；
        # 2026-07-28 全螢幕 y92→63（頂端錨定 -29；白字列實測 108-125 → 79-96）
    depth_region: Region = field(default_factory=lambda: Region(890, 63, 210, 45))
        # 頂部「Depth: Surface / NNNm」段（H046 開場狀態錨；2026-07-17 實機 3 張快照
        # Surface/488m/25790m 實測 3/3，fixtures tests/fixtures/reentry/h046_depth_*.png）
    capacity_reset_threshold: float = 100.0   # ≥此值連續 2 次＝容量飽和：只記一次 INFO＋維持加速輪詢，
                                              # 不再觸發 RESET_WAIT（2026-07-12 死鎖實錄：Mine Capacity 300%
                                              # 升級下顯示 100% ≠ 重置臨近，提早停挖＝死鎖）
    capacity_fast_from: float = 99.0          # ≥此值 banner worker 輪詢加速（容量飽和期間高頻監看橫幅）
    capacity_fast_interval_s: float = 0.5     # 加速後間隔（平時沿用 reset_check_interval_s=2.0）
    # 容量停滯警報（spec 04）：MINING 期間容量這麼久沒變動＝鎬子可能沒真的在挖。
    # 只發 Discord、**不停機**（誤報一次的代價是白叫一聲，停機是整晚不挖礦）。
    # 900s 遠大於一個採集週期（~6 分鐘），正常運作踩不到。
    capacity_stall_alert_s: float = 900.0

    # chill 前證據快取（spec 2026-07-30-prechill-evidence-cache-design.md A 段）
    # 為什麼要：聊天基準到 _on_enter(HARVESTING) 才拍，那時礦已被鎬子挖掉、證據就在基準
    # 裡面、差分恆為 0。MINING 期間先留幾秒的裁圖，交人工前的救援才有 chill **之前**的
    # 參考點。只裁圖不 OCR——OCR 進 MINING 熱路徑會重演 H026。
    prechill_cache_interval_s: float = 1.0    # 取樣間隔（秒）
    prechill_cache_depth: int = 6             # 環形緩衝深度（× interval = 回溯秒數）；
                                              # 6 × (460×280 + 226×335) × 3B ≈ 3.7MB
    prechill_min_age_s: float = 3.0           # 參考點至少要比 chill 早這麼久。**待實機資料修正**：
                                              # 太新的參考可能已含那次挖掘（chill 偵測本身有延遲），
                                              # 太舊則把無關挖掘算進差分、製造假「已被挖走」

    # 交人工前救援（spec 2026-07-30-giveup-rescue-already-mined-design.md）
    giveup_rescue_enabled: bool = True        # 關掉即完全回到 2026-07-30 之前的行為
    # 觀察期（spec 03，2026-07-31）：命中時**照樣交人工**，只記帳與標註「本來會判已進帳」。
    # 這條路今天抓到兩個 bug（回傳整份面板礦名、模糊配到 Lovessence），方向都是「多宣告
    # 一次已進帳」＝靜默放生一顆真稀有礦，且兩個都躲過既有測試。先觀察再自動。
    giveup_rescue_observe: bool = True        # True＝觀察中（不自動略過人工）
    giveup_rescue_observe_target: int = 10    # 累積這麼多次判定後，由 agent session 主動問玩家
    # NORMAL 面板名字欄的兩道幾何閘（2026-07-30 實機量測，crop 座標＝相對
    # backpack_review_region）。靜態 UI（NORMAL/www）本來就會在前後兩張裁圖互相抵銷，
    # 這兩道閘擋的是**會變動**的右側 craft 面板數字被 OCR 讀歪成假礦名。
    panel_name_col_max_x: int = 185           # 名字框中心 x 上界：實測名字 72~103、
                                              # craft 面板（Materials to Craft）自 x≈185 起疊在數字欄
    panel_row_min_y: int = 60                 # 礦物列框中心 y 下界：標頭 y≈14、篩選框 y≈45、
                                              # 第一列 y≈78 → 60 兩側夾（擋掉 NORMAL/www/Sh/Mat）
    panel_name_min_letters: int = 3           # 切掉數量後至少要這麼多字母才算礦名：擋 craft
                                              # 欄被讀歪的 1-2 字雜訊（實測 '•P11/'、'.73'、'4/'）

    # 面板歸零（spec 2026-07-31-panel-zero-rescue-design.md）
    # bot 每次進 MINING 清空 NORMAL 面板的篩選框，維持「進 MINING 時面板必為空」的
    # 不變式。給救援路 B 一個「面板上有白名單礦 = 這場採到了」的存在性判準。
    panel_filter_xy: tuple = (119, 441)       # 篩選框中心（2026-07-31 全螢幕 OCR 定位；
                                              # 實機 OCR 複驗 www 中心 (118,441)，±1px 都點得中）
    # 篩選框那一行（H070 輸入生效驗證用）：打字前後比這塊的墨量，沒變＝字沒進 TextBox。
    panel_filter_band: Region = field(
        default_factory=lambda: Region(0, 424, 226, 36))
    panel_clear_keystrokes: int = 4           # 打幾個 w；改用 key_press（90ms 間隔）後遊戲來得及讀，
                                              # 不需要像舊 typewrite（40ms）那樣過量送 8 個
    panel_clear_settle_s: float = 0.3         # 打完到「抓第一張畫面」的等待。⚠ 不是「到 OCR」——
                                              # grab 在 OCR 之前，OCR 那 ~1.1s 完全不算 settle（舊註解寫反了）
    panel_clear_verify_max_s: float = 1.5     # 讀不到零點時最多重讀到這個秒數（單次 OCR ~1.1s ⇒ 至多 2 讀）。
                                              # 只重讀不重打字：H047/H063 的「多試幾次會翻面」只針對點擊/按鍵
    panel_expected_header: str = "NORMAL"     # 標頭閘：讀到 IONIZED/SPECTRAL 一律不信任面板
    # 列底色 → tier（wiki HSV 官方色碼 + 實機量測交叉驗證，2026-08-02）：
    # 全階級 wiki 色碼已收集（https://rex-reincarnated.fandom.com/wiki/Category:Tiers）
    #
    # 高階（panel_whitelist_hues）：
    #   Otherworldly 334(5E0E32)｜Unfathomable 219(032C79)｜Enigmatic 70(CDF600)
    #   ｜Transcendent 210(0080FF)｜Exquisite 128(56C365)｜Exotic 46(F6C940)
    # 低階（panel_low_tier_hues，反向閘用；D11 量測值，與 wiki 差 ≤1°）：
    #   Mythic 304(FF00EB,wiki305)｜Surreal 166(1DD7A9,wiki165)｜Master 280(9A00E6)
    #   ｜Rare 30(FF8001)｜Uncommon 0(FF2626)｜Common 0(C1C1C1,灰階S=0)
    # ⚠ Rare wiki FF8001 HSV≈30°，Uncommon FF2626 HSV≈0°——兩階色相相近但 Rare 偏橙。
    #   Common／Layer 是灰階（S=0），色相無意義，實機量到 H=0 與 Uncommon 同帶；
    #   兩種灰只能用 V 分辨（色帶起點 x=18：Common 192、Layer 132，D13）。
    # 反向閘語意：色相**不**落在這些帶就當成高階、擋零點成立。
    panel_whitelist_hues: tuple = (46.0, 70.0, 128.0, 210.0, 219.0, 334.0)
    panel_low_tier_hues: tuple = (0.0, 30.0, 166.0, 280.0, 304.0)
    panel_hue_tol_deg: float = 6.0
    panel_hue_sample_x: tuple = (120, 165)    # 取樣窗（crop 座標）：名字與數量之間的純底色帶。
                                              # ⚠ 別往左取，x<10 是面板邊框（深藍 H≈120，與列色無關）
                                              # 這裡的 V 已被漸層衰減到原色 ~55%——要加 S/V
                                              # 判據得改用色帶起點 x=18（＝wiki 原色，D13）
    annotate_undo_window_s: float = 900.0     # 標註 Ctrl+Z 還原限時（spec 05）：只救當下誤按，
                                              # 不刪可能已進版控的舊素材。15 分鐘

    # 雙 chill 對帳（spec 2026-07-30-double-chill-reconciliation-design.md）
    # 兩個都預設關。chill_edge_release_s 的初值**必須**由實機上升緣／回落分布決定，
    # 不可憑感覺填——門檻猜錯會直接製造新的人工次數（見該 spec Blocked On）。
    chill_edge_release_s: float = 0.0         # 分數要回落多久才算下一聲；0 = 對帳停用
    chill_reconcile_enabled: bool = False     # 帳不平時交人工（需 chill_edge_release_s > 0 才生效）

    # Banner 色相 double-chill 偵測（2026-08-02）：音訊 1.5s 滾動窗無法分辨兩聲「連音」，
    # 但 banner 文字是離散的——每則 spawn 訊息有唯一隨機 RGB（16.7M 種），色相跳變＝第二則。
    # 文字在音效之前刷新（~0.4-0.6s），MINING 期間每 tick 取樣即可抓到（詳見 grill 結論）。
    banner_color_sample_enabled: bool = True   # MINING 每 tick 取樣 banner 文字色相
    banner_text_sat_min: int = 60              # HSV 飽和度下限：暗底上高飽和＝文字像素
    banner_text_val_min: int = 80              # HSV 亮度下限
    banner_text_pixel_min: int = 20            # 最少文字像素數；少於此＝無有意義文字
    banner_hue_change_deg: float = 15.0        # 色相差門檻（0-360 制；內部 /2 轉 OpenCV 0-179）
    double_chill_window_s: float = 3.0         # chill 觸發前往回看幾秒內的色相跳變

    # 進場面板色檢（H072，2026-08-01）：chill 觸發進 HARVESTING 時，若面板已有白名單
    # （Exotic+）礦＝chill 前鎬子已挖到→不需要 D3 採集。觀察期一律交人工確認。
    # 前提：_panel_zeroed_at 有值（進 MINING 時面板已清空驗證過）。
    harvest_entry_panel_check: bool = True
    panel_check_observe_target: int = 10    # 累積這麼多次進場面板判定後，由 agent session 主動問玩家
                                            # 是否切自動（不交人工、直接回 MINING）
    detection_disabled_tiers: tuple = ()     # 偵測系統排除的階級（空 = 全偵測）；
                                             # 支援非連續選擇，如 ("Exotic",) = 排除 Exotic

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
    # 回礦語料夾（`miningbot/corpus.py`）：有 click ground truth 的八方位圖搬離
    # snapshots/ 才不會被上面那條 retention 從最舊刪掉（2026-07-28 實測 200 張只剩
    # 58 張、可用配對只剩 1 正 7 負）。獨立上限、到頂時優先刪無 click 的組。
    corpus_max_total_mb: int = 4096
    # `build_reentry_dataset --eval` 判「命中」的半徑：偵測器最高分預測落在真實
    # 座標這個距離內就算中。傳送板本身有大小，像素級精確沒有意義；要調就在這裡調。
    reentry_dataset_hit_radius_px: int = 80
    # 傳送板偵測器（`teleport_board.py`）——全部由 2026-07-28 語料實測而來，
    # 量法與各區域的 HSV 百分位寫在該模組 docstring。語料是單一世界／單一層／
    # 全夜晚、只有 4 個板子實例，**換場景必須重量**。
    teleport_board_hue_range: tuple = (126, 148)   # 紫羅蘭外框（板子中位 133）
    teleport_board_sat_range: tuple = (60, 200)    # 上界擋掉更飽和的夜空/UI（中位 157/121）
    teleport_board_val_range: tuple = (80, 200)    # 下界擋掉更暗的夜空/UI（中位 48/44；板子 115-127）
    teleport_board_roi: tuple = (230, 150, 1600, 750)  # 只排掉螢幕空間 UI 邊緣，非板子位置假設
        # 右緣 1730→1830（2026-07-31，ep35/37/38 標註）：ROI 是**遮罩裁切**，板子跨過右緣時
        # 不是被拒而是被切一半 → 連通塊的 ar/fill/area 全歪（實測 ar 4.85／1.36、area 1930），
        # 三場全 None。兩側夾：板子右緣實測 1696／1799／1809／**1816** → 1830 留 14px；
        # 誤收側右側圖示欄 x 1740~1908、y 694~1068，整塊 ar=0.45、被 1830 裁後 ar≈0.24，
        # 遠在 aspect_range (1.6,3.0) 之外——實測連完全不裁（右緣 1920）四張都仍命中板子。
        # 取 1830 而非 1920 是留給別的世界可能存在的右側 UI。
    teleport_board_close_px: int = 11              # 形態學閉運算核；外框是細長條，不接起來會碎成多塊
    teleport_board_min_area: int = 2500            # 實測板子 3496~5945；小於此的是雜訊
    teleport_board_min_w: int = 40                 # bbox 最小寬高（實測板子 148~201 / 88~94）
    teleport_board_min_h: int = 20
    teleport_board_aspect_range: tuple = (1.6, 3.0)    # 實測 1.68~2.21
    teleport_board_fill_range: tuple = (0.22, 0.60)    # bbox 內遮罩占比，實測 0.27~0.33
    teleport_board_dark_v: int = 90                # 「內部暗像素」的 V 門檻
    teleport_board_bright_v: int = 200             # 「內部極亮像素」的 V 門檻
    teleport_board_min_dark_frac: float = 0.40     # 板子面板是深藍黑，實測 0.56~0.62
    teleport_board_max_bright_frac: float = 0.20   # 發光 UI 元件實測 0.36~0.50，板子 0.05
    teleport_board_aspect_center: float = 2.1      # 以下三項是 candidate_score 的實測中心/寬度
    teleport_board_aspect_tolerance: float = 0.9
    teleport_board_fill_center: float = 0.32
    teleport_board_fill_tolerance: float = 0.28
    teleport_board_dark_ref: float = 0.55
    # 預測分數低於此就不畫圈（畫一個亂猜的圈比不畫更糟）。2026-07-28 實測：語料裡
    # 4 個真板子的分數 0.759 / 0.947 / 0.969 / 0.973，**沒有任何非板子候選通過幾何
    # 閘**，所以這是「最弱一個真命中的下緣」而不是兩側夾出來的分離點。語料長大、
    # 真的出現非板子高分候選時要重新量。
    reentry_predict_min_score: float = 0.70
    # 點擊前把玩家座標吸附到「當下這一幀」的板子（RR#42，2026-08-01）。玩家看的是
    # 八方位掃描那一輪的舊幀，實錄隔了 8 分鐘才點——期間鏡頭/角色漂了 ~156px，
    # 照打就落在板子右邊的雪地。0＝關閉。兩側夾（tests/fixtures/reentry/teleport_board
    # 八組，量測腳本見 docs/open-detection-issues.md D13）：**點在板上**的六次
    # descended 離錨點 37.5/41.4/43.9/45.2/56.9/65.8px（另 auto_38 點在板上但因別的
    # 原因失敗，47.5px），**點在板外**的 auto_42 是 160.3px → 取中間值，兩側各留 ~45px。
    reentry_click_snap_px: int = 110
    # 錨點是板面上緣、系統性偏上：六次成功點擊的 y 一致落在錨點下方 +37~+45px。
    # 吸附時補回這個偏移，才落在成功點擊的位置（x 的殘差 -6~-48px 太散，不補）。
    reentry_click_anchor_dy_px: int = 40
    snapshot_queue_max: int = 16                  # 1080p BGR 約 6MB/張；限制最壞記憶體占用
    snapshot_queue_critical_reserve: int = 4      # 保留給 rare/review/reentry，trace 不得吃滿
    snapshot_shutdown_drain_s: float = 5.0        # Bounded shutdown wait for queued snapshot writes.
    discord_sink_queue_max: int = 64              # 網路斷線時避免事件無界堆積
    perf_log_interval_s: float = 60.0             # 主迴圈延遲分位數寫 heartbeat.log 的間隔
    perf_sample_window: int = 300                 # 每個階段保留最近 N 筆樣本

    # 重置自動回礦（auto re-entry；docs/superpowers/specs/2026-07-08-mine-reentry-design.md）
    reentry_mode: str = "remote"                # "off"=RESET_WAIT 等人工（今日行為）/"remote"=Discord 指位（2026-07-12 spec）/"auto"=全自動（2026-07-08 spec，面板模板校準完成前勿開）
    reentry_surface_button_xy: tuple = (1855, 1015)  # 右下「Go to surface」UI 按鈕中心（2026-07-12 視窗化量測 x1804-1907/y914-1017 → 中心 965；2026-07-28 全螢幕 +50＝1015，實機白字列 1003-1036 佐證——同 d1_slot_region 家族）
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
    reentry_open_capacity_max_pct: float = 5.0   # 開場容量閘（H045，僅 reset 觸發）：拍照前容量 OCR 須
    #   ≤ 此值；亦為 H058 開場前預檢（capacity_blocks_opening）門檻——容量 > 此值時
    #   不點擊「回到地表」、不拖曳俯仰，被動等候。兩側夾：凍結舊幀 Capacity 78%
    #   （2026-07-14 ep3 實機幀）/ 重置進行中（地表）56~71%（RR#2 01:33~01:34 實讀）
    #   vs 真重置完成後 0~1%（H046 0%、H053 RR#7 連續 17 次 1%）。
    #   凍結中傳送驗證可能在凍結開始前真過了——容量歸零是「重置真的完成且畫面是活的」第二訊號。
    #   H046：容量 OCR 與俯仰結果解耦（頂部 Capacity 列不管俯仰有沒有生效都讀得到）。
    #   H053（2026-07-20 RR#7）：舊預設 0.0 太嚴——真重置完成後容量 OCR 穩定讀到 1%（非 0%），
    #   1.0 > 0.0 恆成立→開場閘永遠回 capacity、預算 300s 耗盡卡死。改 10.0＝與
    #   reset_chime_capacity_arm_pct 同概念（同一幀鈴聲路徑早已用「1% ≤ 10%」接受），兩側各 ≥10x 餘裕。
    #   H058（2026-07-20 RR#8~12）：10.0 仍太鬆——banner 消失即起跑、重置第二階段（容量 60~76%
    #   排到 ≤10%）進行中每 20s 一輪 click+pitch+OCR 全卡在卡頓裡被吃（~90s）。改 5.0＋
    #   開場前預檢：容量 > 5% 時不動作只被動觀測。5.0 兩側各 ≥4x 餘裕（真完成 ≤1 vs 收尾 ≥56）。
    #   鈴聲路徑 reset_chime_capacity_arm_pct 仍維持 10.0（預檢路徑照樣呼叫 _maybe_arm_chime 推進錨）。
    reentry_reset_drain_budget_s: float = 900.0  # H066：重置收尾「被動等容量排掉」的**獨立**預算。
    #   H058 讓這段等候吃 reentry_open_budget_s（開場探測預算），於是「等遊戲排容量」與
    #   「探測畫面凍結」共用 300s。2026-07-29 RR#31 容量一路降到 48% 時預算就見底
    #   （97→88,88→82,82→72×8→48,48，實測 ~0.165 個百分點/s，從 ~97% 排到 ≤5% 需 ~575s）。
    #   健康場次只要 ~110~160s，最壞觀測 ~575s，900s 給 1.5 倍餘裕。
    #   ⚠ 拉長不等於白等：舊版 300s 用盡後是「交人工、等玩家回訊息」——RR#31 那次玩家
    #   14 分鐘後才回，比多等 600s 還久。這段期間 bot 不點擊不拖曳，等候本身零風險。
    #   容量「連續沒再降」的輪數只寫進 log／通知供人判讀，**不設門檻**：健康場次最長連
    #   1 輪、RR#31 慢但會動連 7 輪、RR#30 連 9 輪——而 9 是被舊 300s 截斷的上界，
    #   沒有「久到確定不會恢復」的負樣本，寫門檻不可否證（H059 教訓）。
    reentry_frozen_mean_max: float = 0.02       # 凍結探針（H046）：俯仰拖曳前後幀 mean ≤ 此值「且」frac ≤
    reentry_frozen_frac_max: float = 0.0002     #   下值才判凍結。兩側夾：凍結 0.00/0.0000（逐位元相同）vs
    #   活著靜止 0.09/0.0004 vs 夜間地表拖曳最小 0.93/0.018（2026-07-17 ep1）。⚠ 不可改用
    #   pitch_eaten_*（那是「拖曳生效」門檻 8.0/0.15）——H046 就是誤用它把活人鎖 300s
    reentry_pitch_clamp_px: int = 1500          # 俯仰歸位：向下拖到夾限的量（過量無妨，飽和即可）
    reentry_pitch_back_px: int = 370            # 回拉量（R 視窗校準出、寫回這裡）
    reentry_attempt_warn_every: int = 5         # 人工重骰每 N 次提醒可跳過/調視角（0=關；attempt 無上限不變）
    reentry_yaw_sample_sweep: bool = False      # H059 語料收集：成功收尾後原地拍八方位再回原向。
    #   根因（2026-07-20 spec，07-21 覆核成立）：每輪 attempt 都按「回到地表」換重生點＝遊戲
    #   隨機化 yaw，restore_view 轉回的是隨機基底 → 直角/對角各約一半（使用者實測）。根治需
    #   視覺校正，但目前**缺「斜挖」負樣本**、無法依 H040/H054 慣例兩側夾。八方位取樣的相鄰幀
    #   固定差 45°⇒偶數組與奇數組必分屬兩類，分類器可用「週期 2 交替」自洽驗證、不需絕對標籤；
    #   絕對歸屬人工標一輪即可定錨。**預設關**：每 episode 多 ~10-15s，只在收語料的場次開。
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
    # 手動取樣（校準素材收集；也可用於裁追蹤框模板/補 OCR fixture）。R 鍵視窗已於
    # 2026-07-17 退役，改走遙控器 📷／回礦 `仰角`；hotkey_sample 欄位 2026-07-30 刪除。
    manual_snapshot_dir: str = "logs/snapshots/manual"
    sample_pitch_step_px: int = 40              # R 視窗上/下微調一次的拖曳量
    sampler_pitch_focus_settle_s: float = 0.5   # 俯仰鈕：聚焦回遊戲→拖曳前的沉澱。2026-07-11 實機：
                                                 # 三次「聚焦成功」但拖曳全沒生效——焦點剛切回就送
                                                 # 右鍵拖曳會被吃（與旋轉鍵被吃同家族），settle 後再拖

    # --- 失敗路徑俯仰掃描（2026-07-11 spec：標準層 8 方位全空才掃上/下層）---
    sweep_pitch_enabled: bool = False           # 校準完成前保持 False（比照 reentry 慣例）
    sweep_pitch_step_px: int = 100              # 一層 nudge 拖曳量（0=未校準＝停用；正=向下拖）。
                                                 #   0→185（2026-07-28）：值一直是 0，所以玩家在網頁勾了
                                                 #   「掃描俯仰」也永遠回空層序列，功能從實作至今沒跑過。
                                                 #   推導：center_back_px=370＝夾限飽和回拉到挖礦標準角
                                                 #   （約略水平），故 370px≈90°、約 4.1 px/度 → 185px≈45°。
                                                 #   185→100（2026-07-29，harvest 121 實機幀；D07）：45° **抬過頭**
                                                 #   ——up 層把鏡頭吊臂擺進地面，Roblox 拉成貼身特寫，角色蓋住
                                                 #   候選 ROI 所在的畫面中央（dir0/dir4/dir7 加層尾幀都是），八方位
                                                 #   全空是幾何必然；down 層則壓過頭，唯二命中擠在 y=154/162。
                                                 #   100px≈24°，三層落在 −24/0/+24：Roblox 預設垂直 FOV 70°
                                                 #   （D5 boost 只會更大）覆蓋 −59~+11 / −35~+35 / −11~+59，
                                                 #   重疊約 46° 更沒有縫，且離碰撞角更遠。**仍未經實機驗證**：
                                                 #   驗收看 up 層角色有沒有不再塞滿中央、down 層命中有沒有離開
                                                 #   最上緣；不對就只改這個數字，不動任何邏輯
    sweep_pitch_clamp_px: int = 1500            # pitch_reset 飽和拖曳量（沿用 reentry 初值；礦內校準可調）
    sweep_pitch_center_back_px: int = 370       # 挖礦標準角：夾限飽和後回拉量（校準 挖礦/CLI 寫回；0=未校準＝停用）。
                                                 #   370＝2026-07-20 使用者確認：本世界挖礦角＝地表角，沿用
                                                 #   reentry_pitch_back_px；換世界若挖礦角不同須 `校準 挖礦` 另校

    # --- Discord 遠端瞄準（2026-07-11 spec：giveup 附近失候選編號圖，回訊息即指揮）---
    remote_aim_enabled: bool = True             # 關掉＝giveup 附圖/回覆解析全部回到今天行為
    remote_aim_max_candidates: int = 9          # 附圖候選編號上限（防洗版）
    remote_aim_refind_radius_px: int = 160      # fire 前重找 ROI 半徑（同 shape_roi 半徑量級）
    remote_aim_fullframe_fallback: bool = True  # H056：ROI 重找全滅時再全畫面找一次（confirmed 門檻）
    remote_aim_dedup_radius_px: int = 60        # H056：同層同方位近失候選合併半徑（小於框寬 100~207）
    remote_aim_budget_s: float = 120.0          # 單次 fire 全流程預算（對齊+重掃+驗證）
    remote_aim_snapshot_wait_s: float = 3.0     # Total wait budget before rendering or directly sending async snapshots.
    harvest_target_recovery_max: int = 1        # At most one recovery at an accepted/fired absolute direction.
    harvest_target_recovery_radius_px: int = 240  # Expanded ROI around the historical target coordinate.

    # --- 手動瞄準精定位（harvest 101；2026-07-21 spec）：玩家選粗格後限縮該格做特徵偵測，
    # 命中即自動開火框真正中心；抓不到退回放大手選。偵測器色 profile 漸進擴充（現僅綠）。---
    tracker_core_profiles: list = field(
        default_factory=lambda: [("green", (40, 150, 150), (85, 255, 255))])
        # [(name, hsv_lo, hsv_hi)]；非覆蓋色系遇到→偵測 None→退回放大手選（永不誤射）。
        # 新色 fixture 到手才加（兩側夾，比照 tuning-from-incidents）。
    tracker_core_min_area: int = 80             # 框面積下限（cell 原生解析度；綠框實測 256）
    tracker_core_max_area: int = 1800           # 框面積上限：亮綠「地形」與框心同色且大塊實心，
        # 被格邊裁成近方形後 ar/extent/border 三關全過（101 dir1/2/3 實測 4918/15043/17268/25631），
        # best 取面積最大→會蓋掉同格真框朝地形開火。兩側夾：真框心 256×6／663（edge_clipped
        # 33×32）vs 地形最小 4918 → 取 1800（真值 2.7 倍、誤收 1/2.7）。方向＝寧漏勿誤射
        # （漏＝退回放大手選，誤射＝浪費一發且打空）。
    tracker_core_ar_lo: float = 0.6             # 方形長寬比下限（綠框 ar≈1.0）
    tracker_core_ar_hi: float = 1.7             # 方形長寬比上限
    tracker_core_extent_min: float = 0.6        # 實心理度下限（輪廓面積/bbox 面積；綠框 extent≈0.89）
    tracker_core_border_margin: int = 6         # 黑邊環帶寬度（bbox 外側 margin px）
    tracker_core_border_dark_max: int = 70      # 「暗」像素 gray 上限（黑邊判定）
    tracker_core_border_dark_frac_min: float = 0.15  # 環帶暗像素佔比下限（綠框實測 0.35、空格 0）
    remote_aim_zoom_margin_frac: float = 0.15   # grid_cell_region 裁格對稱餘裕（頂緣 clamp y0=0）
    remote_aim_fine_grid: int = 6               # 放大圖細網格 6×6（同回礦 reentry_remote_fine_cols）
    remote_aim_fov_recheck_max: int = 2         # 退路 FOV 作廢重發上限（boost 變 FOV 即作廢重發，不依賴 D5）

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

    # 熱鍵（控制權）。Ctrl+Q／Q 的鍵碼寫死在 main._HotkeyController（GetAsyncKeyState
    # 0x11/0x51），對應的 hotkey_emergency_stop/hotkey_pause 欄位沒人讀，2026-07-30 刪除。
    # 語意留存：Ctrl+Q＝只暫停（不結束程式、不繼續）放開所有按鍵等 Q 繼續；Q＝開關 暫停 ↔ 繼續
    # （也用於人工介入／礦坑重置定位後重啟；啟動環境檢查期間按 Q＝跳過剩餘檢查直接開挖——
    # 原 F8 專用鍵與 Roblox 內建功能衝突而廢棄，2026-07-10）。
    hotkey_quit: str = "f12"                     # 真正結束程式
    antiafk_interval_s: float = 900.0            # 防掛機踢除：暫停中每 N 秒按一次 Space（預設 15 分鐘）
    antiafk_chill_mute_s: float = 6.0            # H060：按 Space 後 N 秒不採信 chill——原地跳的音效
                                                 # 會被認成 chill（2026-07-22 三次 REENTRY 誤報全在按鍵後
                                                 # 2s，分數 0.25/0.38/0.37）。窗長取實機量測的分數尾巴
                                                 # +4s/+5s/+4s 再留邊際；佔保活週期 0.67%，只影響等待狀態

    # 網頁 UI（2026-07-26 spec；P1：IPC 基礎建設）
    # H061（2026-07-26）：這格關掉會讓 main.py 檔頭跳過 web 模組的模組層 import。
    # 真根因是「web import 在 daemon thread 內失敗 → pythonw 無 stderr → 無聲死亡」，
    # 已由 main.py 檔頭的模組層 import ＋ ImportError 降級修掉（詳見該處註解；調查期間
    # 「import lock 死結」的判定是錯的，見 docs/incidents.md H061）。若因故要臨時停用
    # 網頁 UI，改這格即可——每條 web 路徑都守 _web_pending / _web_fallback 是不是 None，
    # 會自動退回既有 Discord fallback（PING、八方位圖、文字命令、遙控器）。
    web_server_enabled: bool = True              # 啟用網頁伺服器（綁定位址見 web_server_host）
    web_server_port: int = 8765                  # 網頁 port（Tailscale Serve 出 HTTPS）
    # 綁定位址＝這台機器的 Tailscale IP（2026-07-26 使用者指定）。手機在同一個
    # tailnet 直接開 http://100.110.130.17:8765 就進得去，不必再跑 `tailscale serve`。
    # 綁在這張網卡而不是 "0.0.0.0" 是刻意的：介入面板**沒有任何認證**，能直接驅動
    # 遊戲；綁 0.0.0.0 等於把它開給所在區網（咖啡廳 Wi-Fi 也算）。tailnet 的裝置
    # 授權就是這裡唯一的門。
    # ⚠ Tailscale 沒啟動時這個位址不存在 → bind 失敗。main.py 會自動退回
    #   127.0.0.1 重試（log 會說），所以本機仍然開得起來，不會整個網頁 UI 消失。
    web_server_host: str = "100.110.130.17"
    # 等 uvicorn 把 socket 綁上的秒數（超時＝放棄這個位址、退回鏈試下一個）。
    # 5.0→20.0（2026-07-29 實機）：14:36 那場退回了 127.0.0.1、手機整場連不進來，
    # 但當時 Tailscale 早就起來（開機在 07-25、bot 起在 14:31）、`100.110.130.17`
    # 事後實測 bind 得上，log 也寫著 `should_exit=False`＝uvicorn **根本還沒綁到
    # 失敗那一步**，只是第一次啟動要付一次性成本（event loop／config.load／
    # protocol import）而主執行緒正忙著 __init__ → 5s 不夠。隨後退回 127.0.0.1
    # 的那次 <1s 就成了，因為模組已經熱了——這正是「超時太短」而非「位址不通」的鐵證。
    # 真的綁不上時 uvicorn 會自己設 should_exit，polling 迴圈立刻跳出，不會白等 20s。
    web_server_bind_wait_s: float = 20.0
    web_fallback_grace_s: float = 30.0           # WebSocket 0 client 後等多久才切 fallback
    # 網頁介入的等待「預算」欄位（web_intervention_budget_s／
    # web_intervention_retry_budget_s／web_join_grace_s）已於 2026-07-30 全部刪除：
    # 回礦 web 介入改成**無限等，只有玩家按提醒訊息上的 🔀 才切 Discord**（使用者指定）。
    # 沿革：120s（借 remote_aim_budget_s）→ 300s → 900s ＋ 120s join grace，每一次
    # 拉長都只是把同一條 race 往後推。RR#34 實錄——18:28:23 推圖＋發 Discord 提醒，
    # 18:30:23 grace 到期退場並清掉重播緩衝（end_intervention_replay），使用者
    # 18:41:45 才開網頁 → 面板全空。玩家是被推播叫來的，任何固定窗都會漏掉他。
    # 中止條件見 main._await_web_reentry_action：礦坑重置／關閉／暫停。
    websocket_ping_interval_s: float = 30.0
    # **P5 Task 2 deprecated**——app-level text-message "ping" 只能在 TCP 全斷才拋，
    # 無法偵測手機背景化／Tailscale relay 半斷的 half-open 連線；改依賴 uvicorn
    # 預設 20s 協議級 ping frame（真正的 keep-alive）。欄位保留以免破壞既有呼叫端，
    # 但 ws_endpoint 不再讀它（silent ignored）。

    # Discord（Phase 2）— token 從 .env 讀，不寫死在程式碼
    discord_bot_token: str = field(default_factory=lambda: os.getenv("DISCORD_BOT_TOKEN", ""))
    discord_channel_id: str = field(default_factory=lambda: os.getenv("DISCORD_CHANNEL_ID", ""))
    discord_poll_interval_s: float = 1.0        # Discord 命令/反應輪詢間隔（秒；單卡 reaction 摘要已把每輪 GET 壓到 1 次）
    discord_repin_quiet_s: float = 4.0          # 釘底防抖安靜窗（秒）：頻道最後一則新訊息後安靜滿此秒數，才把遙控器/回礦卡刪舊貼新到頻道底（輪詢 1s ≈ 4 輪安靜；2026-07-19 spec）
    discord_status_edit_min_interval_s: float = 3.0
    # 狀態訊息 edit_message 降頻（秒）：狀態/動作變動最快每 N 秒 edit 一次，
    # 避免狀態機快速擺盪洗版（2026-07-26 P2 spec §7）。低於此間隔的變動
    # 靠下次 repin（RepinDebouncer）順帶刷新。
    restart_delay_s: float = 10.0               # Discord `重開`：relauncher 等待秒數（確保舊行程完全結束再啟動新的；必須 > snapshot_shutdown_drain_s(5.0) + web thread join timeout(2.0) + audio/放鍵餘裕，不是只蓋 drain）
    restart_marker_max_age_s: float = 300.0      # restart_marker 存活上限（秒）：擋失敗重開留下的過期 marker——舊行程 relauncher 啟動後自己 crash、或新行程還沒到 run() 就死，marker 會一直躺著；下次「跟這次重開無關的手動啟動」若不擋，會誤報「重開完成」到 Discord

    # 選單前置切換（Movement Mode）＋聊天框前置檢查
    # docs/superpowers/specs/2026-07-08-menu-preflight-boost-design.md
    movement_mode_options: tuple = ("Default (Keyboard)", "Keyboard + Mouse", "Click to Move")
    movement_mode_mining: str = "Default (Keyboard)"    # 挖礦用（兩個鍵鼠模式皆可，使用者確認取此值）
    movement_mode_reentry: str = "Click to Move"        # REENTRY 導航用（click-to-move 依賴此模式）
    menu_panel_region: Region = field(default_factory=lambda: Region(440, 100, 1040, 910))
        # Esc 選單面板整塊（分頁列 People/Settings/... ＋ 內容列表），OCR 找標籤/值/箭頭都在此裁圖裡做。
        # ⚠ 這塊是**置中面板**，不隨頂/底錨定平移：2026-07-28 全螢幕實測面板 x434-1484 / y93-1010
        # （視窗化時的舊區 460,130,1000,880 會把分頁列文字上緣切掉 → 找不到 Settings 分頁）。
        # 分頁文字實測中心 People(581,131) Settings(781,131) Gallery(980,131)。
    menu_movement_label_region: Region = field(default_factory=lambda: Region(500, 811, 300, 50))
    menu_movement_value_region: Region = field(default_factory=lambda: Region(1000, 811, 350, 50))
    menu_movement_row_y: int = 836       # 固定列快速路徑；辨識不確定時回退全面板 OCR。
        # 2026-07-28 全螢幕實測：Settings 分頁開啟後 Movement Mode **不在首屏**（Roblox 已在上面
        # 插入 Audio／Chat & Language／Graphics 等段），要捲 4 次 menu_scroll_amount 才出現，
        # 標籤中心 (572,836)／值 'Default (Keyboard)' (1152,837)。快速路徑因此只在「捲屏迴圈停下
        # 之後」成立（箭頭點擊後的複讀正是這個狀態，省一次全面板 OCR）；首次進來必定 miss →
        # 回退全面板 OCR + 捲屏，行為安全。
    menu_arrow_right_x: int = 1425       # 值列右箭頭 x（y 用該列 label 的 y；2026-07-08 實測 1423~1425，
                                         # 2026-07-28 全螢幕複驗仍是 1425——面板寬度不隨版面變）
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

    chat_icon_xy: tuple = (174, 42)      # 左上聊天圖示（收合時點它展開；2026-07-08 實測 (174,71)＝視窗化，
                                         # 2026-07-28 全螢幕 -29＝(174,42)，泡泡亮部 32-54 實測佐證）
    chat_icon_state_region: Region = field(default_factory=lambda: Region(154, 22, 40, 40))
        # 左上聊天圖示狀態判定框（H047：開＝實心白泡泡、關＝空心白邊；40x40 含整個圖示；
        # 任何狀態都看得到，不像輸入列 placeholder 會被自動隱藏——取代舊版輸入列 OCR 信號）
    chat_icon_probe: tuple = (6, 21, 18, 28)
        # 泡泡內部補丁（crop 相對 x0,y0,x1,y1；位於泡泡左下內部，避開中央文字筆劃與右上未讀徽章）
    chat_icon_open_min_gray: float = 180.0    # >= 判開（實心白泡泡）
        # 實測補丁灰階平均：開 237..255（n=42+）、關 81..94（n=19 含未讀徽章「11」樣本、
        # 2026-07-28 全螢幕實測 82.9 無 hover／93.6 游標懸停）→ 兩側夾
    chat_icon_closed_max_gray: float = 130.0  # <= 判關（空心、內部暗）；到 open 之間 unknown
    chat_icon_closed_min_gray: float = 60.0   # < 此值＝補丁沒照到圖示 → unknown，絕不點擊（H063）
        # 2026-07-28 14:09 實機讀到 41.0（三幀分毫不差＝靜態暗色浮層蓋住圖示），舊碼
        # `<=130 就判關` 把它當關 → 連點 3 次 toggle → 把開著的聊天框關掉。
        # 41.0 與實測關值下界 81 的中點 ≈ 61 → 取 60（兩側夾：41 判 unknown、81 判關）。
    chat_open_settle_s: float = 0.8      # 點聊天圖示後等展開動畫（menu_open_settle_s 0.3 偏緊）
    chat_open_max_retries: int = 0       # 判關時只點一次（H063）
        # 舊值 2（＝最多點 3 次）。實機 5 場「點了圖示卻沒反應」的重試 **0 次救回**
        # （2026-07-25 18:23／07-26 12:23、15:27／07-27 16:38／07-28 14:09 皆三讀同值後
        # give_up），成功的場次一律第一次點擊就開；而每多點一次就多一次 toggle，讀值若
        # 本身是錯的（見 chat_icon_closed_min_gray），奇數次點擊剛好把聊天框關掉。

    # ── 聊天喚醒（H064，2026-07-28 實機量測）──────────────────────────────────
    # Roblox 聊天無新訊息會整窗淡出；HARVESTING 一進場就停止採礦 → 聊天基準必然拍在
    # 淡出後、讀到 0 條 has-found → 四個確認信號全滅（採到也判 no-new）。對策是拍基準
    # 前把游標掃過聊天內容區一下把它叫回來。**只移游標、絕不點擊**：聊天隱藏時該座標
    # 下面是 3D 場景，點下去是打到遊戲世界。
    # 實測（2026-07-28 18:2x，全螢幕、Roblox 前景）chat_region 亮像素（>90）：
    #   原位 0 → hover 聊天圖示 (174,42) **304＝只冒出 "Chat" tooltip、聊天沒出來**
    #   → hover 聊天區 (230,250) **13614＝整段聊天出現** → 游標移回中央仍 13503。
    #   hover 僅 0.25s 即生效（0.5s 後量到 13614），離開後 **≥25s 不再淡出**。
    # ⚠ 前提是 Roblox 在前景：合成 hover 在非前景時整個被丟掉（第一次量測全 0 就是這樣）。
    chat_reveal_xy: tuple = (230, 250)   # chat_region 內中段（x0..460 / y81..361 的中間偏上）
    chat_reveal_hover_s: float = 0.3     # 停留時間（實測 0.25 已足，取 0.3 留餘裕）
    chat_reveal_settle_s: float = 0.5    # 移開後等淡入完成再拍（實測 0.5s 已達滿值）
    chat_reveal_min_bright_px: int = 2000
        # 喚醒後 chat_region 亮像素下限，只用來判「這次喚醒有沒有生效」並記 log
        # （失敗不擋流程，維持舊行為）。兩側夾：淡出 0/304 vs 顯示 13503~13614 → 取 2000。

    player_list_region: Region = field(default_factory=lambda: Region(1490, 110, 425, 150))
        # 右上角玩家列表（Tab toggle）標題列＋第一列。2026-07-09 由實機截圖量測：
        # client 座標 header y≈118-145；視窗化時 grab 全螢幕比 client area 低 ~29px → 區域開高吸收偏移。
        # 2026-07-28 切全螢幕（screen == client）後**不需要改**：header 回到 y118-145、第一列 155-200，
        # 仍整段落在 110-260 內（已用當下實機幀裁圖複驗）——這格開高原本就是為了吃掉這 29px。
        # fixtures: tests/fixtures/player_list/（open/open2/closed）
    player_list_phrases: tuple = ("players", "blocks mined")

DEFAULT = Config()
