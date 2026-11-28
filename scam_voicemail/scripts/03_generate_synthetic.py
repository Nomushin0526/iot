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
  python 03_generate_synthetic.py --backend ollama --model gemma3:12b   # ローカルLLM (無料)
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
# カテゴリ固有の話し方 (STYLES より優先。不自然な組み合わせでラベルとずれた文が出るのを防ぐ)
CATEGORY_STYLES = {
    "relative_scam": ["焦った・切迫した口調", "くだけた口調(身内に話す感じ)", "弱々しく困った口調"],
    "normal_personal": ["くだけた口調", "少し急いだ口調", "のんびりした口調"],
}
NAME_EXAMPLES = {"ja": "田中、佐藤、山本", "en": "Smith, Johnson, Brown", "zh": "王、李、张"}
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
        elif provider == "ollama":
            # Ollama の OpenAI互換API (http://localhost:11434/v1) を使う。APIキー不要・無料
            from openai import OpenAI
            installed = ollama_models()
            if installed is None:
                raise SystemExit(f"Ollamaに接続できません ({ollama_host()})。`ollama serve` が動いているか確認してください。")
            self.model = model or os.environ.get("OLLAMA_MODEL") or pick_ollama_model(installed)
            if self.model is None:
                raise SystemExit("Ollamaにモデルがありません。例: ollama pull gemma3:4b")
            if self.model not in installed and f"{self.model}:latest" not in installed:
                raise SystemExit(f"モデル {self.model} が未インストールです。`ollama pull {self.model}` を実行してください。")
            # ラズパイ等のCPU推論は1回数分〜十数分かかるので長めに待つ。リトライは呼び出し側で行う
            self.client = OpenAI(base_url=f"{ollama_host()}/v1", api_key="ollama", timeout=3600, max_retries=0)
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
        if self.provider in ("openai", "ollama"):
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
                temperature=1.0,
                max_tokens=3000,  # 出力が止まらなくなる (Ollama の JSON モードでまれに起きる) のを防ぐ
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


def ollama_host():
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    return host if host.startswith("http") else "http://" + host


