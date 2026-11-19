"""Step 4: Whisper 特有の文字起こしノイズを約30%に付与し、全データを統合して train/val に分割する。

入力: data/raw/hf_en_data.jsonl, data/raw/seed_data.jsonl, data/processed/synthetic.jsonl
出力: data/processed/all_clean.jsonl  (ノイズ付与前の統合データ)
      data/dataset.jsonl              (ノイズ付与後の全データ)
      data/train.jsonl (80%) / data/val.jsonl (20%)  ※ label×category で層化分割

ノイズ付与されたレコードは source に "+asr_noise" を付ける (スキーマは変えない)。
"""
import argparse
import random
import re
from collections import Counter, defaultdict

from common import DATA, PROCESSED, RAW, read_jsonl, write_jsonl

# ---------------------------------------------------------------- ノイズ辞書
JA_HIRAGANA = {
    "電話": "でんわ", "番号": "ばんごう", "料金": "りょうきん", "停止": "ていし", "確認": "かくにん", "連絡": "れんらく",
    "至急": "しきゅう", "本日": "ほんじつ", "携帯": "けいたい", "手続き": "てつづき", "還付金": "かんぷきん", "予約": "よやく",
    "荷物": "にもつ", "折り返し": "おりかえし", "口座": "こうざ", "警察": "けいさつ", "弁護士": "べんごし", "病院": "びょういん",
    "明日": "あした", "お願い": "おねがい", "担当": "たんとう", "支払い": "しはらい", "押して": "おして", "申し訳": "もうしわけ",
    "詳しく": "くわしく", "未納": "みのう", "年金": "ねんきん", "保険": "ほけん", "不在": "ふざい", "点検": "てんけん",
    "今日": "きょう", "大丈夫": "だいじょうぶ", "電気": "でんき", "訴訟": "そしょう", "検査": "けんさ", "声": "こえ",
}
# 同音異義語・誤変換 (Whisperの日本語で実際に起きやすい種類)
JA_HOMOPHONE = {
    "口座": "講座", "至急": "支給", "期限": "機嫌", "回線": "改選", "保険": "保健", "未納": "未能", "解除": "介助",
    "異議": "意義", "機関": "期間", "交換": "好感", "対象": "対照", "請求": "成求", "医療費": "医療日", "還付": "官符",
    "以内": "以外", "検査": "監査", "早めに": "初めに", "折り返し": "織り返し", "指定": "師定", "要請": "養成",
    "法的": "放的", "出頭": "出当", "示談": "自談", "送電": "総電", "再配達": "最配達", "記載": "機材", "担当": "単当",
}
JA_NUM = {"1番": ["一番", "いちばん", "1版"], "2時間": ["二時間", "2次元"], "9番": ["きゅうばん", "九番", "球番"],
          "0番": ["ゼロ番", "れい番"], "1を": ["位置を", "一を"], "2を": ["日を", "二を"], "24時間": ["二十四時間"]}
JA_FILLERS = ["えー", "あの", "えーと", "あー", "まあ", "そのー"]
JA_HALLUCINATION = ["ご視聴ありがとうございました", "チャンネル登録よろしくお願いします", "おやすみなさい", "では、また"]

EN_HOMOPHONE = {"their": "there", "to": "too", "for": "four", "your": "you're", "you're": "your", "its": "it's", "two": "to",
                "right": "write", "here": "hear", "know": "no", "call": "cole", "parcel": "parsel", "customs": "costumes",
                "embassy": "embassie", "visa": "visor", "refund": "re fund", "warrant": "warrent", "press": "pres"}
EN_FILLERS = ["uh", "um", "uh huh", "you know"]
EN_HALLUCINATION = ["Thank you for watching.", "Thanks for watching!", "Please subscribe.", "Bye."]

ZH_HOMOPHONE = {"的": "得", "在": "再", "已": "以", "按": "暗", "领": "令", "查": "察", "注销": "注消", "涉嫌": "设嫌",
                "回电": "回店", "预约": "预越", "包裹": "包过", "护照": "户照", "签证": "签正"}
