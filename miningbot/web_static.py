"""網頁前端 HTML render（設定 / 介入 / 歷史 / episode 詳細 / 標註）。"""
from .game_data import HIGH_TIER_NAMES


def _tier_checked(tier: str, disabled_tiers) -> bool:
    """網頁 checkbox 用：tier 是否未被排除（= 該打勾）。"""
    return tier not in (disabled_tiers or ())

import json


# --- 全站導覽（2026-07-26 補）------------------------------------------------
#
# 先前四個頁面之間**沒有任何連結**：開根網址只看得到 4 欄設定表單，
# /intervention、/history、/annotate 全要手打網址才進得去——功能其實都在，
# 只是使用者找不到（實機回報「網頁內容特別簡潔，感覺有部分功能沒放進去」）。
#
# 手機優先：橫向捲動的一列，點擊區夠大；current 標當前頁。
_NAV_ITEMS = (
    ("/", "⚙️ 設定"),
    ("/intervention", "🎯 介入"),
    ("/history", "📜 歷史"),
    # 2026-07-28：批次標註要找得到才會有人用（三個月只標了 2 張，一半原因是
    # 得先從歷史頁一張一張點進來）。直接給待標註佇列的入口。
    # 2026-07-31 加 tier2：tier0 清一色是 bot 全拒的圖，「bot 接受了但接錯」
    # 那兩個症狀只有 tier2（sweep_accepted / d3_fire / aim_fire）舉得出例子。
    ("/annotate?queue=tier0,tier2", "🏷️ 標註佇列"),
    # 這兩頁的讀者是 AI agent 不是玩家（使用者原話：「這些資料對我來說沒有意義，
    # 對 AI agent 比較有價值，讓他去處理微調的問題」）。排版可以醜，資料要全。
    ("/failures", "🤖 失敗佇列"),
    ("/stats", "📊 統計"),
)

NAV_CSS = """
.nav { display: flex; gap: 0.4rem; padding: 0.5rem 0.6rem; background: #15171c;
       overflow-x: auto; border-bottom: 1px solid #2a2f38; }
.nav a { flex: 0 0 auto; padding: 0.45rem 0.9rem; border-radius: 999px;
         background: #21252e; color: #969ba6; text-decoration: none;
         font-size: 0.9rem; white-space: nowrap; }
.nav a:hover { background: #2c313c; color: #e6e8ec; }
.nav a.current { background: #4d9fff; color: #fff; }
"""


def render_nav(current: str) -> str:
    """回導覽列 HTML。current 是當前路徑（例如 "/history"）。"""
    parts = []
    for href, label in _NAV_ITEMS:
        # 比路徑不比 query string：`/annotate?queue=tier0` 在 `/annotate` 也算當前頁
        cls = ' class="current"' if href.split("?", 1)[0] == current else ""
        parts.append(f'<a href="{href}"{cls}>{label}</a>')
    return '<nav class="nav">%s</nav>' % "".join(parts)


