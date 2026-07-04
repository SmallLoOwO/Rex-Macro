import pytest
from miningbot.game_data import (match_event, is_kept, EVENTS, duration_str,
                                 fuzzy_match_ore, format_event_list_embed,
                                 World, WORLDS, AESTERIA, LUCERNIA, current_world,
                                 current_world_name, set_world, clear_world,
                                 common_ore_names, detect_world, update_world_from_event,
                                 WORLD_EMOJI, emoji_to_world,
                                 ore_world, format_keep_by_world)
import miningbot.game_data as gd


@pytest.fixture
def restore_world_state():
    """快照/還原模組全域世界狀態（測試會注入假世界 / 改 current world）。"""
    saved_worlds = dict(gd.WORLDS)
    saved_current = gd._current_world_name
    yield
    gd.WORLDS.clear(); gd.WORLDS.update(saved_worlds)
    gd._current_world_name = saved_current


def _fake_world(name="Testworld", event_match="unique testworld beacon",
                common_ore="Faketownite"):
    return World(
        name,
        [{"match": event_match, "ore": "FakeRare", "rarity": 1, "duration_s": 60,
          "chance_per_s": 1, "effect": "-", "tier": "X"}],
        [{"ore": common_ore, "rarity": 1, "layer": "L", "tier": "Surreal"}],
    )


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
    from miningbot.game_data import all_events
    embed = format_event_list_embed()
    assert embed["title"] == "REX 事件清單（所有世界）"
    assert len(embed["fields"]) == len(all_events())   # 全世界聯集

def test_embed_world_scoped_lucernia():
    embed = format_event_list_embed(world="Lucernia")
    assert embed["title"] == "REX 事件清單（Lucernia）"
    assert len(embed["fields"]) == len(LUCERNIA.events)  # 只列該世界


def test_embed_keep_status_markers():
    embed = format_event_list_embed({"Hallownest"})
    hall_field = [f for f in embed["fields"] if "Hallownest" in f["name"]][0]
    other_field = [f for f in embed["fields"] if "Dunestride" in f["name"]][0]
    assert hall_field["name"].startswith("✅")
    assert other_field["name"].startswith("❌")


# ---- 分世界結構（World）----

def test_world_aesteria_registered():
    assert "Aesteria" in WORLDS
    assert WORLDS["Aesteria"] is AESTERIA
    assert AESTERIA.name == "Aesteria"

def test_world_undetermined_by_default(restore_world_state):
    # 遊戲沒直接顯示世界 → 預設未確定（None），要靠事件偵測
    clear_world()
    assert current_world() is None
    assert current_world_name() is None

def test_events_alias_points_to_aesteria_events():
    assert EVENTS is AESTERIA.events

def test_set_world_unknown_raises(restore_world_state):
    set_world("Aesteria")
    with pytest.raises(KeyError):
        set_world("Nonexistent")
    assert current_world_name() == "Aesteria"   # 失敗不改變現況


# ---- 世界偵測（透過事件推斷）----

def test_detect_world_identifies_aesteria_from_event():
    # "twisted sarcophagus" 是 Aesteria 的事件（Umbrasnare）
    assert detect_world("Ruinous lies from a twisted sarcophagus tether the mine") == "Aesteria"

def test_detect_world_none_for_unknown_text():
    assert detect_world("some random text with no known event") is None

def test_detect_world_ambiguous_returns_none(restore_world_state):
    # 兩個世界共用同一事件片段 → 無法區分 → None
    WORLDS["Testworld"] = _fake_world(event_match="twisted sarcophagus")
    assert detect_world("a twisted sarcophagus appears") is None

def test_update_world_from_event_locks_world(restore_world_state):
    clear_world()
    update_world_from_event("Ruinous lies from a twisted sarcophagus tether the mine")
    assert current_world_name() == "Aesteria"

def test_update_world_from_event_keeps_none_on_unknown(restore_world_state):
    clear_world()
    update_world_from_event("nothing matches here")
    assert current_world_name() is None

