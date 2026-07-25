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
