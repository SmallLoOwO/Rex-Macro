"""層別深度表與 (世界, 深度) → 層別反推。

背景：遊戲畫面**不顯示「你在第幾層」**，唯一可機讀的位置訊號是頂部 Depth 數值。
回礦 ledger 原本只記使用者宣告的 `層 <名>` 字串（bot 從不驗證），2026-07-22 清點
20 筆實機點擊發現 5 筆標成 "Mantle Layer" 但落地畫面實為 Shamrock，標籤不可信。
本組測試鎖住反推邏輯與表本身的一致性。
"""
import pytest

from miningbot import game_data, ocr, reentry_remote


# ── layer_for_depth：正常命中與邊界 ───────────────────────────────────────
def test_lucernia_7100m_is_shamrock():
    """實機基準：14 張 landing 幀全部 Depth 7100m、層名 Shamrock（2026-07-22 清點）。"""
    assert game_data.layer_for_depth("Lucernia", 7100) == "Shamrock"


@pytest.mark.parametrize("depth,expect", [
    (6999, "Amourite"),      # 前一層的底
    (7000, "Shamrock"),      # 本層的頂（含）
    (7999, "Shamrock"),      # 本層的底（含）
    (8000, "Brittlestone"),  # 下一層的頂
])
def test_layer_boundaries_are_inclusive(depth, expect):
    assert game_data.layer_for_depth("Lucernia", depth) == expect


def test_same_depth_maps_to_different_layer_per_world():
    """跨世界深度完全重疊——0-999m 在七個世界是七個不同的層。

    這就是查表的鍵必須含世界的理由；只有深度定不出層。
    """
    got = {w: game_data.layer_for_depth(w, 500) for w in game_data.LAYER_DEPTHS}
    assert got == {
        "Aesteria": "Spookstone", "Lucernia": "Lucitreum", "World 0": "Statistone",
        "World 1": "Stone", "World 2": "Slate", "Subworld 1": "Moon Stone",
        "Subworld 2": "Space Rock",
    }
    assert len(set(got.values())) == len(got), "七個世界的同深度層名必須互異"


@pytest.mark.parametrize("depth,expect", [
    (7000, "Outer Core"), (7499, "Outer Core"),
    (7500, "Inner Core"), (7999, "Inner Core"),
])
def test_world1_core_splits_into_two_500m_layers(depth, expect):
    """World 1 的 Core 拆成 Outer/Inner 兩個 500m 層 → 不可用 depth//1000 查表。"""
    assert game_data.layer_for_depth("World 1", depth) == expect


@pytest.mark.parametrize("depth", [4000, 5000, 5999])
def test_subworld2_unknown_layer_spans_two_thousand_metres(depth):
    """Subworld 2 的 ??? 是 4000-5999 兩千米寬——另一個「非 1000m」反例。"""
    assert game_data.layer_for_depth("Subworld 2", depth) == "???"


# ── layer_for_depth：查不到一律 None，不夾值 ─────────────────────────────
def test_void_fall_depth_returns_none_not_nearest_layer():
    """H043 虛空墜落實測 25790m（fixtures/reentry/h046_depth_25790m.png）。

    遠超最深層底 9999m。必須回 None——夾到最近的層會把墜落誤記成正常落地。
    """
    assert game_data.layer_for_depth("Lucernia", 25790) is None


@pytest.mark.parametrize("world,depth", [
    (None, 7100),            # 世界尚未偵測到
    ("Lucernia", None),      # Depth OCR 讀不到 / 讀到 Surface
    (None, None),
    ("Nowhere", 7100),       # 新世界還沒同步進表
    ("Lucernia", -1),        # 負深度＝OCR 讀歪
    ("Lucernia", 10000),     # Lucernia 最深 9999
    ("World 2", 6000),       # World 2 只到 5999
])
def test_undeterminable_inputs_return_none(world, depth):
    assert game_data.layer_for_depth(world, depth) is None


# ── 表本身的一致性 ──────────────────────────────────────────────────────
def test_every_registered_world_has_layer_depths():
    assert set(game_data.LAYER_DEPTHS) == set(game_data.WORLDS)


def test_bands_within_a_world_are_ordered_and_non_overlapping():
    for world, bands in game_data.LAYER_DEPTHS.items():
        prev_hi = -1
        for name, lo, hi in bands:
            assert lo <= hi, f"{world}/{name} 區間反了"
            assert lo > prev_hi, f"{world}/{name} 與前一層重疊或未依深度排序"
            prev_hi = hi


