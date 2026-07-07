"""Tests for miningbot.capture per-thread instance cache (pure logic).

`capture.grab` 的螢幕擷取本身 untested by design（無螢幕 CI 不能跑），但「每執行緒
快取 mss 實例、只建一次」是純邏輯——抽成 `_cached` 後可測，且不需 import mss
（factory 用計數器假物件）。鎖定兩個不變量：

1. **重用**：同一執行緒多次取用只呼叫 factory 一次（不再每幀重建 mss → 加速根據）。
2. **執行緒隔離**：不同執行緒各自獨立實例（mss 非執行緒安全；grab 會從主迴圈與
   熱鍵執行緒 _resume→init→_ensure_pickaxe 兩處呼叫，共享單一實例會壞）。
"""
import threading
from miningbot import capture


def test_cached_reuses_instance_on_same_thread():
    local = threading.local()
    count = []
    def factory():
        count.append(1)
        return object()

    a = capture._cached(local, "x", factory)
    b = capture._cached(local, "x", factory)

    assert a is b
    assert len(count) == 1, f"factory 應只被呼叫一次，實際 {len(count)} 次"


def test_cached_constructs_separate_instance_per_thread():
    local = threading.local()
    factory = lambda: object()
    other = {}

    def worker():
        other["obj"] = capture._cached(local, "x", factory)

    main_obj = capture._cached(local, "x", factory)
    t = threading.Thread(target=worker)
    t.start(); t.join()

    assert other["obj"] is not main_obj, "不同執行緒必須拿到各自獨立的實例"
