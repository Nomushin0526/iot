"""文字起こしテキストから詐欺らしさ (0〜1) と根拠の語句を出す。

バックエンド (CONTENT_BACKEND):
  auto       … ANTHROPIC_API_KEY → OPENAI_API_KEY → 学習済み分類器 (models/scam_clf.joblib)
               → 起動中のOllama → keyword の順で使えるもの
  anthropic / openai / classifier / ollama / keyword
外部に送るのは伏せ字処理 (mask_pii) 済みのテキストだけ。LLMが失敗したら keyword にフォールバックする。
"""
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field

from . import config


@dataclass
class ContentResult:
    score: float
    phrases: list[str] = field(default_factory=list)   # 根拠の語句 (原文の部分文字列。画面でハイライト)
    reasons: list[str] = field(default_factory=list)
    backend: str = "keyword"
    error: str = ""


# ---------------------------------------------------------------- 伏せ字 (外部送信前)
_NAME = r"[一-龥々ァ-ヶー]{1,4}"  # 漢字・カタカナの名前 (「の」などを巻き込まないよう平仮名は含めない)
PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[メール]"),
    (re.compile(r"https?://\S+"), "[URL]"),
    (re.compile(r"\+?\d[\d\-‐ー－() ]{7,}\d"), "[番号]"),                 # 電話・口座番号など
    (re.compile(r"〒?\d{3}-\d{4}"), "[郵便番号]"),
    (re.compile(rf"({_NAME})(?=(様|さま|さん|くん|君|ちゃん|殿)(?![一-龥]))"), "[名前]"),
    # 前置き語 (グループ1) は残し、続く名前だけ伏せる
    (re.compile(rf"(私は|わたしは|こちら|俺は)({_NAME})(?=(と申します|です|だけど|だよ))"), "[名前]"),
    (re.compile(rf"({_NAME})(?=と申します)"), "[名前]"),
    (re.compile(r"\b(Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+"), "[name]"),
]
# 組織名を名前と誤認して伏せると判定の手掛かりが消えるので残す
KEEP_WORDS = ("警察", "警視", "役所", "役場", "税務署", "年金", "銀行", "総務省", "大使館", "管理局", "事務所",
              "センター", "協会", "会社", "病院", "クリニック", "歯科", "学校", "保育園")


def mask_pii(text: str) -> str:
    for name in config.MASK_NAMES:
        text = text.replace(name.strip(), "[名前]")
    for pat, repl in PII_PATTERNS:
        def _sub(m):
            prefix = m.group(1) if pat.groups >= 2 and m.group(2) is not None and m.group(1) in (
                "私は", "わたしは", "こちら", "俺は") else ""
            target = m.group(0)[len(prefix):]
            return m.group(0) if any(w in target for w in KEEP_WORDS) else prefix + repl
        text = pat.sub(_sub, text)
    return text