def render_index_html(config, layer_info: dict | None = None) -> str:
    """4 個白名單欄位的設定表單 + JS 提交 fetch /api/config。

    純函式：吃 Config instance、回 HTML 字串。讀 4 個白名單欄位現值填入 form。

    layer_info（2026-07-26）：``{"effective": str, "world": str|None,
    "from_world_map": bool}``。給了就用 ``effective`` 當目標層現值，並在欄位下方
    說明這個值是哪來的。**這是網頁與 Discord `層` 指令同步的關鍵**——執行期真正
    生效的是每世界黏性層 ``sticky_layers[world]``，``cfg.reentry_target_layer``
    只是查不到世界時的 fallback。舊版只顯示後者，於是 Discord 已經把
    Lucernia 記成 Shamrock、設定頁卻還寫 Mantle Layer。

    給 None（沒有 bot 的呼叫端／既有測試）時退回舊行為，只讀 config。
    """
    reentry_mode = getattr(config, "reentry_mode", "remote")
    fallback_layer = getattr(config, "reentry_target_layer", "")
    yaw_sample = getattr(config, "reentry_yaw_sample_sweep", False)
    sweep_pitch = getattr(config, "sweep_pitch_enabled", False)
    detection_tier = getattr(config, "detection_disabled_tiers", ())

    target_layer = fallback_layer
    layer_hint = ""
    if isinstance(layer_info, dict):
        effective = layer_info.get("effective")
        if isinstance(effective, str) and effective:
            target_layer = effective
        world = layer_info.get("world")
        if layer_info.get("from_world_map") and world:
            layer_hint = (f"目前套用 <b>{_esc(world)}</b> 的記憶值"
                          f"（與 Discord <code>層</code> 指令同一份）；"
                          f"未記錄的世界會用預設 <code>{_esc(fallback_layer)}</code>。")
        elif world:
            layer_hint = (f"世界 <b>{_esc(world)}</b> 尚未記錄過目標層，"
                          f"目前用預設值；在這裡儲存等同對該世界下 "
                          f"Discord <code>層</code> 指令。")
        else:
            layer_hint = ("世界尚未偵測到，顯示的是預設值；"
                          "偵測到之後儲存才會記進該世界。")

    yaw_checked = "checked" if yaw_sample else ""
    sweep_checked = "checked" if sweep_pitch else ""
    layer_hint_html = (f'<p class="hint">{layer_hint}</p>' if layer_hint else "")

    # 掃描俯仰勾了不一定會動：`harvester.plan_pitch_layers` 在 step_px==0 或
    # center_back_px<=0（都＝沒校準過）時回空 list，等於整個功能靜默停用。
    # 不講的話玩家勾了、以為開了、行為卻沒變——這正是「設定看不懂」的一種。
    step_px = getattr(config, "sweep_pitch_step_px", 0)
    center_back_px = getattr(config, "sweep_pitch_center_back_px", 0)
    if step_px == 0 or center_back_px <= 0:
        sweep_status = ('<p class="hint warn">⚠ <b>目前就算勾選也不會生效</b>：'
                        '上下掃描需要先量出「一層要拖幾像素」，而這個值尚未校準'
                        f'（<code>sweep_pitch_step_px={_esc(step_px)}</code>）。'
                        '校準前這個開關等於關著。</p>')
    else:
        sweep_status = ('<p class="hint ok">✅ 已校準，勾選即生效'
                        f'（一層 <code>{_esc(step_px)}px</code>）。</p>')

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>MiningBot 玩家設定</title>
<style>{NAV_CSS}
body {{ font-family: system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei",
              sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem;
       background: #0f1115; color: #e6e8ec; color-scheme: dark; }}
h1 {{ font-weight: 600; }}
label {{ display: block; margin: 1rem 0 0.3rem; font-weight: 600;
         color: #c8ccd4; }}
input, select {{ width: 100%; padding: 0.5rem; box-sizing: border-box;
                background: #21252e; color: #e6e8ec;
                border: 1px solid #2a2f38; border-radius: 5px; }}
input:focus, select:focus {{ outline: none; border-color: #4d9fff; }}
/* checkbox 必須排除在 width:100% 之外（2026-07-26 實機回報）：被撐成整行寬之後，
   Chrome 把方塊畫在那一行的正中央，而 label 是 display:block，文字被擠到下一行
   ——視覺上變成「勾選方塊浮在自己的標籤文字上方置中」，看起來就是壞掉的版面。
   手機上更明顯。改成 inline-flex 讓方塊與文字同一行、點擊區維持整段文字。 */
label.check {{ display: flex; align-items: center; gap: 0.5rem;
              font-weight: 600; margin: 1rem 0 0.3rem; }}
label.check input[type="checkbox"] {{ width: auto; flex: 0 0 auto;
              margin: 0; padding: 0; transform: scale(1.3);
              accent-color: #4d9fff; }}
button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; background: #4d9fff; color: #fff;
         border: none; border-radius: 5px; cursor: pointer; font-weight: 600; }}
button:hover {{ background: #5fb0ff; }}
.status {{ margin-top: 1rem; padding: 0.6rem; background: #13223a;
          border: 1px solid #1e3a5f; border-radius: 5px; display: none; }}
.error {{ background: #2a1414; border-color: #5c2424; }}
.hint {{ margin: 0.35rem 0 0; font-size: 0.8rem; color: #969ba6; line-height: 1.5; }}
.hint code {{ background: #21252e; padding: 0 0.25rem; border-radius: 3px;
             color: #c8ccd4; }}
.hint.warn {{ background: #2a2113; border-left: 3px solid #d9a441;
             padding: 0.4rem 0.6rem; color: #e8c87a; }}
.hint.ok {{ background: #13251a; border-left: 3px solid #3ba55d;
           padding: 0.4rem 0.6rem; color: #6dba85; }}
fieldset {{ border-color: #2a2f38; }}
legend {{ color: #c8ccd4; }}
h2 {{ margin-top: 2rem; border-top: 1px solid #2a2f38; padding-top: 1rem;
     font-size: 1.1rem; color: #c8ccd4; }}
</style>
</head>
<body>
{render_nav("/")}
<h1>MiningBot 玩家設定</h1>

<form id="settings-form">
  <label for="reentry_mode">回礦模式</label>
  <select id="reentry_mode" name="reentry_mode">
    <option value="off" {"selected" if reentry_mode == "off" else ""}>off（等人工）</option>
    <option value="remote" {"selected" if reentry_mode == "remote" else ""}>remote（你遠端點傳送板）</option>
    <option value="auto" {"selected" if reentry_mode == "auto" else ""}>auto（全自動）</option>
  </select>
  <p class="hint"><b>礦坑重置後，怎麼回到礦裡繼續挖。</b>
    重置會把你丟回地表，要走到「傳送板」點下去才會回礦坑。<br>
    <code>off</code>＝bot 停在地表等你本人來操作。
    <code>remote</code>＝bot 拍照給你看，你在這個網頁（或 Discord）點傳送板的位置，
    bot 替你點下去——<b>目前的預設做法</b>。
    <code>auto</code>＝bot 自己找傳送板，不問你。</p>

  <label for="reentry_target_layer">目標層</label>
  <input type="text" id="reentry_target_layer" name="reentry_target_layer"
         value="{_esc(target_layer)}" placeholder="例：Mantle Layer">
  <p class="hint"><b>你想回到哪一層礦。</b>
    傳送板上有很多層可選，這裡填的是你希望 bot 幫你認的那一層名字
    （Discord 的 <code>層 &lt;名&gt;</code> 指令改的是同一個值）。
    bot <b>不會驗證</b>這個名字對不對——它只是記帳，用來標記「這次回的是哪層」，
    事後對帳與素材標註看得懂。</p>
  {layer_hint_html}

  <label class="check"><input type="checkbox" id="reentry_yaw_sample_sweep"
                name="reentry_yaw_sample_sweep" {yaw_checked}>
    <span>回礦成功後原地拍八方位（收語料）</span></label>
  <p class="hint"><b>成功回到礦坑後，原地轉一圈拍 8 張照片存起來。</b>
    「語料」＝<b>拿來訓練/校正偵測用的實機圖片庫</b>，不是遊戲功能，開了對挖礦本身
    沒有任何影響，純粹是替之後改程式累積素材。<br>
    收這批圖要解決的問題：每次重生 bot 的面向都是隨機的，導致它常常斜著挖。
    要修好得先有「各種面向長什麼樣」的圖片可比對，而八方位相鄰兩張固定差 45°，
    正好能當自我驗證的資料集。<br>
    <b>代價</b>：每次回礦成功後多花約 15 秒轉一圈，並多佔一些硬碟空間。
    不想收就關掉。</p>

  <label class="check"><input type="checkbox" id="sweep_pitch_enabled"
                name="sweep_pitch_enabled" {sweep_checked}>
    <span>掃描俯仰（找不到礦時，改抬頭／低頭再找一輪）</span></label>
  <p class="hint"><b>「俯仰」＝鏡頭上下角度</b>（左右轉叫方位，上下抬叫俯仰）。<br>
    bot 找礦時會原地轉一圈掃 8 個方向。這個開關管的是<b>那一圈全空之後</b>怎麼辦：
    關著＝就此放棄這一輪；開著＝把鏡頭往上、往下各調一次再各掃一輪，
    撈那些在<b>上一層或下一層</b>、平視角度看不到的礦。<br>
    <b>代價</b>：每次撲空多花<b>約 90-100 秒</b>掃 2 圈（上下各一輪；任一層的鏡頭拖曳
    被遊戲吃掉要重試再 +15 秒），但能少掉一些「明明有礦卻回報全空」。</p>
  {sweep_status}

  <fieldset style="border:1px solid #ccc; padding:0.6rem; border-radius:4px;">
    <legend style="font-weight:bold; padding:0 0.4rem;">偵測階級（打勾 = 會偵測）</legend>{
    chr(10).join(
        f'    <label class="check"><input type="checkbox" class="tier-cb" data-tier="{t}"'
        f' {"checked" if _tier_checked(t, detection_tier) else ""}>'
        f' <span>{t}</span></label>'
        for t in HIGH_TIER_NAMES
    )}
    <p class="hint"><b>取消勾選的階級不會觸發採集偵測。</b>
      通常從最下面（Exotic）開始關——Exotic 長期常見，關掉就不會因為鎬子
      挖到而誤判「已採到稀有 礦」。<br>
      與 Discord <code>階級</code> 指令共用同一份設定。</p>
  </fieldset>

  <button type="submit">儲存</button>
</form>

<h2>D2 連續使用</h2>
<p class="hint">冷卻好就自動再按，範圍自動採礦／削特殊洞穴方塊；跟 Discord <code>掃描</code>/<code>削洞</code>
指令共用同一份設定。<br>⚠ 掃描與採集流程搶同一條 D2 冷卻，開著可能讓 chill 採集掃不出追蹤框。</p>
<label class="check"><input type="checkbox" id="radar-scan"> <span>掃描（Cyberscan，D2 左鍵）</span></label>
<label class="check"><input type="checkbox" id="radar-cave"> <span>削洞（Cave Skim，D2 Z）</span></label>

<div id="status" class="status"></div>
<div id="player-status" class="status" style="display:none;"></div>

<script>
const form = document.getElementById('settings-form');
const status = document.getElementById('status');

form.addEventListener('submit', async (e) => {{
  e.preventDefault();
  // 偵測階級：未勾選的 tier = 被排除的
  const tierCbs = document.querySelectorAll('.tier-cb');
  const disabledTiers = Array.from(tierCbs).filter(cb => !cb.checked).map(cb => cb.dataset.tier);
  const payload = {{
    reentry_mode: document.getElementById('reentry_mode').value,
    reentry_target_layer: document.getElementById('reentry_target_layer').value,
    reentry_yaw_sample_sweep: document.getElementById('reentry_yaw_sample_sweep').checked,
    sweep_pitch_enabled: document.getElementById('sweep_pitch_enabled').checked,
    detection_disabled_tiers: disabledTiers,
  }};
  status.className = 'status';
  status.style.display = 'block';
  status.textContent = '儲存中…';

  try {{
    const results = [];
    for (const [field, value] of Object.entries(payload)) {{
      const r = await fetch('/api/config', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ field, value }}),
      }});
      if (!r.ok) {{
        const err = await r.json().catch(() => ({{}}));
        throw new Error(field + ': ' + (err.error || r.status));
      }}
      results.push(field);
    }}
    status.textContent = '已儲存：' + results.join(', ');
  }} catch (err) {{
    status.className = 'status error';
    status.textContent = '儲存失敗：' + err.message;
  }}
}});

// --- D2 連續使用（2026-07-28）：非 Config 欄位，走 /api/player + /api/radar ---
const radarScanEl = document.getElementById('radar-scan');
const radarCaveEl = document.getElementById('radar-cave');
const playerStatusEl = document.getElementById('player-status');

function showPlayerStatus(text, isError) {{
  playerStatusEl.style.display = 'block';
  playerStatusEl.className = 'status' + (isError ? ' error' : '');
  playerStatusEl.textContent = text;
}}

async function postJSON(url, body) {{
  const r = await fetch(url, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body),
  }});
  if (!r.ok) {{
    const err = await r.json().catch(() => ({{}}));
    throw new Error(err.error || String(r.status));
  }}
  return r.json();
}}

async function loadPlayerState() {{
  try {{
    const data = await fetch('/api/player').then(r => r.json());
    radarScanEl.checked = !!(data.radar && data.radar.scan);
    radarCaveEl.checked = !!(data.radar && data.radar.cave);
  }} catch (err) {{
    showPlayerStatus('玩家狀態載入失敗：' + err.message, true);
  }}
}}

async function toggleRadar(which, checkbox) {{
  try {{
    await postJSON('/api/radar', {{ which, value: checkbox.checked }});
    showPlayerStatus((which === 'scan' ? '掃描' : '削洞') + '：' + (checkbox.checked ? '開' : '關'), false);
  }} catch (err) {{
    checkbox.checked = !checkbox.checked;
    showPlayerStatus('D2 開關更新失敗：' + err.message, true);
  }}
}}
radarScanEl.addEventListener('change', () => toggleRadar('scan', radarScanEl));
radarCaveEl.addEventListener('change', () => toggleRadar('cave', radarCaveEl));

loadPlayerState();
</script>
</body>
</html>
"""


def _esc(s: str) -> str:
    """HTML 屬性值 escape；避免 value 帶 " 或 < > 打破 HTML。"""
    return (str(s)
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def render_history_html(episodes: list[dict]) -> str:
    """P5 Task 7：歷史紀錄面板 HTML（episode 列表 + 篩選；spec §5 A 區）。

    純函式：吃 ``web_history.load_episodes`` 回的 list[dict]，輸出 HTML 字串。
    每列欄位：episode_id / type / first_ts / count；點列跳到 ``/annotate?episode=``。
    篩選 UI：type（all/harvest/reentry）、result、關鍵字（episode_id）。
    result 欄目前 load_episodes 沒給——保留欄位與篩選 UI，未來擴充時連動。
    """
    # Episode 欄顯示帶類型前綴的 label（採#114 / 回#26），連結用唯一 key。
    # 舊版兩欄都用裸編號，於是「採集 #26」與「回礦 #26」在列表上長得一模一樣，
    # 點進去還會互相蓋掉（/episode?id=26 只回其中一個）。
    rows = "".join(
        f'<tr data-id="{_esc(e.get("harvest_id", ""))}"'
        f' data-type="{_esc(e.get("type", ""))}"'
        f' data-result="{_esc(e.get("result", ""))}"'
        f' data-date="{_date_str(e.get("first_ts"))}">'
        # 連詳細頁而不是直接跳標註：先看「這一集發生什麼」才知道要標哪張
        f'<td><a href="/episode?id={_url_q(str(e.get("key") or e.get("harvest_id", "")))}">'
        f'{_esc(e.get("label") or e.get("harvest_id", ""))}</a></td>'
        f'<td>{_esc(e.get("type_label") or e.get("type", ""))}</td>'
        f'<td class="result">{_esc(e.get("result") or "—")}</td>'
        f'<td>{_format_ts(e.get("first_ts"))}</td>'
        f'<td>{e.get("count", 0)}</td>'
        f"</tr>"
        for e in episodes
    )
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiningBot 歷史紀錄</title>
<style>{NAV_CSS}
body {{ font-family: system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei",
              sans-serif; max-width: 900px; margin: 1rem auto;
       padding: 0 0.5rem; background: #0f1115; color: #e6e8ec;
       color-scheme: dark; }}
h1 {{ font-size: 1.2rem; font-weight: 600; }}
.filters {{ display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 1rem 0;
            align-items: end; }}
.filters label {{ display: flex; flex-direction: column; font-size: 0.8rem;
                  color: #969ba6; gap: 0.2rem; }}
.filters select, .filters input {{ padding: 0.35rem; font-size: 0.9rem;
                  background: #21252e; color: #e6e8ec;
                  border: 1px solid #2a2f38; border-radius: 4px; }}
.filters button {{ padding: 0.35rem 0.7rem; background: #21252e; color: #c8ccd4;
                  border: 1px solid #2a2f38; border-radius: 4px; cursor: pointer;
                  font-size: 0.85rem; }}
.filters button:hover {{ background: #2c313c; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.4rem 0.5rem; border-bottom: 1px solid #2a2f38;
         text-align: left; font-size: 0.9rem; }}
th {{ background: #171a21; color: #969ba6; font-weight: 600; }}
tbody tr:hover {{ background: #171a21; }}
tr.hidden {{ display: none; }}
a {{ color: #6ab7ff; text-decoration: none; }}
a:hover {{ color: #8fc6ff; }}
.hint {{ color: #6b7280; font-size: 0.75rem; margin-top: 0.5rem; }}
</style>
</head>
<body>
{render_nav("/history")}
<h1>MiningBot 歷史紀錄</h1>

<form class="filters" id="filters" onsubmit="return false;">
  <label>類型
    <select id="filter-type">
      <option value="all">全部</option>
      <option value="harvest">採集</option>
      <option value="reentry">回礦</option>
    </select>
  </label>
  <!-- 結果篩選停用中：load_episodes 沒有 result 這個欄位（snapshot_index.jsonl
       只有 label/path/written_at，沒有判定結果），所以每列 data-result 都是空字串。
       舊版讓它可選，玩家一選「成功」就是 0 / 60 全空——看起來像壞掉而不是沒資料。
       接上資料來源前先 disabled + 講清楚原因；欄位與 JS 分支都留著，之後只要
       load_episodes 開始給 result 就把 disabled 拿掉即可。 -->
  <label>結果
    <select id="filter-result" disabled title="快照索引尚無判定結果欄位，篩選暫停用">
      <option value="all">全部（尚無資料來源）</option>
    </select>
  </label>
  <label>日期起
    <input type="date" id="filter-from">
  </label>
  <label>日期迄
    <input type="date" id="filter-to">
  </label>
  <label>關鍵字（episode id）
    <input type="text" id="filter-search" placeholder="007">
  </label>
  <button type="button" id="filter-clear">清除</button>
</form>

<table id="episodes">
<thead>
<tr><th>Episode</th><th>類型</th><th>結果</th><th>首張時間</th><th>快照數</th></tr>
</thead>
<tbody>{rows}</tbody>
</table>
<p class="hint">顯示 <span id="match-count">—</span> 筆・點 Episode 進詳細頁（時間軸／快照／標註）；結果欄目前尚無資料來源。</p>

<script>
const typeF = document.getElementById('filter-type');
const resultF = document.getElementById('filter-result');
const searchF = document.getElementById('filter-search');
const fromF = document.getElementById('filter-from');
const toF = document.getElementById('filter-to');
const clearBtn = document.getElementById('filter-clear');
const countEl = document.getElementById('match-count');
function applyFilters() {{
  const t = typeF.value;
  const r = resultF.value;
  const q = searchF.value.trim().toLowerCase();
  // data-date 是 YYYY-MM-DD，跟 <input type="date"> 的 value 同格式，
  // 所以字串比較就等同日期比較（不必 parse）。空值＝不設限。
  const from = fromF.value;
  const to = toF.value;
  let shown = 0;
  for (const tr of document.querySelectorAll('#episodes tbody tr')) {{
    const d = tr.dataset.date || '';
    const okT = t === 'all' || tr.dataset.type === t;
    const okR = r === 'all' || tr.dataset.result === r;
    const okQ = !q || (tr.dataset.id || '').toLowerCase().includes(q);
    const okFrom = !from || (d && d >= from);
    const okTo = !to || (d && d <= to);
    const ok = okT && okR && okQ && okFrom && okTo;
    tr.classList.toggle('hidden', !ok);
    if (ok) shown++;
  }}
  if (countEl) countEl.textContent = shown + ' / ' + document.querySelectorAll('#episodes tbody tr').length;
}}
for (const el of [typeF, resultF, fromF, toF]) el.addEventListener('change', applyFilters);
searchF.addEventListener('input', applyFilters);
clearBtn.addEventListener('click', () => {{
  typeF.value = 'all'; resultF.value = 'all';
  searchF.value = ''; fromF.value = ''; toF.value = '';
  applyFilters();
}});
applyFilters();
</script>
</body>
</html>
"""


def render_annotate_html(
    episode_id: str,
    snapshot_path: str | None,
    rarity_choices: tuple[list[str], list[str]],
    queue: list[dict] | None = None,
) -> str:
    """P5 Task 7：標註工具 HTML（spec §5 C 區）。

    純函式：渲染單張 snapshot 的標註工具——pinch-zoom + 1:1 方形拖曳 +
    稀有度快選 toolbar + 症狀按鈕 + 礦物 / 事故欄位 +
    Submit（POST /api/annotate，JSON body 符合 ``validate_annotation`` schema）。

    rarity_choices = (tiers, variants)——``web_annotation.rarity_choices_from_game_data``
    撈出來的。**variants 自 2026-07-31 起不再渲染**（使用者：變體是礦物本身的屬性，
    對「外框長什麼樣」零資訊，每張多按一顆純粹罰站）；送出的 payload 固定
    ``variant: null``。參數形狀維持二元組，schema 也仍留著這個欄位——舊素材寫過。

    snapshot_path=None/"" 時不渲染 ``<img>``（viewer 顯示佔位文字）；其他 UI 不變。

    ``queue``（2026-07-28）＝``web_history.annotation_queue`` 回的 tier 佇列；
    非空時進「佇列模式」：底部顯示第幾 / 共幾張，`j`/`k` 上下張、數字鍵選看到
    什麼、`Enter` 送出並自動跳下一張。沒有這條連續動線，標註就永遠停在 2 張。

    2026-07-31：**玩家不再挑症狀，只回答「你看到什麼」**（ore/decoy/empty/
    unsure），症狀由它配上 `label_verdict` 推出來的 bot 判定算（
    `web_annotation.symptom_from_observation`）。舊的五顆症狀鍵裡有兩顆
    （誤判／該拒沒拒）只在 bot 已接受候選時成立，玩家得先知道 bot 接受了沒才選
    得對——而那件事 label 早就記著，連座標都有，頁面直接畫成黃圈給他看。
    """
    from .web_annotation import SYMPTOM_BY_OBSERVATION
    from .web_history import label_verdict

    tiers, _variants = rarity_choices   # 變體不再渲染（見 docstring）
    queue_mode = queue is not None       # []＝有進佇列模式但沒東西可標，要講清楚
    queue = list(queue or [])
    if queue and not snapshot_path:
        snapshot_path = queue[0].get("path") or ""
    tier_btns = "".join(
        f'<button type="button" data-tier="{_esc(t)}">{_esc(t)}</button>'
        for t in tiers
    )
    # ⚠ src 必須走 `/snapshot?path=`，**不能直接塞 snapshot_path**。
    # 舊版寫 `src="{snapshot_path}"`，那是 `C:\\Users\\...\\x.png` 這種 Windows 絕對
    # 路徑，瀏覽器會解析成 `file:///C:/...`——http 頁面載 file:// 一律被擋，
    # `naturalWidth` 恆為 0。連鎖後果不只是破圖：clientToNatural() 要除以
    # naturalWidth → NaN → selRect 永遠 null → 按「送出標註」永遠只回
    # 「請先在快照上拖曳出方形」，整個標註工具（spec §5 C）完全不能用。
    # `/snapshot` 這條 route 早就存在（episode 頁一直用得好好的），只有這裡沒接上。
    img_block = (
        f'<img id="snapshot" src="/snapshot?path={_url_q(snapshot_path)}" '
        f'alt="snapshot" draggable="false">'
        if snapshot_path
        else '<div class="placeholder">本 episode 無快照（請由 /history 選有快照的列）</div>'
    )
    img_basename = ""
    if snapshot_path:
        # 取 basename（POSIX/Windows 都用 split）; 用作 POST image 欄位——避免
        # /api/annotate 把絕對路徑當 category 前綴。
        img_basename = snapshot_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    img_basename_js = _js_str(img_basename)
    # source_path＝原始全幀路徑，POST 時一起送給 /api/annotate 用來裁出配對 PNG
    # （spec §5「每張 2 檔」）。server 端會走跟 /snapshot 同一份路徑守門，
    # 所以這裡送完整路徑是安全的——它本來就是 server 自己寫進 snapshot_index 的值。
    img_source_js = _js_str(snapshot_path or "")
    # 佇列每列附 bot 當下判定（verdict/mark_x/mark_y）——症狀就是靠它推的；
    # episode 讓稀有度在同一場內短暫固定（同一場多半是同一顆礦）。
    queue_js = json.dumps(
        [{"path": r.get("path", ""), "label": r.get("label", ""),
          "verdict": r.get("verdict"), "episode": r.get("episode"),
          "x": r.get("mark_x"), "y": r.get("mark_y")} for r in queue],
        ensure_ascii=False)
    # 單張模式（`?snapshot=`）沒有佇列列可抄，從檔名自己推——檔名尾端就是 label。
    init_verdict_js = json.dumps(
        label_verdict(img_basename.rsplit(".", 1)[0]), ensure_ascii=False)
    symptom_map_js = json.dumps(SYMPTOM_BY_OBSERVATION, ensure_ascii=False)
    if queue:
        queue_bar = ('<div id="queue-bar">佇列模式：<span id="queue-pos"></span>'
                     '　<code>j</code>/<code>k</code> 上下張・'
                     '<code>1</code>-<code>4</code> 選你看到什麼・'
                     '<code>Enter</code> 送出並跳下一張・'
                     '<code>Ctrl</code>+<code>Z</code> 還原上一張</div>')
    elif queue_mode:
        queue_bar = ('<div id="queue-bar" class="empty">佇列是空的——目前沒有'
                     '待標註的快照（掃描全空／框被拒／瞄準失敗／已接受的候選），'
                     '或全都標過了</div>')
    else:
        queue_bar = ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>MiningBot 標註工具</title>
<style>{NAV_CSS}
body {{ margin: 0; background: #1a1a1a; color: white; font-family: sans-serif;
       display: flex; flex-direction: column; height: 100vh; }}
header {{ padding: 0.5rem 1rem; background: #222; border-bottom: 1px solid #444;
         font-size: 0.9rem; }}
header code {{ background: #333; padding: 0.1rem 0.4rem; border-radius: 3px; }}
#main {{ flex: 1; display: flex; overflow: hidden; min-height: 0; }}
#viewer {{ flex: 1; position: relative; overflow: hidden; touch-action: none;
           background: #000; user-select: none; }}
#snapshot {{ transform-origin: 0 0; position: absolute; top: 0; left: 0;
             max-width: none; user-select: none; -webkit-user-drag: none; }}
#selection {{ position: absolute; border: 2px solid #ffe600; pointer-events: none;
              display: none; box-sizing: border-box;
              box-shadow: 0 0 0 9999px rgba(0,0,0,0.25); }}
.placeholder {{ color: #888; padding: 2rem; text-align: center; }}
.toolbar {{ width: 280px; padding: 0.8rem; background: #222; overflow-y: auto;
            border-left: 1px solid #444; font-size: 0.85rem; }}
.toolbar h2 {{ font-size: 0.9rem; margin: 0.8rem 0 0.3rem; color: #aaa;
              font-weight: normal; }}
.toolbar button {{ padding: 0.3rem 0.5rem; margin: 0.15rem 0.1rem; background: #333;
                  color: white; border: 1px solid #555; border-radius: 3px;
                  cursor: pointer; font-size: 0.85rem; }}
.toolbar button.active {{ background: #4d9fff; border-color: #4d9fff; }}
/* 症狀互斥（2026-07-31 使用者要求）：只有「1 有礦框」才標得了稀有度，
   其餘三個選項下整區鎖住並清空——先前只是送出時丟掉，畫面上還亮著，
   玩家以為自己標了。 */
.toolbar button:disabled {{ opacity: 0.35; cursor: not-allowed; }}
#tiers-lock:empty {{ display: none; }}
.submit:disabled {{ background: #444; cursor: not-allowed; }}
/* 整句白話（FN/FP 這種術語玩家看不懂），一行一顆才放得下 */
#observations button {{ display: block; width: 100%; margin: 0.2rem 0;
                        text-align: left; line-height: 1.35; }}
#observations .obs-hint {{ font-size: 0.72rem; color: #999; line-height: 1.4;
                          margin: 0 0 0.5rem 0.1rem; }}
/* bot 當下判定：從 label 讀的（`sweep_accepted_dir4_947_520`），不是玩家猜的 */
#botline {{ font-size: 0.8rem; line-height: 1.4; padding: 0.4rem 0.5rem;
           border-radius: 3px; background: #2b2b16; color: #e8e08a; }}
#botline.rejected {{ background: #16262b; color: #9fd2e0; }}
#botline.unknown {{ background: #2b2b2b; color: #aaa; }}
#derived {{ font-size: 0.8rem; color: #bbb; margin: 0.5rem 0 0; }}
#derived b {{ color: #fff; }}
#sticky-note {{ font-size: 0.75rem; color: #8fbf9c; margin: 0.4rem 0 0;
               line-height: 1.4; }}
/* bot 接受／看到的位置：畫面座標固定大小，縮放時不跟著變小才找得到 */
#botmark {{ position: absolute; width: 28px; height: 28px; margin: -14px 0 0 -14px;
           border: 2px solid #ffe600; border-radius: 50%; pointer-events: none;
           display: none; box-shadow: 0 0 0 1px rgba(0,0,0,0.6); }}
.toolbar label {{ display: block; font-size: 0.8rem; margin-top: 0.5rem;
                  color: #aaa; }}
.toolbar input[type="text"] {{ width: 100%; padding: 0.3rem; background: #111;
                               color: white; border: 1px solid #555;
                               border-radius: 3px; box-sizing: border-box;
                               font-size: 0.85rem; }}
.submit {{ display: block; width: 100%; padding: 0.6rem; margin-top: 1rem;
           background: #4d9fff; color: white; border: none; border-radius: 4px;
           font-size: 0.95rem; cursor: pointer; }}
.hint {{ font-size: 0.75rem; color: #888; margin-top: 0.4rem; line-height: 1.4; }}
#status {{ padding: 0.4rem 1rem; background: #333; font-size: 0.8rem;
           min-height: 1.4rem; color: #ddd; }}
#queue-bar {{ padding: 0.35rem 1rem; background: #1f3b2a; font-size: 0.8rem;
             color: #bfe6cd; border-bottom: 1px solid #2c5240; }}
#queue-bar.empty {{ background: #3a3a3a; color: #aaa; }}
#queue-bar code {{ background: #14261c; padding: 0 0.25rem; border-radius: 3px; }}
</style>
</head>
<body>
{render_nav("/annotate")}
<header>
  <strong>MiningBot 標註工具</strong>　episode: <code>{_esc(episode_id)}</code>
</header>
{queue_bar}
<div id="main">
  <div id="viewer">
    {img_block}
    <div class="placeholder" id="done-note" style="display:none">
      沒有其他圖片了 ✓<br><span style="font-size:0.85em">標錯可按 Ctrl+Z 還原上一張</span>
    </div>
    <div id="selection"></div>
    <div id="botmark"></div>
  </div>
  <div class="toolbar">
    <h2>bot 當下判定</h2>
    <div id="botline"></div>

    <h2>你看到什麼</h2>
    <div id="observations">
      <button type="button" data-obs="ore">1　有礦框／追蹤目標</button>
      <p class="obs-hint">畫面裡真的有一個礦的追蹤框——框出它。</p>
      <button type="button" data-obs="decoy">2　有東西，但不是礦框</button>
      <p class="obs-hint">亮綠地形、裝備、UI 之類「長得像框」的東西——框出它。這種硬負樣本對調門檻最有用。</p>
      <button type="button" data-obs="empty">3　什麼都沒有</button>
      <p class="obs-hint">整張圖沒有目標也沒有像框的東西，不必框。</p>
      <button type="button" data-obs="unsure" class="active">4　不確定</button>
      <p class="obs-hint">看不出來、不想憑肉眼猜，之後有更多資訊再回頭標。</p>
    </div>
    <p id="derived"></p>

    <h2 id="tiers-head">稀有度（低 → 高）</h2>
    <p id="tiers-lock" class="obs-hint"></p>
    <div id="tiers">{tier_btns or '<span class="hint">（game_data 無 tier）</span>'}</div>
    <p id="sticky-note"></p>

    <button type="button" class="submit" id="submit">送出標註</button>
    <p class="hint">在快照上拖曳出方形（1:1）；Shift + 拖曳 = 平移；
    滾輪 / 雙指 = 縮放；Esc 清除方形；Ctrl + Z 還原上一張。</p>
  </div>
</div>
<div id="status">提示：看 bot 判定 → 選你看到什麼 → 框出來 → 送出</div>

<script>
const viewer = document.getElementById('viewer');
const img = document.getElementById('snapshot');
const sel = document.getElementById('selection');
const statusEl = document.getElementById('status');
const botmark = document.getElementById('botmark');
const botlineEl = document.getElementById('botline');
const derivedEl = document.getElementById('derived');

let zoom = 1.0;
let pan = [0, 0];
let selRect = null;       // {{ x, y, size }} in natural img coords
let activeTier = null;
// 選擇跨張記憶（2026-07-30）：大多數待標快照是「什麼都沒有」，玩家選過一次後
// 下一張直接帶上次的選擇，不必每張重選。localStorage 是瀏覽器原生、純前端、
// 免改後端。tier 不記——它是「畫面裡那個礦」的屬性，每張不同，
// 記了反而無聲套用錯誤稀有度。
const OBS_KEY = 'annotate.observation';
let activeObs = localStorage.getItem(OBS_KEY) || 'unsure';

// 症狀不由玩家挑：（你看到什麼 × bot 當下判定）推出來。這張表由 Python 端的
// web_annotation.SYMPTOM_BY_OBSERVATION 直接渲染下來，只有一份定義。
const SYMPTOM_BY_OBS = {symptom_map_js};
const SYMPTOM_LABELS = {{
  false_negative: '漏判（有框沒抓到）',
  false_positive: '誤判（抓了但那裡沒東西）',
  should_reject_failed: '該拒沒拒（抓到不是框的東西）',
  no_target: '確認空幀（真陰性）',
  unknown: '不確定',
}};
// bot 接受在哪但玩家沒框時的預設框大小（與 main._AUTO_FIXTURE_DEFAULT_SIZE 同值）
const BOT_MARK_SIZE = 50;
let bot = {init_verdict_js};   // {{ verdict: 'accepted'|'after'|'rejected'|null, x, y }}
// 稀有度短暫固定：同一場（episode）的連續幾張多半是同一顆礦，不必每張重選；
// 換場自動清空——跨場硬記會無聲把上一顆礦的稀有度套到別的礦上。
let curEpisode = null;
const stickyEl = document.getElementById('sticky-note');

// ── 佇列模式（2026-07-28）──────────────────────────────────────────────
// 一次把待標快照排成一串連續走完。沒有這條動線就永遠停在 2 張。
const queue = {queue_js};
let qIndex = 0;
let imageName = {img_basename_js};
let sourcePath = {img_source_js};
const queuePosEl = document.getElementById('queue-pos');
// 首張是 server 直接渲染的（queue[0]），curEpisode 要跟著起跑，否則在第一張選了
// 稀有度、按 j 到同一場的第二張就會被當成換場清掉。
if (queue.length) curEpisode = queue[0].episode || null;

function derivedSymptom() {{
  const column = SYMPTOM_BY_OBS[activeObs] || SYMPTOM_BY_OBS.unsure;
  // 只認 'accepted'；沒記判定的一律走 rejected 那欄（見 symptom_from_observation）
  return column[bot.verdict === 'accepted' ? 'accepted' : 'rejected'];
}}

function renderBotLine() {{
  if (!botlineEl) return;
  const at = (bot.x === null || bot.x === undefined)
    ? '' : `（黃圈 ${{bot.x}},${{bot.y}}）`;
  let text, cls;
  if (bot.verdict === 'accepted') {{
    text = `接受了這個候選${{at}}`; cls = '';
  }} else if (bot.verdict === 'after') {{
    // 採集成功／框消失之後才拍的畫面——沒有框是正常的，不是誤判。
    // 但框如果**還在**就是漏判證據，所以這張圖仍值得標。
    text = '事後畫面：這時 bot 認定框已經不在（採到了或框消失）'
         + '——看不到框是正常的；框還在才是問題';
    cls = 'rejected';
  }} else if (bot.verdict === 'rejected') {{
    text = at ? `看到候選但沒採信${{at}}` : '整張沒有任何候選';
    cls = 'rejected';
  }} else {{
    text = '這張沒記判定（當成沒接受處理）'; cls = 'unknown';
  }}
  botlineEl.textContent = text;
  botlineEl.className = cls;
  if (derivedEl) {{
    const s = derivedSymptom();
    derivedEl.innerHTML = '會記成：<b>'
      + (s ? SYMPTOM_LABELS[s] : '對照組——bot 判對了') + '</b>';
  }}
}}

// bot 判定的位置畫成黃圈：玩家一眼看到「bot 抓的是這裡」，才判得出那裡到底是
// 礦框、像礦的地形、還是空的——這正是舊版症狀 2 與 3 分不出來的原因。
function applyBotMark() {{
  if (!botmark) return;
  if (bot.x === null || bot.x === undefined) {{
    botmark.style.display = 'none';
    return;
  }}
  botmark.style.display = 'block';
  botmark.style.left = (pan[0] + bot.x * zoom) + 'px';
  botmark.style.top = (pan[1] + bot.y * zoom) + 'px';
}}

function renderQueuePos() {{
  if (!queuePosEl || !queue.length) return;
  queuePosEl.textContent = `第 ${{qIndex + 1}} / ${{queue.length}} 張　`
    + (queue[qIndex].label || '');
}}

function showQueueItem(i) {{
  if (!queue.length || !img) return;
  qIndex = (i + queue.length) % queue.length;
  const item = queue[qIndex];
  sourcePath = item.path;
  imageName = item.path.split('/').pop().split('\\\\').pop();
  img.src = '/snapshot?path=' + encodeURIComponent(item.path);
  selRect = null; sel.style.display = 'none';
  bot = {{ verdict: item.verdict, x: item.x, y: item.y }};
  resetToolbar(item.episode);  // 同一場沿用稀有度，換場清空
  renderBotLine();
  applyBotMark();
  renderQueuePos();
  setQueueDone(false);
}}

// 佇列走完＝真的沒有下一張了：把圖收掉並鎖住送出鍵。先前只改一行文字、圖還留在
// 畫面上，看起來跟「還有一張待標」一模一樣，再按一次 Enter 就是同一張重複標註
// （使用者 2026-07-31 回報）。Ctrl+Z 還原時再叫 setQueueDone(false) 復原。
function setQueueDone(done) {{
  const submitBtn = document.getElementById('submit');
  const doneNote = document.getElementById('done-note');
  if (submitBtn) submitBtn.disabled = !!done;
  if (img) img.style.display = done ? 'none' : '';
  if (doneNote) doneNote.style.display = done ? 'block' : 'none';
  if (done) {{
    selRect = null;
    sel.style.display = 'none';
    if (botmark) botmark.style.display = 'none';
    if (queuePosEl) queuePosEl.textContent = '已標完，沒有其他圖片了 ✓';
    statusEl.textContent = '沒有其他圖片了——標錯了可按 Ctrl+Z 還原上一張，'
      + '或重新整理看有沒有新快照';
  }}
}}
renderQueuePos();

function applyTransform() {{
  if (!img) return;
  img.style.transform = `translate(${{pan[0]}}px, ${{pan[1]}}px) scale(${{zoom}})`;
  applyBotMark();      // 黃圈跟著平移/縮放走，否則放大後指到別的地方
}}

// 預設顯示全圖（見「全 8 方位」這類 1920×1080 全幀）：naturalWidth/Height 遠
// 大於 #viewer 的顯示區，zoom=1 等於原始像素→畫面只看得到一角，每次都要手動
// 縮小才看得到全貌。改成 load 完就縮到「整張塞進 viewer」＋置中，需要細看再
// 自己滾輪/雙指放大。
function fitToView() {{
  if (!img || !img.naturalWidth || !img.naturalHeight) return;
  const vw = viewer.clientWidth, vh = viewer.clientHeight;
  if (!vw || !vh) return;
  zoom = Math.min(vw / img.naturalWidth, vh / img.naturalHeight);
  pan = [(vw - img.naturalWidth * zoom) / 2, (vh - img.naturalHeight * zoom) / 2];
  applyTransform();
}}
if (img) {{
  img.addEventListener('load', fitToView);
  if (img.complete && img.naturalWidth) fitToView();  // 首次載入時可能已經 cache 命中，load 事件不會再等
  else applyTransform();                               // 圖還沒到之前先套預設值，避免 transform 是空字串
}}

// ── wheel zoom（桌機） ────────────────────────────────────────────────
viewer.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const f = e.deltaY > 0 ? 0.9 : 1.1;
  zoom = Math.max(0.2, Math.min(8.0, zoom * f));
  applyTransform();
}}, {{ passive: false }});

// ── 雙指 pinch zoom（手機） ───────────────────────────────────────────
let pinchInitDist = null;
let pinchInitZoom = null;
viewer.addEventListener('touchstart', (e) => {{
  if (e.touches.length === 2) {{
    pinchInitDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY);
    pinchInitZoom = zoom;
  }}
}});
viewer.addEventListener('touchmove', (e) => {{
  if (e.touches.length === 2 && pinchInitDist !== null) {{
    e.preventDefault();
    const d = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY);
    zoom = Math.max(0.2, Math.min(8.0, pinchInitZoom * (d / pinchInitDist)));
    applyTransform();
  }}
}}, {{ passive: false }});
viewer.addEventListener('touchend', (e) => {{
  if (e.touches.length < 2) {{
    pinchInitDist = null;
    pinchInitZoom = null;
  }}
}});

// ── 拖曳：單指畫方形 / Shift + 單指 = 平移 ──────────────────────────
let pointerStart = null;     // [clientX, clientY, naturalX, naturalY, isPan]
let dragging = false;

function clientToNatural(clientX, clientY) {{
  const rect = img.getBoundingClientRect();
  // rect 是 transform 後的顯示 bbox；natural 寬 = img.naturalWidth
  const nx = (clientX - rect.left) * (img.naturalWidth / rect.width);
  const ny = (clientY - rect.top) * (img.naturalHeight / rect.height);
  return [nx, ny];
}}

viewer.addEventListener('pointerdown', (e) => {{
  if (!img) return;
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const [nx, ny] = clientToNatural(e.clientX, e.clientY);
  const isPan = e.shiftKey || (e.pointerType === 'touch' && e.touches && e.touches.length === 2);
  pointerStart = [e.clientX, e.clientY, nx, ny, isPan];
  dragging = false;
  if (isPan) viewer.setPointerCapture(e.pointerId);
}});

viewer.addEventListener('pointermove', (e) => {{
  if (!img || !pointerStart) return;
  const dx = e.clientX - pointerStart[0];
  const dy = e.clientY - pointerStart[1];
  if (Math.abs(dx) + Math.abs(dy) > 4) dragging = true;
  if (!dragging) return;

  if (pointerStart[4]) {{  // pan：直接用 movementX/Y（pointer events 標準欄位）
    pan[0] += (e.movementX || 0);
    pan[1] += (e.movementY || 0);
    applyTransform();
    return;
  }}

  // 畫 1:1 方形——以 pointerdown 起點為中心；size = max(|dx|, |dy|) * 2
  const [sx, sy] = [pointerStart[2], pointerStart[3]];
  const sizeDisp = Math.max(Math.abs(dx), Math.abs(dy)) * 2;
  const rect = img.getBoundingClientRect();
  const scaleDisp = rect.width / img.naturalWidth;
  // #selection 是相對 #viewer 絕對定位，但圖片本身被 translate(pan) 位移過。
  // 舊版只算 sx * scaleDisp（圖片內部座標），沒加上圖片在 viewer 內的偏移，
  // 所以只要平移過畫面，黃框就會整個偏掉 pan 的量。用兩者的 rect 差取偏移，
  // 對 pan 與 zoom 都成立（不必自己重推 transform）。
  const vrect = viewer.getBoundingClientRect();
  const originX = rect.left - vrect.left;
  const originY = rect.top - vrect.top;
  const dispX = originX + sx * scaleDisp;
  const dispY = originY + sy * scaleDisp;
  sel.style.display = 'block';
  sel.style.left = (dispX - sizeDisp / 2) + 'px';
  sel.style.top = (dispY - sizeDisp / 2) + 'px';
  sel.style.width = sizeDisp + 'px';
  sel.style.height = sizeDisp + 'px';
}});

viewer.addEventListener('pointerup', (e) => {{
  if (!img || !pointerStart) {{ pointerStart = null; dragging = false; return; }}
  if (dragging && !pointerStart[4]) {{
    const rect = img.getBoundingClientRect();
    const sizeDisp = parseFloat(sel.style.width) || 0;
    const sizeNat = Math.round(sizeDisp * (img.naturalWidth / rect.width));
    if (sizeNat >= 5) {{
      selRect = {{ x: pointerStart[2], y: pointerStart[3], size: sizeNat }};
      statusEl.textContent = `已標方形 (cx=${{Math.round(selRect.x)}}, `
        + `cy=${{Math.round(selRect.y)}}, size=${{selRect.size}})`;
    }} else {{
      sel.style.display = 'none';
      selRect = null;
    }}
  }}
  if (pointerStart[4]) {{ try {{ viewer.releasePointerCapture(e.pointerId); }} catch (_) {{}} }}
  pointerStart = null;
  dragging = false;
}});
viewer.addEventListener('pointercancel', () => {{
  pointerStart = null; dragging = false;
}});

// Esc 清除方形；佇列模式另有 j/k/數字/Enter
// ⚠ 游標在文字欄裡時全部不攔。工具列現在沒有文字欄了（礦物/事故/類別已移除），
// 但守門留著——之後再加任何輸入框都不必重新想起這件事。
function typingInField(e) {{
  const t = e.target;
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'
                 || t.isContentEditable);
}}
document.addEventListener('keydown', (e) => {{
  if (typingInField(e)) return;
  if (e.key === 'Escape') {{
    sel.style.display = 'none';
    selRect = null;
    statusEl.textContent = '已清除方形';
    return;
  }}
  // Ctrl+Z 在佇列空掉之後仍要能用——標完最後一張才發現標錯是最常見的情形。
  if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {{
    undoLastSubmit();
    e.preventDefault();
    return;
  }}
  if (!queue.length) return;
  if (e.key === 'j') {{ showQueueItem(qIndex + 1); e.preventDefault(); }}
  else if (e.key === 'k') {{ showQueueItem(qIndex - 1); e.preventDefault(); }}
  else if (e.key === 'Enter') {{ submitAnnotation(); e.preventDefault(); }}
  else if (e.key >= '1' && e.key <= '4') {{
    const btns = document.querySelectorAll('#observations button');
    const b = btns[Number(e.key) - 1];
    if (b) {{ b.click(); e.preventDefault(); }}
  }}
}});

// ── toolbar：tier / observation 單選切換 ────────────────────────────
// tier 允許再點一次已選的按鈕取消（deselect）——先前點了就卡死選不掉，
// 玩家點錯稀有度或想改標「沒東西」都無法回到未選狀態。symptom 永遠要有現役值
// （預設「不確定」），不開放取消到空，佇列/送出邏輯都假設它恆不為 null。
function bindSingleSelect(containerId, setter, opts) {{
  const deselectable = !!(opts && opts.deselectable);
  const btns = document.querySelectorAll(`#${{containerId}} button`);
  btns.forEach((b) => {{
    b.addEventListener('click', () => {{
      if (deselectable && b.classList.contains('active')) {{
        b.classList.remove('active');
        setter(null);
        return;
      }}
      btns.forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      setter(b);
    }});
  }});
}}
bindSingleSelect('tiers', (b) => {{
  activeTier = b ? (b.dataset.tier || null) : null;
  renderSticky();
}}, {{ deselectable: true }});
bindSingleSelect('observations', (b) => {{
  activeObs = b.dataset.obs;
  localStorage.setItem(OBS_KEY, activeObs);  // 跨張記憶：下一張帶上來
  renderBotLine();                            // 推出來的症狀即時更新
  applyObsGating();                           // 非「有礦框」→ 稀有度鎖住並清空
}});

// 症狀與稀有度互斥（使用者 2026-07-31）：稀有度是「畫面裡那顆礦」的屬性，
// 玩家說看到的不是礦框（2/3/4）時它根本不成立。送出時本來就會丟掉，但畫面上
// 還亮著＝玩家以為自己標了；直接鎖住整區並清空選擇。
function applyObsGating() {{
  const isOre = activeObs === 'ore';
  document.querySelectorAll('#tiers button').forEach((b) => {{
    b.disabled = !isOre;
    if (!isOre) b.classList.remove('active');
  }});
  if (!isOre) activeTier = null;
  const lock = document.getElementById('tiers-lock');
  if (lock) lock.textContent = isOre ? '' : '（只有選「1 有礦框」時才標稀有度）';
  renderSticky();
}}

// 佇列翻頁時把 toolbar 選擇歸位（見 showQueueItem）：「看到什麼」帶上次的記憶
// （玩家選過 3「什麼都沒有」就固定住，不必每張重選）；稀有度**同一場沿用**
// ——同一個 episode 的連續幾張多半是同一顆礦的不同方位/幀，每張重選純粹是罰站
// （使用者 2026-07-31 要求）。換場（或單張模式）一律清空：跨場沿用會無聲把上一
// 顆礦的稀有度套到別的礦上，那是污染語料而不是省事。
function resetToolbar(episode) {{
  const ep = episode || null;
  if (ep === null || ep !== curEpisode) {{
    activeTier = null;
    document.querySelectorAll('#tiers button')
      .forEach((b) => b.classList.remove('active'));
  }}
  curEpisode = ep;
  activeObs = localStorage.getItem(OBS_KEY) || 'unsure';
  document.querySelectorAll('#observations button')
    .forEach((b) => b.classList.toggle('active', b.dataset.obs === activeObs));
  applyObsGating();
}}

function renderSticky() {{
  if (!stickyEl) return;
  if (!activeTier) {{
    stickyEl.textContent = curEpisode
      ? '選了稀有度後，同一場（' + curEpisode + '）的下一張會自動沿用'
      : '';
    return;
  }}
  stickyEl.textContent = '📌 沿用中：' + activeTier
    + '——換場自動清空，點同一顆按鈕可取消';
}}

// 首載入也要同步：HTML 裡 'unsure' 按鈕硬寫了 class="active"，但若 localStorage
// 記的是別的選擇，按鈕高亮跟 activeObs 會不一致。
document.querySelectorAll('#observations button')
  .forEach((b) => b.classList.toggle('active', b.dataset.obs === activeObs));
renderBotLine();
applyBotMark();
applyObsGating();

// ── 送出：POST /api/annotate（validate_annotation schema） ──────────
document.getElementById('submit').addEventListener('click', submitAnnotation);

// 「類別路徑」欄位已移除（2026-07-29）——玩家不會知道素材該進哪個資料夾。
// 從檔名自己認：回礦快照是 `…_reentry_ep<N>_…`，其餘都是追蹤框那條路。
// 先前那個欄位預設永遠是 aim，回礦素材只要玩家沒手動改就一律misfile。
function categoryFor(name) {{
  return /reentry_ep\\d+/.test(name || '') ? 'reentry/teleport_board' : 'aim';
}}

async function submitAnnotation() {{
  const symptom = derivedSymptom();
  // 框從哪來：玩家拖的優先；玩家說「什麼都沒有」但 bot 卻接受了（＝誤判），
  // 就用 bot 自己記的座標當框心——那塊裁圖正是要拿去調門檻的硬負樣本，
  // 而叫玩家去框一個「他說不存在的東西」是矛盾的。
  let annotation = null;
  if (selRect) {{
    annotation = {{
      type: 'square',
      cx: Math.round(selRect.x),
      cy: Math.round(selRect.y),
      size: selRect.size,
    }};
  }} else if (symptom !== 'no_target'
             && bot.x !== null && bot.x !== undefined) {{
    annotation = {{ type: 'square', cx: bot.x, cy: bot.y, size: BOT_MARK_SIZE }};
  }}
  // no_target（人確認過的真陰性）走全幀存檔，不需要框；其餘一定要有框，
  // 不然素材只剩一份指不到裁圖的孤兒 json。
  if (symptom !== 'no_target' && !annotation) {{
    statusEl.textContent = '請先在快照上拖曳出方形（或選「什麼都沒有」）';
    return;
  }}
  // 稀有度是「畫面裡那個礦物」的屬性，只有玩家說看到礦框時才成立；其餘情況
  // 就算他先前點過也不送出去（applyObsGating 已經先清掉，這裡是第二道）。
  // variant 恆為 null：變體對外框長相零資訊，UI 已移除（2026-07-31）。
  const isOre = activeObs === 'ore';
  const payload = {{
    image: imageName,
    source_path: sourcePath,
    tier: isOre ? activeTier : null,
    variant: null,
    mineral: null,
    source: {{ kind: 'manual' }},
    observation: activeObs,       // 玩家原話；症狀是它推出來的，推導不可逆
    symptom: symptom,
    related_incident: null,
  }};
  if (symptom !== 'no_target') {{
    payload.annotation = annotation;
    payload.category = categoryFor(imageName);
  }}
  statusEl.textContent = '送出中…';
  try {{
    const r = await fetch('/api/annotate', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload),
    }});
    if (!r.ok) {{
      const err = await r.json().catch(() => ({{}}));
      throw new Error(err.error || ('HTTP ' + r.status));
    }}
    const data = await r.json().catch(() => ({{}}));
    statusEl.textContent = `已送出 ✓ ${{data.category || ''}}　` + verdictText(data.verdict);
    // 標過的就從佇列拿掉——不然下一輪又從第一張重來。Ctrl+Z 用：記下這張是從哪個
    // 位置拿掉的、後端把它寫去哪；單張模式（?snapshot=）沒有佇列列，item 記 null。
    const removed = queue.length ? queue.splice(qIndex, 1)[0] : null;
    undoStack.push({{ item: removed, index: qIndex, image: payload.image,
                     category: payload.category || null,
                     symptom: payload.symptom }});
    if (queue.length || removed) {{
      if (!queue.length) {{
        setQueueDone(true);
        return;
      }}
      showQueueItem(qIndex);
    }}
  }} catch (err) {{
    statusEl.textContent = '送出失敗：' + err.message;
  }}
}}

// ── Ctrl+Z：還原上一張標註（2026-07-31 使用者要求）──────────────────
// 「送出並跳下一張」按太快就會標錯，而素材一旦落地就進了語料與去重集合，
// 下次進佇列再也看不到那張圖。還原＝叫後端把 json/png 刪掉（去重集合跟著
// 消失），前端把它插回原位再顯示一次。堆疊可以一路往回退，不只一層。
const undoStack = [];
async function undoLastSubmit() {{
  const last = undoStack[undoStack.length - 1];
  if (!last) {{
    statusEl.textContent = '沒有可還原的標註';
    return;
  }}
  statusEl.textContent = '還原中…';
  try {{
    const r = await fetch('/api/annotate/undo', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ image: last.image, category: last.category,
                             symptom: last.symptom }}),
    }});
    if (!r.ok) {{
      const err = await r.json().catch(() => ({{}}));
      throw new Error(err.error || ('HTTP ' + r.status));
    }}
    undoStack.pop();
    if (last.item) {{
      const at = Math.min(last.index, queue.length);
      queue.splice(at, 0, last.item);
      showQueueItem(at);
    }} else {{
      setQueueDone(false);
    }}
    statusEl.textContent = '已還原 ↩ ' + last.image + '——重標一次';
  }} catch (err) {{
    statusEl.textContent = '還原失敗：' + err.message;
  }}
}}

// 即時回判決：標完當下就知道這張圖是不是真的暴露 bug，還是偵測器其實已經修好了。
// 沒有 verdict（偵測模組不可用）就只顯示存檔結果，不假裝有判決。
function verdictText(v) {{
  if (!v) return '（無現行判定）';
  const label = SYMPTOM_LABELS[v.your_label] || '沒問題';
  const parts = Object.entries(v.score || {{}}).map(([k, n]) => k + ' ' + n);
  const detail = parts.length ? '（' + parts.join('、') + '）' : '';
  const judged = v.detector === 'accepted' ? '接受' : '拒絕';
  const agree = v.agree === null ? '—' : (v.agree ? '✅ 一致' : '❌ 不一致');
  return `現行判：${{judged}}${{detail}}／你標：${{label}} → ${{agree}}`;
}}
</script>
</body>
</html>
"""


def render_episode_html(detail: dict, annotations: list[dict]) -> str:
    """episode 詳細頁（spec §5 B）：事件時間軸 + 快照縮圖按 label 分組 + 標註歷程。

    2026-07-26 補：`/api/episode/{id}` 這條 endpoint 從 P5 就存在，但**前端零使用**
    ——後端做了、前端沒接，跟 INTERVENTION_RESULT 同一型缺口。歷史頁先前直接跳
    `/annotate`，玩家永遠看不到「這一集到底發生了什麼」。

    detail：``web_history.load_episode_detail`` 回的 dict
    annotations：``web_history.list_annotations_for_episode`` 回的 list

    縮圖用 ``/snapshot?path=...`` 取圖（那條 route 也是這次才補的；先前 <img> 必破圖）。
    """
    ep_id = str(detail.get("harvest_id", ""))
    ep_type = str(detail.get("type", ""))
    # label 帶類型前綴（採#114 / 回#26）；ep_id 維持裸編號，標註連結要用它比對素材檔名。
    ep_label = str(detail.get("label") or ep_id)
    ep_type_label = str(detail.get("type_label") or ep_type)
    snaps = list(detail.get("snapshots", []))
    snaps.sort(key=lambda r: r.get("written_at") or 0)

    # 時間軸：一列一筆，時間 + label
    timeline = "".join(
        f'<li><span class="t">{_format_ts(r.get("written_at"))}</span>'
        f'<code>{_esc(r.get("label", "?"))}</code></li>'
        for r in snaps
    ) or '<li class="empty">此 episode 沒有快照紀錄</li>'

    # 縮圖按 label 分組（同一 label 常有 before/after 或多方位，擺一起才看得出對照）
    groups: dict[str, list[dict]] = {}
    for r in snaps:
        groups.setdefault(str(r.get("label", "?")), []).append(r)

    # 分組順序改按**標註優先序**，不再按字母（2026-07-26）：關鍵的排最上面。
    # 舊版 sorted(groups) 讓一整批成熟的東西（聊天框／背包／chill）夾在中間，
    # 真正要標的 sweep_empty / aim_overlay 散落各處。同 tier 內按最早時間排，
    # 讓同一輪掃描的八個方位維持 dir0→dir7 的自然順序。
    from miningbot.web_history import annotation_tier, ANNOTATION_TIER_LABELS

    def _group_key(label: str):
        first = min((r.get("written_at") or 0) for r in groups[label])
        return (annotation_tier(label), first, label)

    ordered_labels = sorted(groups, key=_group_key)

    # 每個 tier 一個**橫向流動網格**，而不是「一個 label 一個整寬區塊」。
    # 舊版 18 個 label ＝ 18 個堆疊區塊，一集要捲很久才看得完；改成 wrap 之後
    # 同一 tier 的圖全部排在一起，一眼掃得到。label 移到縮圖下方當說明，
    # 同 label 的多張（before/after）靠排序保持相鄰。
    tier_buckets: dict[int, list[str]] = {}
    for label in ordered_labels:
        cards = "".join(
            '<figure><a href="/annotate?episode={ep}&snapshot={q}" '
            'title="標註這張">'
            '<img loading="lazy" src="/snapshot?path={q}" alt="{lb}"></a>'
            '<figcaption><span class="lb">{lb}</span>{ts}</figcaption></figure>'.format(
                ep=_esc(ep_id),
                q=_url_q(str(r.get("path", ""))),
                lb=_esc(label),
                ts=_format_ts(r.get("written_at")),
            )
            for r in groups[label]
        )
        tier_buckets.setdefault(annotation_tier(label), []).append(cards)

    thumb_blocks = []
    for tier in sorted(tier_buckets):
        n = sum(len(groups[lb]) for lb in ordered_labels
                if annotation_tier(lb) == tier)
        thumb_blocks.append(
            f'<h3 class="tier t{tier}">{_esc(ANNOTATION_TIER_LABELS[tier])}'
            f'<span class="n">{n}</span></h3>'
            f'<div class="thumbs">{"".join(tier_buckets[tier])}</div>'
        )
    thumbs = "".join(thumb_blocks) or '<p class="empty">沒有快照可顯示</p>'

    ann_rows = "".join(
        f'<tr><td><code>{_esc(str(a.get("image", "")))}</code></td>'
        f'<td>{_esc(str(a.get("tier") or "—"))}</td>'
        f'<td>{_esc(str(a.get("variant") or "—"))}</td>'
        f'<td>{_esc(str(a.get("mineral") or "—"))}</td>'
        f'<td>{_esc(str(a.get("symptom") or "—"))}</td>'
        f'<td>{_esc(str(a.get("related_incident") or "—"))}</td></tr>'
        for a in annotations
    ) or ('<tr><td colspan="6" class="empty">尚無標註'
          '——點上面任一張縮圖開始標</td></tr>')

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>episode {_esc(ep_label)}</title>
<style>{NAV_CSS}
body {{ font-family: system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei",
              sans-serif; max-width: 1000px; margin: 0 auto 3rem;
       padding: 0 0.6rem; background: #0f1115; color: #e6e8ec;
       color-scheme: dark; }}
h1 {{ font-size: 1.15rem; margin: 0.8rem 0 0.2rem; font-weight: 600; }}
h2 {{ font-size: 0.95rem; margin: 1.6rem 0 0.4rem; color: #969ba6;
     border-bottom: 1px solid #2a2f38; padding-bottom: 0.2rem; }}
h3 {{ font-size: 0.85rem; margin: 0.8rem 0 0.3rem; color: #969ba6; }}
h3 .n {{ background: #21252e; border-radius: 999px; padding: 0 0.45rem;
        margin-left: 0.4rem; font-weight: normal; color: #969ba6; }}
/* tier 標題：把「該標哪些」講白，玩家不必自己記哪些 label 是成熟的 */
h3.tier {{ margin: 1.4rem 0 0.2rem; font-size: 0.9rem; font-weight: bold;
          color: #c8ccd4; border-bottom: 2px solid #2a2f38; padding-bottom: 0.25rem; }}
h3.tier.t0 {{ border-bottom-color: #e5534b; }}
h3.tier.t1 {{ border-bottom-color: #e08c3b; }}
h3.tier.t2 {{ border-bottom-color: #d9b02c; }}
h3.tier.t3 {{ border-bottom-color: #2a2f38; color: #6b7280; }}
.meta {{ color: #6b7280; font-size: 0.85rem; }}
ul.timeline {{ list-style: none; padding: 0; margin: 0;
              max-height: 16rem; overflow-y: auto; }}
ul.timeline li {{ display: flex; gap: 0.6rem; padding: 0.15rem 0;
                 font-size: 0.82rem; border-bottom: 1px solid #1a1d24; }}
ul.timeline .t {{ color: #6b7280; flex: 0 0 10.5rem; }}
ul.timeline code {{ color: #b8bcc6; }}
/* wrap 而不是單列橫捲：一集動輒 18~32 張，橫捲要一直拖才看得完下一張。 */
.thumbs {{ display: flex; flex-wrap: wrap; gap: 0.6rem; padding-bottom: 0.3rem; }}
.thumbs figure {{ margin: 0; flex: 0 0 auto; text-align: center; max-width: 320px; }}
.thumbs figcaption .lb {{ display: block; font-family: monospace;
              font-size: 0.68rem; color: #6b7280; word-break: break-all; }}
/* max-width 是必要的，不是美化：聊天裁圖是 1220×37 這種極端長寬比，只設
   height:110px 會把縮圖拉成 3629px 寬（2026-07-26 實測），一列要橫捲很久才看得完
   下一張。夾住寬度並 object-fit: contain 保持比例。 */
.thumbs img {{ height: 110px; max-width: 320px; object-fit: contain;
              border: 1px solid #2a2f38; border-radius: 4px;
              display: block; background: #171a21; }}
.thumbs figure:hover img {{ border-color: #4d9fff; }}
.thumbs figcaption {{ font-size: 0.7rem; color: #6b7280; margin-top: 0.15rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.35rem 0.4rem; border-bottom: 1px solid #2a2f38;
         text-align: left; font-size: 0.82rem; }}
th {{ background: #171a21; color: #969ba6; font-weight: 600; }}
td code {{ color: #b8bcc6; }}
.empty {{ color: #6b7280; }}
a {{ color: #6ab7ff; text-decoration: none; }}
a:hover {{ color: #8fc6ff; }}
</style>
</head>
<body>
{render_nav("/history")}
<h1>episode {_esc(ep_label)} <span class="meta">（{_esc(ep_type_label)}）</span></h1>
<p class="meta">{_format_ts(detail.get("first_ts"))}
  ~ {_format_ts(detail.get("last_ts"))}　快照 {detail.get("count", 0)} 張
  ・<a href="/history">← 回列表</a></p>

<h2>事件時間軸</h2>
<ul class="timeline">{timeline}</ul>

<h2>快照（依標註優先序，點縮圖去標註）</h2>
{thumbs}

<h2>玩家介入／標註歷程</h2>
<table>
<thead><tr><th>素材</th><th>tier</th><th>變體</th><th>礦物</th>
<th>症狀</th><th>關聯事故</th></tr></thead>
<tbody>{ann_rows}</tbody>
</table>
</body>
</html>
"""


def _url_q(s: str) -> str:
    """把字串 escape 成可放進 URL query 的值（同時對 HTML 屬性安全）。"""
    from urllib.parse import quote
    return _esc(quote(str(s), safe=""))


def _date_str(ts) -> str:
    """unix timestamp → "YYYY-MM-DD"（給 <input type=\"date\"> 直接字串比較）。"""
    if ts is None:
        return ""
    try:
        import time
        return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def _format_ts(ts) -> str:
    """把 unix timestamp（float/int）格式化成本地時間字串；None 回 '—'。"""
    if ts is None:
        return "—"
    try:
        import time
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return str(ts)


def _js_str(s: str) -> str:
    """把 Python 字串 embed 成 JS 字串實字面（單行、用單引號、escape）。

    用於 f-string 內直接放進 ``<script>`` 的 JS 字串常數（例如 image 檔名）。
    """
    import json
    return json.dumps(str(s), ensure_ascii=False)


_AGENT_PAGE_CSS = """
body { margin: 0; background: #101010; color: #ddd; font-family: monospace;
       font-size: 13px; }
h1 { font-size: 1rem; margin: 0.6rem 1rem; }
.meta { padding: 0 1rem 0.6rem; color: #999; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #333; padding: 0.25rem 0.4rem; text-align: left;
         vertical-align: top; }
th { background: #1c1c1c; position: sticky; top: 0; }
tr:nth-child(even) { background: #161616; }
td.note { color: #a08a4a; }
td.ok { color: #57f287; }
td.bad { color: #ed4245; }
a { color: #6ab7ff; }
"""


def render_failures_html(data: dict) -> str:
    """偵測失敗佇列（spec D4a）。**讀者是 agent，不是玩家：排版可以醜，資料要全。**

    每列＝一張 tier0 快照 + 現行偵測器判定 + 分數明細；沒有判決的那些照實寫出
    原因（全幀不是那支偵測器吃的格式），不假裝有答案。
    """
    rows = []
    for item in data.get("items", []):
        verdict = item.get("verdict")
        if verdict:
            cls = "ok" if verdict.get("detector") == "accepted" else "bad"
            score = "、".join(f"{k} {v}" for k, v in
                             (verdict.get("score") or {}).items()) or "—"
            judged = f'<td class="{cls}">{_esc(verdict.get("detector", ""))}</td>' \
                     f'<td>{_esc(score)}</td>'
        else:
            judged = (f'<td class="note">（無判決）</td>'
                      f'<td class="note">{_esc(item.get("verdict_note") or "")}</td>')
        path = item.get("path", "")
        rows.append(
            "<tr>"
            f'<td>{_esc(_format_ts(item.get("written_at")))}</td>'
            f'<td>{_esc(item.get("label", ""))}</td>'
            f"{judged}"
            f'<td><a href="/snapshot?path={_url_q(path)}">圖</a>　'
            f'<a href="/annotate?snapshot={_url_q(path)}">標註</a></td>'
            f'<td>{_esc(path)}</td>'
            "</tr>")
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>MiningBot 偵測失敗佇列</title>
<style>{NAV_CSS}{_AGENT_PAGE_CSS}</style></head>
<body>
{render_nav("/failures")}
<h1>偵測失敗佇列（tier0：掃描全空／框被拒／瞄準失敗）</h1>
<div class="meta">共 {data.get('total', 0)} 張，顯示 {data.get('shown', 0)} 張
（<code>?limit=</code> 可改，預設 {data.get('limit', 0)}）。
JSON：<a href="/api/failures">/api/failures</a></div>
<table>
<tr><th>時間</th><th>label</th><th>現行判</th><th>分數</th><th>連結</th><th>path</th></tr>
{"".join(rows)}
</table>
</body>
</html>
"""


def render_stats_html(data: dict) -> str:
    """「什麼最常爆」統計（spec D4b）。讀者一樣是 agent：排版可以醜，資料要全。"""
    rows = "".join(
        "<tr>"
        f'<td>{_esc(r["kind"])}</td>'
        f'<td>{r["today"]}</td><td>{r["week"]}</td><td>{r["total"]}</td>'
        "</tr>"
        for r in data.get("labels", []))
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><title>MiningBot 統計</title>
<style>{NAV_CSS}{_AGENT_PAGE_CSS}</style></head>
<body>
{render_nav("/stats")}
<h1>什麼最常爆（快照標籤聚合，按本週次數排序）</h1>
<div class="meta">今日 {_esc(data.get('today') or '—')}：
{data.get('total_today', 0)} 筆／本週（含今日往回 7 天）{data.get('total_week', 0)} 筆／
全部 {data.get('total', 0)} 筆。時間取自索引的 <code>written_at</code>，
不看目錄 mtime（LocalCache 的目錄時間會過期數小時）。
JSON：<a href="/api/stats">/api/stats</a></div>
<table>
<tr><th>種類</th><th>今日</th><th>本週</th><th>全部</th></tr>
{rows}
</table>
</body>
</html>
"""


def render_intervention_html() -> str:
    """P4 即時介入面板：pinch-zoom <img> + tap UI（與標註工具同渲染管線）。

    連 WebSocket → 收 INTERVENTION_NEEDED event → 顯示截圖 →
    玩家 pinch/scroll zoom + 點擊 → 送 fire_at / reentry_click 命令。
    """
    return _INTERVENTION_HTML.replace(
        "%(nav_css)s", NAV_CSS).replace(
        "%(nav)s", render_nav("/intervention"))


_INTERVENTION_HTML = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>MiningBot 介入面板</title>
<style>%(nav_css)s
body { margin: 0; background: #1a1a1a; color: white; font-family: sans-serif;
       display: flex; flex-direction: column; height: 100vh; }
header { padding: 0.4rem 0.8rem; background: #222; border-bottom: 1px solid #444;
         display: flex; justify-content: space-between; align-items: flex-start;
         gap: 0.6rem; }
#status { font-size: 0.85rem; color: #888; flex: 1; min-width: 0;
          white-space: pre-line; line-height: 1.4; }
/* 主體：左邊圖片全高、右邊側欄放所有按鍵——圖片不再被上方資訊列壓縮，
   按鈕直排變大更好點（同標註工具的佈局） */
#main { flex: 1; display: flex; overflow: hidden; min-height: 0; }
#container { flex: 1; position: relative; overflow: hidden; touch-action: none;
             background: #000; }
#side { width: 210px; flex: 0 0 auto; background: #222; border-left: 1px solid #444;
        overflow-y: auto; display: flex; flex-direction: column; gap: 0.35rem;
        padding: 0.4rem; box-sizing: border-box; }
#status-line { font-size: 0.72rem; color: #9ad; line-height: 1.4;
               padding: 0.2rem 0.3rem; background: #1a1a1a; border-radius: 4px; }
/* 遙控器：兩欄 grid，省垂直空間 */
#remote-bar { display: grid; grid-template-columns: 1fr 1fr; gap: 0.25rem; }
#remote-bar button { padding: 0.4rem 0.2rem; border: 0; border-radius: 6px;
                     background: #3a3a3a; color: #eee; font-size: 0.78rem;
                     cursor: pointer; text-align: center; }
/* 方位切換列（prev/dir/next/dots 一行） */
#nav-row { display: flex; gap: 0.3rem; align-items: center; justify-content: center; }
#dir-label { font-size: 0.85rem; font-weight: bold; min-width: 4rem; text-align: center; }
#nav-row button { padding: 0.35rem 0.6rem; border: 0; border-radius: 6px;
                  background: #3a3a3a; color: #eee; font-size: 0.85rem; cursor: pointer; }
#nav-row button:disabled { opacity: 0.35; cursor: default; }
/* 方位小圓點：置中、可換行 */
#dots { display: flex; gap: 0.2rem; justify-content: center; flex-wrap: wrap; }
#dots span { width: 0.5rem; height: 0.5rem; border-radius: 50%;
             background: #555; display: block; }
#dots span.on { background: #4d9fff; }
#dots span.seen { background: #888; }
/* 動作鍵：全寬直排，比水平 scroll 列大得多 */
#toolbar { display: flex; flex-direction: column; gap: 0.3rem; }
#toolbar button { display: block; width: 100%; padding: 0.6rem; border: 0;
                  border-radius: 6px; background: #3a3a3a; color: #eee;
                  font-size: 0.9rem; cursor: pointer; box-sizing: border-box; }
#toolbar button:disabled { opacity: 0.35; cursor: default; }
#toolbar button[hidden] { display: none; }
#toolbar button.act { background: #4a4a4a; }
#toolbar button.skip { background: #6d6d6d; }
#toolbar button.confirm { background: #1f7a3d; }
/* 與標註工具同一套渲染：原生 <img> + CSS transform，不做 canvas drawImage 重採樣 */
#snapshot { transform-origin: 0 0; position: absolute; top: 0; left: 0;
            max-width: none; user-select: none; -webkit-user-drag: none; }
#predict-mark { position: absolute; display: none; pointer-events: none;
                transform: translate(-50%, -50%);
                width: 44px; height: 44px; border: 3px solid #57f287;
                border-radius: 50%; box-shadow: 0 0 0 1px rgba(0,0,0,0.6); }
#predict-mark::before, #predict-mark::after {
  content: ''; position: absolute; background: #57f287; }
#predict-mark::before { width: 12px; height: 2px; top: 50%; left: 50%;
                        transform: translate(-50%, -50%); }
#predict-mark::after { width: 2px; height: 12px; top: 50%; left: 50%;
                       transform: translate(-50%, -50%); }
.pm-label { position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
            background: rgba(0,0,0,0.65); color: #57f287; font: bold 13px sans-serif;
            padding: 2px 8px; white-space: nowrap; margin-bottom: 4px;
            border-radius: 3px; }
.hint { padding: 0.3rem 1rem; background: #333; font-size: 0.8rem; color: #aaa; }
#note { padding: 0.3rem 1rem; background: #5a4a1e; font-size: 0.8rem;
        color: #ffe9b0; display: none; }
</style>
</head>
<body>
%(nav)s
<header>
  <strong>MiningBot 介入面板</strong>
  <span id="status">等待 bot 事件…</span>
</header>
<div id="main">
  <div id="container">
    <img id="snapshot" alt="">
    <div id="predict-mark"><span class="pm-label"></span></div>
  </div>
  <div id="side">
    <div id="status-line">連線中…</div>
    <div id="remote-bar">
      <button id="rc-resume" type="button" title="繼續挖礦（等同按 Q）">&#9654;&#65039; 繼續</button>
      <button id="rc-pause" type="button" title="暫停（等同 Ctrl+Q）">&#9208;&#65039; 暫停</button>
      <button id="rc-ability" type="button" title="遊戲內按一次 X">&#9889; 能力</button>
      <button id="rc-frame" type="button" title="看目前畫面">&#128247; 即時畫面</button>
      <button id="rc-reenter" type="button" title="手動觸發回礦">&#127968; 回礦</button>
      <button id="rc-clear" type="button" title="清空背包面板篩選框（避免路 B 假陽性）">&#129529; 清空</button>
    </div>
    <div id="toolbar">
      <div id="nav-row">
        <button id="prev" type="button" title="上一個方位">&#9664;</button>
        <span id="dir-label">&#8212;</span>
        <button id="next" type="button" title="下一個方位">&#9654;</button>
      </div>
      <span id="dots"></span>
      <button id="adopt" class="confirm" type="button" hidden title="直接送出 bot 猜的位置">&#127919; 採用建議</button>
      <button id="sweep" class="act" type="button" title="重新拍一輪八方位">&#10227; 重掃</button>
      <button id="reroll" class="act" type="button" title="換一個重生點">&#127922; 重骰</button>
      <button id="confirm" class="confirm" type="button" title="下礦沒問題，開挖">&#9989; 好</button>
      <button id="void" class="skip" type="button" title="這筆點擊資料有問題，作廢">&#128465; 作廢</button>
      <button id="skip" class="skip" type="button" title="放棄回礦，回正常挖礦">&#9197; 跳過</button>
    </div>
    <div id="note"></div>
    <p class="hint" id="hint">手機：雙指 pinch-zoom + 拖曳；桌機：滾輪縮放 + 拖曳。<b>直接點畫面上的傳送板</b>送出位置；有綠圈＝bot 猜的位置，按 &#127919; 採用建議一鍵送出</p>
  </div>
</div>

<script>
const snapshotImg = document.getElementById('snapshot');
const predictMark = document.getElementById('predict-mark');
const predictLabel = predictMark.querySelector('.pm-label');
const container = document.getElementById('container');
const statusEl = document.getElementById('status');
const noteEl = document.getElementById('note');
const dirLabel = document.getElementById('dir-label');
const dotsEl = document.getElementById('dots');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const adoptBtn = document.getElementById('adopt');
const sweepBtn = document.getElementById('sweep');
const rerollBtn = document.getElementById('reroll');
const confirmBtn = document.getElementById('confirm');
const voidBtn = document.getElementById('void');
const skipBtn = document.getElementById('skip');
const statusLineEl = document.getElementById('status-line');
const hintEl = document.getElementById('hint');
const rcResumeBtn = document.getElementById('rc-resume');
const rcPauseBtn = document.getElementById('rc-pause');
const rcAbilityBtn = document.getElementById('rc-ability');
const rcFrameBtn = document.getElementById('rc-frame');
const rcReenterBtn = document.getElementById('rc-reenter');
const rcClearBtn = document.getElementById('rc-clear');

let zoom = 1.0;         // 縮放倍率（fit-to-container 初始值 + 使用者 pinch/wheel）
let pan = [0, 0];       // 拖曳 pan（螢幕像素，與標註工具同模型）
let currentEvent = null;  // {flow, routing_key, summary, mode, frame_count}
let ws = null;

// 八方位圖：frames[i] = {img, dir}；pendingMeta 是「下一個 binary 屬於誰」。
// WebSocket 同一條連線保證順序，所以 meta 後面緊接著的那張就是它的圖。
let frames = [];
let pendingMeta = null;
let curFrame = 0;
let seen = new Set();
let pendingFrameSnapshot = false;  // 📷 即時畫面：下一張 binary 是單張快照，不進 frames[]
// 確認階段（回礦 awaiting_confirm）：畫面上是點擊處/落點證據圖，點它不會送出任何
// 東西——bot 主迴圈此刻在等 好/重骰/作廢，沒有人在收 reentry_click。
let confirmMode = false;

const CLICK_HINT = '手機：雙指 pinch-zoom + 拖曳；桌機：滾輪縮放 + 拖曳。直接點畫面上的傳送板送出位置；有綠圈＝bot 猜的位置，按 \\uD83C\\uDFAF 採用建議一鍵送出';
const CONFIRM_HINT = '這兩張是證據圖（點擊處／落點），可放大檢查——此時點畫面不會送出座標。確認後按下面的按鈕。';

const STATUS_COLORS = { need: '#f0b232', ok: '#57f287', fail: '#ed4245', idle: '#888' };
function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.style.color = STATUS_COLORS[kind] || STATUS_COLORS.idle;
}

// ── 通知：分頁標題閃爍 + 提示音 ──────────────────────────────────────────
// 玩家不會一直盯著這一頁。沒有這段，網頁介入等於「剛好有看到才有用」——
// 實機 2026-07-26 就是這樣白等到逾時。
const BASE_TITLE = 'MiningBot 介入面板';
let flashTimer = null;
function startFlashing(label) {
  stopFlashing();
  let on = false;
  flashTimer = setInterval(() => {
    on = !on;
    document.title = on ? ('\\u{1F534} ' + label) : BASE_TITLE;
  }, 1000);
}
function stopFlashing() {
  if (flashTimer) { clearInterval(flashTimer); flashTimer = null; }
  document.title = BASE_TITLE;
}
// 專心看著這一頁時不必再閃
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) stopFlashing();
});

// Web Audio 合成，不載外部音檔——CSP 擋掉所有外部資源，音檔一定會失敗。
// 瀏覽器自動播放限制：初次開頁時 AudioContext 被 suspended，beep() 丟不出去。
// 用 shared context ＋ unlock 模式：開頁時 try beep，被擋就排隊；使用者一碰
// 螢幕就 resume → 補一聲（開頁這個動作本身就是 gesture，但行動瀏覽器常拖到
// WebSocket 收到 INTERVENTION_NEEDED 時 gesture 已過，resume 無效）。
let _audioCtx = null;
let _beepQueued = false;

function _playBeep(ac) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.connect(gain); gain.connect(ac.destination);
  osc.frequency.value = 880;
  gain.gain.setValueAtTime(0.0001, ac.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.25, ac.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.45);
  osc.start();
  osc.stop(ac.currentTime + 0.5);
}

function beep() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    if (!_audioCtx) _audioCtx = new AC();
    if (_audioCtx.state === 'suspended') {
      _beepQueued = true;          // 等使用者碰一下螢幕再補
      return;
    }
    _playBeep(_audioCtx);
  } catch (e) { /* 標題閃爍仍在 */ }
}

// 解鎖音訊：第一次互動（點／按鍵）即 resume，補播佇列中的 beep
function _unlockAudio() {
  if (!_audioCtx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) _audioCtx = new AC();
  }
  if (_audioCtx && _audioCtx.state === 'suspended') {
    _audioCtx.resume().then(() => {
      if (_beepQueued) { _playBeep(_audioCtx); _beepQueued = false; }
    });
  } else if (_audioCtx && _beepQueued) {
    _playBeep(_audioCtx); _beepQueued = false;
  }
}
document.addEventListener('pointerdown', _unlockAudio);
document.addEventListener('keydown', _unlockAudio);

// 與標註工具同一套：img + CSS transform。瀏覽器原生解碼 PNG、單次縮放，
// 不像 canvas drawImage 會先重採樣到 backing store 再 CSS 縮放（兩次，手機糊）。
function applyTransform() {
  snapshotImg.style.transform = `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom})`;
  positionPredictMark();
}

// 預設縮到整張塞進容器——1920×1080 全幀 zoom=1 只看得到一角（同標註工具）
function fitToView() {
  if (!snapshotImg.naturalWidth || !snapshotImg.naturalHeight) return;
  const cw = container.clientWidth, ch = container.clientHeight;
  if (!cw || !ch) return;
  zoom = Math.min(cw / snapshotImg.naturalWidth, ch / snapshotImg.naturalHeight);
  // 置中（同 2026-07-27 letterbox 修正的精神：靠左貼齊在寬螢幕上黑邊全擠一邊）
  pan = [(cw - snapshotImg.naturalWidth * zoom) / 2,
         (ch - snapshotImg.naturalHeight * zoom) / 2];
  applyTransform();
}

// bot 猜的傳送板位置：固定大小的圓圈 overlay，不畫在圖上——推給網頁的那份跟原始
// 快照是同一批位元組，語料不可被疊圖污染。沒有預測就隱藏。
function positionPredictMark() {
  const p = currentPrediction();
  if (!p) { predictMark.style.display = 'none'; return; }
  predictMark.style.left = (pan[0] + p.x * zoom) + 'px';
  predictMark.style.top = (pan[1] + p.y * zoom) + 'px';
  predictMark.style.display = 'block';
  predictLabel.textContent = 'bot 猜這裡 ' + (p.score != null ? p.score.toFixed(2) : '');
}

function showCurrentFrame(i) {
  const f = frames[i];
  if (!f || !f.url) return;
  snapshotImg.src = f.url;      // load 事件 → fitToView + positionPredictMark
  seen.add(i);
  renderNav();
}

function currentPrediction() {
  const f = frames[curFrame];
  return (f && f.predict) || null;
}

function renderNav() {
  const n = frames.length;
  const multi = n > 1;
  prevBtn.disabled = !multi;
  nextBtn.disabled = !multi;
  // 沒有預測（偵測回空／分數低於門檻）時面板與舊行為逐項一致：不畫圈、不加鍵。
  adoptBtn.hidden = !(currentEvent && currentEvent.flow === 'reentry'
                      && currentPrediction());
  // 俯仰層前綴（2026-07-31）：手動瞄準改推 3 層 × 8 方位，只印「方位 3/24」的話
  // 玩家分不出手上這張是平視還是抬頭——而那正是他要挑的東西。
  const LAYER_TXT = {up: '抬頭層', mid: '平視層', down: '低頭層'};
  const curLayer = frames[curFrame] && frames[curFrame].layer;
  const layerTxt = (curLayer && LAYER_TXT[curLayer]) ? (LAYER_TXT[curLayer] + '・') : '';
  // label（2026-08-01）：確認階段推的是「點擊處／落點」兩張證據圖，標成
  // 「方位 1/2」玩家分不出哪張是哪張。有 label 就直接用它當標題。
  const curLabel = frames[curFrame] && frames[curFrame].label;
  dirLabel.textContent = n
    ? (curLabel ? (curLabel + ' ' + (curFrame + 1) + '/' + n)
       : (layerTxt + '方位 ' + ((frames[curFrame] && frames[curFrame].dir) || (curFrame + 1))
          + '/' + n))
    : '\\u2014';
  dotsEl.innerHTML = '';
  for (let i = 0; i < n; i++) {
    const d = document.createElement('span');
    if (i === curFrame) d.className = 'on';
    else if (seen.has(i)) d.className = 'seen';
    dotsEl.appendChild(d);
  }
}

function showFrame(i) {
  if (!frames.length) return;
  curFrame = (i + frames.length) % frames.length;
  // 換方位時把縮放/平移歸位——fitToView 在 img load 後重設
  zoom = 1.0; pan = [0, 0];
  showCurrentFrame(curFrame);
}

function loadImage(bytes, slot) {
  const blob = new Blob([bytes], { type: 'image/png' });
  const url = URL.createObjectURL(blob);
  // 預解碼：naturalWidth/Height 在 onload 後才有，fitToView 靠它算初始 zoom
  const pre = new Image();
  pre.onload = () => {
    if (!frames[slot]) return;
    frames[slot].url = url;
    frames[slot].natW = pre.naturalWidth;
    frames[slot].natH = pre.naturalHeight;
    if (slot === curFrame) showCurrentFrame(slot);
    renderNav();
  };
  pre.src = url;
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      // 📷 即時畫面優先判斷：跟候選/回礦的圖走不同顯示邏輯，不進 frames[]
      // （那是「翻頁看方位」用的陣列，即時畫面只有一張、也不該被當成候選點擊）。
      if (pendingFrameSnapshot) {
        pendingFrameSnapshot = false;
        // 清掉 currentEvent：這張圖跟任何介入流程無關，點下去不該誤送 fire_at/
        // reentry_click——sendClick 本來就會在 currentEvent 為空時擋下並提示。
        currentEvent = null;
        frames = [{ img: null, dir: null }];
        curFrame = 0; seen = new Set();
        zoom = 1.0; pan = [0, 0];  // 上一輪留下的放大不該帶進這張無關的即時畫面
        loadImage(e.data, 0);
        setStatus('📷 即時畫面（僅供查看，不能點擊送出）', 'idle');
        return;
      }
      // 有 meta＝八方位其中一張；沒有＝舊的單幀路徑（harvest 開火用）
      if (pendingMeta) {
        const slot = pendingMeta.index;
        frames[slot] = { img: null, dir: pendingMeta.dir, layer: pendingMeta.layer,
                         predict: pendingMeta.predict, label: pendingMeta.label };
        loadImage(e.data, slot);
        pendingMeta = null;
      } else {
        frames = [{ img: null, dir: 1 }];
        curFrame = 0; seen = new Set();
        zoom = 1.0; pan = [0, 0];  // 同上：新一輪開火幀不該繼承前一輪的縮放
        loadImage(e.data, 0);
      }
      return;
    }
    let msg;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    const p = (msg && msg.payload) || {};
    if (!msg || msg.type !== 'event') return;
    if (p.event === 'INTERVENTION_FRAME') {
      // p.index===0 是每一輪新事件的第一張——縮放/平移在這裡歸位，而不是等玩家
      // 翻頁時才靠 showFrame() 歸位；不然上一輪介入結束時留的放大倍率，會直接
      // 套在下一輪還沒看過的第一張圖上，玩家每次都得先手動縮小才看得到全貌。
      if (p.index === 0) { frames = []; seen = new Set(); curFrame = 0; zoom = 1.0; pan = [0, 0]; }
      pendingMeta = { index: p.index, dir: p.dir, layer: p.layer, total: p.total,
                      predict: p.predict, label: p.label };
    } else if (p.event === 'INTERVENTION_NEEDED') {
      currentEvent = p;
      const isReentry = p.flow === 'reentry';
      // mode==='confirm'（2026-08-01）＝這批是 awaiting_confirm 的證據圖（點擊處／
      // 落點），不是要玩家點位置的掃描圖。點畫面在這階段沒有消費端（主迴圈已離開
      // 等待迴圈），所以停掉點擊送出，並把按鈕換成 好/重骰/作廢。
      confirmMode = p.mode === 'confirm';
      setStatus((confirmMode ? '' : '需要介入：') + (p.summary || p.flow), 'need');
      noteEl.style.display = p.note ? 'block' : 'none';
      noteEl.textContent = p.note || '';
      hintEl.textContent = confirmMode ? CONFIRM_HINT : CLICK_HINT;
      // 回礦才有重掃/重骰/跳過；harvest 開火沒有等價路徑。好/作廢只在
      // awaiting_confirm 才出現（這裡的 confirm mode，或 INTERVENTION_RESULT 那支）。
      for (const b of [rerollBtn, skipBtn]) b.hidden = !isReentry;
      sweepBtn.hidden = !isReentry || confirmMode;
      confirmBtn.hidden = !confirmMode; voidBtn.hidden = !confirmMode;
      curFrame = 0;
      zoom = 1.0; pan = [0, 0];  // 保底：萬一這裡才是這輪第一次拿到 frames
      renderNav();       // 採用建議鍵由 renderNav 依「這張有沒有預測」決定顯不顯示
      if (frames.length) { curFrame = 0; showCurrentFrame(0); }
      startFlashing(p.summary || '需要介入');
      beep();
    } else if (p.event === 'INTERVENTION_RESULT') {
      // verdict 由 main._broadcast_intervention_result 給：
      //   harvest: fire_ok / fire_failed / fire_aborted / rejected_reset / skip / web_timeout
      //   reentry: descended / awaiting_confirm / still_surface / 放棄 / rejected_reset /
      //            轉向被吃 / web_escalate（玩家按 🔀 主動退回）/ web_aborted（礦坑重置／
      //            關閉／暫停中止；回礦已無逾時，2026-07-30 起不再有 web_timeout）
      const v = p.verdict || '';
      const ok = (v === 'fire_ok' || v === 'descended');
      // awaiting_confirm：Depth 已確認下礦，但 bot 設定要求人工放行才開挖——
      // 這不是「結束」也不是「失敗」，是換一組按鈕等玩家表態（好/重骰/作廢），
      // 原本這步只能切回 Discord 打字，玩家人已經在網頁上了不該被踢出去。
      const awaitingConfirm = v === 'awaiting_confirm';
      // 逾時／中止／主動切 Discord：這集之後這個頁面就不是主控了，跟 ok 一樣收起面板，
      // 不然玩家還以為能繼續點這批已經作廢的舊圖。
      const done = ok || v === 'web_timeout' || v === 'web_escalate' || v === 'web_aborted';
      setStatus(p.summary || v, awaitingConfirm ? 'need' : (ok ? 'ok' : 'fail'));
      stopFlashing();
      if (awaitingConfirm) {
        // 緊接著會來一批 mode='confirm' 的證據圖（點擊處／落點），那支會再設一次
        // 同樣的按鈕組；這裡先切好，圖還在路上時面板就已經是可以回答的狀態。
        confirmMode = true;
        hintEl.textContent = CONFIRM_HINT;
        adoptBtn.hidden = true; sweepBtn.hidden = true;
        rerollBtn.hidden = false; confirmBtn.hidden = false; voidBtn.hidden = false;
        skipBtn.hidden = false;
      } else if (done) {
        // 2026-08-01：介入結束要清掉畫面上的證據圖，不然面板「不會消失」、
        // 玩家以為還能點。清 frames + 空白 img + currentEvent=null（sendClick 擋）。
        currentEvent = null;
        confirmMode = false;
        frames = []; seen = new Set(); curFrame = 0;
        snapshotImg.removeAttribute('src');
        zoom = 1.0; pan = [0, 0];
        hintEl.textContent = CLICK_HINT;
        for (const b of [adoptBtn, sweepBtn, rerollBtn, confirmBtn, voidBtn,
                         skipBtn]) b.hidden = true;
        renderNav();
      }
    } else if (p.event === 'FRAME_SNAPSHOT') {
      pendingFrameSnapshot = true;   // 下一個 binary frame 是快照，見上面 ArrayBuffer 分支
    } else if (p.event === 'STATUS') {
      // 跟 Discord 遙控器 embed 同一份資料來源（main._status_snapshot）——
      // (paused, state) 一變就會廣播，這裡只是換一種排版顯示。
      const up = p.uptime_s || 0;
      const h = Math.floor(up / 3600), m = Math.floor((up % 3600) / 60);
      const s = p.stats || {}, r = p.radar || {};
      statusLineEl.textContent =
        `● ${p.state || '?'}${p.paused ? '（暫停）' : ''}　${p.last_action || ''}　`
        + `運行 ${h}h${String(m).padStart(2, '0')}m　音訊 ${(p.audio_score || 0).toFixed(2)}　`
        + `boost ${s.boosts || 0}・刷新 ${s.rerolls || 0}・稀有 ${s.rares || 0}・卡住 ${s.stuck || 0}　`
        + `掃描${r.scan ? '開' : '關'}／削洞${r.cave ? '開' : '關'}`;
      rcResumeBtn.disabled = !p.paused && p.state !== 'NEEDS_HUMAN' && p.state !== 'RESET_WAIT';
      rcPauseBtn.disabled = !!p.paused;
    } else if (p.event === 'STATUS_NOTE') {
      setStatus(p.text || '', 'need');
    }
  };
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'command', payload: { cmd: 'request_status' } }));
  };
  ws.onclose = () => {
    setStatus('WebSocket 斷線，5s 後重連…', 'fail');
    setTimeout(connect, 5000);
  };
}

// 點擊送出（pointer 無拖曳時）
let pointerDownPos = null;
let didDrag = false;
container.addEventListener('pointerdown', (e) => {
  pointerDownPos = [e.clientX, e.clientY];
  didDrag = false;
});
container.addEventListener('pointermove', (e) => {
  if (pointerDownPos) {
    const dx = e.clientX - pointerDownPos[0];
    const dy = e.clientY - pointerDownPos[1];
    if (Math.abs(dx) + Math.abs(dy) > 5) didDrag = true;
  }
  if (pointerDownPos && didDrag && e.buttons > 0) {
    pan[0] += (e.movementX || 0);
    pan[1] += (e.movementY || 0);
    applyTransform();
  }
});
container.addEventListener('pointerup', (e) => {
  if (pointerDownPos && !didDrag) {
    sendClick(e.clientX, e.clientY);
  }
  pointerDownPos = null;
  didDrag = false;
});
container.addEventListener('pointercancel', () => {
  pointerDownPos = null;
  didDrag = false;
});

// 滾輪 zoom
container.addEventListener('wheel', (e) => {
  e.preventDefault();
  const factor = e.deltaY > 0 ? 0.9 : 1.1;
  zoom = Math.max(0.2, Math.min(8.0, zoom * factor));
  applyTransform();
}, { passive: false });

// 雙指 pinch（手機）— 簡化版，只認兩指距離變化
let pinchInitialDist = null;
let pinchInitialZoom = null;
container.addEventListener('touchstart', (e) => {
  if (e.touches.length === 2) {
    pinchInitialDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY,
    );
    pinchInitialZoom = zoom;
  }
});
container.addEventListener('touchmove', (e) => {
  if (e.touches.length === 2 && pinchInitialDist !== null) {
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY,
    );
    zoom = Math.max(0.2, Math.min(8.0, pinchInitialZoom * (dist / pinchInitialDist)));
    applyTransform();
  }
}, { passive: false });
container.addEventListener('touchend', () => {
  pinchInitialDist = null;
  pinchInitialZoom = null;
});

function sendClick(clientX, clientY) {
  if (!currentEvent) {
    setStatus('尚無 INTERVENTION_NEEDED 事件，忽略點擊', 'idle');
    return;
  }
  // 與標註工具同一條座標換算：getBoundingClientRect 反映 CSS transform，
  // rect.width = naturalWidth * zoom（顯示寬度），naturalWidth 是原圖解析度
  const rect = snapshotImg.getBoundingClientRect();
  const nativeX = Math.round((clientX - rect.left) * (snapshotImg.naturalWidth / rect.width));
  const nativeY = Math.round((clientY - rect.top) * (snapshotImg.naturalHeight / rect.height));
  sendClickNative(nativeX, nativeY);
}

// 「採用建議」與手動點擊共用這一段：送出的座標一定等於圈心，也不會長出第二套換算。
function sendClickNative(nativeX, nativeY) {
  if (!currentEvent) {
    setStatus('尚無 INTERVENTION_NEEDED 事件，忽略點擊', 'idle');
    return;
  }
  if (confirmMode) {
    // 確認階段沒有人在收 reentry_click（主迴圈在等 好/重骰/作廢），送了只會靜靜
    // 躺在 pending 裡等 TTL 過期——說清楚，別讓玩家以為自己已經重點了一次。
    setStatus('這是證據圖，點畫面不會送出；請按 好／重骰／作廢', 'need');
    return;
  }
  const cmd = currentEvent.flow === 'reentry' ? 'reentry_click' : 'fire_at';
  const ep_id = {};
  // routing_key = "harvest:007" 或 "reentry:26"
  const parts = currentEvent.routing_key.split(':', 2);
  const flow = parts[0];
  const epId = parts[1];
  if (flow === 'harvest') ep_id.harvest_id = epId;
  else ep_id.attempt_id = epId;
  const payload = Object.assign({ cmd, flow }, ep_id, { x: nativeX, y: nativeY });
  // 帶上方位：bot 收到後會先轉過去再點（面板顯示的是掃描/候選拍照當下的畫面）。
  // harvest 候選清單一張圖可能裝好幾個候選（同方位同層疊在一起），還要帶 layer
  // 讓 bot 知道除了轉方位還要不要調俯仰——沒帶就退回舊「當下畫面直接開火」行為。
  if (frames[curFrame]) {
    if (frames[curFrame].dir != null) payload.dir = frames[curFrame].dir;
    if (flow === 'harvest' && frames[curFrame].layer) payload.layer = frames[curFrame].layer;
  }
  ws.send(JSON.stringify({ type: 'command', payload }));
  const dirTxt = payload.dir ? ('方位 ' + payload.dir + ' 的 ') : '';
  setStatus('已送出' + dirTxt + '(' + nativeX + ', ' + nativeY + ')，等待 bot 執行…', 'need');
  stopFlashing();
}

// img 載入完 → fitToView（zoom/pan 重設）+ 預測圈定位
snapshotImg.addEventListener('load', () => { fitToView(); positionPredictMark(); });

function sendControl(cmd, label) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'command', payload: { cmd } }));
  setStatus('已送出' + label + '，等待 bot…', 'need');
  stopFlashing();
}

prevBtn.addEventListener('click', () => showFrame(curFrame - 1));
nextBtn.addEventListener('click', () => showFrame(curFrame + 1));
adoptBtn.addEventListener('click', () => {
  const p = currentPrediction();
  if (p) sendClickNative(p.x, p.y);
});
sweepBtn.addEventListener('click', () => sendControl('sweep', '重掃'));
rerollBtn.addEventListener('click', () => sendControl('reroll', '重骰'));
confirmBtn.addEventListener('click', () => {
  sendControl('confirm', '好');
  // 立刻清 currentEvent：送出與後端 descended 廣播之間若點畫面，sendClickNative
  // 仍會通過 currentEvent+confirmMode 雙閘送出 reentry_click。清掉就擋住（2026-08-01）。
  currentEvent = null;
  confirmMode = false;
  hintEl.textContent = CLICK_HINT;
  for (const b of [sweepBtn, rerollBtn, confirmBtn, voidBtn, skipBtn]) b.hidden = true;
});
voidBtn.addEventListener('click', () => sendControl('void', '作廢'));
skipBtn.addEventListener('click', () => {
  sendControl('skip', '跳過');
  currentEvent = null;
});
// 遙控器列（2026-07-28）：跟 Discord ▶️⏸️⚡📷🏠 對應，任何時候都能按，
// 不像上面那排要等 INTERVENTION_NEEDED 才出現。
rcResumeBtn.addEventListener('click', () => sendControl('resume', '繼續'));
rcPauseBtn.addEventListener('click', () => sendControl('pause', '暫停'));
rcAbilityBtn.addEventListener('click', () => sendControl('ability', '能力'));
rcFrameBtn.addEventListener('click', () => sendControl('request_frame', '即時畫面'));
rcReenterBtn.addEventListener('click', () => sendControl('reenter', '手動回礦'));
rcClearBtn.addEventListener('click', () => sendControl('clearpanel', '清空背包面板'));
// 鍵盤左右鍵切方位（桌機看八張圖時比點按鈕快）
window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') showFrame(curFrame - 1);
  else if (e.key === 'ArrowRight') showFrame(curFrame + 1);
});

for (const b of [sweepBtn, rerollBtn, confirmBtn, voidBtn, skipBtn]) b.hidden = true;
window.addEventListener('resize', () => { if (snapshotImg.naturalWidth) fitToView(); });
renderNav();
// 容器還沒展開（naturalWidth=0）時 fitToView 是 no-op；圖到逹 load 事件會自動呼叫
connect();
</script>
</body>
</html>
"""
