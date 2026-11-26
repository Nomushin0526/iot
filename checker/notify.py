"""Slack Incoming Webhook で家族に通知する (標準ライブラリのみ)。"""
import json
import urllib.request

from . import config
from .number_check import mask
from .risk import LEVEL_JA


def build_message(result: dict, manual: bool = False) -> str:
    number = result.get("number", "")
    shown = number if config.SLACK_SHOW_NUMBER else mask(number, show_last=2)
    icon = {"red": ":rotating_light:", "yellow": ":warning:", "green": ":white_check_mark:"}[result["level"]]
    lines = [
        f"{icon} *留守電チェック: 危険度 {result['risk']}/9 ({LEVEL_JA[result['level']]})*"
        + ("  ※ボタンから手動通知" if manual else ""),
        f"番号: {shown or '不明'}  ({' / '.join(result.get('number_reasons', [])) or '-'})",
    ]
    if result.get("content_reasons"):
        lines.append("内容: " + " / ".join(result["content_reasons"][:4]))
    if result.get("phrases"):
        lines.append("気になる語句: " + "、".join(f"「{p}」" for p in result["phrases"][:5]))
    if result["level"] == "red":
        lines.append("折り返す前に、本人に電話して確認してください。")
    return "\n".join(lines)


def send_slack(text: str) -> tuple[bool, str]:
    if not config.SLACK_WEBHOOK_URL:
        return False, "SLACK_WEBHOOK_URL が未設定"
    req = urllib.request.Request(
        config.SLACK_WEBHOOK_URL,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    # テスト送信: リポジトリ直下で `python -m checker.notify`
    # .env の SLACK_WEBHOOK_URL に、危険度8の例と同じ形のメッセージを1通送る
    sample = {
        "risk": 8, "level": "red", "number": "+8612345678",
        "number_reasons": ["国際電話 (国番号 +861…)"],
        "content_reasons": ["還付金・払い戻し", "ATMへの誘導"],
        "phrases": ["還付金", "ATM", "本日中"],
    }
    text = "【テスト送信】詐欺チェッカーからの通知テストです\n" + build_message(sample)
    print(text, "\n")
    ok, info = send_slack(text)
    print("送信成功" if ok else "送信失敗", f"({info})")
