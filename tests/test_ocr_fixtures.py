"""OCR 回歸測試集：對「實機聊天框裁圖」跑完整 OCR 管線，鎖住跨背景的讀取能力。

背景（2026-07-03 H014 假陰性根因）：verify 用單一 min_channel 前處理，在亮粉糖果礦區
背景下彩色聊天行全滅——真正採到的「has found Diamorite」（底部新行）沒讀到 →
confirmed=False → RESWEEP → 已採走掃不到 → 誤交人工。

fixtures 取自 logs/snapshots/trace 的實機裁圖（chat_region crop），涵蓋三種背景：
- h014_*：亮粉背景（dark_mask 才讀得到彩色行）
- h005_mixed_dark_bg：暗棕混合背景（min_channel/gray 各救回不同行）
- h010_faded_no_text：聊天淡出、無字（所有 pass 都必須回 0——防幻覺文字假陽性）

之後改前處理/門檻，跑這套即知有沒有「修好一種背景、弄壞另一種」。
新背景（如全黑礦坑）的樣本從 snapshots 累積後照樣補進來。
需要本機 tesseract（同 production 引擎）；未裝時整檔 skip，不擋純邏輯 CI。
"""
import os
import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from miningbot import ocr, game_data  # noqa: E402
from miningbot.config import DEFAULT as cfg  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "chat")
KW = ("has found", "found a")


def _engine_ready() -> bool:
    """實際跑一次小圖 OCR 確認引擎可用（tesserocr 或 pytesseract 任一）。"""
    try:
        ocr.read_text(np.zeros((20, 120, 3), dtype=np.uint8), cfg.tesseract_path)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _engine_ready(), reason="tesseract 引擎不可用")


def _load(name: str):
    # cv2.imread 在 Windows 吃不了非 ASCII 路徑（專案資料夾是中文名）→ fromfile+imdecode
    data = np.fromfile(os.path.join(FIXTURES, name), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    assert img is not None, f"fixture 讀不到: {name}"
    return img


def test_h014_pink_bg_fusion_confirms_diamorite_harvest():
    # H014 實況重演：before 聊天淡出全空、after 底部新行是 Diamorite（暗紫字＋亮粉背景）。
    # 單一 min_channel 讀不到 Diamorite（當時的假陰性）；融合讀取必須確認採集成功。
    before = ocr.read_text_multi(_load("h014_before_faded_pink.png"), cfg.tesseract_path)
    after = ocr.read_text_multi(_load("h014_after_pink_bg.png"), cfg.tesseract_path)
    assert any("diamorite" in t.lower() for t in after), \
        "至少一個前處理 pass 要能讀到 has found Diamorite 行"
    # 當時世界已鎖 Lucernia → 排除清單用 Lucernia 的（Jollycane 在清單內、Diamorite 不在）
    common = tuple(o["ore"] for o in game_data.LUCERNIA.common_ores)
    assert ocr.any_new_rare_found(before, after, common, KW) is True


def test_h010_faded_chat_reads_nothing_in_every_pass():
    # 聊天淡出＝畫面只剩礦壁：所有 pass 都不得讀出 found 行（防止新前處理引入幻覺文字）
    texts = ocr.read_text_multi(_load("h010_faded_no_text.png"), cfg.tesseract_path)
    for t in texts:
        assert ocr.count_found(t, KW) == 0


def test_h005_mixed_dark_bg_union_recovers_more_lines_than_any_single_pass():
    # 暗棕混合背景：三種前處理各救回不同子集（實測 min_channel=3、gray=4、dark_mask=4 行），
    # 聯集必須「嚴格優於」任何單一 pass，且要含只有 gray 讀得到的底部 Saerylium 行
    texts = ocr.read_text_multi(_load("h005_mixed_dark_bg.png"), cfg.tesseract_path)
    per_pass = [ocr.extract_new_found_lines("", t, KW) for t in texts]
    union = ocr.extract_new_found_lines_multi([""] * len(texts), texts, KW)
    assert len(union) > max(len(p) for p in per_pass)
    assert any("saeryliu" in l.lower() for l in union)   # 容忍 OCR 尾端雜訊（Saeryliuim）


def test_h020_pink_bg_fuzzy_confirms_valytium_harvest():
    # H020 實況重演（2026-07-03 21:22）：before 聊天淡出全空；after 底部兩行
    # 「has found Diamantine」（Surreal、被動挖到）＋「has found Valytium」（Exotic、D3 採到）。
    # 亮粉背景讓三 pass 的精確關鍵字全滅（dark_mask 讀成 "hee foumel velyiiuinm"）→
    # 當時 rare [0,0,0]->[0,0,0] 假陰性誤交人工。模糊匹配必須救回 Valytium 行。
    before = ocr.read_text_multi(_load("h020_before_faded_pink.png"), cfg.tesseract_path)
    after = ocr.read_text_multi(_load("h020_after_pink_bg.png"), cfg.tesseract_path)
    common = tuple(o["ore"] for o in game_data.LUCERNIA.common_ores)
    rares = tuple(r["ore"] for r in game_data.rare_ores("Lucernia").values())
    # 當時的行為（精確匹配、無 fuzzy）＝假陰性——鎖住這個事實，若未來 OCR 前處理
    # 進步到精確匹配就讀得到，這條會 fail 提醒我們 fuzzy 兜底可以簡化
    assert ocr.any_new_rare_found(before, after, common, KW) is False
    # fuzzy 兜底（rare_names 白名單詞彙表）必須確認採集成功
    assert ocr.any_new_rare_found(before, after, common, KW, rare_names=rares) is True
