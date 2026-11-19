"""Step 3: シードデータを few-shot として LLM で留守電テキストを水増し生成する。

- 目標: 最終データ合計 2,000件 (label 1: 1,000 / label 0: 1,000)。
  既存の HF データ (01) とシード (02) の件数を差し引いた残りを合成データで埋める。
- バックエンド: OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY のうち設定済みのものを自動選択。
  キーが無い場合は --backend template でオフライン生成 (動作確認・ベースライン用)。
- 10件ずつバッチ生成し data/processed/synthetic.jsonl に逐次追記する。
  再実行すると既存件数を数えて不足分だけ生成する (レジューム可能)。

例:
  python 03_generate_synthetic.py                 # 自動でAPIキーを検出
  python 03_generate_synthetic.py --backend anthropic --model claude-haiku-5-5
  python 03_generate_synthetic.py --backend template
"""
import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict

from common import PROCESSED, RAW, append_jsonl, read_jsonl

OUT = PROCESSED / "synthetic.jsonl"

CATEGORY_DESC = {
    "auto_voice_gov": "総務省・NTT・携帯キャリア・電力会社などを騙る詐欺の自動音声。「2時間後に電話が停止」「未納料金がある」「1番を押してください」などで不安を煽りオペレーターに繋がせる。",
    "intl_scam_zh_en": "中国大使館・領事館・入国管理局・DHL/FedEx等の国際宅配業者を騙る中国語または英語の詐欺自動音声。荷物差し押さえ・ビザ取消・事件関与などを告げ番号を押させる。",
    "refund_scam": "市役所・区役所・税務署・年金事務所・協会けんぽを騙る還付金詐欺の留守電。医療費・保険料・年金の払い戻しがあり期限が今日までと急がせ、ATMへ誘導したり折り返しを求める。",
    "fake_police_billing": "ニセ警察官・ニセ弁護士・ニセ金融庁・架空請求。「口座が犯罪に悪用された」「逮捕状」「訴訟・出頭」「未払いサイト料金」「電子マネー購入」など脅しで連絡や送金を迫る。",
    "relative_scam": "息子・孫など親族をかたるオレオレ詐欺の留守電。「スマホを落とした」「番号が変わった」「風邪で声が変」「会社のお金をなくした」「示談金」などで折り返しやお金の用意を求める。",
    "normal_auto_voice": "正常な自動音声の留守電。病院・歯科・美容室の予約確認、宅配便の不在連絡、ガス・水道点検や工事の案内、自治体の防災情報など。番号を押す案内や折り返し依頼を含むこともあるが、金銭要求や脅しはない。",
    "normal_business": "銀行・保険会社・不動産管理会社・学校・保育園・勤務先・役所などからの通常の事務連絡の留守電。書類確認・更新案内・面接結果などで折り返しを依頼するが、金銭の要求・ATM誘導・脅しはない。",
    "normal_personal": "家族・友人・知人・同僚からの日常的な留守電。「えーと」「あ、もしもし」等のフィラーやくだけた口調を含む。予定の連絡、お礼、折り返し依頼など。",
}

# カテゴリごとの言語配分 (負例にも en/zh を入れて「中国語=詐欺」のショートカット学習を防ぐ)
LANG_WEIGHTS = {
    "intl_scam_zh_en": {"zh": 0.5, "en": 0.5},
    "normal_auto_voice": {"ja": 0.8, "en": 0.1, "zh": 0.1},
    "normal_business": {"ja": 0.8, "en": 0.1, "zh": 0.1},
    "normal_personal": {"ja": 0.8, "en": 0.1, "zh": 0.1},
}
LANG_NAME = {"ja": "日本語", "en": "英語", "zh": "中国語(簡体字)"}

STYLES = {
    1: ["丁寧で事務的", "威圧的・高圧的", "機械音声風(抑揚のない自動ガイダンス)", "焦った・切迫した口調"],
    0: ["丁寧で事務的", "機械音声風(自動ガイダンス)", "くだけた口調", "少し急いだ口調"],
}
LENGTHS = {
    "ja": [("15秒程度", "60〜90文字"), ("30秒程度", "130〜170文字"), ("45秒程度", "200〜250文字")],
    "zh": [("15秒程度", "50〜70字"), ("30秒程度", "100〜130字"), ("45秒程度", "150〜190字")],
    "en": [("15秒程度", "35〜45語"), ("30秒程度", "70〜85語"), ("45秒程度", "105〜120語")],
}

