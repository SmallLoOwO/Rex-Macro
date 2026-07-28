"""網頁前端 HTML render（設定 / 介入 / 歷史 / episode 詳細 / 標註）。"""


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
)

NAV_CSS = """
.nav { display: flex; gap: 0.4rem; padding: 0.5rem; background: #1b1b1b;
       overflow-x: auto; border-bottom: 1px solid #333; }
.nav a { flex: 0 0 auto; padding: 0.45rem 0.9rem; border-radius: 999px;
         background: #2a2a2a; color: #ddd; text-decoration: none;
         font-size: 0.9rem; white-space: nowrap; }
.nav a.current { background: #0084ff; color: #fff; }
"""


def render_nav(current: str) -> str:
    """回導覽列 HTML。current 是當前路徑（例如 "/history"）。"""
    parts = []
    for href, label in _NAV_ITEMS:
        cls = ' class="current"' if href == current else ""
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
body {{ font-family: sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }}
label {{ display: block; margin: 1rem 0 0.3rem; font-weight: bold; }}
input, select {{ width: 100%; padding: 0.4rem; box-sizing: border-box; }}
/* checkbox 必須排除在 width:100% 之外（2026-07-26 實機回報）：被撐成整行寬之後，
   Chrome 把方塊畫在那一行的正中央，而 label 是 display:block，文字被擠到下一行
   ——視覺上變成「勾選方塊浮在自己的標籤文字上方置中」，看起來就是壞掉的版面。
   手機上更明顯。改成 inline-flex 讓方塊與文字同一行、點擊區維持整段文字。 */
label.check {{ display: flex; align-items: center; gap: 0.5rem;
              font-weight: bold; margin: 1rem 0 0.3rem; }}
label.check input[type="checkbox"] {{ width: auto; flex: 0 0 auto;
              margin: 0; padding: 0; transform: scale(1.3); }}
button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; background: #0084ff; color: white;
         border: none; border-radius: 4px; cursor: pointer; }}
.status {{ margin-top: 1rem; padding: 0.6rem; background: #e6f4ff; border-radius: 4px;
          display: none; }}
