#!/usr/bin/env python3
"""通知ボタンの状態を調べる (Thonny で開いて「実行」するだけ。引数なし)。

30秒の間、ボタンが押された・離された瞬間と、押していた時間を表示する。
最後に、ボタンと回路のどちらが悪そうかを表示する。

先に run_server.py を止めておくこと (同じピンを使うため。止めずに実行すると GPIO busy になる)。
"""
import time

from gpiozero import Button

PIN = 26
SECONDS = 30

if __import__("sys").argv[1:] == ["--mock"]:  # PC での動作確認用
    from gpiozero.pins.mock import MockFactory
    from gpiozero import Device
    Device.pin_factory = MockFactory()
    SECONDS = 1

b = Button(PIN, pull_up=True)
t0 = time.monotonic()
pressed_at = None
pulses = []


def on_press():
    global pressed_at
    pressed_at = time.monotonic()


def on_release():
    if pressed_at is None:
        return
    ms = (time.monotonic() - pressed_at) * 1000
    pulses.append(ms)
    print(f"  {time.monotonic() - t0:5.1f}秒  押していた時間 {ms:7.1f} ms")


b.when_pressed = on_press
b.when_released = on_release

print(f"{SECONDS}秒間テストします。")
print("最初の10秒は触らない → そのあと、ボタンをしっかり3回、0.5秒ずつ押して離してください。\n")
time.sleep(SECONDS)
b.close()

short = [p for p in pulses if p < 50]
long_ = [p for p in pulses if p >= 50]
print(f"\n===== 結果 =====")
print(f"反応した回数: {len(pulses)}  (50ms以上: {len(long_)} 回 / 50ms未満の短いもの: {len(short)} 回)")
if not pulses:
    print("→ 押しても信号が変わっていない。63列(GPIO26)と58列(GND)の線、ボタンの向きを確認してください。")
elif len(long_) >= 1 and len(short) <= 3:
    print("→ ボタンも回路も正常そうです。run_server.py に戻ってボタンを試してください。")
elif len(short) > len(long_):
    print("→ 押している間に接点がついたり離れたりしています (ボタンの接触不良)。")
    print("  ボタンを挿し直す・90度回す・別のボタンに交換する、を試してください。")
else:
    print("→ 判断がつきません。この結果をそのまま貼ってください。")
