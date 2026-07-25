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
  // 換算 client → canvas 座標
  const rect = canvas.getBoundingClientRect();
  const cx = clientX - rect.left;
  const cy = clientY - rect.top;
  // canvas 顯示尺寸 = canvas_size（CSS pixel）
  const canvasSize = [rect.width, rect.height];
  // 送命令：cmd + flow + harvest_id/attempt_id + client_xy + canvas_size + zoom + pan_offset
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
      client_xy: [cx, cy],
      canvas_size: canvasSize,
      zoom, pan_offset: pan,
    },
  }));
  statusEl.textContent = `已送出點擊 (${Math.round(cx)}, ${Math.round(cy)}) — ${cmd}`;
}

window.addEventListener('resize', fitCanvas);
fitCanvas();
connect();
</script>
</body>
</html>
"""
