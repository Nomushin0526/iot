"""LED・7セグ・バーグラフ・ボタン・キーパッドの制御 (gpiozero / lgpio)。

ピン割り当てとビット割り当ては CLAUDE.md の表に合わせている。変更したら両方を更新すること。
USE_HARDWARE=0 または gpiozero が実機ピンを使えない環境では MockFactory で動く (PCでの開発用)。
"""
import os
import threading
import time

from gpiozero import Button, Device, DigitalOutputDevice

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
    # 黄は赤と緑を交互に点けて作る (SequentialRGB)。値は点灯時間の割合。
    # 実機で 0.3:1 は緑に見えたため赤を長めにしている (diag_display.py で確認)。RGB_YELLOW="1,0.25,0" のように環境変数で調整できる
    "yellow": tuple(float(x) for x in os.environ.get("RGB_YELLOW", "1,0.25,0").split(",")),
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


ALL_PINS = {
    **{f"7セグ用595 {k.upper()}": v for k, v in SEG_SR.items()},
    **{f"バーグラフ用595 {k.upper()}": v for k, v in BAR_SR.items()},
    **{f"RGB {k}": v for k, v in RGB_PINS.items()},
    "通知ボタン": NOTIFY_BUTTON,
    **{f"キーパッド行{i + 1}": p for i, p in enumerate(KEYPAD_ROWS)},
    **{f"キーパッド列{i + 1}": p for i, p in enumerate(KEYPAD_COLS)},
}


def find_busy_pins() -> list[str]:
    """どのピンが他のプログラム等に使われているか1本ずつ調べる (GPIO busy の原因究明用)。"""
    busy = []
    for name, pin in ALL_PINS.items():
        try:
            DigitalOutputDevice(pin).close()
        except Exception as e:
            hint = " ← SPIが有効だと使えない (raspi-config で SPI を無効に)" if pin in (7, 8, 9, 10, 11) else ""
            busy.append(f"GPIO{pin} ({name}): {e}{hint}")
    return busy


def use_mock_pins() -> None:
    from gpiozero.pins.mock import MockFactory, MockPWMPin
    Device.pin_factory = MockFactory(pin_class=MockPWMPin)


# ---------------------------------------------------------------- 部品クラス
class SequentialRGB:
    """RGB LED を「1色ずつ高速に切り替えて」混ぜた色を出す。

    この装置の配線は、RGB LED の共通の足 (カソード) に 220Ω を1本だけ付けている。
    この配線で2色を同時に点けると、点灯電圧の低い赤に電流が集まり、緑・青が光らない
    (黄 = 赤+緑 が赤にしか見えない)。そこで2色以上のときは 1/100 秒ごとに色を順番に
    点け、同時に点く色が常に1つになるようにする。1色だけのときは点けっぱなし。
    gpiozero の RGBLED と同じ color / off / blink / close を持つ。
    """

    FRAME = 0.01  # 1周期 10ms (100Hz) → 目にはちらつかず混ざって見える

    def __init__(self, red: int, green: int, blue: int):
        self._leds = [DigitalOutputDevice(p) for p in (red, green, blue)]
        self._color = (0, 0, 0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def color(self) -> tuple:
        return self._color

    @color.setter
    def color(self, value) -> None:
        self._start(tuple(value), blink=None)

    def off(self) -> None:
        self.color = (0, 0, 0)

    def blink(self, on_time=0.5, off_time=0.5, on_color=(1, 1, 1), background=True) -> None:
        self._start(tuple(on_color), blink=(on_time, off_time))

    def _halt(self) -> None:
        if self._thread and self._thread.is_alive():
            self._stop.set()
            self._thread.join(timeout=1)
        self._thread = None
        self._stop.clear()
        for led in self._leds:
            led.off()

    def _start(self, color: tuple, blink) -> None:
        self._halt()
        self._color = color
        active = [(led, v) for led, v in zip(self._leds, color) if v > 0]
        if blink is None and len(active) <= 1:
            for led, _ in active:   # 1色だけなら点けっぱなし (切り替え不要)
                led.on()
            return
        self._thread = threading.Thread(target=self._loop, args=(active, blink), daemon=True, name="rgb")
        self._thread.start()

    def _loop(self, active, blink) -> None:
        total = sum(v for _, v in active) or 1
        t0 = time.monotonic()
        while not self._stop.is_set():
            if blink:
                on_t, off_t = blink
                if (time.monotonic() - t0) % (on_t + off_t) >= on_t:  # 点滅の「消えている」時間
                    self._stop.wait(self.FRAME)
                    continue
            if len(active) == 1:
                active[0][0].on()
                self._stop.wait(self.FRAME)
                active[0][0].off()
                continue
            for led, v in active:  # 同時に点くのは常に1色だけ
                led.on()
                self._stop.wait(self.FRAME * v / total)
                led.off()
                if self._stop.is_set():
                    break

    def close(self) -> None:
        self._halt()
        for led in self._leds:
            led.close()


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
        self.rgb = SequentialRGB(**RGB_PINS)  # 共通抵抗1本の配線でも色を混ぜられるように
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
    """短く押す → on_press (家族へ通知)。2秒長押し → on_hold (表示リセット)。

    実機でチャタリング (接点の跳ね・接触不良で1回の操作が何十回にも数えられる) が出たため、
      - 50ms 未満の押下はノイズとして無視
      - 一度反応したら 1 秒間は次の操作を受け付けない
    """

    MIN_PRESS = 0.05   # これより短い押下はノイズ
    COOLDOWN = 1.0     # 反応した後に無視する時間

    def __init__(self, on_press, on_hold, hold_time: float = 2.0):
        self._held = False
        self._pressed_at = 0.0
        self._last_action = -1e9
        self.button = Button(NOTIFY_BUTTON, pull_up=True, hold_time=hold_time, bounce_time=0.02)
        self.button.when_pressed = self._when_pressed
        self.button.when_held = self._when_held
        self.button.when_released = self._when_released
        self._on_press, self._on_hold = on_press, on_hold

    def _when_pressed(self):
        self._pressed_at = time.monotonic()

    def _accept(self) -> bool:
        now = time.monotonic()
        if now - self._last_action < self.COOLDOWN:
            return False
        self._last_action = now
        return True

    def _when_held(self):
        self._held = True
        if self._accept():
            self._on_hold()

    def _when_released(self):
        held, self._held = self._held, False
        if held or time.monotonic() - self._pressed_at < self.MIN_PRESS:
            return
        if self._accept():
            self._on_press()

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