# ---------------------------------------------------------------- キーワード判定 (フォールバック)
# (正規表現, 重み, 説明)。Whisperのひらがな化・誤変換も拾えるよう表記ゆれを入れている
KEYWORDS = [
    # Whisper実測の誤変換: 還付金→乾吹金 など (同音の漢字の組み合わせを広めに拾う)
    (r"[還乾換勧完官環][付吹府布普符譜]金?|かんぷ(きん)?|カンプ|払い戻し|払戻|過払い|給付金", 0.45, "還付金・払い戻し"),
    (r"ATM|エーティーエム|現金自動", 0.45, "ATMへの誘導"),
    (r"キャッシュカード|暗証番号|あんしょう", 0.5, "カード・暗証番号"),
    (r"未納|みのう|未払い|滞納|延滞", 0.35, "未納・未払い"),
    (r"(\d|[一二]|数)時間(後|以内)に?.{0,12}(停止|止ま|使えなく)|ご?利用.{0,6}停止|回線.{0,6}停止", 0.5, "電話停止の予告"),
    (r"([0-9０-９一二三九]|いち|きゅう)番?を?押して|ボタンを押", 0.35, "番号を押す指示"),
    (r"(口座|講座).{0,10}(犯罪|悪用|不正|凍結)|犯罪に.{0,6}(使|悪用)", 0.55, "口座の犯罪利用"),
    (r"逮捕|逮捕状|捜査|出頭|訴訟|裁判所|差し押さえ|差押", 0.4, "逮捕・訴訟の脅し"),
    (r"電子マネー|ギフトカード|プリペイド|Amazonギフト|iTunes", 0.5, "電子マネー購入の要求"),
    (r"(本日|今日)(中|まで)|至急|しきゅう|(期限|機嫌)(が|は).{0,8}(今日|本日)|今すぐ", 0.2, "期限で急かす"),
    (r"(市|区|町)?(役所|役場|仕役所)|保険年金|保健燃金|年金事務所|税務署|社会保険", 0.15, "役所・年金などを名乗る"),
    (r"(番号|電話).{0,6}変わ(った|りました)|スマホ.{0,4}落とし|携帯.{0,4}(壊|なくし|落とし)", 0.45, "番号変更(親族かたり)"),
    (r"示談金?|会社のお金|小切手|カバン.{0,6}(忘れ|なくし)", 0.45, "示談・紛失したお金"),
    (r"誰にも言わない|内緒|家族に.{0,4}(言わ|話さ)", 0.4, "口止め"),
    (r"(俺|おれ|オレ)(だけど|だよ|、俺)", 0.25, "名乗らない身内"),
    (r"大使館|领事馆|大使馆|入国管理|入管|出入境|移民局|Immigration|Embassy|customs|海关|DHL|FedEx", 0.4, "大使館・入管・国際宅配"),
    (r"包裹|签证|护照|洗钱|涉嫌|警方|按[0-9一二九]", 0.4, "中国語の詐欺定型句"),
    (r"suspend|warrant|arrest|legal action|press [0-9]", 0.4, "英語: 脅し・番号を押す指示"),
    (r"social security|SSN|identity theft|compromised", 0.45, "英語: 社会保障番号・個人情報"),
    (r"virus|malware|infected|technical support|tech support|remote access|IP address", 0.45, "英語: サポート詐欺"),
    (r"congratulations|you('ve| have) (been selected|won)|prize|gift card|reward", 0.45, "英語: 当選・ギフトカード"),
    (r"refund|overcharge|unauthorized (charge|purchase|activity)|suspicious activity", 0.35, "英語: 返金・不正利用"),
    (r"verify (your|some)|confirm your|bank account|credit card number|account number", 0.3, "英語: 個人情報の確認要求"),
]
# 正常な連絡によく出る語 (スコアを下げる)
SAFE_KEYWORDS = [
    (r"予約|診療|検診|再配達|不在連絡票|配達|点検|断水|工事のため|回覧板|面接|車検|図書館|保育園|学校", 0.35),
    (r"また(電話|連絡)するね|じゃあね|またね|ありがとう(ね|ございました)", 0.2),
]


def keyword_score(text: str) -> ContentResult:
    if not text.strip():
        return ContentResult(0.0, [], ["文字起こしが空"], "keyword")
    remain, phrases, reasons = 1.0, [], []
    for pat, w, label in KEYWORDS:
        hits = [m.group(0) for m in re.finditer(pat, text, flags=re.I)]
        if hits:
            remain *= 1 - w
            phrases += hits
            reasons.append(label)
    score = 1 - remain
    for pat, w in SAFE_KEYWORDS:
        if re.search(pat, text) and score < 0.6:  # 強い詐欺の手掛かりがあるときは下げない
            score *= 1 - w
    return ContentResult(round(score, 3), list(dict.fromkeys(phrases)), reasons, "keyword")


# ---------------------------------------------------------------- LLM判定
SYSTEM_PROMPT = """あなたは留守番電話の詐欺判定器です。
入力は留守電音声の自動文字起こし(誤変換・句読点の欠落・ひらがな化を含む)です。日本語・英語・中国語がありえます。
個人情報は [名前] [番号] などに伏せてあります。伏せ字があること自体は詐欺の根拠にしないでください。

次の観点で詐欺・不審電話らしさを 0〜1 で評価してください。
- 公的機関・通信会社・警察・大使館・宅配業者などを名乗り、停止・未納・還付・逮捕・荷物差し押さえ等で不安や期待を煽る
- ATM・キャッシュカード・暗証番号・電子マネー・送金・口座移動を求める
- 「番号を押して」「至急折り返し」「今日中」で急かす / 口止めする
- 名乗らない身内・番号変更・示談金・紛失したお金(親族かたり)
正常な例: 病院・美容室の予約確認、宅配の不在連絡、点検・工事の案内、学校や職場の事務連絡、家族・知人の日常的な連絡。

JSONのみで出力:
{"score": 0〜1の数値, "phrases": ["根拠になった語句を入力テキストからそのまま抜き出したもの", ...], "reasons": ["短い理由", ...]}"""


