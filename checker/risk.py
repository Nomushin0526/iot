"""番号スコアと内容スコアを危険度 0〜9 に統合する。"""

CONTENT_WEIGHT = 0.75   # 話の内容を重視 (番号だけでは知らない正規の番号も多いため)
NUMBER_WEIGHT = 0.25


def combine(number_score: float, content_score: float | None, blacklisted: bool = False) -> int:
    """
    - 音声なし (キーパッド入力など): 番号スコアだけで判定
    - 音声あり: 内容 75% + 番号 25%。ただし内容スコアそのものを下限にする
      (話の内容がはっきり詐欺なら、普通の番号からでも危険と出す)
    - 危険番号リスト一致は最低でも 8
    """
    if content_score is None:
        combined = number_score
    else:
        combined = max(CONTENT_WEIGHT * content_score + NUMBER_WEIGHT * number_score, content_score)
    risk = round(max(0.0, min(1.0, combined)) * 9)
    if blacklisted:
        risk = max(risk, 8)
    return risk


def level(risk: int) -> str:
    """安全=green (0〜3) / 注意=yellow (4〜6) / 危険=red (7〜9)。表示色と同じ区分。"""
    return "green" if risk <= 3 else "yellow" if risk <= 6 else "red"


LEVEL_JA = {"green": "安全", "yellow": "注意", "red": "危険"}
