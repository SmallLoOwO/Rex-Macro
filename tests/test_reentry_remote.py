import numpy as np
from miningbot.reentry_remote import (RemoteReply, parse_reply, coarse_cell_region,
                                      fine_cell_to_screen, render_zoom, draw_click_marker)


class TestParseReply:
    def test_coarse(self):
        # 訊息面 1-8（2026-07-18 使用者要求 1 起算）→ 內部 0-based
        r = parse_reply("3 C2")
        assert (r.kind, r.dir_idx, r.cell) == ("coarse", 2, "C2")
        assert parse_reply("1 A1").dir_idx == 0
        assert parse_reply("8 C2").dir_idx == 7

    def test_coarse_invalid(self):
        assert parse_reply("0 C2") is None       # 方位 1-8，0 不合法
        assert parse_reply("9 C2") is None
        assert parse_reply("3 G2") is None       # 欄超界
        assert parse_reply("3 C5") is None       # 粗網格列只有 1-4

    def test_fine_bare_and_layer_override(self):
        r = parse_reply("B3")
        assert (r.kind, r.cell, r.layer) == ("fine", "B3", "")
        r = parse_reply("b5 Core Layer")          # 細網格列到 6；層名可含空白
        assert (r.kind, r.cell, r.layer) == ("fine", "B5", "Core Layer")

    def test_fine_invalid(self):
        assert parse_reply("B7") is None          # 細網格列只有 1-6
        assert parse_reply("G3") is None

    def test_walk_retired(self):
        # `走` 走位指令 2026-07-18 退役（遠端本就人工，不需要走近）
        assert parse_reply("走 C2") is None
        assert parse_reply("walk d4") is None

    def test_magnify(self):
        # `放大 <細格>`（2026-07-18）：等細格時再裁一層
        r = parse_reply("放大 B3")
        assert (r.kind, r.cell) == ("magnify", "B3")
        assert parse_reply("magnify f6").cell == "F6"
        assert parse_reply("放大") is None        # 缺細格
        assert parse_reply("放大 G3") is None     # 細格超界
        assert parse_reply("放大 B7") is None

    def test_keywords(self):
        assert parse_reply("掃").kind == "sweep"
        assert parse_reply("SWEEP").kind == "sweep"
        assert parse_reply("重骰").kind == "reroll"
        assert parse_reply("跳過").kind == "skip"
        assert parse_reply("好").kind == "confirm"
        assert parse_reply("OK").kind == "confirm"
        assert parse_reply("作廢").kind == "void"

    def test_layer_command(self):
        r = parse_reply("層 Mantle Layer")
        assert (r.kind, r.layer) == ("layer", "Mantle Layer")
        assert parse_reply("layer Core Layer").layer == "Core Layer"
        assert parse_reply("層") is None          # 空層名不合法

    def test_noise_and_fullwidth(self):
        assert parse_reply("　3　C2　").kind == "coarse"   # 全形空白
        assert parse_reply("哈哈這是聊天") is None
        assert parse_reply("") is None
        assert parse_reply("3") is None           # 單數字（無 aim 候選語意）