def _parse_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        raise ValueError(f"no JSON in response: {raw[:200]!r}")
    data = json.loads(m.group(0))
    score = float(data["score"])
    if not 0 <= score <= 1:
        raise ValueError(f"score out of range: {score}")
    return data


def _anthropic(text: str) -> str:
    import anthropic
    client = anthropic.Anthropic(max_retries=2, timeout=60)
    kwargs = dict(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_config={"effort": "low"},
    )
    # 安全分類器の拒否時に別モデルへ自動で切り替える (対応モデルのみ)
    if config.ANTHROPIC_MODEL in {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}:
        r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        r = client.messages.create(**kwargs)
    if r.stop_reason == "refusal":
        raise RuntimeError("refusal")
    return "".join(b.text for b in r.content if b.type == "text")


def _openai_compatible(text: str, base_url: str | None, api_key: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key, timeout=300, max_retries=1)
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return r.choices[0].message.content


def ollama_models() -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{config.OLLAMA_HOST.rstrip('/')}/api/tags", timeout=2) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None


def _ollama_model() -> str:
    if config.OLLAMA_MODEL:
        return config.OLLAMA_MODEL
    installed = ollama_models() or []
    for m in ("gemma3:12b", "gemma3n:e4b", "gemma3:4b"):
        if m in installed:
            return m
    if not installed:
        raise RuntimeError("Ollama has no models")
    return installed[0]


def pick_backend() -> str:
    b = config.CONTENT_BACKEND
    if b != "auto":
        return b
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    from . import classifier
    if classifier.available():  # 学習済みモデルがあれば Ollama より先に使う (Pi で数ミリ秒、Ollama は数十秒)
        return "classifier"
    if ollama_models():
        return "ollama"
    return "keyword"


def check_content(text: str, backend: str | None = None) -> ContentResult:
    backend = backend or pick_backend()
    if backend == "keyword" or not text.strip():
        return keyword_score(text)
    if backend == "classifier":  # Pi の中で完結するので伏せ字は不要
        try:
            from . import classifier
            score, top = classifier.predict(text)
            kw = keyword_score(text)  # 画面のハイライト用の語句はキーワード判定から借りる
            # 詐欺寄りと判定したときだけ、効いた文字列を根拠として出す (安全なのに「反応した」と出ると紛らわしい)
            reasons = (["学習モデルが反応した文字列: " + "・".join(f"「{t}」" for t in top)]
                       if top and score >= 0.5 else []) + kw.reasons
            return ContentResult(round(score, 3), kw.phrases, reasons[:5], "classifier")
        except Exception as e:
            fallback = keyword_score(text)
            fallback.error = f"classifier failed: {type(e).__name__}: {str(e)[:150]}"
            print(f"[content] {fallback.error} -> keyword fallback")
            return fallback
    masked = mask_pii(text)
    try:
        if backend == "anthropic":
            raw, name = _anthropic(masked), f"anthropic:{config.ANTHROPIC_MODEL}"
        elif backend == "openai":
            raw, name = _openai_compatible(masked, None, os.environ["OPENAI_API_KEY"], config.OPENAI_MODEL), f"openai:{config.OPENAI_MODEL}"
        elif backend == "ollama":
            model = _ollama_model()
            raw = _openai_compatible(masked, f"{config.OLLAMA_HOST.rstrip('/')}/v1", "ollama", model)
            name = f"ollama:{model}"
        else:
            raise ValueError(f"unknown backend {backend}")
        data = _parse_json(raw)
        # LLMが返した語句のうち、実際に原文(伏せ字前)にあるものだけ採用 (ハイライト用)
        phrases = [p for p in data.get("phrases", []) if isinstance(p, str) and p and p in text]
        return ContentResult(round(float(data["score"]), 3), phrases, [str(r) for r in data.get("reasons", [])][:5], name)
    except Exception as e:
        fallback = keyword_score(text)
        fallback.error = f"{backend} failed: {type(e).__name__}: {str(e)[:150]}"
        print(f"[content] {fallback.error} -> keyword fallback")
        return fallback