def test_layer_names_unique_within_a_world():
    for world, bands in game_data.LAYER_DEPTHS.items():
        names = [n for n, _, _ in bands]
        assert len(names) == len(set(names)), f"{world} 有重複層名"


def test_variable_depth_layers_are_excluded_from_the_table():
    """Frost 每次礦場重置隨機取代一層、無固定區間 → 不可列入深度表。"""
    assert "Frost" in game_data.VARIABLE_DEPTH_LAYERS
    for world, bands in game_data.LAYER_DEPTHS.items():
        assert not (set(n for n, _, _ in bands) & game_data.VARIABLE_DEPTH_LAYERS)


# ── Depth 數值 OCR 解析 ─────────────────────────────────────────────────
@pytest.mark.parametrize("text,expect", [
    ("Depth: 7100m $108,587.35", 7100),   # 實機頂部列（尾端金額雜訊）
    ("Depth: 25790m_ $1\n", 25790),       # H043 墜落值照回，不在此處攔截
    ("Depth: 488m", 488),
    ("Depth: 7,100m", 7100),              # 千分位
    ("depth 0m", 0),
])
def test_parse_depth_meters_reads_value(text, expect):
    assert ocr.parse_depth_meters(text) == expect


@pytest.mark.parametrize("text", [
    "Depth: Surface $108,543.35",         # 地表沒有數值
    "", None,
    "Mine Capacity: 0%",                  # 沒有 depth 欄位
    "Depth: 9999999999m",                 # 超出 sanity 上限＝OCR 讀歪
])
def test_parse_depth_meters_returns_none(text):
    assert ocr.parse_depth_meters(text) is None


def test_parse_depth_meters_agrees_with_is_surface_on_the_same_text():
    """兩個解析器對同一行不得互相矛盾（地表↔有數值）。"""
    surface = "Depth: Surface $1"
    inside = "Depth: 7100m $1"
    assert ocr.parse_depth_surface(surface) is True
    assert ocr.parse_depth_meters(surface) is None
    assert ocr.parse_depth_surface(inside) is False
    assert ocr.parse_depth_meters(inside) == 7100


# ── record_landing ──────────────────────────────────────────────────────
def _ctx():
    return reentry_remote.RemoteReentryContext(
        episode_id=17, created_at=100.0, sticky_layer="Mantle Layer")


def test_record_landing_annotates_last_click():
    """實測值與宣告值並存——兩者都在才看得出標籤與畫面不符（5/20 筆的情形）。"""
    ctx = _ctx()
    reentry_remote.record_click(ctx, (10, 20), "Mantle Layer", (0, 0, 1, 1), 123.0)
    assert reentry_remote.record_landing(ctx, 7100, "Shamrock") is True
    assert ctx.clicks[-1]["depth_m"] == 7100
    assert ctx.clicks[-1]["layer_seen"] == "Shamrock"
    assert ctx.clicks[-1]["layer"] == "Mantle Layer"


def test_record_landing_annotates_only_the_latest_click():
    ctx = _ctx()
    reentry_remote.record_click(ctx, (1, 2), "Shamrock", (0, 0, 1, 1), 1.0)
    reentry_remote.record_click(ctx, (3, 4), "Shamrock", (0, 0, 1, 1), 2.0)
    reentry_remote.record_landing(ctx, 7100, "Shamrock")
    assert "depth_m" not in ctx.clicks[0]
    assert ctx.clicks[1]["depth_m"] == 7100


def test_record_landing_writes_none_rather_than_skipping():
    """量不到就寫 None：事後分析才分得出「沒量到」與「量到某層」。"""
    ctx = _ctx()
    reentry_remote.record_click(ctx, (1, 2), "Shamrock", (0, 0, 1, 1), 1.0)
    assert reentry_remote.record_landing(ctx, None, None) is True
    assert ctx.clicks[-1]["depth_m"] is None
    assert ctx.clicks[-1]["layer_seen"] is None


def test_record_landing_without_clicks_reports_false():
    assert reentry_remote.record_landing(_ctx(), 7100, "Shamrock") is False


def test_landing_fields_reach_the_ledger_entry():
    """ledger_entry 帶出 clicks → 新欄位自動進 ledger，無需另改序列化。"""
    ctx = _ctx()
    reentry_remote.record_click(ctx, (1, 2), "Mantle Layer", (0, 0, 1, 1), 1.0)
    reentry_remote.record_landing(ctx, 7100, "Shamrock")
    entry = reentry_remote.ledger_entry(ctx, "success", world="Lucernia",
                                        duration_s=1.0)
    assert entry["clicks"][0]["layer_seen"] == "Shamrock"
    assert entry["clicks"][0]["depth_m"] == 7100
