"""電話番号の判定: 危険番号リスト (CSV) との照合 + ルール。スコアは 0〜1。"""
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NumberResult:
    number: str            # 正規化後 (例: 0501234567, +12025550100)
    score: float
    reasons: list[str] = field(default_factory=list)
    kind: str = "unknown"  # international / ip_phone / mobile / toll_free / landline / hidden / invalid


def normalize(raw: str) -> str:
    """全角→半角、記号除去。+81 は国内表記 (0始まり) に直す。"""
    s = (raw or "").translate(str.maketrans("０１２３４５６７８９＋－ー（）　", "0123456789+--() "))
    s = s.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if plus:
        if digits.startswith("81"):
            return "0" + digits[2:]
        return "+" + digits
    return digits


def mask(number: str, show_last: int = 0) -> str:
    """ログ・通知用に伏せる。ルール判定に使う先頭(国番号/050等)だけ残す。"""
    n = normalize(number)
    if not n:
        return ""
    head = 3 if n.startswith("+") else 4 if n[:2] in ("05", "01", "00") else 3
    tail = n[-show_last:] if show_last else ""
    return n[:head] + "*" * max(0, len(n) - head - len(tail)) + tail


def load_blacklist(path: Path) -> dict[str, str]:
    """CSV (列: number, note)。# で始まる行はコメント。"""
    out = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        rows = (line for line in f if line.strip() and not line.lstrip().startswith("#"))
        for row in csv.DictReader(rows):
            n = normalize(row.get("number", ""))
            if n:
                out[n] = (row.get("note") or "").strip()
    return out


def check_number(raw: str, blacklist: dict[str, str]) -> NumberResult:
    n = normalize(raw)
    rules: list[tuple[float, str, str]] = []  # (score, kind, reason)

    if not n:
        return NumberResult("", 0.5, ["番号が不明 (非通知・未入力)"], "hidden")
    if n in blacklist:
        note = blacklist[n]
        rules.append((1.0, "blacklist", "危険番号リストに一致" + (f" ({note})" if note else "")))

    if n.startswith("+"):
        rules.append((0.8, "international", f"国際電話 (国番号 +{n[1:4]}…)"))
    elif n.startswith("010"):
        rules.append((0.8, "international", "国際電話 (010発信)"))
    elif n.startswith("050"):
        rules.append((0.5, "ip_phone", "050 (IP電話。詐欺で使われやすい)"))
    elif n.startswith(("0120", "0800")):
        rules.append((0.2, "toll_free", "フリーダイヤル"))
    elif n.startswith(("070", "080", "090")):
        rules.append((0.1, "mobile", "携帯電話"))
    elif n.startswith("0"):
        rules.append((0.1, "landline", "固定電話"))

    if not n.startswith("+") and not n.startswith("010") and not (10 <= len(n) <= 11):
        rules.append((0.3, "invalid", f"国内番号として桁数が不自然 ({len(n)}桁)"))

    if not rules:
        return NumberResult(n, 0.3, ["判別できない番号"], "unknown")
    score = max(r[0] for r in rules)
    kind = max(rules, key=lambda r: r[0])[1]
    return NumberResult(n, score, [r[2] for r in rules], kind)