SYSTEM_PROMPT = (
    "あなたは電話詐欺対策システムの研究用データセットを作成するアシスタントです。"
    "留守番電話に録音されたメッセージを音声認識で文字起こししたテキストを作成します。"
    "生成データは詐欺を検知する分類器の学習にのみ使われます。"
    "実在の個人の氏名・実在する電話番号・実在の口座番号は絶対に含めないでください(機関名は実在のものを使ってよい)。"
    "話し言葉として自然で、1件ずつ内容・言い回し・機関名・金額・状況が異なるようにしてください。"
    '出力は必ず {"messages": ["...", "..."]} 形式のJSONのみとしてください。'
)


# ---------------------------------------------------------------- LLMバックエンド
class LLMBackend:
    def __init__(self, provider, model=None):
        self.provider = provider
        if provider == "openai":
            from openai import OpenAI
            self.client = OpenAI()
            self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        elif provider == "anthropic":
            import anthropic
            self.anthropic = anthropic
            self.client = anthropic.Anthropic(max_retries=3)
            self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
        elif provider == "gemini":
            from google import genai
            self.genai = genai
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        else:
            raise ValueError(provider)

    def complete(self, user_prompt: str) -> str:
        if self.provider == "openai":
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
                temperature=1.0,
            )
            return r.choices[0].message.content
        if self.provider == "anthropic":
            kwargs = dict(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={"effort": "low"},
            )
            # 安全分類器による拒否時に別モデルへ自動フォールバック (対応モデルのみ)
            if self.model in {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}:
                r = self.client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                r = self.client.messages.create(**kwargs)
            if r.stop_reason == "refusal":
                raise RuntimeError(f"refusal: {getattr(r.stop_details, 'category', None)}")
            return "".join(b.text for b in r.content if b.type == "text")
        if self.provider == "gemini":
            r = self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=self.genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, response_mime_type="application/json", temperature=1.0),
            )
            return r.text


def detect_provider():
    for key, prov in (("OPENAI_API_KEY", "openai"), ("ANTHROPIC_API_KEY", "anthropic"), ("GEMINI_API_KEY", "gemini")):
        if os.environ.get(key):
            return prov
    return None


def build_prompt(category, label, lang, style, length, n, examples):
    sec, size = length
    ex = "\n".join(f"- {e['text']}" for e in examples)
    kind = "詐欺・不審電話" if label == 1 else "正常な(詐欺ではない)留守電"
    return (
        f"## 作成するデータ\n"
        f"- 種別: {kind}\n- カテゴリ: {category}\n- 内容: {CATEGORY_DESC[category]}\n"
        f"- 言語: {LANG_NAME[lang]}\n- 話し方: {style}\n- 長さ: 読み上げ{sec}({size})\n- 件数: {n}件\n\n"
        f"## お手本(この雰囲気を参考に、そのまま真似せず新しい内容で)\n{ex}\n\n"
        "## 条件\n"
        "- 機関名・人名(架空)・金額・期限・押すボタン番号・状況を1件ごとに変える\n"
        "- 留守電なので相手の応答は含めず、発信者の一方的な発話のみ\n"
        "- 句読点は通常どおり付ける(ノイズは後工程で付与する)\n"
        f'- JSON {{"messages": [...]}} に{n}件の文字列を入れて出力'
    )


def parse_messages(raw: str) -> list[str]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    msgs = data.get("messages", []) if isinstance(data, dict) else []
    return [s.strip() for s in msgs if isinstance(s, str) and len(s.strip()) >= 15]


# ---------------------------------------------------------------- 重複除去
def norm(t):
    return re.sub(r"[\s、。，．,.!?！？「」]", "", t.lower())


def ngrams(t, n=3):
    t = norm(t)
    return {t[i:i + n] for i in range(max(1, len(t) - n + 1))}


class Deduper:
    def __init__(self, texts, threshold=0.85):
        self.exact = set()
        self.grams = []
        self.th = threshold
        for t in texts:
            self.add(t)

    def is_dup(self, t):
        if norm(t) in self.exact:
            return True
        g = ngrams(t)
        return any(len(g & h) / max(1, len(g | h)) >= self.th for h in self.grams)

    def add(self, t):
        self.exact.add(norm(t))
        self.grams.append(ngrams(t))


