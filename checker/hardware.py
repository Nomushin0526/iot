"""LED・7セグ・バーグラフ・ボタン・キーパッドの制御 (gpiozero / lgpio)。

ピン割り当てとビット割り当ては CLAUDE.md の表に合わせている。変更したら両方を更新すること。
USE_HARDWARE=0 または gpiozero が実機ピンを使えない環境では MockFactory で動く (PCでの開発用)。
"""
import threading
import time

from gpiozero import Button, Device, DigitalOutputDevice, RGBLED

# ---------------------------------------------------------------- ピン (BCM)
SEG_SR = dict(ser=21, rck=20, sck=16)   # 74HC595 A: 7セグ
BAR_SR = dict(ser=12, rck=8, sck=25)    # 74HC595 B: バーグラフ (SPIは無効のままにする)
RGB_PINS = dict(red=24, green=23, blue=18)
NOTIFY_BUTTON = 26                      # もう片方はGND → pull_up=True
KEYPAD_ROWS = (4, 17, 27, 22)           # 出力
KEYPAD_COLS = (5, 6, 13, 19)            # 入力 (内部プルダウン)
KEYPAD_KEYS = (
    ("1", "2", "3", "A"),
    ("4", "5", "6", "B"),
    ("7", "8", "9", "C"),
    ("*", "0", "#", "D"),
)

# ---------------------------------------------------------------- 7セグ (5161AS, カソードコモン)
# 595の出力番号 → セグメント: Q1=c Q2=d Q3=e Q4=g Q5=f Q6=a Q7=b (Q0未使用)
SEG_TO_Q = {"a": 6, "b": 7, "c": 1, "d": 2, "e": 3, "f": 5, "g": 4}
GLYPHS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g", " ": "", "E": "adefg", "P": "abefg", "A": "abcefg", "b": "cdefg",
    "C": "adef", "d": "bcdeg", "F": "aefg", "#": "bcefg", "*": "abfg",
}
# バーグラフ: 1段目→7段目 = Q7, Q6, ..., Q1 (595側がアノード → HIGHで点灯)
BAR_ORDER_Q = (7, 6, 5, 4, 3, 2, 1)
BAR_LEVELS = len(BAR_ORDER_Q)

COLORS = {
    "green": (0, 1, 0),
    "yellow": (1, 0.6, 0),
    "red": (1, 0, 0),
    "blue": (0, 0, 1),
    "off": (0, 0, 0),
}


def glyph_bits(ch: str) -> int:
    """文字 → 595 に送る8ビット (bit i = Qi)。"""
    bits = 0
    for seg in GLYPHS.get(ch, GLYPHS["-"]):
        bits |= 1 << SEG_TO_Q[seg]
    return bits


def bar_bits(level: int) -> int:
    level = max(0, min(BAR_LEVELS, level))
    bits = 0
    for q in BAR_ORDER_Q[:level]:
        bits |= 1 << q
    return bits


def risk_to_bar(risk: int) -> int:
    """危険度 0〜9 → バーグラフ 0〜7 段。0 は消灯、9 は全点灯。"""
    return round(max(0, min(9, risk)) * BAR_LEVELS / 9)


def risk_to_color(risk: int) -> str:
    return "green" if risk <= 3 else "yellow" if risk <= 6 else "red"


def use_mock_pins() -> None:
    from gpiozero.pins.mock import MockFactory, MockPWMPin
    Device.pin_factory = MockFactory(pin_class=MockPWMPin)


# ---------------------------------------------------------------- 部品クラス
class ShiftRegister:
    """74HC595。Q7 から順に8ビット送って RCK を立ち上げると、最後に送ったビットが Q0 に入る。"""

    def __init__(self, ser: int, rck: int, sck: int):
        self.ser = DigitalOutputDevice(ser)
        self.rck = DigitalOutputDevice(rck)
        self.sck = DigitalOutputDevice(sck)
        self.value = 0

    def write(self, bits: int) -> None:
        self.rck.off()
        for q in range(7, -1, -1):
            self.ser.value = (bits >> q) & 1
            self.sck.on()
            self.sck.off()
        self.rck.on()   # 立ち上がりで出力に反映
        self.rck.off()
        self.value = bits & 0xFF

    def close(self) -> None:
        for d in (self.ser, self.rck, self.sck):
            d.close()


