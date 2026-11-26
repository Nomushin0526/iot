#!/usr/bin/env python3
"""表示の不具合の切り分け用。サーバーと同じ部品クラス (checker/hardware.py) を使い、
条件を1つずつ変えて「どの条件で表示が崩れるか」を調べる。

    python3 diag_display.py

各ステップで LED を見て y / n を入力する。最後に結果のまとめが出るので、それを貼る。
サーバー (run_server.py) と hw_test.py は止めてから実行すること。
"""
import sys
import time

from checker import hardware as hw

results = []


def ask(step: str, expect: str) -> None:
    print(f"\n[{step}]")
    print(f"  期待: {expect}")
    ans = input("  そのとおりに見える? (y/n、違う場合は見え方を書いてもよい) > ").strip()
    results.append((step, expect, ans or "(未入力)"))


def main():
    if "--mock" in sys.argv:  # PC での動作確認用
        hw.use_mock_pins()
    panel = hw.Panel()
    keypad = None
    try:
        # 1. 表示だけ (キーパッドなし)。色はPWMを使わない赤
        panel.show_char("4")
        panel.show_bar(3)
        panel.set_color("red")
        ask("1 表示だけ", "7セグ「4」、バーグラフ 下から3段、LED 赤")

        # 2. 黄色 (緑を60%にするPWMあり)
        panel.rgb.color = (1, 0.6, 0)
        ask("2 黄色 (PWM 60%)", "LED 黄色 (オレンジっぽい黄)。7セグ・バーはステップ1のまま")

        # 3. 黄色 (PWMなし: 赤と緑を両方100%)
        panel.rgb.color = (1, 1, 0)
        ask("3 黄色 (PWMなし)", "LED 黄色 (黄緑っぽくてもOK)。7セグ・バーはステップ1のまま")

        # 4. キーパッドの読み取りを動かす (サーバーと同じ状態)
        keypad = hw.Keypad(on_key=lambda k: print(f"  キー: {k}"))
        keypad.start()
        print("\n  キーパッドの読み取りを開始しました。5秒ほど表示を見てください…")
        time.sleep(5)
        ask("4 キーパッド読み取り中", "7セグ「4」・バー3段のまま変わらない (ちらつかない)")

        # 5. キーパッドを動かしたまま表示を書き直す
        panel.show_char("7")
        panel.show_bar(5)
        panel.set_color("red")
        time.sleep(3)
        ask("5 キーパッド読み取り中に書き換え", "7セグ「7」、バー5段、LED 赤")

        # 6. キーパッドを止めて書き直す
        keypad.close()
        keypad = None
        time.sleep(0.2)
        panel.show_char("2")
        panel.show_bar(2)
        panel.set_color("green")
        ask("6 キーパッド停止後に書き換え", "7セグ「2」、バー2段、LED 緑")
    finally:
        if keypad:
            keypad.close()
        panel.close()

    print("\n===== 結果 (これをそのまま貼ってください) =====")
    for step, expect, ans in results:
        print(f"{step}: {ans}   (期待: {expect})")


if __name__ == "__main__":
    main()
