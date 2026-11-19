#!/usr/bin/env python3
"""
留守電の詐欺チェッカー：部品ごとの動作確認スクリプト（配線図 fraud_wiring.png と対応）

1つ配線するごとに、その部品だけテストする:
    python3 hw_test.py rgb      # RGB LED が 緑→黄→赤→青 と光る
    python3 hw_test.py seg      # 7セグに 0〜9 が順に出る
    python3 hw_test.py bar      # バーグラフが 0〜7 段階で伸び縮みする
    python3 hw_test.py button   # ボタンを押すと表示される
    python3 hw_test.py keypad   # 押したキーが表示される
    python3 hw_test.py all      # 全部まとめて（危険度のデモ）

Ctrl+C で終了。sudo は不要（gpiozero が使えれば動く）。
"""
import sys
import time
from gpiozero import RGBLED, OutputDevice, DigitalOutputDevice, Button

# ---------------- ピン割り当て（BCM番号） ----------------
SEG_SER, SEG_RCK, SEG_SCK = 21, 20, 16      # 左の74HC595（7セグ用）
BAR_SER, BAR_RCK, BAR_SCK = 12, 8, 25       # 右の74HC595（バーグラフ用）
RGB_R, RGB_G, RGB_B = 24, 23, 18
BUTTON_PIN = 26
KEY_ROWS = [4, 17, 27, 22]                  # キーパッド差し込み口 1〜4番
KEY_COLS = [5, 6, 13, 19]                   # キーパッド差し込み口 5〜8番
KEYS = [["1", "2", "3", "A"],
        ["4", "5", "6", "B"],
        ["7", "8", "9", "C"],
        ["*", "0", "#", "D"]]

# 7セグ：どのセグメントが 595 のどの出力(Q番号)につながっているか（配線図のオレンジ線）
SEG_TO_Q = {"c": 1, "d": 2, "e": 3, "g": 4, "f": 5, "a": 6, "b": 7}
DIGIT_SEGS = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg",
              5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg"}
# バーグラフ：48列から順に光らせる（配線図の紫線：48列=Q7 … 54列=Q1）
BAR_ORDER_Q = [7, 6, 5, 4, 3, 2, 1]


class ShiftRegister:
    """74HC595 1個を3本の線で動かす"""

    def __init__(self, ser, rck, sck):
        self.ser = OutputDevice(ser)
        self.rck = OutputDevice(rck)
        self.sck = OutputDevice(sck)

    def write(self, outputs):
        """outputs: 光らせたい Q番号の集合（例 {1, 3}）"""
        for q in range(7, -1, -1):          # Q7 から順に送ると、最後に Q0 まで並ぶ
            self.ser.value = q in outputs
            self.sck.on()
            self.sck.off()
        self.rck.on()                       # まとめて出力に反映
        self.rck.off()


class Panel:
    def __init__(self):
        self.seg = ShiftRegister(SEG_SER, SEG_RCK, SEG_SCK)
        self.bar = ShiftRegister(BAR_SER, BAR_RCK, BAR_SCK)
        self.rgb = RGBLED(RGB_R, RGB_G, RGB_B)

    def show_digit(self, n):
        if n is None:
            self.seg.write(set())
        else:
            self.seg.write({SEG_TO_Q[s] for s in DIGIT_SEGS[n]})

    def show_bar(self, level):
        level = max(0, min(7, level))
        self.bar.write(set(BAR_ORDER_Q[:level]))

    def show_risk(self, risk):
        """危険度 0〜9 を 7セグ・バーグラフ・RGB にまとめて表示"""
        self.show_digit(risk)
        self.show_bar(round(risk * 7 / 9))
        if risk <= 2:
            self.rgb.color = (0, 1, 0)       # 安全：緑
        elif risk <= 5:
            self.rgb.color = (1, 0.6, 0)     # 注意：黄
        else:
            self.rgb.color = (1, 0, 0)       # 危険：赤

    def clear(self):
        self.show_digit(None)
        self.show_bar(0)
        self.rgb.off()


class Keypad:
    def __init__(self):
        self.rows = [DigitalOutputDevice(p) for p in KEY_ROWS]
        self.cols = [Button(p, pull_up=False) for p in KEY_COLS]

    def read(self):
        pressed = []
        for r, row in enumerate(self.rows):
            row.on()
            time.sleep(0.001)
            for c, col in enumerate(self.cols):
                if col.is_pressed:
                    pressed.append(KEYS[r][c])
            row.off()
        return pressed


def test_rgb(p):
    for name, color in [("緑", (0, 1, 0)), ("黄", (1, 0.6, 0)), ("赤", (1, 0, 0)), ("青", (0, 0, 1))]:
        print("RGB:", name)
        p.rgb.color = color
        time.sleep(1)
    p.rgb.off()


def test_seg(p):
    while True:
        for n in range(10):
            print("7セグ:", n)
            p.show_digit(n)
            time.sleep(0.6)


def test_bar(p):
    while True:
        for lv in list(range(8)) + list(range(6, 0, -1)):
            p.show_bar(lv)
            time.sleep(0.25)


def test_button():
    b = Button(BUTTON_PIN, pull_up=True)
    print("ボタンを押してください")
    while True:
        b.wait_for_press()
        print("押された")
        b.wait_for_release()


def test_keypad():
    k = Keypad()
    last = []
    print("キーを押してください（押したキーと表示が違う場合は差し込み口の向きが逆）")
    while True:
        now = k.read()
        if now != last and now:
            print("押されたキー:", " ".join(now))
        last = now
        time.sleep(0.05)


def test_all(p):
    print("危険度 0→9 を順に表示します")
    for r in range(10):
        print("危険度", r)
        p.show_risk(r)
        time.sleep(0.8)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    panel = Panel() if mode in ("rgb", "seg", "bar", "all") else None
    try:
        if mode == "rgb":
            test_rgb(panel)
        elif mode == "seg":
            test_seg(panel)
        elif mode == "bar":
            test_bar(panel)
        elif mode == "button":
            test_button()
        elif mode == "keypad":
            test_keypad()
        elif mode == "all":
            test_all(panel)
        else:
            print(__doc__)
    except KeyboardInterrupt:
        pass
    finally:
        if panel:
            panel.clear()