class Panel:
    """7セグ・バーグラフ・RGB LED をまとめた表示パネル。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.seg = ShiftRegister(**SEG_SR)
        self.bar = ShiftRegister(**BAR_SR)
        self.rgb = RGBLED(**RGB_PINS, active_high=True)
        self.clear()  # 電源投入直後の595の不定状態を消す

    def show_char(self, ch: str) -> None:
        with self._lock:
            self.seg.write(glyph_bits(ch))

    def show_bar(self, level: int) -> None:
        with self._lock:
            self.bar.write(bar_bits(level))

    def set_color(self, name: str) -> None:
        with self._lock:
            self.rgb.color = COLORS[name]

    def show_risk(self, risk: int) -> None:
        """危険度 0〜9 を 7セグ・バーグラフ・色で表示する。"""
        risk = max(0, min(9, int(risk)))
        with self._lock:
            self.seg.write(glyph_bits(str(risk)))
            self.bar.write(bar_bits(risk_to_bar(risk)))
            self.rgb.color = COLORS[risk_to_color(risk)]

    def busy(self) -> None:
        """判定中: 7セグ「-」、青点滅、バーグラフ消灯。"""
        with self._lock:
            self.seg.write(glyph_bits("-"))
            self.bar.write(0)
            self.rgb.blink(on_time=0.3, off_time=0.3, on_color=COLORS["blue"], background=True)

    def error(self) -> None:
        with self._lock:
            self.seg.write(glyph_bits("E"))
            self.bar.write(0)
            self.rgb.blink(on_time=0.15, off_time=0.15, on_color=COLORS["red"], background=True)

    def clear(self) -> None:
        with self._lock:
            self.seg.write(0)
            self.bar.write(0)
            self.rgb.off()

    def close(self) -> None:
        self.clear()
        self.seg.close()
        self.bar.close()
        self.rgb.close()


class NotifyButton:
    """短く押す → on_press (家族へ通知)。2秒長押し → on_hold (表示リセット)。"""

    def __init__(self, on_press, on_hold, hold_time: float = 2.0):
        self._held = False
        self.button = Button(NOTIFY_BUTTON, pull_up=True, hold_time=hold_time)
        self.button.when_held = self._when_held
        self.button.when_released = self._when_released
        self._on_press, self._on_hold = on_press, on_hold

    def _when_held(self):
        self._held = True
        self._on_hold()

    def _when_released(self):
        if not self._held:
            self._on_press()
        self._held = False

    def close(self):
        self.button.close()


class Keypad:
    """4×4 キーパッド。行を1本ずつHIGHにして、HIGHになった列を読む。"""

    def __init__(self, on_key, poll: float = 0.02):
        self.rows = [DigitalOutputDevice(p) for p in KEYPAD_ROWS]
        self.cols = [Button(p, pull_up=False) for p in KEYPAD_COLS]
        self._on_key = on_key
        self._poll = poll
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="keypad")

    def start(self):
        self._thread.start()

    def scan(self) -> str | None:
        for r, row in enumerate(self.rows):
            row.on()
            time.sleep(0.001)
            for c, col in enumerate(self.cols):
                if col.is_pressed:
                    row.off()
                    return KEYPAD_KEYS[r][c]
            row.off()
        return None

    def _loop(self):
        last = None
        while not self._stop.is_set():
            key = self.scan()
            if key and key != last:  # 押した瞬間だけ通知 (押しっぱなしは1回)
                try:
                    self._on_key(key)
                except Exception as e:  # キー処理の失敗でスキャンを止めない
                    print(f"[keypad] handler error: {e}")
            last = key
            time.sleep(self._poll)

    def close(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        for d in self.rows + self.cols:
            d.close()
