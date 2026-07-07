from miningbot.preflight import PreflightFacts, run_checks

def facts(**kw):
    base = dict(marker_real_count=3, chill_ref_count=6, rare_ores_json_age_days=10,
                ores_all_present=True, d4_cooldown_present=True, discord_token_set=True,
                tesserocr_ok=True, rapidocr_ok=True, log_dir_abspath="C:/x/logs",
                snapshots_total_mb=100, audio_decimate=8, audio_interval_s=0.3)
    base.update(kw)
    return PreflightFacts(**base)

def test_run_checks_all_good_yields_no_warnings():
    assert [m for lv, m in run_checks(facts()) if lv == "WARN"] == []

def test_missing_markers_warns_pure_hsv_fallback():
    warns = [m for lv, m in run_checks(facts(marker_real_count=0)) if lv == "WARN"]
    assert any("純 HSV" in m for m in warns)

def test_few_chill_refs_warns_family_coverage():
    # H034：chill 至少 4+ 音效家族，單參考必漏
    warns = [m for lv, m in run_checks(facts(chill_ref_count=2)) if lv == "WARN"]
    assert any("chill" in m for m in warns)

def test_chill_ref_budget_overrun_warns():
    # 12 refs×k=4 一輪 ~312ms > 0.3s 間隔必積壓（config 註解實測值：~12ms/ref @k=8）
    warns = [m for lv, m in run_checks(facts(chill_ref_count=30)) if lv == "WARN"]
    assert any("積壓" in m or "預算" in m for m in warns)

def test_onedrive_log_dir_with_big_snapshots_warns():
    warns = [m for lv, m in run_checks(facts(
        log_dir_abspath="C:/Users/p/OneDrive/Desktop/game/logs",
        snapshots_total_mb=700)) if lv == "WARN"]
    assert any("OneDrive" in m for m in warns)

def test_stale_rare_ores_json_warns_fetch_ores():
    warns = [m for lv, m in run_checks(facts(rare_ores_json_age_days=90)) if lv == "WARN"]
    assert any("fetch_ores" in m for m in warns)
