from miningbot.calibrate_pitch import apply_calib_step, parse_calib_command


def test_parse_defaults_and_explicit_px():
    assert parse_calib_command("r", 40) == ("reset", 0)
    assert parse_calib_command("q", 40) == ("quit", 0)
    assert parse_calib_command("u", 40) == ("up", 40)      # 未給 px 用預設步長
    assert parse_calib_command("d 60", 40) == ("down", 60)
    assert parse_calib_command("UP 25", 40) == ("up", 25)  # 大小寫不敏感


def test_parse_rejects_garbage():
    # 寧可不動不誤動：解析不出回 None（與 reentry_remote.parse_reply 同哲學）
    assert parse_calib_command("", 40) is None
    assert parse_calib_command("x", 40) is None
    assert parse_calib_command("u 0", 40) is None
    assert parse_calib_command("u -5", 40) is None
    assert parse_calib_command("u abc", 40) is None
    assert parse_calib_command("r 10", 40) is None


def test_apply_step_accounting_saturates_at_clamp():
    assert apply_calib_step(120, "reset", 0) == 0
    assert apply_calib_step(0, "up", 40) == 40
    assert apply_calib_step(40, "down", 25) == 15
    assert apply_calib_step(15, "down", 100) == 0   # 夾限飽和：不記負值


from miningbot.calibrate_pitch import parse_calib_target, can_accept_calibration


def test_parse_calib_target_defaults_and_aliases():
    assert parse_calib_target(()) == "mining"            # 無參數預設挖礦（spec 第 1 節）
    assert parse_calib_target(("挖礦",)) == "mining"
    assert parse_calib_target(("MINING",)) == "mining"   # 大小寫不敏感
    assert parse_calib_target(("回礦",)) == "reentry"
    assert parse_calib_target(("reentry",)) == "reentry"
    assert parse_calib_target(("garbage",)) is None      # 寧可不動不誤動


def test_can_accept_calibration_gates():
    ok, _ = can_accept_calibration(False, False)
    assert ok
    ok, reason = can_accept_calibration(True, False)
    assert not ok and "回礦" in reason                    # episode 進行中拒絕
    ok, reason = can_accept_calibration(False, True)
    assert not ok and "校準" in reason                    # 已在校準中拒絕


from miningbot.calibrate_pitch import (
    CALIB_TITLE, CALIB_STEPS, CALIB_EMOJIS, CALIB_ACTIONS, CalibSession,
    next_step, calib_field_names, build_calib_embed)


def test_next_step_cycles_and_recovers():
    assert next_step(1) == 5
    assert next_step(5) == 10
    assert next_step(10) == 50
    assert next_step(50) == 1                 # 循環回頭
    assert next_step(999) == 1                # 非法現值回 1（防記帳壞掉卡死）


def test_calib_field_names_mapping():
    assert calib_field_names("mining") == (
        "sweep_pitch_center_back_px", "sweep_pitch_clamp_px")
    assert calib_field_names("reentry") == (
        "reentry_pitch_back_px", "reentry_pitch_clamp_px")


def test_calib_session_defaults():
    sess = CalibSession(target="mining", offset=300)
    assert sess.step == 5                     # 初始幅度 5（計畫 Global Constraints）
    assert sess.prev_paused is False
    assert sess.message_id is None
    assert sess.reactions_seen == {}


def test_calib_actions_cover_all_emojis():
    assert set(CALIB_ACTIONS) == set(CALIB_EMOJIS)
    assert set(CALIB_ACTIONS.values()) == {
        "up", "down", "step", "home", "snap", "save", "exit"}


def test_build_calib_embed_shows_state():
    embed = build_calib_embed("mining", 435, 0, 10)
    assert embed["title"] == CALIB_TITLE
    d = embed["description"]
    assert "sweep_pitch_center_back_px" in d
    assert "435" in d and "10" in d           # offset 與幅度都要看得到
    assert "挖礦標準角" in d
    assert "⚠" not in d
    warned = build_calib_embed("reentry", 400, 400, 5, warn="拖曳疑似被吃")
    assert "⚠" in warned["description"] and "回礦標準角" in warned["description"]


from miningbot.calibrate_pitch import rewrite_config_value

_CONFIG_SNIPPET = (
    "    reentry_pitch_clamp_px: int = 1500          # 俯仰歸位夾限\n"
    "    reentry_pitch_back_px: int = 400            # 回拉量（校準寫回這裡）\n"
    "    sweep_pitch_center_back_px: int = 0         # 0=未校準＝停用\n"
)


def test_rewrite_config_value_changes_only_target_line():
    out = rewrite_config_value(_CONFIG_SNIPPET, "sweep_pitch_center_back_px", 435)
    assert "sweep_pitch_center_back_px: int = 435         # 0=未校準＝停用" in out
    # 其他行 byte-level 不變（含 clamp 行與另一欄位）
    assert "reentry_pitch_clamp_px: int = 1500          # 俯仰歸位夾限" in out
    assert "reentry_pitch_back_px: int = 400            # 回拉量（校準寫回這裡）" in out


def test_rewrite_config_value_two_fields_independent():
    out = rewrite_config_value(_CONFIG_SNIPPET, "reentry_pitch_back_px", 380)
    assert "reentry_pitch_back_px: int = 380            # 回拉量（校準寫回這裡）" in out
    assert "sweep_pitch_center_back_px: int = 0" in out


def test_rewrite_config_value_idempotent_same_value():
    # 值已相同仍回改寫文（冪等；spec 第 3 節）——呼叫端不必特判
    out = rewrite_config_value(_CONFIG_SNIPPET, "reentry_pitch_back_px", 400)
    assert out is not None and "reentry_pitch_back_px: int = 400" in out


def test_rewrite_config_value_missing_or_ambiguous_anchor():
    assert rewrite_config_value(_CONFIG_SNIPPET, "no_such_field", 1) is None
    doubled = _CONFIG_SNIPPET + "    reentry_pitch_back_px: int = 999\n"
    assert rewrite_config_value(doubled, "reentry_pitch_back_px", 1) is None  # 錨點不唯一不硬寫
