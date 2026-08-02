"""量 NORMAL 面板列底色的階級色相——`TIER_HUES` 的校準工具（D13，2026-08-02）。

使用者持續分批提供「背包裡剛好有某幾階」的畫面，每批都用**同一套協議**量，
讀數才能跨批互比。

用法（Roblox 全螢幕、面板可見）：
    uv run python -m miningbot.measure_tier_hues                  # 直接抓當下畫面
    uv run python -m miningbot.measure_tier_hues <png>            # 量既有檔（全幀或已裁的面板）
    uv run python -m miningbot.measure_tier_hues <png> --bands 75-110 111-146
    uv run python -m miningbot.measure_tier_hues --save out.png   # 抓圖並存檔（要收進 fixture 時）

素材與 ground truth 在 `tests/fixtures/panel_tiers/`，迴歸 `tests/test_panel_tier_hues.py`，
量測敘事在 `docs/open-detection-issues.md` D13。

## 為什麼協議要固定（使用者 2026-08-02 指出「背包內的顏色是帶有漸層的」）

面板每列**有水平漸層（左亮右暗）**，但漸層只在 V 上——Transcendent 帶從 x=20 的
V=252 掉到 x=212 的 V=68，而 H 沿整條列恆定 210.0°（幅度 0.0°），垂直方向同樣恆定。
→ 取樣位置改變 V、**不改變 H**。色相閘只用 H，故階級判定不受取樣位置影響；
**但要加 S/V 判據時，必須連取樣窗一起指定**，否則數字沒有跨階級可比性。

`SAMPLE_X` 用 `cfg.panel_hue_sample_x`（120-165）＝ production 實際會看的那塊像素。
要量未衰減的原色請改用 `BAND_ORIGIN_X`（18）——實測那裡就是 wiki 官方色（ΔBGR ≤2）。

## 三條規則（缺一就量錯）

1. 固定窗，與 production 同一處。
2. **逐列中位 → 跨列中位，不用平均**。礦名文字是少數像素，中位吃不掉；環形平均
   會被抗鋸齒污染——首次量 Unfathomable 得 227.4°（差 8.4°、看起來像表值錯了），
   改逐列中位後是 220.0°。**那次差點寫出一個假修復。**
3. `S > SAT_MIN` 濾文字邊緣，但**灰階列（Common／Layer，S=0）不能因此被跳過**——
   那會讓整條帶從結果裡消失（盲區）。整條帶無飽和像素時確認確實是灰再回 H=0。
"""
import argparse
import os

import cv2
import numpy as np

from .config import DEFAULT as cfg
from .game_data import TIER_HUES

SAT_MIN = 60          # 低於此視為灰階／文字邊緣
MIN_PIXELS = 20       # 一列至少要這麼多飽和像素才採計
MIN_BAND_PX = 6       # 連續這麼多列同色才算一條帶
GREY_SAT_MAX = 30     # 整條帶的 S 低於此＝真的是灰階列，不是裁錯位置
BAND_ORIGIN_X = 18    # 色帶起點＝wiki 原色（漸層由此往右衰減）

# 低階不在 TIER_HUES（在的話零點閘會把它們當高階），但量測時要認得出來——否則
# 每次都報「不符任何已知階級」，真正的新階級會淹沒在雜訊裡。
# 值＝wiki 官方色碼換算，2026-08-02 實機逐一驗過。
LOW_TIER_HUES = {"Rare": 30.0, "Master": 280.0, "Surreal": 166.0, "Mythic": 304.0,
                 "Uncommon": 0.0}
# 灰階列的兩階只差亮度（x=18 未衰減處量）。空白區／面板外框也是灰但更暗，
# 用 GREY_TIER_TOL 夾住才不會把它們報成 Common／Layer。
GREY_TIER_VALUES = {"Common": 192, "Layer": 132}
GREY_TIER_TOL = 12


def _load(path=None):
    """讀檔或抓當下畫面；全幀自動裁 `ore_panel_region`。"""
    if path is None:
        from .capture import grab
        img = grab()
    else:
        img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise SystemExit(f"讀不到 {path}")
    if img.shape[:2] == (1080, 1920):
        r = cfg.ore_panel_region
        img = img[r.y:r.y + r.h, r.x:r.x + r.w]
    return img


def row_hue(hsv, y, x0, x1):
    """單列的底色 (H, S, V)；飽和像素不足回 None（灰階列會落在這裡）。"""
    strip = hsv[y, x0:x1]
    m = strip[:, 1] > SAT_MIN
    if m.sum() < MIN_PIXELS:
        return None
    return (float(np.median(strip[m, 0])) * 2,
            float(np.median(strip[m, 1])),
            float(np.median(strip[m, 2])))


def band_hue(hsv, y0, y1, x0, x1):
    """一條帶的 (H, S, V, 採計列數)：逐列中位後再跨列中位（抗文字污染）。

    整條帶都沒有飽和像素 → 灰階列（Common／Layer）：確認確實是灰再回 H=0，
    與 production 的 `vision.panel_row_hues` 同語意。回 None＝取樣位置有問題。
    """
    rows = [row_hue(hsv, y, x0, x1) for y in range(y0, y1 + 1)]
    rows = [r for r in rows if r]
    if rows:
        return (float(np.median([r[0] for r in rows])),
                float(np.median([r[1] for r in rows])),
                float(np.median([r[2] for r in rows])),
                len(rows))
    sat = float(np.median(hsv[y0:y1 + 1, x0:x1, 1]))
    if sat > GREY_SAT_MAX:
        return None
    val = float(np.median(hsv[y0:y1 + 1, x0:x1, 2]))
    return (0.0, sat, val, y1 - y0 + 1)