class TestGeometry:
    def test_coarse_cell_region_c3(self):
        # 6×4、1920×1080：格 320×270。C=idx2、3=idx2 → (640, 540, 320, 270)
        assert coarse_cell_region("C3") == (640, 540, 320, 270)

    def test_coarse_cell_region_invalid(self):
        assert coarse_cell_region("C5") is None
        assert coarse_cell_region("G1") is None

    def test_fine_cell_to_screen_center_of_subcell(self):
        region = (640, 540, 320, 270)             # 粗格 C3
        # 細 6×6：子格 53×45（floor）。A1＝region 左上子格中心
        x, y = fine_cell_to_screen(region, "A1")
        assert (x, y) == (640 + 53 // 2 + 0, 540 + 45 // 2 + 0)
        x, y = fine_cell_to_screen(region, "F6")
        assert x == 640 + 5 * (320 // 6) + (320 // 6) // 2
        assert y == 540 + 5 * (270 // 6) + (270 // 6) // 2

    def test_fine_cell_invalid(self):
        assert fine_cell_to_screen((0, 0, 320, 270), "B7") is None

    def test_fine_cell_subregion(self):
        from miningbot.reentry_remote import fine_cell_subregion
        region = (640, 540, 320, 270)             # 粗格 C3；細 6×6 子格 53×45
        assert fine_cell_subregion(region, "A1") == (640, 540, 53, 45)
        assert fine_cell_subregion(region, "F6") == (640 + 5 * 53, 540 + 5 * 45, 53, 45)
        # 連鎖：子區域再裁一層
        sub = fine_cell_subregion(region, "A1")
        assert fine_cell_subregion(sub, "B2") == (640 + 8, 540 + 7, 8, 7)

    def test_fine_cell_subregion_invalid(self):
        from miningbot.reentry_remote import fine_cell_subregion
        assert fine_cell_subregion((0, 0, 320, 270), "G1") is None
        assert fine_cell_subregion((0, 0, 320, 270), "B7") is None
        assert fine_cell_subregion((), "B3") is None      # 尚未放大（無 zoom_region）

    def test_magnify_scale(self):
        from miningbot.reentry_remote import magnify_scale
        # 首層放大輸出 320*3=960 寬；53px 子區域 → round(960/53)=18
        assert magnify_scale(53, 960, 3) == 18
        assert magnify_scale(8, 960, 3) == 24             # cap 防爆圖
        assert magnify_scale(500, 960, 3) == 3            # 不小於 base_scale
        assert magnify_scale(0, 960, 3) == 3              # 異常回 base


class TestRender:
    def test_render_zoom_shape_and_input_intact(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        out = render_zoom(frame, (640, 540, 320, 270), scale=3)
        assert out.shape == (810, 960, 3)
        assert frame.sum() == 0                   # 輸入不被改
        assert out.sum() > 0                      # 有畫網格

    def test_draw_click_marker(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        out = draw_click_marker(frame, (700, 600))
        assert frame.sum() == 0
        assert out[600, 700 - 30:700 + 30].sum() > 0


def test_remote_aim_grid_rows_backward_compat():
    """GRID_ROWS 擴到 6 列後，remote_aim 預設 rows=4 行為不變。"""
    from miningbot.remote_aim import grid_cell_center
    assert grid_cell_center("A5") is None                 # 預設 rows=4 仍拒
    assert grid_cell_center("A5", rows=6) is not None     # 顯式 rows=6 才收


import json
from miningbot.reentry_remote import (RemoteReentryContext, next_episode_id,
                                      log_command, record_click, ledger_entry, void_entry)


class TestContextLedger:
    def _ctx(self):
        return RemoteReentryContext(episode_id=17, created_at=100.0,
                                    sticky_layer="Mantle Layer")

    def test_next_episode_id(self):
        assert next_episode_id(None) == 1
        assert next_episode_id('{"episode": 16, "outcome": "success"}') == 17
        assert next_episode_id('{"type": "void", "episode": 16}') == 17
        assert next_episode_id("not json") == 1

    def test_log_and_click_accumulate(self):
        ctx = self._ctx()
        ctx.cur_dir = 3
        log_command(ctx, "3 C2", parse_reply("3 C2"), now=101.0)
        record_click(ctx, (700, 600), "Mantle Layer", (640, 540, 320, 270), now=102.0)
        assert ctx.log[0]["kind"] == "coarse" and ctx.log[0]["pose_dir"] == 3
        assert ctx.clicks[0]["pos"] == (700, 600) and ctx.clicks[0]["invalid"] is False

    def test_ledger_entry_fields(self):
        ctx = self._ctx()
        record_click(ctx, (700, 600), "Core Layer", (640, 540, 320, 270), now=102.0)
        e = ledger_entry(ctx, "success", world="Aesteria", duration_s=88.5)
        assert e["episode"] == 17 and e["outcome"] == "success"
        assert e["world"] == "Aesteria" and e["sticky_layer"] == "Mantle Layer"
        assert e["clicks"][0]["layer"] == "Core Layer"
        json.dumps(e, ensure_ascii=False)         # 必須可序列化

    def test_void_entry(self):
        v = void_entry(17, click_index=0, now=200.0)
        assert v["type"] == "void" and v["episode"] == 17 and v["click_index"] == 0


from miningbot.reentry_remote import effective_zoom_steps


class TestZoomParse:
    def test_zoom_bare_and_steps(self):
        r = parse_reply("遠")
        assert (r.kind, r.steps) == ("zoom_out", 0)      # 0＝未指定，用 config 預設
        r = parse_reply("far 3")
        assert (r.kind, r.steps) == ("zoom_out", 3)
        r = parse_reply("近 2")
        assert (r.kind, r.steps) == ("zoom_in", 2)
        assert parse_reply("NEAR").kind == "zoom_in"

    def test_zoom_invalid(self):
        assert parse_reply("遠 abc") is None
        assert parse_reply("遠 0") is None
        assert parse_reply("遠 -3") is None               # 負數（isdigit False）
        assert parse_reply("遠 3 5") is None              # 多餘參數

    def test_effective_zoom_steps(self):
        assert effective_zoom_steps(0, 4, 12) == 4        # 未指定 → default
        assert effective_zoom_steps(3, 4, 12) == 3
        assert effective_zoom_steps(99, 4, 12) == 12      # 超上限 clamp、不拒收


from miningbot.reentry_remote import plan_zoom_restore


class TestZoomRestore:
    def test_plan_zoom_restore(self):
        assert plan_zoom_restore(0, 30, 7) == []                       # 沒碰過不歸位
        assert plan_zoom_restore(5, 30, 7) == [("i", 30), ("o", 7)]
        assert plan_zoom_restore(-2, 30, 7) == [("i", 30), ("o", 7)]   # 拉近過也歸位
        assert plan_zoom_restore(5, 30, 0) == []                       # 未校準防禦（上游已擋）

    def test_zoom_recorded_in_log_and_click(self):
        ctx = RemoteReentryContext(episode_id=1, created_at=0.0, sticky_layer="L")
        ctx.net_zoom = 3
        log_command(ctx, "遠 3", parse_reply("遠 3"), now=1.0)
        record_click(ctx, (1, 2), "L", (0, 0, 320, 270), now=2.0)
        assert ctx.log[0]["zoom"] == 3
        assert ctx.clicks[0]["zoom"] == 3


# ===== Task 4：REENTRY 互動 embed 純函式（2026-07-13 spec）=====
from miningbot.reentry_remote import (build_reentry_embed, reaction_to_reentry_reply,
                                      REENTRY_REACTIONS)


class TestReentryEmbed:
    def _ctx(self, phase="awaiting_cmd"):
        ctx = RemoteReentryContext(episode_id=42, created_at=100.0, sticky_layer="Mantle Layer")
        ctx.attempt = 3
        ctx.phase = phase
        return ctx

    def test_title_and_episode_id(self):
        e = build_reentry_embed(self._ctx(), "Mantle Layer", now=160.0, evac_done=False)
        assert e["title"] == "⛏ 回礦 #42"

    def test_sticky_layer_in_description(self):
        e = build_reentry_embed(self._ctx(), "Core Layer", now=160.0, evac_done=False)
        assert "Core Layer" in e["description"]

    def test_attempt_in_description(self):
        e = build_reentry_embed(self._ctx(), "L", now=160.0, evac_done=False)
        assert "attempt**：3" in e["description"]

    def test_minutes_elapsed(self):
        ctx = self._ctx()
        e = build_reentry_embed(ctx, "L", now=160.0, evac_done=False)   # (160-100)//60=1
        assert "1 分鐘" in e["description"]
        e2 = build_reentry_embed(ctx, "L", now=100.0, evac_done=False)  # 0 分
        assert "0 分鐘" in e2["description"]

    def test_phase_colors(self):
        assert build_reentry_embed(self._ctx("awaiting_cmd"), "L", 100.0, False)["color"] == 0x5865F2
        assert build_reentry_embed(self._ctx("awaiting_fine"), "L", 100.0, False)["color"] == 0xFEE75C
        assert build_reentry_embed(self._ctx("awaiting_confirm"), "L", 100.0, False)["color"] == 0x57F287

    def test_phase_labels_in_description(self):
        for phase, label in [("awaiting_cmd", "等指令"), ("awaiting_fine", "等細格"),
                             ("awaiting_confirm", "等確認")]:
            e = build_reentry_embed(self._ctx(phase), "L", 100.0, False)
            assert label in e["description"]

    def test_evac_done_annotation(self):
        e = build_reentry_embed(self._ctx(), "L", 100.0, evac_done=True)
        assert "已撤離" in e["description"]
        e2 = build_reentry_embed(self._ctx(), "L", 100.0, evac_done=False)
        assert "已撤離" not in e2["description"]

    def test_footer_mentions_photos_and_updates(self):
        e = build_reentry_embed(self._ctx(), "L", 100.0, False)
        assert "照片訊息在上方" in e["footer"]["text"]
        assert "原地更新" in e["footer"]["text"]

    def test_pitch_offset_line(self):
        # 2026-07-18 使用者要求：目前角度顯示在回礦卡；07-19 提示改裸 `上|下 [px]`
        # （使用者照舊提示打了帶前綴以外的簡寫沒反應——現在裸寫即可用）
        e = build_reentry_embed(self._ctx(), "L", 100.0, False, pitch_offset_px=400)
        assert "夾限上 400px" in e["description"]
        assert "上|下" in e["description"]
        e2 = build_reentry_embed(self._ctx(), "L", 100.0, False)   # 未傳＝不顯示該行
        assert "夾限上" not in e2["description"]


class TestReactionToReply:
    def test_known_emojis(self):
        assert reaction_to_reentry_reply("🎲").kind == "reroll"
        assert reaction_to_reentry_reply("⏭️").kind == "skip"
        assert reaction_to_reentry_reply("📷").kind == "sweep"

    def test_unknown_emoji_returns_none(self):
        assert reaction_to_reentry_reply("👍") is None
        assert reaction_to_reentry_reply("") is None

    def test_reactions_constant(self):
        assert REENTRY_REACTIONS == ("🎲", "⏭️", "📷")


# ===== H044：開場探測節奏＋手動觸發記帳 =====
from miningbot.reentry_remote import plan_open_retry


def test_plan_open_retry_probe_when_interval_elapsed():
    assert plan_open_retry(0.0, 25.0, 20.0, 300.0, 0.0) == "probe"


def test_plan_open_retry_wait_before_interval():
    assert plan_open_retry(0.0, 10.0, 20.0, 300.0, 0.0) == "wait"


def test_plan_open_retry_give_up_at_budget():
    assert plan_open_retry(0.0, 300.0, 20.0, 300.0, 250.0) == "give_up"


def test_plan_open_retry_budget_wins_over_interval():
    # 預算已盡且間隔也到：give_up 優先（不再多點一擊）
    assert plan_open_retry(0.0, 400.0, 20.0, 300.0, 0.0) == "give_up"


def test_ctx_trigger_default_reset_and_ledger_records_it():
    ctx = RemoteReentryContext(episode_id=9, created_at=0.0,
                               sticky_layer="Mantle Layer")
    assert ctx.trigger == "reset"
    entry = ledger_entry(ctx, "success", "Aesteria", 12.3)
    assert entry["trigger"] == "reset"


def test_embed_footer_marks_manual_trigger():
    ctx = RemoteReentryContext(episode_id=9, created_at=0.0,
                               sticky_layer="Mantle Layer",
                               trigger="manual")
    embed = build_reentry_embed(ctx, "Mantle Layer", 60.0, False)
    assert embed["footer"]["text"].startswith("手動觸發｜")
    ctx.trigger = "reset"
    embed = build_reentry_embed(ctx, "Mantle Layer", 60.0, False)
    assert "手動觸發" not in embed["footer"]["text"]


# ===== 重骰保留 session 仰角（2026-07-19 使用者反映：重骰後被拉回 config 標準角）=====
from miningbot.reentry_remote import effective_pitch_back


def test_effective_pitch_back_none_session_uses_config_default():
    # episode 內沒調過（session=None）→ config 標準角
    assert effective_pitch_back(None, 400, 1500) == 400


def test_effective_pitch_back_keeps_user_adjustment():
    # `上|下 [px]` 調過 → 重骰/重探開場沿用使用者記帳值
    assert effective_pitch_back(260, 400, 1500) == 260


def test_effective_pitch_back_negative_saturates_at_clamp():
    # 記帳被 `下` 調到負值＝實際已在夾限 → 回拉 0（不可回退 config 洗掉使用者意圖）
    assert effective_pitch_back(-100, 400, 1500) == 0


def test_effective_pitch_back_caps_at_clamp_px():
    # 記帳超過飽和拖曳量 → cap 在 clamp（拉滿即止，不放大成脫韁值）
    assert effective_pitch_back(5000, 400, 1500) == 1500


# ===== 仰角指令（2026-07-17：R 取樣視窗退役，俯仰控制移進 Discord 回礦流程）=====
def test_parse_pitch_reset():
    assert parse_reply("仰角 歸位").kind == "pitch_reset"
    assert parse_reply("pitch reset").kind == "pitch_reset"


def test_parse_pitch_nudge_direction_and_px():
    r = parse_reply("仰角 上")
    assert (r.kind, r.cell, r.steps) == ("pitch", "up", 0)    # steps=0＝用預設步長
    r = parse_reply("仰角 下 120")
    assert (r.kind, r.cell, r.steps) == ("pitch", "down", 120)
    r = parse_reply("pitch up 40")
    assert (r.kind, r.cell, r.steps) == ("pitch", "up", 40)


def test_parse_pitch_rejects_garbage():
    assert parse_reply("仰角") is None            # 缺方向
    assert parse_reply("仰角 斜") is None
    assert parse_reply("仰角 上 -5") is None      # 像素只收正整數（方向由 上/下 表達）
    assert parse_reply("仰角 上 0") is None


def test_parse_bare_up_down_aliases_pitch():
    # 2026-07-19 使用者反映：卡上寫 `上|下 [px]` 但裸打不帶「仰角」前綴沒反應
    r = parse_reply("上 20")
    assert (r.kind, r.cell, r.steps) == ("pitch", "up", 20)
    r = parse_reply("下")
    assert (r.kind, r.cell, r.steps) == ("pitch", "down", 0)
    r = parse_reply("up 40")
    assert (r.kind, r.cell, r.steps) == ("pitch", "up", 40)
    assert parse_reply("歸位").kind == "pitch_reset"


def test_parse_bare_up_down_rejects_garbage():
    assert parse_reply("上 -5") is None
    assert parse_reply("上 0") is None
    assert parse_reply("上 abc") is None
    assert parse_reply("上次那個先跳過") is None   # 一般聊天不誤觸


# ===== H045/H046：開場雙閘（凍結探針＋容量歸零）＝傳送驗證過後、拍照前的最後守門 =====
from miningbot.reentry_remote import plan_opening_gate, probe_frozen

# 凍結探針門檻（config 預設；兩側夾見 probe_frozen docstring）
_FROZEN_MEAN_MAX = 0.02
_FROZEN_FRAC_MAX = 0.0002


def test_probe_frozen_on_bitwise_identical_frames():
    # 凍結＝逐位元相同（H044 量測＋2026-07-17 17:23:01 ep1 實錄）
    assert probe_frozen(0.0, 0.0, _FROZEN_MEAN_MAX, _FROZEN_FRAC_MAX) is True


def test_probe_frozen_rejects_alive_static_scene():
    # 活著但靜止（H044 07-12 夜間地表無輸入量測）：mean 0.09/frac 0.0004
    assert probe_frozen(0.09, 0.0004, _FROZEN_MEAN_MAX, _FROZEN_FRAC_MAX) is False


def test_probe_frozen_rejects_dark_surface_drag():
    # H046 根因幀：夜間地表拖曳後 mean 0.93~5.13 被 pitch_eaten 門檻（8.0）誤鎖
    # 300s——凍結探針必須放行（2026-07-17 17:27:47 最小值 0.9267/0.0185）
    assert probe_frozen(0.9266653645833334, 0.0184921875,
                        _FROZEN_MEAN_MAX, _FROZEN_FRAC_MAX) is False
    assert probe_frozen(1.63851953125, 0.0273984375,
                        _FROZEN_MEAN_MAX, _FROZEN_FRAC_MAX) is False


def test_opening_gate_frozen_defers():
    # 凍結中不拍照不發圖，回 H044 探測迴圈（H045 實錄 2026-07-14 18:26:40）
    assert plan_opening_gate(True, True, "reset", 0.0, 0.0) == "frozen"


def test_opening_gate_defers_when_not_on_surface():
    # H046(b)：狀態錨——Depth 讀到 NNNm＝礦內/虛空墜落中，繼續探測點擊
    assert plan_opening_gate(False, False, "reset", 0.0, 0.0) == "not_surface"
    assert plan_opening_gate(False, None, "reset", 0.0, 0.0) == "depth_unread"


def test_opening_gate_defers_on_stale_capacity():
    # 凍結舊幀 Capacity 78%（2026-07-14 18:26:41 reentry_ep3_dir0 實機幀）
    assert plan_opening_gate(False, True, "reset", 78.0, 0.0) == "capacity"


def test_opening_gate_defers_when_capacity_unreadable():
    # OCR 讀不到＝資訊不足，保守等下一探（H044 預算 300s 收口，有界）
    assert plan_opening_gate(False, True, "reset", None, 0.0) == "capacity_unread"


def test_opening_gate_proceeds_on_surface_zero_capacity():
    # H046(b) 修正核心：人在地表＋容量 0＝開場成立，「點擊有沒有造成幀差」不再是條件
    # （2026-07-17 17:24:55 實機幀：Depth: Surface / Capacity: 0%）
    assert plan_opening_gate(False, True, "reset", 0.0, 0.0) == "proceed"


def test_opening_gate_frozen_wins_over_everything():
    # 凍結時其他讀值全來自凍結舊幀，本就不可信
    assert plan_opening_gate(True, False, "reset", 78.0, 0.0) == "frozen"


def test_opening_gate_manual_trigger_skips_capacity():
    # 手動回礦（挖礦中觸發）容量本來就非 0：容量閘不適用；地表錨仍要過
    assert plan_opening_gate(False, True, "manual", 78.0, 0.0) == "proceed"
    assert plan_opening_gate(False, True, "manual", None, 0.0) == "proceed"
    assert plan_opening_gate(False, False, "manual", None, 0.0) == "not_surface"
    assert plan_opening_gate(True, True, "manual", None, 0.0) == "frozen"


# ===== H046 depth 錨解析（實機拖尾雜訊全來自裁圖右緣的金額 "$..."）=====
from miningbot.ocr import parse_depth_surface


def test_parse_depth_surface_true_on_surface():
    assert parse_depth_surface("Depth: Surface $i1C\n") is True     # 2026-07-17 實機讀值
    assert parse_depth_surface("depth surface") is True


def test_parse_depth_surface_false_in_mine():
    assert parse_depth_surface("Depth: 488m = $10\n") is False      # 2026-07-14 實機讀值
    assert parse_depth_surface("Depth: 25790m_ $1\n") is False
    assert parse_depth_surface("Depth: 33,290,005m") is False       # H043 虛空墜落深度


def test_parse_depth_surface_none_without_depth():
    assert parse_depth_surface("") is None
    assert parse_depth_surface("Capacity: 78%") is None
    assert parse_depth_surface("$108,770.35") is None


# ===== H046(c) 預防性修正：下礦點擊驗證改狀態錨（Depth Surface→NNNm）=====
# 開場閘已改狀態制（plan_opening_gate），但 _rr_click 的成功驗證仍是轉移式幀差
# ——同一型結構缺陷（重複點已成功的傳送板畫面可能毫無變化）。兩側夾證據沿用
# h046_depth_* fixtures（真實引擎 Surface/488m/25790m 3/3，tests/test_depth_fixtures.py）。
from miningbot.reentry_remote import plan_click_verdict


def test_click_verdict_depth_flip_is_success():
    # Depth 翻成 NNNm＝真下礦；幀差有沒有動、窗到沒到期都不是條件
    assert plan_click_verdict(False, False, False) == "descended"
    assert plan_click_verdict(False, True, False) == "descended"
    assert plan_click_verdict(False, False, True) == "descended"


def test_click_verdict_waits_within_window():
    # 窗內 Surface（傳送尚未發生）或讀不到（載入中）都繼續輪詢
    assert plan_click_verdict(True, False, False) == "wait"
    assert plan_click_verdict(None, False, False) == "wait"
    assert plan_click_verdict(None, True, False) == "wait"


def test_click_verdict_still_surface_after_timeout():
    # H046(b) 同構：畫面大動（地表→地表換重生點 diff ≥26.8）但 Depth 仍 Surface
    # ＝沒下礦——舊轉移式驗證在這裡假成功，狀態錨必須判失敗
    assert plan_click_verdict(True, True, True) == "still_surface"
    assert plan_click_verdict(True, False, True) == "still_surface"


def test_click_verdict_depth_unread_falls_back_to_frame_diff():
    # 降級路徑（CLAUDE.md fail-safe 邊界）：Depth OCR 讀不到時退回舊幀差訊號
    # ——有動＝交人工確認（寧問勿假成功）、沒動＝點擊無效留 awaiting_fine
    assert plan_click_verdict(None, True, True) == "moved_unconfirmed"
    assert plan_click_verdict(None, False, True) == "no_change"


# ===== 開場探測 give_up 通知附讀值（遠端一眼判虛空/凍結/按鈕失效）=====
from miningbot.reentry_remote import format_gate_readings


def test_format_gate_readings_all_present():
    s = format_gate_readings(True, 0.0, 0.93, 0.0185)
    assert "Surface" in s
    assert "0%" in s
    assert "0.93" in s
    assert "0.0185" in s


def test_format_gate_readings_in_mine():
    # Depth=NNNm（虛空墜落中）＋容量凍結舊幀 78%
    s = format_gate_readings(False, 78.0, 0.0, 0.0)
    assert "NNNm" in s
    assert "78%" in s
    assert "0.00" in s


def test_format_gate_readings_unreadable():
    # 全讀不到（H046 ep1 capacity=None 十一連發型）：不可拋例外、要標「讀不到」
    s = format_gate_readings(None, None, 0.0, 0.0)
    assert s.count("讀不到") == 2