def ollama_models():
    """起動中のOllamaにインストール済みのモデル名一覧。起動していなければ None。"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{ollama_host()}/api/tags", timeout=2) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


# モデル未指定時の優先順 (大きい=高品質だが遅い)
OLLAMA_PREFERENCE = ["gemma3:27b", "gemma3:12b", "gemma3n:e4b", "gemma3:4b"]


def pick_ollama_model(installed):
    for m in OLLAMA_PREFERENCE:
        if m in installed:
            return m
    gemma = [m for m in installed if m.startswith("gemma")]
    return (gemma or installed or [None])[0]


def detect_provider():
    for key, prov in (("OPENAI_API_KEY", "openai"), ("ANTHROPIC_API_KEY", "anthropic"), ("GEMINI_API_KEY", "gemini")):
        if os.environ.get(key):
            return prov
    if ollama_models():  # APIキーが無くてもOllamaが起動していれば使う
        return "ollama"
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
        "- 機関名・人名・金額・期限・押すボタン番号・状況を1件ごとに変える\n"
        f"- 人名は具体的なありふれた名字(例: {NAME_EXAMPLES[lang]} など、毎回違うもの)を使う。「〇〇」「XXXX」などの伏せ字や「(架空)」のような注記は絶対に書かない\n"
        "- 電話番号・口座番号は読み上げない(「この番号に」「折り返し」などと表現する)\n"
        "- 書き言葉の箇条書きや「期日：」のような表記は使わず、電話で話した言葉そのままにする\n"
        "- 留守電なので相手の応答は含めず、発信者の一方的な発話のみ\n"
        "- 句読点は通常どおり付ける(ノイズは後工程で付与する)\n"
        f'- JSON {{"messages": [...]}} に{n}件の文字列を入れて出力'
    )


def parse_messages(raw: str) -> list[str]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        msgs = data.get("messages", [])
    else:
        # 途中で打ち切られた JSON: "messages": [ の後ろにある、閉じた文字列だけを回収する
        body = (raw or "").split('"messages"', 1)[-1]
        msgs = [json.loads(f'"{s}"') for s in re.findall(r'"((?:[^"\\]|\\.)*)"', body)]
    out = []
    for s in msgs:
        if not isinstance(s, str):
            continue
        s = fill_placeholders(s.strip())
        if len(s) >= 15 and not PLACEHOLDER_RE.search(s):
            out.append(s)
    return out


# 小型モデルは「〇〇区役所」「〇〇様」のような伏せ字を多用する。捨てると歩留まりが極端に下がるので、
# ありふれた地名・名字に置き換えて使う (置き換えられないものは PLACEHOLDER_RE で捨てる)
_PLACES = ["中央", "港", "北", "南", "青葉", "緑", "西", "東", "横浜", "千葉", "さいたま", "川崎", "大宮", "豊島", "世田谷"]
_SURNAMES = ["佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "松本", "井上", "木村"]
_PH = r"(?:〇〇|○○|◯◯|〇|○)"


def fill_placeholders(t: str) -> str:
    rnd = random.Random(t)  # 同じ文には同じ置き換え (再現性)
    t = re.sub(r"[（(][^）)]*架空[^）)]*[）)]", "", t)                       # (架空の人名) などの注記
    t = re.sub(r"\d{0,4}-?[XxＸ]{3,4}-?[XxＸ]{3,4}", "こちらの番号", t)         # 03-XXXX-XXXX
    t = re.sub(_PH + r"(?=(市|区|町|村|県|府|都|役所|役場))", lambda m: rnd.choice(_PLACES), t)
    t = re.sub(_PH + r"(?=(様|さま|さん|くん|ちゃん|と申します|です))", lambda m: rnd.choice(_SURNAMES), t)
    t = re.sub(_PH + r"(?=月)", lambda m: str(rnd.randint(1, 12)), t)
    t = re.sub(_PH + r"(?=日)", lambda m: str(rnd.randint(1, 28)), t)
    t = re.sub(_PH + r"(?=時)", lambda m: str(rnd.randint(9, 17)), t)
    t = re.sub(_PH + r"(?=万)", lambda m: str(rnd.randint(1, 50)), t)
    t = re.sub(_PH + r"(?=円)", lambda m: rnd.choice(["12,800", "28,000", "35,600", "48,000", "6,500"]), t)
    return re.sub(r"\s{2,}", " ", t).strip()


# 小型モデルが出しがちな伏せ字・メタ注記 (学習時のショートカットになるので除外)
PLACEHOLDER_RE = re.compile(r"〇〇|○○|◯◯|XXX|xxx|\*\*\*|架空|\[.*?\]|【|】|[:：]\s*[〇○0-9]|\(仮\)|（仮）|<.*?>")


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
    ap.add_argument("--backend", default="auto", choices=["auto", "openai", "anthropic", "gemini", "ollama", "template"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--target-per-label", type=int, default=1000)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=1.0, help="API呼び出し間の待機秒")
    ap.add_argument("--max-batches", type=int, default=0, help="0=無制限 (お試し実行用)")
    ap.add_argument("--categories", default="", help="カンマ区切りで生成対象カテゴリを限定 (例: refund_scam,relative_scam)")
    ap.add_argument("--languages", default="", help="カンマ区切りで生成対象の言語を限定 (例: en,zh)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    provider = detect_provider() if args.backend == "auto" else args.backend
    if provider is None:
        sys.exit("APIキー (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY) も起動中のOllamaも見つかりません。"
                 "Ollamaを起動するか、オフライン生成なら --backend template を指定してください。")
    backend = None if provider == "template" else LLMBackend(provider, args.model)
    source = "template" if provider == "template" else f"llm:{provider}:{backend.model}"
    print(f"backend = {source}")

    seeds = read_jsonl(RAW / "seed_data.jsonl")
    hf = read_jsonl(RAW / "hf_en_data.jsonl")
    if not seeds:
        sys.exit("seed_data.jsonl がありません。先に 02_create_seed_data.py を実行してください。")
    quotas = compute_quotas(seeds, hf + seeds, args.target_per_label)
    if args.categories:
        only = set(args.categories.split(","))
        quotas = {k: v for k, v in quotas.items() if k[0] in only}
    if args.languages:
        langs = set(args.languages.split(","))
        quotas = {k: v for k, v in quotas.items() if k[1] in langs}

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
        style = rng.choice(CATEGORY_STYLES.get(cat, STYLES[label]))
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