def detect_bands(hsv, x0, x1, img=None):
    """自動切色帶：逐列取一個 key，連續同 key >= MIN_BAND_PX 的算一條。

    彩色列的 key 是取整的 H。灰階列（S=0）沒有 H，若一律給同一個 key，
    Common／Layer／面板空白區會被併成一大條（實測 y291-688 三者混在一起）。
    故灰階列改用**亮度分桶**當 key——那正是區分兩種灰的唯一軸。
    """
    keys = []
    for y in range(hsv.shape[0]):
        r = row_hue(hsv, y, x0, x1)
        if r is not None:
            keys.append(("h", round(r[0])))
            continue
        sat = float(np.median(hsv[y, x0:x1, 1]))
        val = float(np.median(hsv[y, x0:x1, 2]))
        keys.append(("grey", round(val / 12)) if sat <= GREY_SAT_MAX else None)
    bands, cur, start = [], "init", None
    for i, k in enumerate(keys):
        if k != cur:
            if start is not None and i - start >= MIN_BAND_PX:
                bands.append((start, i - 1))
            cur, start = k, i
    if start is not None and len(keys) - start >= MIN_BAND_PX:
        bands.append((start, len(keys) - 1))
    return bands


def nearest_tier(h):
    """最接近的已知階級。回 (名稱, 角差, 是否低階)。"""
    best, bd, low = None, 999.0, False
    for table, is_low in ((TIER_HUES, False), (LOW_TIER_HUES, True)):
        for t, th in table.items():
            d = min(abs(h - th), 360 - abs(h - th))
            if d < bd:
                best, bd, low = t, d, is_low
    return best, bd, low


def origin_bgr(img, y0, y1):
    """色帶起點 x=18 的 BGR＝wiki 原色（未被漸層衰減）。"""
    pad = min(4, max(0, (y1 - y0) // 4))
    seg = img[y0 + pad:y1 - pad + 1, BAND_ORIGIN_X:BAND_ORIGIN_X + 2]
    return np.median(seg.reshape(-1, 3), axis=0).astype(int)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="?", help="PNG 路徑；省略＝抓當下畫面")
    ap.add_argument("--bands", nargs="*", default=None,
                    help="手動指定 y 範圍（如 75-110），省略＝自動偵測")
    ap.add_argument("--save", help="把抓到的畫面存到這個路徑（收 fixture 用）")
    args = ap.parse_args()

    img = _load(args.image)
    if args.save:
        full = args.save
        cv2.imencode(".png", img)[1].tofile(full)
        print(f"已存 {full}（{os.path.getsize(full)} bytes）")
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    x0, x1 = cfg.panel_hue_sample_x

    bands = ([tuple(int(v) for v in b.split("-")) for b in args.bands]
             if args.bands else detect_bands(hsv, x0, x1))
    # 第一列之前是標頭與篩選框（同 cfg.panel_row_min_y 的理由），不是礦列
    bands = [(a, b) for a, b in bands if b >= cfg.panel_row_min_y]

    src = args.image or "（當下畫面）"
    print(f"{src}  crop={img.shape}  取樣窗 x={x0}-{x1}（固定，同 production）")
    print(f"協議：逐列中位→跨列中位，S>{SAT_MIN}，每列至少 {MIN_PIXELS} 像素")
    print()
    print(f"{'y 範圍':>14}{'H':>8}{'S':>6}{'V':>6}{'列數':>6}"
          f"   {'最接近階級':<14}{'Δ':>6}   x=18 原色")
    unknown = []
    for y0, y1 in bands:
        r = band_hue(hsv, y0, y1, x0, x1)
        if r is None:
            continue
        h, s, v, n = r
        tier, d, is_low = nearest_tier(h)
        bgr = origin_bgr(img, y0, y1)
        if s <= GREY_SAT_MAX:
            # 灰階：H 無意義，只能用 x=18 的未衰減亮度分辨 Common / Layer
            grey = [t for t, gv in GREY_TIER_VALUES.items()
                    if abs(int(bgr[0]) - gv) <= GREY_TIER_TOL]
            if grey:
                tier, d = f"{grey[0]}(灰)", 0.0
                note = f"  灰階 V={bgr[0]}，H 無意義"
            else:
                tier, d = "-", 0.0
                note = f"  灰階 V={bgr[0]}：非礦列（面板外框／空白區）"
        elif d <= 1.5:
            note = "  (低階，不在 TIER_HUES 是對的)" if is_low else ""
        else:
            note = "   <== 未知色相！新階級？"
            unknown.append((y0, y1, h, bgr))
        print(f"{y0:>6}-{y1:<7}{h:>8.1f}{s:>6.0f}{v:>6.0f}{n:>6}"
              f"   {tier:<14}{d:>5.1f}°   {str(bgr):<18}{note}")

    if unknown:
        print()
        print("[!] 未知色相——先查該列礦名的 tier（game_data.rare_ores）再決定要不要進 TIER_HUES：")
        for y0, y1, h, bgr in unknown:
            print(f"    y{y0}-{y1}  H={h:.1f}°  x=18 原色 BGR={bgr}")
        print("  Imaginary 是雙色漸層 42°+201°，固定窗可能只讀到其一或混色。")


if __name__ == "__main__":
    main()
