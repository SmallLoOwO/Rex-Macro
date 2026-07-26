"""網頁前端 HTML render（P3 玩家設定面板）。"""


def render_index_html(config) -> str:
    """4 個白名單欄位的設定表單 + JS 提交 fetch /api/config。

    純函式：吃 Config instance、回 HTML 字串。讀 4 個白名單欄位現值填入 form。
    """
    reentry_mode = getattr(config, "reentry_mode", "remote")
    target_layer = getattr(config, "reentry_target_layer", "")
    yaw_sample = getattr(config, "reentry_yaw_sample_sweep", False)
    sweep_pitch = getattr(config, "sweep_pitch_enabled", False)

    yaw_checked = "checked" if yaw_sample else ""
    sweep_checked = "checked" if sweep_pitch else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<title>MiningBot 玩家設定</title>
<style>
body {{ font-family: sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }}
label {{ display: block; margin: 1rem 0 0.3rem; font-weight: bold; }}
input, select {{ width: 100%; padding: 0.4rem; box-sizing: border-box; }}
button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; background: #0084ff; color: white;
         border: none; border-radius: 4px; cursor: pointer; }}
.status {{ margin-top: 1rem; padding: 0.6rem; background: #e6f4ff; border-radius: 4px;
          display: none; }}
.error {{ background: #ffe6e6; }}
</style>
</head>
<body>
<h1>MiningBot 玩家設定</h1>

<form id="settings-form">
  <label for="reentry_mode">回礦模式</label>
  <select id="reentry_mode" name="reentry_mode">
    <option value="off" {"selected" if reentry_mode == "off" else ""}>off（等人工）</option>
    <option value="remote" {"selected" if reentry_mode == "remote" else ""}>remote（Discord 點傳送板）</option>
    <option value="auto" {"selected" if reentry_mode == "auto" else ""}>auto（全自動）</option>
  </select>

  <label for="reentry_target_layer">目標層</label>
  <input type="text" id="reentry_target_layer" name="reentry_target_layer"
         value="{_esc(target_layer)}" placeholder="例：Mantle Layer">

  <label><input type="checkbox" id="reentry_yaw_sample_sweep" name="reentry_yaw_sample_sweep"
                {yaw_checked}>
    回礦後拍八方位（收語料）</label>

  <label><input type="checkbox" id="sweep_pitch_enabled" name="sweep_pitch_enabled"
                {sweep_checked}>
    掃描俯仰（失敗路徑掃上下層）</label>

  <button type="submit">儲存</button>
</form>

<div id="status" class="status"></div>

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
    rows = "".join(
        f'<tr data-id="{_esc(e.get("harvest_id", ""))}"'
        f' data-type="{_esc(e.get("type", ""))}"'
        f' data-result="{_esc(e.get("result", ""))}">'
        f'<td><a href="/annotate?episode={_esc(e.get("harvest_id", ""))}">'
        f'{_esc(e.get("harvest_id", ""))}</a></td>'
        f'<td>{_esc(e.get("type", ""))}</td>'
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
<style>
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
<h1>MiningBot 歷史紀錄</h1>

<form class="filters" id="filters" onsubmit="return false;">
  <label>類型
    <select id="filter-type">
      <option value="all">全部</option>
      <option value="harvest">採集</option>
      <option value="reentry">回礦</option>
    </select>
  </label>
  <label>結果
    <select id="filter-result">
      <option value="all">全部</option>
      <option value="success">成功</option>
      <option value="fail">失敗</option>
      <option value="unknown">未確認</option>
    </select>
  </label>
  <label>關鍵字（episode id）
    <input type="text" id="filter-search" placeholder="007">
  </label>
</form>

<table id="episodes">
<thead>
<tr><th>Episode</th><th>類型</th><th>結果</th><th>首張時間</th><th>快照數</th></tr>
</thead>
<tbody>{rows}</tbody>
</table>
<p class="hint">點 Episode 連到標註工具；結果欄目前尚無資料來源。</p>

<script>
const typeF = document.getElementById('filter-type');
const resultF = document.getElementById('filter-result');
const searchF = document.getElementById('filter-search');
function applyFilters() {{
  const t = typeF.value;
  const r = resultF.value;
  const q = searchF.value.trim().toLowerCase();
  for (const tr of document.querySelectorAll('#episodes tbody tr')) {{
    const okT = t === 'all' || tr.dataset.type === t;
    const okR = r === 'all' || tr.dataset.result === r;
    const okQ = !q || (tr.dataset.id || '').toLowerCase().includes(q);
    tr.classList.toggle('hidden', !(okT && okR && okQ));
  }}
}}
typeF.addEventListener('change', applyFilters);
resultF.addEventListener('change', applyFilters);
searchF.addEventListener('input', applyFilters);
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
    img_block = (
        f'<img id="snapshot" src="{_esc(snapshot_path)}" alt="snapshot" draggable="false">'
        if snapshot_path
        else '<div class="placeholder">本 episode 無快照（請由 /history 選有快照的列）</div>'
    )
    img_basename = ""
    if snapshot_path:
        # 取 basename（POSIX/Windows 都用 split）; 用作 POST image 欄位——避免
        # /api/annotate 把絕對路徑當 category 前綴。
        img_basename = snapshot_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    img_basename_js = _js_str(img_basename)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>MiningBot 標註工具</title>
<style>
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
  const dispX = sx * scaleDisp;
  const dispY = sy * scaleDisp;
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
    return """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>MiningBot 介入面板</title>
<style>
body { margin: 0; background: #1a1a1a; color: white; font-family: sans-serif;
       display: flex; flex-direction: column; height: 100vh; }
header { padding: 0.5rem 1rem; background: #222; border-bottom: 1px solid #444;
         display: flex; justify-content: space-between; align-items: center; }
#status { font-size: 0.9rem; color: #888; }
#container { flex: 1; position: relative; overflow: hidden; touch-action: none; }
canvas { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
.hint { padding: 0.3rem 1rem; background: #333; font-size: 0.8rem; color: #aaa; }
</style>
</head>
<body>
<header>
  <strong>MiningBot 介入面板</strong>
  <span id="status">等待 bot 事件…</span>
</header>
<div class="hint">手機：雙指 pinch-zoom + 拖曳；桌機：滾輪縮放 + 拖曳；點擊送出位置</div>
<div id="container">
  <canvas id="canvas"></canvas>
</div>

<script>
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const container = document.getElementById('container');
const statusEl = document.getElementById('status');

const CANVAS_NATIVE = [1920, 1080];
let scale = 1;          // fit-to-container 初始 scale
let zoom = 1.0;         // pinch/scroll zoom（疊加在 scale 之上）
let pan = [0, 0];       // 拖曳 pan（native 座標）
let currentEvent = null;  // {flow, routing_key, summary}
let ws = null;

function fitCanvas() {
  const cw = container.clientWidth;
  const ch = container.clientHeight;
  scale = Math.min(cw / CANVAS_NATIVE[0], ch / CANVAS_NATIVE[1]);
  redraw();
}

function redraw() {
  const totalScale = scale * zoom;
  canvas.style.width = (CANVAS_NATIVE[0] * totalScale) + 'px';
  canvas.style.height = (CANVAS_NATIVE[1] * totalScale) + 'px';
  canvas.style.transform = `translate(${-pan[0] * totalScale}px, ${-pan[1] * totalScale}px)`;
}

function showImage(pngBytes) {
  const blob = new Blob([pngBytes], { type: 'image/png' });
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = () => {
    canvas.width = CANVAS_NATIVE[0];
    canvas.height = CANVAS_NATIVE[1];
    ctx.drawImage(img, 0, 0, CANVAS_NATIVE[0], CANVAS_NATIVE[1]);
    URL.revokeObjectURL(url);
  };
  img.src = url;
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      showImage(e.data);
      return;
    }
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'event' && msg.payload?.event === 'INTERVENTION_NEEDED') {
      currentEvent = msg.payload;
      statusEl.textContent = `需要介入：${msg.payload.summary || msg.payload.flow}`;
    } else if (msg.type === 'ping') {
      // server heartbeat；用 ws.pong 不過 ws API 用不著，這裡 noop
    }
  };
  ws.onclose = () => {
    statusEl.textContent = 'WebSocket 斷線，5s 後重連…';
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
  // 拖曳 pan（pointer isDown + didDrag）
  if (pointerDownPos && didDrag && e.buttons > 0) {
    const totalScale = scale * zoom;
    pan[0] -= (e.movementX || 0) / totalScale;
    pan[1] -= (e.movementY || 0) / totalScale;
    redraw();
  }
});
container.addEventListener('pointerup', (e) => {
  if (pointerDownPos && !didDrag) {
    // tap：算原生座標送出
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
    statusEl.textContent = '尚無 INTERVENTION_NEEDED 事件，忽略點擊';
    return;
  }
  // P5 Task 1：client 端直接算原生座標（避免 server 處理 zoom/pan 座標空間 mismatch）
  // rect.width 是 transform 後的顯示寬度；canvas.width 是原生 1920
  const rect = canvas.getBoundingClientRect();
  const nativeX = Math.round((clientX - rect.left) * (canvas.width / rect.width));
  const nativeY = Math.round((clientY - rect.top) * (canvas.height / rect.height));
  // 送命令：cmd + flow + harvest_id/attempt_id + x + y（thin validator schema）
  const cmd = currentEvent.flow === 'reentry' ? 'reentry_click' : 'fire_at';
  const ep_id = {};
  // routing_key = "harvest:007" 或 "reentry:attempt_3"
  const [flow, epId] = currentEvent.routing_key.split(':', 2);
  if (flow === 'harvest') ep_id.harvest_id = epId;
  else ep_id.attempt_id = epId;
  ws.send(JSON.stringify({
    type: 'command',
    payload: {
      cmd, flow, ...ep_id,
      x: nativeX, y: nativeY,
    },
  }));
  statusEl.textContent = `已送出點擊 (${nativeX}, ${nativeY}) — ${cmd}`;
}

window.addEventListener('resize', fitCanvas);
fitCanvas();
connect();
</script>
</body>
</html>
"""
