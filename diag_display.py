#!/usr/bin/env python3
"""表示の確認・調整用 (サーバーと同じ部品クラス checker/hardware.py を使う)。

    python3 diag_display.py

  0. 7セグの線を1本ずつ点けて、つながり方のずれを見つける
  1. バーグラフを1段ずつ点けて、光らない段を見つける
  2. 黄色の作り方 (赤と緑を交互に点ける時間の割合) を3通り試し、一番黄色に見えるものを選ぶ

各ステップで見え方を入力する。最後に結果のまとめが出るので、それを貼る。
サーバー (run_server.py) と hw_test.py は止めてから実行すること。
"""
import sys

from checker import hardware as hw

# 配線図 (fraud_wiring.jpg) での位置:
#   595 A (7セグ用) の出力 Q1〜Q7 は下側 25〜31列。7セグは 34〜38列 (上: g f 共通 a b / 下: e d 共通 c dp)
#   595 B (バー用)   の出力 Q1〜Q7 は下側 40〜46列。バーグラフの1〜7段目は 48〜54列
SEG_PIN_COL = {"g": "34列上", "f": "35列上", "a": "37列上", "b": "38列上", "e": "34列下", "d": "35列下", "c": "37列下"}
SEG_STEPS = sorted(((q, seg) for seg, q in hw.SEG_TO_Q.items()))  # [(1,'c'), (2,'d'), ...]
BAR_STAGES = [(i + 1, q, 46 - (7 - q), 48 + i) for i, q in enumerate(hw.BAR_ORDER_Q)]
# 前回: 赤:緑 = 0.5:1 でも緑に見えた → 赤を多めにした候補
YELLOW_CANDIDATES = {"D": (1, 0.5, 0), "E": (1, 0.25, 0), "F": (1, 0.1, 0)}

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
        # 0. 7セグを1本ずつ (595 A の Q1〜Q7 を1つずつ HIGH にする)
        print("\n7セグの線の名前:  a=上の横線  b=右上  c=右下  d=下の横線  e=左下  f=左上  g=真ん中の横線")
        for q, seg in SEG_STEPS:
            panel.seg.write(1 << q)
            ask(f"0-Q{q} 7セグ",
                f"光っている線はどれ? (a〜g の記号 / なし)  期待: {seg}  "
                f"[595 A の Q{q}={24 + q}列下 → オレンジ線 → 7セグ {SEG_PIN_COL[seg]}]")
        panel.seg.write(0)

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
