from miningbot.game_data import match_event, is_kept, EVENTS, duration_str, fuzzy_match_ore, format_event_list_embed


def test_match_event_exact_phrase():
    ev = match_event("A minature dust devil forms in the Maculite layer...")
    assert ev is not None
    assert ev["ore"] == "Dunestride"


def test_match_event_case_insensitive():
    ev = match_event("SOFT PETALS ABSORB THE SUN")
    assert ev is not None
    assert ev["ore"] == "Sunflower"


def test_match_event_partial_ocr_truncated():
    # OCR 只讀到前半段（事件列文字太長被截斷），match 片段在句首才穩
    ev = match_event("Hordes of eyes lock their piercing ga")  # 末尾被截斷
    assert ev is not None
    assert ev["ore"] == "The All-Seeing"


def test_match_event_no_match_returns_none():
    ev = match_event("Some unknown event that doesn't exist")
    assert ev is None


def test_match_event_multiple_hits_returns_highest_rarity():
    # 若 OCR 同時讀到兩個事件的片段，回傳稀有度最高的
    text = "fluttering and dust devil together"
    ev = match_event(text)
    assert ev["ore"] == "Dunestride"          # 8.4M > 6.6M (Mythical Hive)


def test_is_kept_no_keep_list_rerolls_everything():
    # 無 keep_ores（預設）→ 所有已知事件都刷新（保守策略，等 Discord 指定後才有保留）
    assert is_kept("Hordes of eyes lock their piercing gaze") is False   # tier A 仍刷新
    assert is_kept("sanctum of tears") is False                           # tier S 仍刷新


def test_is_kept_custom_keep_list():
    # 使用者指定保留 Hallownest
    keep = {"Hallownest"}
    assert is_kept("sanctum of tears", keep_ores=keep) is True
    assert is_kept("dust devil", keep_ores=keep) is False                 # Dunestride 不在清單


def test_is_kept_unknown_event_rerolls():
    assert is_kept("unknown event text") is False


def test_all_events_have_required_fields():
    required = {"match", "ore", "rarity", "duration_s", "chance_per_s", "effect", "tier"}
    for ev in EVENTS:
        assert required.issubset(ev.keys()), f"{ev.get('ore')} missing fields"


def test_all_match_phrases_unique():
    phrases = [ev["match"] for ev in EVENTS]
    assert len(phrases) == len(set(phrases)), "duplicate match phrases"


def test_duration_str_formats():
    ev_20min = {"duration_s": 20 * 60}
    ev_frac = {"duration_s": 33.3 * 60}
    assert duration_str(ev_20min) == "20min"
    assert duration_str(ev_frac) == "33.3min"


# ---- fuzzy_match_ore ----

def test_fuzzy_match_exact():
    assert fuzzy_match_ore("Hallownest") == "Hallownest"
    assert fuzzy_match_ore("Dunestride") == "Dunestride"


def test_fuzzy_match_case_insensitive():
    assert fuzzy_match_ore("hallownest") == "Hallownest"
    assert fuzzy_match_ore("THE ALL-SEEING") == "The All-Seeing"


def test_fuzzy_match_substring():
    assert fuzzy_match_ore("hall") == "Hallownest"
    assert fuzzy_match_ore("sun") == "Sunflower"


def test_fuzzy_match_full_phrase_in_query():
    # "the all seeing" 包含 "The All-Seeing" → 命中
    assert fuzzy_match_ore("the all seeing") == "The All-Seeing"


def test_fuzzy_match_no_match():
    assert fuzzy_match_ore("nonexistent") is None
    assert fuzzy_match_ore("") is None


# ---- format_event_list_embed ----

def test_embed_has_all_events():
    embed = format_event_list_embed()
    assert embed["title"] == "REX 事件清單"
    assert len(embed["fields"]) == len(EVENTS)


def test_embed_keep_status_markers():
    embed = format_event_list_embed({"Hallownest"})
    hall_field = [f for f in embed["fields"] if "Hallownest" in f["name"]][0]
    other_field = [f for f in embed["fields"] if "Dunestride" in f["name"]][0]
    assert hall_field["name"].startswith("✅")
    assert other_field["name"].startswith("❌")