def test_common_ores_union_when_world_undetermined(restore_world_state):
    # 未確定 → 用所有世界聯集當排除清單（保守）
    clear_world()
    WORLDS["Testworld"] = _fake_world(common_ore="Faketownite")
    names = set(n.lower() for n in common_ore_names())
    assert "lovelocket" in names      # Aesteria
    assert "faketownite" in names     # 假世界（聯集）

def test_common_ores_narrow_after_world_locked(restore_world_state):
    # 鎖定 Aesteria 後 → 只用 Aesteria 的清單，不含假世界的礦
    WORLDS["Testworld"] = _fake_world(common_ore="Faketownite")
    set_world("Aesteria")
    names = set(n.lower() for n in common_ore_names())
    assert "lovelocket" in names
    assert "faketownite" not in names


# ---- common_ore_names（D3 採集確認的低稀有度排除清單）----

def test_common_ores_have_required_fields():
    required = {"ore", "rarity", "layer", "tier"}
    for o in AESTERIA.common_ores:
        assert required.issubset(o.keys()), f"{o.get('ore')} missing fields"
        assert isinstance(o["rarity"], int) and o["rarity"] > 0

def test_common_ores_cover_surreal_and_mythic_tiers():
    tiers = {o["tier"] for o in AESTERIA.common_ores}
    assert {"Surreal", "Mythic"}.issubset(tiers)

def test_common_ore_names_deduped():
    names = common_ore_names()
    assert len(names) == len(set(names))

def test_common_ore_names_contains_known_lows():
    # 普通鎬子礦（低稀有度）應在排除清單：Surreal + Mythic 都涵蓋
    names = set(n.lower() for n in common_ore_names())
    for expect in ("lovelocket", "bandeau", "peppermint core", "sub-zero", "compact snow",
                   "crystallized solarite", "pool noodle", "passionblaze", "mystifall"):
        assert expect in names

def test_common_ore_names_excludes_rare_ores():
    # 稀有礦（Exotic 以上，如 Lilaverine/Rosarium）不該在「低稀有度排除清單」裡
    names = set(n.lower() for n in common_ore_names())
    for rare in ("lilaverine", "rosarium"):
        assert rare not in names


# ---- Lucernia 世界（低稀有度礦；事件待補）----

def test_world_lucernia_registered():
    assert "Lucernia" in WORLDS
    assert WORLDS["Lucernia"] is LUCERNIA
    assert LUCERNIA.name == "Lucernia"

def test_lucernia_events_populated():
    # 使用者 2026-06-30 補齊 Lucernia 事件（18 筆，按稀有度升序）
    assert len(LUCERNIA.events) == 18
    rarities = [ev["rarity"] for ev in LUCERNIA.events]
    assert rarities == sorted(rarities)

def test_lucernia_event_match_phrases_unique():
    phrases = [ev["match"] for ev in LUCERNIA.events]
    assert len(phrases) == len(set(phrases)), "duplicate Lucernia match phrases"

def test_lucernia_events_have_required_fields():
    required = {"match", "ore", "rarity", "duration_s", "chance_per_s", "effect", "tier"}
    for ev in LUCERNIA.events:
        assert required.issubset(ev.keys()), f"{ev.get('ore')} missing fields"

def test_detect_world_identifies_lucernia_from_event():
    # "eternal clock" 是 Lucernia 事件（DOOMSDAY）
    assert detect_world("Deafening chimes of an eternal clock boom throughout the mine") == "Lucernia"

def test_detect_world_distinguishes_lucernia_from_aesteria():
    # 兩世界的 match 片段互斥 → 各自唯一命中
    assert detect_world("a serene ballad tugs the strings") == "Lucernia"
    assert detect_world("a twisted sarcophagus tether the mine") == "Aesteria"

def test_lucernia_common_ores_have_required_fields():
    required = {"ore", "rarity", "layer", "tier"}
    for o in LUCERNIA.common_ores:
        assert required.issubset(o.keys()), f"{o.get('ore')} missing fields"
        assert isinstance(o["rarity"], int) and o["rarity"] > 0