ZH_FILLERS = ["那个", "嗯", "就是", "呃"]
ZH_HALLUCINATION = ["字幕由Amara.org社区提供", "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "谢谢观看"]

PUNCT_RE = re.compile(r"[、。，．,.!?！？「」『』\"“”…:：;；]")


# ---------------------------------------------------------------- ノイズ関数
def remove_punct(t, lang, rng):
    t = PUNCT_RE.sub(" " if lang == "en" else "", t)
    return re.sub(r"\s+", " ", t).strip()


def segment_spaces(t, lang, rng):
    """Whisperのセグメント結合で句点位置にスペースが入る/句点が消える。"""
    if lang == "en":
        return t
    return re.sub(r"[。．]", lambda m: rng.choice([" ", "", "。"]), t)


def dict_replace(t, table, rng, p):
    keys = [k for k in table if k in t]
    for k in keys:
        if rng.random() < p:
            v = table[k]
            v = rng.choice(v) if isinstance(v, list) else v
            t = t.replace(k, v, 1)
    return t


def ja_hiragana(t, lang, rng):
    return dict_replace(t, JA_HIRAGANA, rng, 0.5)


def ja_homophone(t, lang, rng):
    return dict_replace(t, JA_HOMOPHONE, rng, 0.5)


def ja_numbers(t, lang, rng):
    return dict_replace(t, JA_NUM, rng, 0.7)


def en_homophone(t, lang, rng):
    words = t.split(" ")
    out = []
    for w in words:
        core = re.sub(r"[^\w']", "", w).lower()
        if core in EN_HOMOPHONE and rng.random() < 0.35:
            w = w.lower().replace(core, EN_HOMOPHONE[core])
        out.append(w)
    return " ".join(out)


def en_lowercase(t, lang, rng):
    return t.lower()


def zh_homophone(t, lang, rng):
    return dict_replace(t, ZH_HOMOPHONE, rng, 0.4)


def insert_fillers(t, lang, rng):
    fillers = {"ja": JA_FILLERS, "en": EN_FILLERS, "zh": ZH_FILLERS}[lang]
    sep = " " if lang == "en" else ""
    parts = re.split(r"(?<=[、。，,.])", t) if lang != "en" else t.split(" ")
    out = []
    for p in parts:
        if p and rng.random() < (0.06 if lang == "en" else 0.2):
            out.append(rng.choice(fillers) + {"en": ",", "ja": rng.choice(["", "、"]), "zh": rng.choice(["", "，"])}[lang])
        out.append(p)
    return sep.join(out).strip()


def repeat_phrase(t, lang, rng):
    """Whisperの繰り返し出力 (同じ句が連続する)。"""
    unit = t.split(" ") if lang == "en" else re.split(r"(?<=[、。，,])", t)
    if len(unit) < 3:
        return t
    i = rng.randrange(len(unit))
    unit.insert(i, unit[i])
    return (" " if lang == "en" else "").join(unit)


def hallucination(t, lang, rng):
    """無音区間・録音末尾で出やすい定番の幻覚フレーズ。"""
    h = {"ja": JA_HALLUCINATION, "en": EN_HALLUCINATION, "zh": ZH_HALLUCINATION}[lang]
    return t + (" " if lang == "en" else "") + rng.choice(h)


def truncate(t, lang, rng):
    """録音が途中で切れた (留守電の録音時間切れ)。"""
    if len(t) < 60:
        return t
    cut = rng.randint(int(len(t) * 0.75), len(t) - 1)
    return t[:cut]


# (関数, 選択重み, 対象言語)
NOISES = [
    (remove_punct, 5, {"ja", "en", "zh"}),
    (segment_spaces, 2, {"ja", "zh"}),
    (ja_hiragana, 4, {"ja"}),
    (ja_homophone, 4, {"ja"}),
    (ja_numbers, 2, {"ja"}),
    (en_homophone, 4, {"en"}),
    (en_lowercase, 2, {"en"}),
    (zh_homophone, 4, {"zh"}),
    (insert_fillers, 2, {"ja", "en", "zh"}),
    (repeat_phrase, 1, {"ja", "en", "zh"}),
    (truncate, 1, {"ja", "en", "zh"}),
    (hallucination, 1, {"ja", "en", "zh"}),
]
# 句読点削除は最後に適用する (他の処理が句読点を手掛かりにするため)
ORDER = {f.__name__: i for i, (f, _, _) in enumerate(NOISES)}
ORDER["remove_punct"] = 99
ORDER["segment_spaces"] = 98


def add_noise(text, lang, rng):
    """1〜3種のノイズを適用。文字列が変化しなかった場合は引き直す。"""
    for _ in range(10):
        noisy, applied = _add_noise_once(text, lang, rng)
        if noisy != text:
            return noisy, applied
    return remove_punct(text, lang, rng), ["remove_punct"]


def _add_noise_once(text, lang, rng):
    cands = [(f, w) for f, w, langs in NOISES if lang in langs]
    k = rng.choice([1, 2, 2, 3])
    chosen = set()
    while len(chosen) < min(k, len(cands)):
        f = rng.choices([c[0] for c in cands], weights=[c[1] for c in cands])[0]
        chosen.add(f)
    noisy = text
    for f in sorted(chosen, key=lambda f: ORDER[f.__name__]):
        noisy = f(noisy, lang, rng)
    return noisy, sorted(f.__name__ for f in chosen)


# ---------------------------------------------------------------- 分割・集計
def stratified_split(records, val_ratio, rng):
    groups = defaultdict(list)
    for r in records:
        groups[(r["label"], r["category"])].append(r)
    train, val = [], []
    for g in groups.values():
        rng.shuffle(g)
        n_val = max(1, round(len(g) * val_ratio)) if len(g) > 1 else 0
        val.extend(g[:n_val])
        train.extend(g[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def print_summary(all_recs, train, val):
    print("\n" + "=" * 72)
    print(f"{'label':>5} {'category':<24}{'total':>7}{'train':>7}{'val':>6}  langs")
    print("-" * 72)
    ct, ctr, cv = (Counter((r["label"], r["category"]) for r in x) for x in (all_recs, train, val))
    langs = defaultdict(Counter)
    for r in all_recs:
        langs[(r["label"], r["category"])][r["language"]] += 1
    for key in sorted(ct, key=lambda k: (-k[0], k[1])):
        lg = " ".join(f"{l}:{n}" for l, n in sorted(langs[key].items()))
        print(f"{key[0]:>5} {key[1]:<24}{ct[key]:>7}{ctr[key]:>7}{cv[key]:>6}  {lg}")
    print("-" * 72)
    for lab in (1, 0):
        n = lambda xs: sum(1 for r in xs if r["label"] == lab)
        print(f"{'label=' + str(lab):>30}{n(all_recs):>7}{n(train):>7}{n(val):>6}")
    print(f"{'TOTAL':>30}{len(all_recs):>7}{len(train):>7}{len(val):>6}")
    lang_c = Counter(r["language"] for r in all_recs)
    noisy = sum(1 for r in all_recs if r["source"].endswith("+asr_noise"))
    print(f"\nlanguage: {dict(lang_c)}")
    print(f"asr_noise: {noisy}/{len(all_recs)} ({noisy / len(all_recs):.1%})")
    src = Counter(r["source"].replace("+asr_noise", "") for r in all_recs)
    print(f"source: {dict(src)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--noise-ratio", type=float, default=0.3)
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--show-examples", type=int, default=8)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    records = []
    for path in (RAW / "hf_en_data.jsonl", RAW / "seed_data.jsonl", PROCESSED / "synthetic.jsonl"):
        recs = read_jsonl(path)
        print(f"load {path.relative_to(DATA.parent)}: {len(recs)}")
        records.extend(recs)
    # 重複ID・重複テキストの除去
    seen_id, seen_text, uniq = set(), set(), []
    for r in records:
        if r["id"] in seen_id or r["text"] in seen_text:
            continue
        seen_id.add(r["id"]); seen_text.add(r["text"]); uniq.append(r)
    if len(uniq) != len(records):
        print(f"dedup: {len(records)} -> {len(uniq)}")
    records = uniq
    write_jsonl(PROCESSED / "all_clean.jsonl", records)

    # ノイズ付与 (label×language ごとに同じ割合で付与し、ノイズとラベルの相関を防ぐ)
    groups = defaultdict(list)
    for i, r in enumerate(records):
        groups[(r["label"], r["language"])].append(i)
    targets = set()
    for idxs in groups.values():
        targets.update(rng.sample(idxs, round(len(idxs) * args.noise_ratio)))
    examples, noise_stats = [], Counter()
    out = []
    for i, r in enumerate(records):
        r = dict(r)
        if i in targets:
            noisy, applied = add_noise(r["text"], r["language"], rng)
            noise_stats.update(applied)
            examples.append((r["language"], r["text"], noisy, applied))
            r["text"] = noisy
            r["source"] += "+asr_noise"
        out.append(r)

    rng.shuffle(out)
    write_jsonl(DATA / "dataset.jsonl", out)
    train, val = stratified_split(out, args.val_ratio, rng)
    write_jsonl(DATA / "train.jsonl", train)
    write_jsonl(DATA / "val.jsonl", val)

    print(f"\nnoise functions applied: {dict(noise_stats.most_common())}")
    print("\n--- noise examples ---")
    shown = []
    for lg in ("ja", "en", "zh"):
        pool = [e for e in examples if e[0] == lg]
        shown += rng.sample(pool, min(args.show_examples // 3 + (lg == "ja"), len(pool)))
    for lang, before, after, applied in shown:
        print(f"[{lang}] {applied}\n  before: {before}\n  after : {after}")
    print_summary(out, train, val)
    print(f"\nsaved: data/dataset.jsonl ({len(out)}), data/train.jsonl ({len(train)}), data/val.jsonl ({len(val)})")


if __name__ == "__main__":
    main()
