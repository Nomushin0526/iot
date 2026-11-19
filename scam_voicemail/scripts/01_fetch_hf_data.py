"""Step 1: Hugging Face の英語詐欺通話データセットを取得し、留守電風テキストに整形する。

BothBosu/scam-dialogue は "caller: ... receiver: ..." 形式の対話なので、
caller 側の発話だけを冒頭から連結し、50〜300文字に収まる範囲を「留守電メッセージ」とみなす。
出力: data/raw/hf_en_data.jsonl
"""
import argparse
import random
import re

from datasets import concatenate_datasets, load_dataset

from common import RAW, write_jsonl

TURN_RE = re.compile(r"(caller|receiver)\s*:\s*", re.IGNORECASE)
MIN_CHARS, MAX_CHARS = 50, 300
ACK_RE = re.compile(r"^(sure|of course|okay|ok|yes|yeah|great|absolutely|certainly|no problem|i understand|thank you|thanks)\b", re.I)

# scam-dialogue の type 列 → 本プロジェクトのカテゴリ名
CATEGORY_MAP = {
    "ssn": "hf_ssn_scam",
    "refund": "hf_refund_scam",
    "support": "hf_tech_support_scam",
    "reward": "hf_reward_scam",
    "delivery": "hf_delivery",
    "insurance": "hf_insurance",
    "telemarketing": "hf_telemarketing",
    "wrong": "hf_wrong_number",
}


def caller_turns(dialogue: str) -> list[str]:
    parts = TURN_RE.split(dialogue)
    # split結果: ['', 'caller', 'text', 'receiver', 'text', ...]
    turns = []
    for i in range(1, len(parts) - 1, 2):
        if parts[i].lower() == "caller":
            t = parts[i + 1].strip()
            if t:
                turns.append(t)
    return turns


def to_voicemail(dialogue: str) -> str | None:
    """caller発話を先頭から連結し、50〜300文字の留守電風テキストを作る。"""
    text = ""
    for n, turn in enumerate(caller_turns(dialogue)):
        if n > 0:
            # 2ターン目以降: 受話者への相づち・返答文 (Sure thing. / Of course. 等) を除去
            sents = re.split(r"(?<=[.!?])\s+", turn)
            sents = [s for s in sents if len(s) >= 25 and not ACK_RE.match(s)]
            turn = " ".join(sents)
            if not turn:
                continue
        # 受話者への質問 (Is this John? 等) は留守電に不自然なので除去
        turn = re.sub(r"\b(Hello|Hi),?\s+is this [^?]+\?\s*", r"\1. ", turn, flags=re.I).strip()
        cand = (text + " " + turn).strip()
        if len(cand) > MAX_CHARS:
            if len(text) >= MIN_CHARS:
                break
            # 1ターンが長すぎる場合は文単位で切り詰め
            sents = re.split(r"(?<=[.!?])\s+", cand)
            cand = ""
            for s in sents:
                if len(cand) + len(s) + 1 > MAX_CHARS:
                    break
                cand = (cand + " " + s).strip()
            text = cand
            break
        text = cand
    text = re.sub(r"\s+", " ", text).strip()
    return text if MIN_CHARS <= len(text) <= MAX_CHARS else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="BothBosu/scam-dialogue")
    ap.add_argument("--per-label", type=int, default=250, help="ラベルごとの抽出件数 (200〜300推奨)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    ds = load_dataset(args.dataset)
    full = concatenate_datasets([ds[s] for s in ds])
    print(f"loaded {args.dataset}: {len(full)} rows")

    rng = random.Random(args.seed)
    buckets = {0: [], 1: []}
    seen = set()
    for i, row in enumerate(full):
        text = to_voicemail(row["dialogue"])
        if not text or text in seen:
            continue
        seen.add(text)
        buckets[int(row["label"])].append({
            "id": f"hf_{i:05d}",
            "text": text,
            "label": int(row["label"]),
            "category": CATEGORY_MAP.get(row["type"], f"hf_{row['type']}"),
            "language": "en",
            "source": f"hf:{args.dataset}",
        })

    out = []
    for label, recs in buckets.items():
        # type ごとに均等になるようラウンドロビンで抽出
        by_cat = {}
        for r in recs:
            by_cat.setdefault(r["category"], []).append(r)
        for v in by_cat.values():
            rng.shuffle(v)
        picked = []
        while len(picked) < args.per_label and any(by_cat.values()):
            for k in sorted(by_cat):
                if by_cat[k] and len(picked) < args.per_label:
                    picked.append(by_cat[k].pop())
        print(f"label={label}: candidates={len(recs)} picked={len(picked)}")
        out.extend(picked)

    path = RAW / "hf_en_data.jsonl"
    write_jsonl(path, out)
    print(f"saved {len(out)} records -> {path}")


if __name__ == "__main__":
    main()