def test_lucernia_common_ores_count():
    # 原六圖層 17 Surreal + 15 Mythic = 32；2026 春季更新四圖層 +19、洞穴限定 +7 = 58
    assert len(LUCERNIA.common_ores) == 58

def test_lucernia_common_ores_cover_surreal_and_mythic_tiers():
    tiers = {o["tier"] for o in LUCERNIA.common_ores}
    assert {"Surreal", "Mythic"}.issubset(tiers)

def test_lucernia_common_ores_no_duplicate_names():
    # 春季圖層/洞穴限定與原六圖層分段附加後，rarity 全域遞增不再成立
    # （洞穴 rarity 是洞穴內機率、尺度不同）——改守「無重複礦名」（排除清單去重的前提）
    names = [o["ore"] for o in LUCERNIA.common_ores]
    assert len(names) == len(set(names))

def test_lucernia_common_ores_in_global_union():
    # 世界未確定時用全世界聯集；Lucernia 的 礦應出現在聯集
    names = set(n.lower() for n in common_ore_names())
    for expect in ("presentine", "zerocite", "contemptus gemma", "shattered amulet"):
        assert expect in names

def test_lucernia_narrows_after_world_locked(restore_world_state):
    # 鎖定 Lucernia 後 → 只用 Lucernia 清單，不含 Aesteria 的礦
    set_world("Lucernia")
    names = set(n.lower() for n in common_ore_names())
    assert "presentine" in names            # Lucernia
    assert "lovelocket" not in names        # Aesteria 專屬


# ---- Discord 表情分頁（WORLD_EMOJI / emoji_to_world）----

def test_world_emoji_covers_all_registered_worlds():
    # 每個已註冊世界都要有對應表情按鈕（漏了就點不到那個分頁）
    assert set(WORLD_EMOJI.keys()) == set(WORLDS.keys())

def test_world_emoji_values_distinct():
    # 表情不可重複（重複會讓 emoji_to_world 模稜兩可）
    emojis = list(WORLD_EMOJI.values())
    assert len(emojis) == len(set(emojis)), "duplicate world emojis"

def test_emoji_to_world_roundtrip():
    for world, emoji in WORLD_EMOJI.items():
        assert emoji_to_world(emoji) == world

def test_emoji_to_world_unknown_returns_none():
    assert emoji_to_world("🦑") is None
    assert emoji_to_world("") is None


# ---- 保留清單依世界分組（ore_world / format_keep_by_world）----
# !keep/!unkeep 回覆要把保留清單依世界分組，使用者才看得出每個保留 礦屬於哪個世界。

def test_ore_world_maps_event_ore_to_its_world():
    assert ore_world("Celinity") == "Lucernia"      # choir of fairies
    assert ore_world("Ephemryst") == "Aesteria"

def test_ore_world_unknown_returns_none():
    assert ore_world("NotExistOre") is None

def test_format_keep_by_world_empty():
    assert format_keep_by_world(set()) == "（空）"

def test_format_keep_by_world_groups_each_world_onto_its_own_line():
    out = format_keep_by_world({"Ephemryst", "Sunflower", "Celinity", "Wintburg"})
    lines = out.split("\n")
    assert "【Aesteria】Ephemryst, Sunflower" in lines
    assert "【Lucernia】Celinity, Wintburg" in lines

def test_format_keep_by_world_sorts_ores_within_world():
    # 反順序加入也要 sorted
    out = format_keep_by_world({"Wintburg", "Celinity"})
    assert "【Lucernia】Celinity, Wintburg" in out.split("\n")

def test_format_keep_by_world_world_order_follows_WORLDS():
    out = format_keep_by_world({"Wintburg", "Ephemryst"})   # Lucernia + Aesteria
    # Aesteria 必須在 Lucernia 之前（依 WORLDS 順序），與加入順序無關
    assert out.index("【Aesteria】") < out.index("【Lucernia】")