.error {{ background: #ffe6e6; }}
.hint {{ margin: 0.35rem 0 0; font-size: 0.8rem; color: #666; line-height: 1.5; }}
.hint code {{ background: #eee; padding: 0 0.25rem; border-radius: 3px; }}
.hint.warn {{ background: #fff6e0; border-left: 3px solid #e0a12c;
             padding: 0.4rem 0.6rem; color: #6a4c00; }}
.hint.ok {{ background: #eefaf0; border-left: 3px solid #3ba55d;
           padding: 0.4rem 0.6rem; color: #1f6b38; }}
h2 {{ margin-top: 2rem; border-top: 1px solid #ddd; padding-top: 1rem; font-size: 1.1rem; }}
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
    <b>代價</b>：每次撲空多花時間掃 2 圈，但能少掉一些「明明有礦卻回報全空」。</p>
  {sweep_status}

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
  const payload = {{
    reentry_mode: document.getElementById('reentry_mode').value,
    reentry_target_layer: document.getElementById('reentry_target_layer').value,
    reentry_yaw_sample_sweep: document.getElementById('reentry_yaw_sample_sweep').checked,
    sweep_pitch_enabled: document.getElementById('sweep_pitch_enabled').checked,
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
body {{ font-family: sans-serif; max-width: 900px; margin: 1rem auto;
       padding: 0 0.5rem; }}
h1 {{ font-size: 1.2rem; }}
.filters {{ display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 1rem 0;
            align-items: end; }}
.filters label {{ display: flex; flex-direction: column; font-size: 0.8rem;
                  color: #555; gap: 0.2rem; }}
.filters select, .filters input {{ padding: 0.3rem; font-size: 0.9rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.4rem 0.5rem; border-bottom: 1px solid #ddd;
         text-align: left; font-size: 0.9rem; }}
th {{ background: #f5f5f5; }}
tr.hidden {{ display: none; }}
a {{ color: #0084ff; text-decoration: none; }}
.hint {{ color: #888; font-size: 0.75rem; margin-top: 0.5rem; }}
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
) -> str:
    """P5 Task 7：標註工具 HTML（spec §5 C 區）。

    純函式：渲染單張 snapshot 的標註工具——pinch-zoom + 1:1 方形拖曳 +
    Rarity 快選 toolbar（tier / variant）+ 症狀按鈕 + 礦物 / 事故欄位 +
    Submit（POST /api/annotate，JSON body 符合 ``validate_annotation`` schema）。

    rarity_choices = (tiers, variants)——``web_annotation.rarity_choices_from_game_data``
    撈出來的；tiers 動態生成、variants 固定 ``["原色", "Spectral", "Ionized"]``。

    snapshot_path=None/"" 時不渲染 ``<img>``（viewer 顯示佔位文字）；其他 UI 不變。
    """
    tiers, variants = rarity_choices
    tier_btns = "".join(
        f'<button type="button" data-tier="{_esc(t)}">{_esc(t)}</button>'
        for t in tiers
    )
    variant_btns = "".join(
        f'<button type="button" data-variant="{_esc(v)}">{_esc(v)}</button>'
        for v in variants
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
.toolbar button.active {{ background: #0084ff; border-color: #0084ff; }}
.toolbar label {{ display: block; font-size: 0.8rem; margin-top: 0.5rem;
                  color: #aaa; }}
.toolbar input[type="text"] {{ width: 100%; padding: 0.3rem; background: #111;
                               color: white; border: 1px solid #555;
                               border-radius: 3px; box-sizing: border-box;
                               font-size: 0.85rem; }}
.submit {{ display: block; width: 100%; padding: 0.6rem; margin-top: 1rem;
           background: #0084ff; color: white; border: none; border-radius: 4px;
           font-size: 0.95rem; cursor: pointer; }}
.hint {{ font-size: 0.75rem; color: #888; margin-top: 0.4rem; line-height: 1.4; }}
#status {{ padding: 0.4rem 1rem; background: #333; font-size: 0.8rem;
           min-height: 1.4rem; color: #ddd; }}
</style>
</head>
<body>
{render_nav("/annotate")}
<header>
  <strong>MiningBot 標註工具</strong>　episode: <code>{_esc(episode_id)}</code>
</header>
<div id="main">
  <div id="viewer">
    {img_block}
    <div id="selection"></div>
  </div>
  <div class="toolbar">
    <h2>Rarity（Tier）</h2>
    <div id="tiers">{tier_btns or '<span class="hint">（game_data 無 tier）</span>'}</div>

    <h2>變體</h2>
    <div id="variants">{variant_btns}</div>

    <h2>症狀</h2>
    <div id="symptoms">
      <button type="button" data-symptom="false_negative">漏判 FN</button>
      <button type="button" data-symptom="false_positive">誤判 FP</button>
      <button type="button" data-symptom="should_reject_failed">該拒沒拒</button>
      <button type="button" data-symptom="unknown" class="active">不確定</button>
    </div>

    <label>礦物（可選）
      <input type="text" id="mineral" placeholder="例：Tin / Sapphire">
    </label>
    <label>相關事故（可選）
      <input type="text" id="related-incident" placeholder="例：H042 / H057">
    </label>
    <label>類別路徑（預設 aim）
      <input type="text" id="category" value="aim" placeholder="aim / reentry/teleport_board">
    </label>

    <button type="button" class="submit" id="submit">送出標註</button>
    <p class="hint">在快照上拖曳出方形（1:1）；Shift + 拖曳 = 平移；
    滾輪 / 雙指 = 縮放；Esc 清除方形。</p>
  </div>
</div>
<div id="status">提示：拖曳出方形 → 選 rarity / 症狀 → 送出</div>

<script>
const viewer = document.getElementById('viewer');
const img = document.getElementById('snapshot');
const sel = document.getElementById('selection');
const statusEl = document.getElementById('status');

let zoom = 1.0;
let pan = [0, 0];
let selRect = null;       // {{ x, y, size }} in natural img coords
let activeTier = null;
let activeVariant = null;
let activeSymptom = 'unknown';

function applyTransform() {{
  if (!img) return;
  img.style.transform = `translate(${{pan[0]}}px, ${{pan[1]}}px) scale(${{zoom}})`;
}}
if (img) applyTransform();

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

// Esc 清除方形
document.addEventListener('keydown', (e) => {{
  if (e.key === 'Escape') {{
    sel.style.display = 'none';
    selRect = null;
    statusEl.textContent = '已清除方形';
  }}
}});

// ── toolbar：tier / variant / symptom 單選切換 ──────────────────────
function bindSingleSelect(containerId, setter) {{
  const btns = document.querySelectorAll(`#${{containerId}} button`);
  btns.forEach((b) => {{
    b.addEventListener('click', () => {{
      btns.forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      setter(b);
    }});
  }});
}}
bindSingleSelect('tiers', (b) => {{ activeTier = b.dataset.tier || null; }});
bindSingleSelect('variants', (b) => {{
  const v = b.dataset.variant;
  activeVariant = (!v || v === '原色') ? null : v;
}});
bindSingleSelect('symptoms', (b) => {{ activeSymptom = b.dataset.symptom; }});

// ── 送出：POST /api/annotate（validate_annotation schema） ──────────
document.getElementById('submit').addEventListener('click', async () => {{
  if (!selRect) {{
    statusEl.textContent = '請先在快照上拖曳出方形';
    return;
  }}
  const mineral = document.getElementById('mineral').value.trim();
  const incident = document.getElementById('related-incident').value.trim();
  const category = document.getElementById('category').value.trim();
  const payload = {{
    image: {img_basename_js},
    source_path: {img_source_js},
    annotation: {{
      type: 'square',
      cx: Math.round(selRect.x),
      cy: Math.round(selRect.y),
      size: selRect.size,
    }},
    tier: activeTier,
    variant: activeVariant,
    mineral: mineral || null,
    source: {{ kind: 'manual' }},
    symptom: activeSymptom,
    related_incident: incident || null,
  }};
  if (category) payload.category = category;
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
    statusEl.textContent = `已送出 ✓ ${{data.category || ''}}`;
  }} catch (err) {{
    statusEl.textContent = '送出失敗：' + err.message;
  }}
}});
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
body {{ font-family: sans-serif; max-width: 1000px; margin: 0 auto 3rem;
       padding: 0 0.6rem; }}
h1 {{ font-size: 1.15rem; margin: 0.8rem 0 0.2rem; }}
h2 {{ font-size: 0.95rem; margin: 1.6rem 0 0.4rem; color: #444;
     border-bottom: 1px solid #ddd; padding-bottom: 0.2rem; }}
h3 {{ font-size: 0.85rem; margin: 0.8rem 0 0.3rem; color: #666; }}
h3 .n {{ background: #eee; border-radius: 999px; padding: 0 0.45rem;
        margin-left: 0.4rem; font-weight: normal; }}
/* tier 標題：把「該標哪些」講白，玩家不必自己記哪些 label 是成熟的 */
h3.tier {{ margin: 1.4rem 0 0.2rem; font-size: 0.9rem; font-weight: bold;
          color: #222; border-bottom: 2px solid #ddd; padding-bottom: 0.25rem; }}
h3.tier.t0 {{ border-bottom-color: #e5534b; }}
h3.tier.t1 {{ border-bottom-color: #e08c3b; }}
h3.tier.t2 {{ border-bottom-color: #d9b02c; }}
h3.tier.t3 {{ border-bottom-color: #ccc; color: #777; }}
.meta {{ color: #777; font-size: 0.85rem; }}
ul.timeline {{ list-style: none; padding: 0; margin: 0;
              max-height: 16rem; overflow-y: auto; }}
ul.timeline li {{ display: flex; gap: 0.6rem; padding: 0.15rem 0;
                 font-size: 0.82rem; border-bottom: 1px solid #f0f0f0; }}
ul.timeline .t {{ color: #888; flex: 0 0 10.5rem; }}
/* wrap 而不是單列橫捲：一集動輒 18~32 張，橫捲要一直拖才看得完下一張。 */
.thumbs {{ display: flex; flex-wrap: wrap; gap: 0.6rem; padding-bottom: 0.3rem; }}
.thumbs figure {{ margin: 0; flex: 0 0 auto; text-align: center; max-width: 320px; }}
.thumbs figcaption .lb {{ display: block; font-family: monospace;
              font-size: 0.68rem; color: #555; word-break: break-all; }}
/* max-width 是必要的，不是美化：聊天裁圖是 1220×37 這種極端長寬比，只設
   height:110px 會把縮圖拉成 3629px 寬（2026-07-26 實測），一列要橫捲很久才看得完
   下一張。夾住寬度並 object-fit: contain 保持比例。 */
.thumbs img {{ height: 110px; max-width: 320px; object-fit: contain;
              border: 1px solid #ccc; border-radius: 4px;
              display: block; background: #fafafa; }}
.thumbs figcaption {{ font-size: 0.7rem; color: #888; margin-top: 0.15rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.35rem 0.4rem; border-bottom: 1px solid #ddd;
         text-align: left; font-size: 0.82rem; }}
th {{ background: #f5f5f5; }}
.empty {{ color: #999; }}
a {{ color: #0084ff; text-decoration: none; }}
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


def render_intervention_html() -> str:
    """P4 即時介入面板：pinch-zoom canvas + tap UI。

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
header { padding: 0.5rem 1rem; background: #222; border-bottom: 1px solid #444;
         display: flex; justify-content: space-between; align-items: center;
         gap: 0.6rem; flex-wrap: wrap; }
#status { font-size: 0.9rem; color: #888; flex: 1 1 100%; }
/* 方位切換 + 動作鍵。回礦時傳送板通常不在當下視野內，所以面板必須讓玩家
   在八個方位之間翻找——這一列就是整個回礦網頁流程可用與否的關鍵。 */
#toolbar { display: flex; gap: 0.35rem; align-items: center; padding: 0.4rem 0.6rem;
           background: #262626; border-bottom: 1px solid #444;
           overflow-x: auto; }
#toolbar button { flex: 0 0 auto; padding: 0.45rem 0.7rem; border: 0;
                  border-radius: 6px; background: #3a3a3a; color: #eee;
                  font-size: 0.9rem; cursor: pointer; }
#toolbar button:disabled { opacity: 0.35; cursor: default; }
#toolbar button.act { background: #4a4a4a; }
#toolbar button.skip { background: #6d6d6d; }
#toolbar button.confirm { background: #1f7a3d; }
/* 遙控器列（2026-07-28）：跟 Discord 遙控器（▶️⏸️⚡📷🏠）同一套動作，任何時候都在，
   不像下面 #toolbar 那樣只在特定介入流程才出現——玩家隨時可能想暫停/看畫面。 */
#remote-bar { display: flex; gap: 0.35rem; align-items: center; padding: 0.4rem 0.6rem;
              background: #1f1f1f; border-bottom: 1px solid #444; overflow-x: auto; }
#remote-bar button { flex: 0 0 auto; padding: 0.4rem 0.6rem; border: 0; border-radius: 6px;
                     background: #3a3a3a; color: #eee; font-size: 0.85rem; cursor: pointer; }
#status-line { padding: 0.3rem 1rem; background: #262626; font-size: 0.78rem;
              color: #9ad; border-bottom: 1px solid #333; line-height: 1.5; }
#dir-label { flex: 0 0 auto; font-size: 0.95rem; font-weight: bold;
             min-width: 5.5rem; text-align: center; }
/* 方位小圓點：一眼看出總共幾張、現在第幾張、哪些已經看過 */
#dots { display: flex; gap: 0.25rem; flex: 0 0 auto; }
#dots span { width: 0.55rem; height: 0.55rem; border-radius: 50%;
             background: #555; display: block; }
#dots span.on { background: #0084ff; }
#dots span.seen { background: #888; }
#container { flex: 1; position: relative; overflow: hidden; touch-action: none; }
canvas { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
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
<div id="remote-bar">
  <button id="rc-resume" type="button" title="繼續挖礦（等同按 Q）">&#9654;&#65039; 繼續</button>
  <button id="rc-pause" type="button" title="暫停（等同 Ctrl+Q）">&#9208;&#65039; 暫停</button>
  <button id="rc-ability" type="button" title="遊戲內按一次 X">&#9889; 能力</button>
  <button id="rc-frame" type="button" title="看目前畫面">&#128247; 即時畫面</button>
  <button id="rc-reenter" type="button" title="手動觸發回礦">&#127968; 手動回礦</button>
</div>
<div id="status-line">連線中…</div>
<div id="toolbar">
  <button id="prev" type="button" title="上一個方位">&#9664;</button>
  <span id="dir-label">&#8212;</span>
  <button id="next" type="button" title="下一個方位">&#9654;</button>
  <span id="dots"></span>
  <button id="sweep" class="act" type="button" title="重新拍一輪八方位">&#10227; 重掃</button>
  <button id="reroll" class="act" type="button" title="換一個重生點">&#127922; 重骰</button>
  <button id="confirm" class="confirm" type="button" title="下礦沒問題，開挖">&#9989; 好</button>
  <button id="void" class="skip" type="button" title="這筆點擊資料有問題，作廢">&#128465; 作廢</button>
  <button id="skip" class="skip" type="button" title="放棄回礦，回正常挖礦">&#9197; 跳過</button>
</div>
<div id="note"></div>
<div class="hint">手機：雙指 pinch-zoom + 拖曳；桌機：滾輪縮放 + 拖曳。<b>直接點畫面上的傳送板</b>送出位置</div>
<div id="container">
  <canvas id="canvas"></canvas>
</div>

<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('container');
const statusEl = document.getElementById('status');
const noteEl = document.getElementById('note');
const dirLabel = document.getElementById('dir-label');
const dotsEl = document.getElementById('dots');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const sweepBtn = document.getElementById('sweep');
const rerollBtn = document.getElementById('reroll');
const confirmBtn = document.getElementById('confirm');
const voidBtn = document.getElementById('void');
const skipBtn = document.getElementById('skip');
const statusLineEl = document.getElementById('status-line');
const rcResumeBtn = document.getElementById('rc-resume');
const rcPauseBtn = document.getElementById('rc-pause');
const rcAbilityBtn = document.getElementById('rc-ability');
const rcFrameBtn = document.getElementById('rc-frame');
const rcReenterBtn = document.getElementById('rc-reenter');

const CANVAS_NATIVE = [1920, 1080];
let scale = 1;          // fit-to-container 初始 scale
let zoom = 1.0;         // pinch/scroll zoom（疊加在 scale 之上）
let pan = [0, 0];       // 拖曳 pan（native 座標）
let currentEvent = null;  // {flow, routing_key, summary, mode, frame_count}
let ws = null;

// 八方位圖：frames[i] = {img, dir}；pendingMeta 是「下一個 binary 屬於誰」。
// WebSocket 同一條連線保證順序，所以 meta 後面緊接著的那張就是它的圖。
let frames = [];
let pendingMeta = null;
let curFrame = 0;
let seen = new Set();
let pendingFrameSnapshot = false;  // 📷 即時畫面：下一張 binary 是單張快照，不進 frames[]

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

function beep() {
  // Web Audio 合成，不載外部音檔——CSP 擋掉所有外部資源，音檔一定會失敗。
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    const ac = new AC();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.connect(gain); gain.connect(ac.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ac.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ac.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 0.45);
    osc.start();
    osc.stop(ac.currentTime + 0.5);
    setTimeout(() => ac.close(), 1000);
  } catch (e) { /* 自動播放被瀏覽器擋：靜音即可，標題閃爍仍在 */ }
}

function fitCanvas() {
  const cw = container.clientWidth;
  const ch = container.clientHeight;
  scale = Math.min(cw / CANVAS_NATIVE[0], ch / CANVAS_NATIVE[1]);
  redraw();
}

function redraw() {
  const totalScale = scale * zoom;
  const dispW = CANVAS_NATIVE[0] * totalScale;
  const dispH = CANVAS_NATIVE[1] * totalScale;
  canvas.style.width = dispW + 'px';
  canvas.style.height = dispH + 'px';
  // 置中留白（2026-07-27 瀏覽器實測）：16:9 的畫面塞進非 16:9 的容器一定會留邊，
  // 舊版靠左上貼齊，寬螢幕上整塊黑邊集中在右側，看起來像圖沒載完。
  // 只在「比容器小」時置中；放大到超出容器時 offset 為 0，拖曳範圍不受影響。
  // 用 transform 而非 margin：getBoundingClientRect 會反映 transform，
  // sendClick 的座標換算因此自動跟著對，不必另外補償。
  const offX = Math.max(0, (container.clientWidth - dispW) / 2);
  const offY = Math.max(0, (container.clientHeight - dispH) / 2);
  canvas.style.transform =
    `translate(${offX - pan[0] * totalScale}px, ${offY - pan[1] * totalScale}px)`;
}

function drawFrame(i) {
  const f = frames[i];
  if (!f || !f.img) return;
  canvas.width = CANVAS_NATIVE[0];
  canvas.height = CANVAS_NATIVE[1];
  ctx.drawImage(f.img, 0, 0, CANVAS_NATIVE[0], CANVAS_NATIVE[1]);
  seen.add(i);
  renderNav();
  redraw();
}

function renderNav() {
  const n = frames.length;
  const multi = n > 1;
  prevBtn.disabled = !multi;
  nextBtn.disabled = !multi;
  dirLabel.textContent = n
    ? ('方位 ' + ((frames[curFrame] && frames[curFrame].dir) || (curFrame + 1)) + '/' + n)
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
  // 換方位時把縮放/平移歸位——放大看完某一角再切張，維持舊視窗只會看到一片放大的地面
  zoom = 1.0; pan = [0, 0];
  drawFrame(curFrame);
}

function loadImage(bytes, slot) {
  const blob = new Blob([bytes], { type: 'image/png' });
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = () => {
    if (frames[slot]) frames[slot].img = img;
    URL.revokeObjectURL(url);
    if (slot === curFrame) drawFrame(slot);
    renderNav();
  };
  img.src = url;
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
        loadImage(e.data, 0);
        setStatus('📷 即時畫面（僅供查看，不能點擊送出）', 'idle');
        return;
      }
      // 有 meta＝八方位其中一張；沒有＝舊的單幀路徑（harvest 開火用）
      if (pendingMeta) {
        const slot = pendingMeta.index;
        frames[slot] = { img: null, dir: pendingMeta.dir, layer: pendingMeta.layer };
        loadImage(e.data, slot);
        pendingMeta = null;
      } else {
        frames = [{ img: null, dir: 1 }];
        curFrame = 0; seen = new Set();
        loadImage(e.data, 0);
      }
      return;
    }
    let msg;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    const p = (msg && msg.payload) || {};
    if (!msg || msg.type !== 'event') return;
    if (p.event === 'INTERVENTION_FRAME') {
      if (p.index === 0) { frames = []; seen = new Set(); curFrame = 0; }
      pendingMeta = { index: p.index, dir: p.dir, layer: p.layer, total: p.total };
    } else if (p.event === 'INTERVENTION_NEEDED') {
      currentEvent = p;
      const isReentry = p.flow === 'reentry';
      setStatus('需要介入：' + (p.summary || p.flow), 'need');
      noteEl.style.display = p.note ? 'block' : 'none';
      noteEl.textContent = p.note || '';
      // 回礦才有重掃/重骰/跳過；harvest 開火沒有等價路徑。好/作廢只在
      // awaiting_confirm 才出現（INTERVENTION_RESULT 那支再開）。
      for (const b of [sweepBtn, rerollBtn, skipBtn]) b.hidden = !isReentry;
      confirmBtn.hidden = true; voidBtn.hidden = true;
      curFrame = 0;
      renderNav();
      if (frames.length) drawFrame(0);
      startFlashing(p.summary || '需要介入');
      beep();
    } else if (p.event === 'INTERVENTION_RESULT') {
      // verdict 由 main._broadcast_intervention_result 給：
      //   harvest: fire_ok / fire_failed / fire_aborted / rejected_reset / skip / web_timeout
      //   reentry: descended / awaiting_confirm / still_surface / 放棄 / rejected_reset /
      //            轉向被吃 / web_timeout（逾時退回 Discord）/ web_escalate（玩家按 🔀 主動退回）
      const v = p.verdict || '';
      const ok = (v === 'fire_ok' || v === 'descended');
      // awaiting_confirm：Depth 已確認下礦，但 bot 設定要求人工放行才開挖——
      // 這不是「結束」也不是「失敗」，是換一組按鈕等玩家表態（好/重骰/作廢），
      // 原本這步只能切回 Discord 打字，玩家人已經在網頁上了不該被踢出去。
      const awaitingConfirm = v === 'awaiting_confirm';
      // 逾時／主動切 Discord：這集之後這個頁面就不是主控了，跟 ok 一樣收起面板，
      // 不然玩家還以為能繼續點這批已經作廢的舊圖。
      const done = ok || v === 'web_timeout' || v === 'web_escalate';
      setStatus(p.summary || v, awaitingConfirm ? 'need' : (ok ? 'ok' : 'fail'));
      stopFlashing();
      if (awaitingConfirm) {
        sweepBtn.hidden = true;
        rerollBtn.hidden = false; confirmBtn.hidden = false; voidBtn.hidden = false;
        skipBtn.hidden = false;
      } else if (done) {
        currentEvent = null;
        for (const b of [sweepBtn, rerollBtn, confirmBtn, voidBtn, skipBtn]) b.hidden = true;
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
    const totalScale = scale * zoom;
    pan[0] -= (e.movementX || 0) / totalScale;
    pan[1] -= (e.movementY || 0) / totalScale;
    redraw();
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
  zoom = Math.max(0.5, Math.min(8.0, zoom * factor));
  redraw();
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
    zoom = Math.max(0.5, Math.min(8.0, pinchInitialZoom * (dist / pinchInitialDist)));
    redraw();
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
  // client 端直接算原生座標（避免 server 處理 zoom/pan 座標空間 mismatch）
  const rect = canvas.getBoundingClientRect();
  const nativeX = Math.round((clientX - rect.left) * (canvas.width / rect.width));
  const nativeY = Math.round((clientY - rect.top) * (canvas.height / rect.height));
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

function sendControl(cmd, label) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: 'command', payload: { cmd } }));
  setStatus('已送出' + label + '，等待 bot…', 'need');
  stopFlashing();
}

prevBtn.addEventListener('click', () => showFrame(curFrame - 1));
nextBtn.addEventListener('click', () => showFrame(curFrame + 1));
sweepBtn.addEventListener('click', () => sendControl('sweep', '重掃'));
rerollBtn.addEventListener('click', () => sendControl('reroll', '重骰'));
confirmBtn.addEventListener('click', () => {
  sendControl('confirm', '好');
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
// 鍵盤左右鍵切方位（桌機看八張圖時比點按鈕快）
window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') showFrame(curFrame - 1);
  else if (e.key === 'ArrowRight') showFrame(curFrame + 1);
});

for (const b of [sweepBtn, rerollBtn, confirmBtn, voidBtn, skipBtn]) b.hidden = true;
window.addEventListener('resize', fitCanvas);
renderNav();
fitCanvas();
connect();
</script>
</body>
</html>
"""
