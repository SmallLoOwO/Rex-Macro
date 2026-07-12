import numpy as np
from miningbot.reentry_remote import (RemoteReply, parse_reply, coarse_cell_region,
                                      fine_cell_to_screen, render_zoom, draw_click_marker)


class TestParseReply:
    def test_coarse(self):
        r = parse_reply("3 C2")
        assert (r.kind, r.dir_idx, r.cell) == ("coarse", 3, "C2")

    def test_coarse_invalid(self):
        assert parse_reply("8 C2") is None       # 方位只有 0-7
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

    def test_walk(self):
        r = parse_reply("走 C2")
        assert (r.kind, r.cell) == ("walk", "C2")
        assert parse_reply("walk d4").cell == "D4"
        assert parse_reply("走 C5") is None       # walk 用粗網格（列 1-4）

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

