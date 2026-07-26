# `chat_icon/` — 聊天圖示開／關外觀判定（H047）

取代舊的輸入列提示字 OCR（見 [`../chat_ui/`](../chat_ui/README.md) 為何退役）。
判定看左上聊天圖示**內部補丁的灰度**：`vision.chat_icon_state`。

| 檔案 | 狀態 | 期望 |
|---|---|---|
| `h047_icon_open_solid.png` | 開：實心白泡泡 | `open` |
| `h047_icon_closed_hollow.png` | 關：空心白邊 | `closed` |
| `h047_icon_closed_hollow_badge11.png` | 關，且圖示上疊著未讀徽章「11」 | `closed`（徽章免疫） |

## 兩側夾

內部補丁灰度：**開 238..255 vs 關 81..87**。中間那段大 gap 判 `unknown`。

## unknown 絕不點擊

灰度落在兩側夾中間（例如礦坑重置的白閃過渡幀）一律回 `unknown`，**不做任何點擊**。
方向是刻意不對稱的：誤判「開」頂多維持現狀，誤判「關」點下去會把開著的聊天框關掉。
比照 `_ensure_player_list_closed` 的 toggle 安全方向。

徽章那張是必要的負樣本——未讀數字會蓋在圖示上，判定必須對它免疫，否則有人跟 bot 說話
就會讓開／關判定翻面。
