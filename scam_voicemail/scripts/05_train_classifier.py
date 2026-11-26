"""Step 5: 軽量テキスト分類器 (文字n-gram TF-IDF + ロジスティック回帰) を学習する。

入力: data/train.jsonl / data/val.jsonl (04 の出力)
出力: リポジトリ直下の models/scam_clf.joblib  (詐欺チェッカー checker/classifier.py が読み込む)

文字単位の n-gram を使うので、Whisper の誤変換 (還付金→乾吹金 など) や句読点の欠落があっても
部分的に一致する文字列から判定できる。Raspberry Pi 5 でも学習は数秒、判定は数ミリ秒。

    python 05_train_classifier.py
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from common import DATA, ROOT, read_jsonl

MODEL_PATH = ROOT.parent / "models" / "scam_clf.joblib"


def build_pipeline(C: float) -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 3), min_df=2,
                                  sublinear_tf=True, max_features=60000)),
        ("clf", LogisticRegression(C=C, class_weight="balanced", max_iter=3000)),
    ])


def metrics(y_true, y_pred) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    n = len(y_true)
    return {"n": n, "accuracy": (tp + tn) / n if n else 0, "recall": tp / (tp + fn) if tp + fn else 0,
            "fpr": fp / (fp + tn) if fp + tn else 0, "tp": tp, "fn": fn, "fp": fp, "tn": tn}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--C", type=float, default=4.0, help="正則化の強さの逆数 (大きいほど学習データに合わせる)")
    ap.add_argument("--out", type=Path, default=MODEL_PATH)
    args = ap.parse_args()

    train, val = read_jsonl(DATA / "train.jsonl"), read_jsonl(DATA / "val.jsonl")
    if not train:
        raise SystemExit("data/train.jsonl がありません。先に 03 → 04 を実行してください。")
    sources = defaultdict(int)
    for r in train:
        sources[r["source"].replace("+asr_noise", "")] += 1
    print(f"train {len(train)} / val {len(val)}   sources: {dict(sources)}")
    if all(s in ("template", "seed_manual") or s.startswith("hf:") for s in sources):
        print("注意: 合成データがテンプレート生成のみです。LLMで生成したデータで学習し直すことを推奨します。")

    pipe = build_pipeline(args.C)
    pipe.fit([r["text"] for r in train], [r["label"] for r in train])

    pred = pipe.predict([r["text"] for r in val])
    m = metrics([r["label"] for r in val], pred)
    print(f"\n=== val (n={m['n']})")
    print(f"正解率 {m['accuracy']:.1%}   検出率 {m['recall']:.1%}   誤検知率 {m['fpr']:.1%}")
    print(f"混同行列  TP={m['tp']} FN={m['fn']} FP={m['fp']} TN={m['tn']}")
    by_cat = defaultdict(list)
    for r, p in zip(val, pred):
        by_cat[r["category"]].append(int(r["label"] == p))
    print("カテゴリ別 正解率:")
    for c, oks in sorted(by_cat.items()):
        print(f"  {c:<24} {sum(oks) / len(oks):.1%}  (n={len(oks)})")
    noisy = [(r, p) for r, p in zip(val, pred) if r["source"].endswith("+asr_noise")]
    if noisy:
        print(f"ASRノイズあり の正解率: {sum(r['label'] == p for r, p in noisy) / len(noisy):.1%} (n={len(noisy)})")

    # 再学習: train + val 全部で最終モデルを作る (評価値は上の val のものを記録)
    final = build_pipeline(args.C)
    final.fit([r["text"] for r in train + val], [r["label"] for r in train + val])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "pipeline": final,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "n_train": len(train) + len(val),
        "sources": dict(sources),
        "val_metrics": m,
        "C": args.C,
    }, args.out)
    print(f"\nsaved -> {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")

    # 動作確認: 典型例のスコア
    samples = [
        "こちらは市役所です。医療費の還付金があります。本日中にATMで手続きしてください。",
        "こちらはそうむしょうです お客様の電話は2時間後に停止します 1番を押してください",
        "さくら歯科です。明日午後3時のご予約の確認です。変更は診療時間内にお電話ください。",
        "あ、もしもしお母さんだけど、週末そっちに行くね。また電話するね。",
    ]
    print("\n例:")
    for s, p in zip(samples, final.predict_proba(samples)[:, 1]):
        print(f"  {p:.2f}  {s}")


if __name__ == "__main__":
    main()