def test_format_keep_by_world_omits_empty_world_lines():
    # 只有 Aesteria 的 礦 → 不該出現空的【Lucernia】行
    assert format_keep_by_world({"Ephemryst"}) == "【Aesteria】Ephemryst"

def test_format_keep_by_world_unknown_ore_into_other_bucket():
    out = format_keep_by_world({"Ephemryst", "MysteryOre"})
    lines = out.split("\n")
    assert "【Aesteria】Ephemryst" in lines
    assert "【其他】MysteryOre" in lines
    assert "【Lucernia】" not in out          # 沒 礦的世界不出現


# ---- 2026 春季更新（Lucernia 擴充）：Amourite/Shamrock/Brittlestone/Harmonine 四圖層
#      + Floral/Lucky/Eggshell 洞穴 —— H014 誤判的環境（情人節主題礦區）----
# 這些圖層的 Surreal/Mythic 會被動進聊天：漏列 → 聊天淡出喚醒後舊行被當「新稀有」→ 假成功。
# 資料源：rex-reincarnated wiki Lucernia 頁（2026-07-03 抓取）。

def test_lucernia_includes_spring_layer_surreal_mythic():
    names = {o["ore"] for o in LUCERNIA.common_ores}
    # H014 實機聊天出現過的被動 find（Amourite 圖層 + Floral 洞穴）
    assert {"Diamantine", "Ladyfeeb", "Dulcinette", "Beehive"} <= names
    # 各圖層代表礦（Shamrock/Brittlestone/Harmonine + 洞穴限定）
    assert {"Siogyne", "Toppatrick", "Polkegg", "Baggsket",
            "Synthesite", "Cirfith", "Rotatrim", "Duskgravite"} <= names

def test_lucernia_excludes_d3_targets_of_spring_layers():
    # Exotic/Exquisite 以上是 D3 採集目標，絕不可進排除清單（否則重演 H014 假陰性：
    # 真採到 Diamorite 卻被排除 → confirmed=False → 誤交人工）
    names = {o["ore"] for o in LUCERNIA.common_ores}
    assert names.isdisjoint({"Diamorite", "Saerylium", "Essentium", "Valytium",
                             "Everbloom", "Clovara", "Dolce", "Cupid", "Sweetheart"})

def test_lucernia_common_ores_all_surreal_or_mythic():
    # 排除清單的角色＝「會被動進聊天的低階」；REX 只有 Surreal/Mythic 兩階會被動進聊天
    assert {o["tier"] for o in LUCERNIA.common_ores} == {"Surreal", "Mythic"}


# ---- 三態分類（classify_found_ore）：排除清單→common、白名單→rare、都不在→unknown ----
# 白名單 = assets/rare_ores.json（fetch_ores 從 wiki 抓的 Exotic+ 高階礦）。
# unknown 仍算採集成功（安全方向），但通知會標注請人核對——清單漂移自己浮出來。

def test_classify_rare_ore_returns_tier_info():
    kind, info = gd.classify_found_ore("diamorite")
    assert kind == "rare"
    assert info["tier"] == "Exquisite"

def test_classify_tolerates_variant_prefix_and_tail_noise():
    assert gd.classify_found_ore("spectral diamorite")[0] == "rare"
    assert gd.classify_found_ore("everbloom (floral cave)")[0] == "rare"

def test_classify_common_ore_with_world_locked():
    gd.set_world("Lucernia")
    try:
        assert gd.classify_found_ore("jollycane (candied cave)")[0] == "common"
        assert gd.classify_found_ore("diamantine")[0] == "common"
    finally:
        gd.clear_world()

def test_classify_unknown_ore():
    kind, info = gd.classify_found_ore("xyzzyplugh")
    assert kind == "unknown" and info is None

def test_classify_empty_is_unknown():
    assert gd.classify_found_ore("")[0] == "unknown"


