"""判定の評価: 正解率・検出率・誤検知率・混同行列。

使い方 (リポジトリ直下で):
  # 1) 実運用ログ: data/check_log.csv の label 列に 1(詐欺)/0(正常) を記入してから
  python -m checker.evaluate --log data/check_log.csv

  # 2) 評価用セット (CSV 列: audio,text,number,label。audio か text のどちらかがあればよい)
  #    県警公開の詐欺音声や、自分で読み上げた正常な留守電をまとめたもの
  python -m checker.evaluate --csv data/eval_set.csv

  # 3) テキストのデータセット (scam_voicemail/data/val.jsonl) で内容判定だけを評価
  python -m checker.evaluate --jsonl scam_voicemail/data/val.jsonl --backend keyword
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from . import config


def metrics(pairs: list[tuple[int, int]]) -> dict:
    """pairs = [(正解, 予測), ...]  1=詐欺"""
    c = Counter(pairs)
    tp, fn, fp, tn = c[(1, 1)], c[(1, 0)], c[(0, 1)], c[(0, 0)]
    n = len(pairs)
    return {
        "n": n, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        "accuracy": (tp + tn) / n if n else 0,
        "recall": tp / (tp + fn) if tp + fn else 0,       # 検出率 (詐欺を詐欺と言えた割合)
        "fpr": fp / (fp + tn) if fp + tn else 0,          # 誤検知率 (正常を詐欺と言った割合)
        "precision": tp / (tp + fp) if tp + fp else 0,
    }


def report(title: str, pairs: list[tuple[int, int]], groups: dict[str, list[tuple[int, int]]] | None = None):
    m = metrics(pairs)
    print(f"\n=== {title} (n={m['n']})")
    print(f"正解率 {m['accuracy']:.1%}   検出率 {m['recall']:.1%}   誤検知率 {m['fpr']:.1%}   適合率 {m['precision']:.1%}")
    print("混同行列           予測:詐欺  予測:正常")
    print(f"  正解:詐欺       {m['tp']:>8}  {m['fn']:>8}")
    print(f"  正解:正常       {m['fp']:>8}  {m['tn']:>8}")
    if groups:
        print("カテゴリ別 正解率:")
        for g, ps in sorted(groups.items()):
            print(f"  {g:<26} {metrics(ps)['accuracy']:.1%}  (n={len(ps)})")


def threshold_table(scored: list[tuple[int, int]]):
    """scored = [(正解, 危険度0〜9)]。しきい値ごとの検出率・誤検知率。"""
    print("\nしきい値  検出率  誤検知率   (危険度がしきい値以上を「詐欺」とみなす)")
    for t in range(1, 10):
        m = metrics([(y, int(r >= t)) for y, r in scored])
        mark = "  ← 現在の通知しきい値" if t == config.NOTIFY_THRESHOLD else ""
        print(f"   {t}      {m['recall']:>6.1%}  {m['fpr']:>6.1%}{mark}")


def eval_log(path: Path, threshold: int):
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8")) if r.get("label", "").strip() in ("0", "1")]
    if not rows:
        raise SystemExit(f"{path} に label (1/0) が記入された行がありません")
    scored = [(int(r["label"]), int(r["risk"])) for r in rows]
    report(f"{path.name} 危険度>={threshold}", [(y, int(r >= threshold)) for y, r in scored])
    threshold_table(scored)
    secs = [float(r["transcribe_sec"]) for r in rows if r.get("transcribe_sec")]
    if secs:
        print(f"\n文字起こし時間: 平均 {sum(secs) / len(secs):.1f}秒, 最大 {max(secs):.1f}秒 (n={len(secs)})")


def eval_csv(path: Path, threshold: int, backend: str | None):
    from .pipeline import run_check
    scored, groups = [], defaultdict(list)
    for row in csv.DictReader(path.open(encoding="utf-8")):
        audio = (row.get("audio") or "").strip() or None
        if audio and not Path(audio).is_absolute():
            audio = str(path.parent / audio)
        text = None if audio else (row.get("text") or "")
        r = run_check(audio_path=audio, text=text, number=row.get("number", ""), source="eval",
                      auto_notify=False, save=False, content_backend=backend)
        y = int(row["label"])
        scored.append((y, r["risk"]))
        groups[row.get("category") or ("scam" if y else "normal")].append((y, int(r["risk"] >= threshold)))
        print(f"  label={y} risk={r['risk']} {Path(audio).name if audio else (text or '')[:30]}")
    report(f"{path.name} 危険度>={threshold}", [(y, int(r >= threshold)) for y, r in scored], groups)
    threshold_table(scored)


def eval_jsonl(path: Path, backend: str, score_threshold: float, limit: int):
    from .content_check import check_content
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    if limit:
        rows = rows[:limit]
    pairs, groups = [], defaultdict(list)
    for i, r in enumerate(rows, 1):
        c = check_content(r["text"], backend)
        p = (r["label"], int(c.score >= score_threshold))
        pairs.append(p)
        groups[r["category"]].append(p)
        if backend != "keyword" and i % 20 == 0:
            print(f"  {i}/{len(rows)}")
    report(f"{path.name} 内容スコア>={score_threshold} ({backend})", pairs, groups)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", type=Path)
    src.add_argument("--csv", type=Path)
    src.add_argument("--jsonl", type=Path)
    ap.add_argument("--threshold", type=int, default=config.NOTIFY_THRESHOLD, help="危険度のしきい値 (0〜9)")
    ap.add_argument("--score-threshold", type=float, default=0.5, help="--jsonl 用: 内容スコアのしきい値")
    ap.add_argument("--backend", default=None, help="keyword / anthropic / openai / ollama (省略時は自動)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.log:
        eval_log(args.log, args.threshold)
    elif args.csv:
        eval_csv(args.csv, args.threshold, args.backend)
    else:
        eval_jsonl(args.jsonl, args.backend or "keyword", args.score_threshold, args.limit)


if __name__ == "__main__":
    main()
