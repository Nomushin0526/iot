#!/usr/bin/env python3
"""表示の確認・調整用 (サーバーと同じ部品クラス checker/hardware.py を使う)。

    python3 diag_display.py

  1. バーグラフを1段ずつ点けて、光らない段を見つける
  2. 黄色の作り方 (赤と緑を交互に点ける時間の割合) を3通り試し、一番黄色に見えるものを選ぶ

各ステップで見え方を入力する。最後に結果のまとめが出るので、それを貼る。
サーバー (run_server.py) と hw_test.py は止めてから実行すること。
"""
import sys

from checker import hardware as hw

# 配線図 (fraud_wiring.jpg) での位置: 595 B の出力 Q7〜Q1 は 46〜40列、バーグラフの1〜7段目は 48〜54列
BAR_STAGES = [(i + 1, q, 46 - (7 - q), 48 + i) for i, q in enumerate(hw.BAR_ORDER_Q)]
YELLOW_CANDIDATES = {"A": (0.5, 1, 0), "B": (0.3, 1, 0), "C": (0.15, 1, 0)}

results = []


def ask(step: str, question: str) -> str:
    ans = input(f"\n[{step}] {question}\n  > ").strip() or "(未入力)"
    results.append((step, ans))
    return ans


def main():
    if "--mock" in sys.argv:  # PC での動作確認用
        hw.use_mock_pins()
    panel = hw.Panel()
    try:
        panel.show_char("8")
        ask("0 7セグ", "7セグに「8」(全部の線) が表示されている? (y / 欠けている線を書く)")

        # 1. バーグラフを1段ずつ
        for stage, q, q_col, bar_col in BAR_STAGES:
            panel.bar.write(1 << q)
            ask(f"1-{stage} バー{stage}段目",
                f"バーグラフの下から{stage}段目だけが光っている? (y/n)  "
                f"[595 B の Q{q}={q_col}列 → 紫線 → バー{bar_col}列]")
        panel.show_bar(0)

        # 2. 黄色の割合
        panel.show_char("4")
        for key, color in YELLOW_CANDIDATES.items():
            panel.rgb.color = color
            ask(f"2-{key} 黄色候補{key}", f"LED は何色に見える? (黄 / オレンジ / 赤 / 黄緑 など)  [赤:緑 = {color[0]}:{color[1]}]")
        panel.rgb.color = hw.COLORS["green"]
        ask("2-緑", "LED は緑? (y/n)")
        panel.rgb.color = hw.COLORS["red"]
        ask("2-赤", "LED は赤? (y/n)")
    finally:
        panel.close()

    print("\n===== 結果 (これをそのまま貼ってください) =====")
    for step, ans in results:
        print(f"{step}: {ans}")


if __name__ == "__main__":
    main()