# ---- 模糊兜底（2026-07-04 H033 對策）：RapidOCR 對遊戲字型 i/l 同形的誤讀信心很高
# （Essentium→Essentlum 不觸發低信心 WARNING）、精確 startswith 對不上 → 真採到的
# 高階被標「⚠ 未知礦名」；低階被動 find 的同類誤讀（Dianantine 等）則洗版未知警告。
# 兜底＝對兩張表取最近鄰：門檻 CLASSIFY_FUZZY_RATIO 遠高於 H020 垃圾救援層的 0.62——
# 這裡只修「近失拼字」，真正的清單漂移（新礦名）仍須落 unknown 浮出來；
# rare 須嚴格贏過 common（寧漏勿假，與 ocr 模糊路徑同規則）、平手判 common。

def test_classify_fuzzy_rescues_il_confusion_as_rare():
    # H033 實錄（2026-07-04 16:25）：聊天實際顯示 Essentium、RapidOCR 讀成 Essentlum
    kind, info = gd.classify_found_ore("essentlum")
    assert kind == "rare_fuzzy"
    assert info["ore"] == "Essentium"
    assert info["fuzzy_ratio"] >= gd.CLASSIFY_FUZZY_RATIO

def test_classify_fuzzy_does_not_mutate_whitelist_table():
    gd.classify_found_ore("essentlum")
    kind, info = gd.classify_found_ore("essentium")    # 精確路徑拿的是快取表的原 dict
    assert kind == "rare" and "fuzzy_ratio" not in info

def test_classify_fuzzy_common_misread_stays_common():
    gd.set_world("Lucernia")
    try:
        # H027–H030 實錄誤讀（Diamantine 被動 find），舊版全標「⚠ 未知礦名」洗版通知
        assert gd.classify_found_ore("dianantine")[0] == "common"
        assert gd.classify_found_ore("diamantina")[0] == "common"
    finally:
        gd.clear_world()

def test_classify_fuzzy_far_names_stay_unknown():
    # 低於門檻的（含 0.62~0.80 之間「模糊救援層會收」的程度）仍是 unknown：
    # 清單漂移警示不能被兜底吃掉
    assert gd.classify_found_ore("velyiiuinm")[0] == "unknown"   # H020 實錄，對 Valytium 0.667


# ---- 白名單依世界收斂（與 common_ore_names 同款模式）----
# 世界已由事件鎖定 → 只查該世界的高階白名單（同名礦跨世界階級可能不同、也不可能
# 採到別世界的礦）；未定 → 聯集（保守）。

def test_classify_scopes_whitelist_to_locked_world():
    gd.set_world("Lucernia")
    try:
        assert gd.classify_found_ore("arachnophyte")[0] == "rare"      # Lucernia 高階
        assert gd.classify_found_ore("abyssium")[0] == "unknown"       # Aesteria 高階 → 本世界不可能
    finally:
        gd.clear_world()

def test_classify_uses_union_when_world_unknown():
    gd.clear_world()
    assert gd.classify_found_ore("arachnophyte")[0] == "rare"
    assert gd.classify_found_ore("abyssium")[0] == "rare"

def test_rare_ores_scoped_by_world_and_union():
    assert "abyssium" not in gd.rare_ores("Lucernia")
    assert "abyssium" in gd.rare_ores("Aesteria")
    assert "abyssium" in gd.rare_ores(None) and "arachnophyte" in gd.rare_ores(None)


def test_rare_ore_names_converges_by_world():
    # 與 common_ore_names 同款收斂：未鎖世界→聯集；鎖定→只回該世界白名單名稱
    gd.clear_world()
    names = gd.rare_ore_names()
    assert "Valytium" in names            # Lucernia Exotic（H020 實際採到的）
    assert "Abyssium" in names            # Aesteria 高階（聯集要有）
    try:
        gd.set_world("Lucernia")
        scoped = gd.rare_ore_names()
        assert "Valytium" in scoped
        assert "Abyssium" not in scoped
    finally:
        gd.clear_world()