# ---------------------------------------------------------------- 割り当て
def compute_quotas(seeds, existing, target_per_label):
    """(category, lang) -> 合成データで必要な件数"""
    cats_by_label = defaultdict(list)
    for s in seeds:
        if s["category"] not in cats_by_label[s["label"]]:
            cats_by_label[s["label"]].append(s["category"])
    quotas = {}
    for label, cats in cats_by_label.items():
        have = sum(1 for r in existing if r["label"] == label)
        need = max(0, target_per_label - have)
        base, rem = divmod(need, len(cats))
        for i, cat in enumerate(cats):
            n_cat = base + (1 if i < rem else 0)
            w = LANG_WEIGHTS.get(cat, {"ja": 1.0})
            langs = list(w)
            alloc = {l: int(n_cat * w[l]) for l in langs}
            alloc[langs[0]] += n_cat - sum(alloc.values())
            for l, n in alloc.items():
                quotas[(cat, l)] = n
    return quotas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto", choices=["auto", "openai", "anthropic", "gemini", "template"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--target-per-label", type=int, default=1000)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=1.0, help="API呼び出し間の待機秒")
    ap.add_argument("--max-batches", type=int, default=0, help="0=無制限 (お試し実行用)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    provider = detect_provider() if args.backend == "auto" else args.backend
    if provider is None:
        sys.exit("APIキー (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY) が見つかりません。"
                 "オフライン生成は --backend template を指定してください。")
    backend = None if provider == "template" else LLMBackend(provider, args.model)
    source = "template" if provider == "template" else f"llm:{provider}:{backend.model}"
    print(f"backend = {source}")

    seeds = read_jsonl(RAW / "seed_data.jsonl")
    hf = read_jsonl(RAW / "hf_en_data.jsonl")
    if not seeds:
        sys.exit("seed_data.jsonl がありません。先に 02_create_seed_data.py を実行してください。")
    quotas = compute_quotas(seeds, hf + seeds, args.target_per_label)

    done = read_jsonl(OUT)
    have = Counter((r["category"], r["language"]) for r in done)
    dedup = Deduper([r["text"] for r in hf + seeds + done])
    seeds_by_cat = defaultdict(list)
    for s in seeds:
        seeds_by_cat[s["category"]].append(s)
    label_of = {s["category"]: s["label"] for s in seeds}

    rng = random.Random(args.seed + len(done))  # レジューム時に同じ乱数列を繰り返さない
    print(f"resume: {len(done)} existing synthetic records")
    batches, failures = 0, Counter()

    while True:
        deficits = {k: q - have[k] for k, q in quotas.items() if q - have[k] > 0 and failures[k] < 8}
        if not deficits:
            break
        if args.max_batches and batches >= args.max_batches:
            print("max-batches reached")
            break
        key = max(deficits, key=deficits.get)
        cat, lang = key
        label = label_of[cat]
        n = min(args.batch_size, deficits[key])
        style = rng.choice(STYLES[label])
        length = rng.choice(LENGTHS[lang])

        if backend is None:
            import template_gen
            texts = template_gen.generate(cat, lang, style, n * 3, rng)  # 重複除去で減る分を多めに
        else:
            pool = seeds_by_cat[cat]
            same_lang = [s for s in pool if s["language"] == lang]
            examples = rng.sample(same_lang, min(3, len(same_lang)))
            others = [s for s in pool if s not in examples]
            examples += rng.sample(others, min(5 - len(examples), len(others)))
            prompt = build_prompt(cat, label, lang, style, length, n, examples)
            texts = []
            for attempt in range(5):
                try:
                    texts = parse_messages(backend.complete(prompt))
                    break
                except Exception as e:  # レート制限・一時的エラー → 指数バックオフ
                    wait = min(60, 2 ** attempt * 2 + rng.random())
                    print(f"  ! {type(e).__name__}: {str(e)[:120]} -> retry in {wait:.0f}s")
                    time.sleep(wait)
            time.sleep(args.sleep)

        new = []
        for t in texts:
            if len(new) >= n:
                break
            if dedup.is_dup(t):
                continue
            dedup.add(t)
            have[key] += 1
            new.append({
                "id": f"syn_{cat}_{lang}_{have[key]:04d}",
                "text": t, "label": label, "category": cat, "language": lang, "source": source,
            })
        if not new:
            failures[key] += 1
        append_jsonl(OUT, new)  # バッチごとに追記 → 中断しても再開可能
        batches += 1
        total = sum(have.values())
        print(f"[batch {batches:3d}] {cat}/{lang} style={style} +{len(new)}  ({total}/{sum(quotas.values())})")

    exhausted = [k for k in quotas if have[k] < quotas[k]]
    if exhausted:
        print(f"WARNING: 目標に届かなかったバケット: {[(k, have[k], quotas[k]) for k in exhausted]}")
    print(f"synthetic total = {sum(have.values())} -> {OUT}")
    by_label = Counter()
    for (cat, lang), c in have.items():
        by_label[label_of[cat]] += c
    print(f"by label: {dict(by_label)}")


if __name__ == "__main__":
    main()
