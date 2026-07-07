"""啟動自檢：把「靜默降級」變成看得見的警告。

純決策層——main 收集 I/O 事實（檔案存在/計數/大小/引擎可用性）塞進 PreflightFacts，
run_checks 只做判斷（可測、禁 mock 規範友善）。每條警告對應一個文件明載的降級路徑。
"""
from dataclasses import dataclass

_MS_PER_REF_K8 = 13.0     # k=8 實測 8 refs ~98ms、12 refs ~131ms（config 註解）→ 保守取 13ms/ref
_BUDGET_FRAC = 0.8        # 音訊執行緒預算：一輪比對不得吃超過 interval 的 8 成

@dataclass
class PreflightFacts:
    marker_real_count: int          # assets/markers 無 alpha 實機裁圖數（形狀確認集）
    chill_ref_count: int            # assets/chill_refs/*.wav 數
    rare_ores_json_age_days: float  # assets/rare_ores.json mtime 距今天數；缺檔給 -1
    ores_all_present: bool
    d4_cooldown_present: bool
    discord_token_set: bool
    tesserocr_ok: bool
    rapidocr_ok: bool
    log_dir_abspath: str
    snapshots_total_mb: float
    audio_decimate: int
    audio_interval_s: float

def run_checks(f: PreflightFacts) -> list:
    out = []
    if f.marker_real_count == 0:
        out.append(("WARN", "assets/markers 無實機裁圖 → 追蹤框偵測退回純 HSV（形狀確認停用）"))
    if f.chill_ref_count == 0:
        out.append(("WARN", "chill_refs 空 → 退回單一參考檔（H034：至少 4+ 音效家族，單參考必漏）"))
    elif f.chill_ref_count < 4:
        out.append(("WARN", f"chill 參考只有 {f.chill_ref_count} 個（<4 家族），漏抓風險高（H034）"))
    est_ms = f.chill_ref_count * _MS_PER_REF_K8 * (8 / max(f.audio_decimate, 1))
    if est_ms > f.audio_interval_s * 1000 * _BUDGET_FRAC:
        out.append(("WARN", f"chill 參考 {f.chill_ref_count} 個估 {est_ms:.0f}ms/輪，"
                            f"超出 {f.audio_interval_s}s 間隔預算 → 音訊積壓風險，調 audio_match_decimate"))
    if f.rare_ores_json_age_days < 0:
        out.append(("WARN", "assets/rare_ores.json 缺 → fuzzy 兜底/三態分類降級全 unknown（跑 fetch_ores）"))
    elif f.rare_ores_json_age_days > 60:
        out.append(("WARN", f"rare_ores.json 已 {f.rare_ores_json_age_days:.0f} 天未更新，"
                            f"遊戲更新後記得跑 fetch_ores"))
    if not f.ores_all_present:
        out.append(("WARN", "assets/ores_all.json 缺（fetch_ores 產物）"))
    if not f.d4_cooldown_present:
        out.append(("INFO", "d4_cooldown.png 缺 → D4 退回定時刷新後備模式"))
    if not f.discord_token_set:
        out.append(("INFO", "Discord token 未設 → 通知/遠距命令停用"))
    if not f.tesserocr_ok:
        out.append(("WARN", "tesserocr 不可用 → 退回 pytesseract（每次 OCR +2.5s，boost 偵測會被餓死）"))
    if not f.rapidocr_ok:
        out.append(("WARN", "RapidOCR 不可用 → 聊天 OCR 退回 tesseract 三 pass（讀歪類假陰性風險回升）"))
    if "onedrive" in f.log_dir_abspath.lower() and f.snapshots_total_mb > 500:
        out.append(("WARN", f"log 目錄在 OneDrive 同步夾且 snapshots 已 {f.snapshots_total_mb:.0f}MB"
                            f" → 同步負擔/IO 干擾；考慮 log_dir 移出或依賴保留策略"))
    return out
