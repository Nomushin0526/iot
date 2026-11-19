"""PC上で動くテスト (GPIOは gpiozero の模擬ピン)。リポジトリ直下で `python -m pytest tests -q`"""
import os

os.environ["USE_HARDWARE"] = "0"
os.environ["CONTENT_BACKEND"] = "keyword"  # テストで外部APIを呼ばない
os.environ["SLACK_WEBHOOK_URL"] = ""

import pytest
from gpiozero import Device

from checker import config, hardware as hw
from checker.content_check import keyword_score, mask_pii
from checker.number_check import check_number, load_blacklist, mask, normalize
from checker.risk import combine, level


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_CSV", tmp_path / "log.csv")
    monkeypatch.setattr(config, "RESULTS_JSONL", tmp_path / "results.jsonl")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    yield
    if Device.pin_factory is not None:
        Device.pin_factory.reset()


# ---------------------------------------------------------------- 表示のビット割り当て
def test_glyph_bits_match_wiring():
    # 1 = b,c → Q7,Q1 / 8 = 全セグ → Q1〜Q7 (Q0 は未使用)
    assert hw.glyph_bits("1") == (1 << 7) | (1 << 1)
    assert hw.glyph_bits("8") == 0b11111110
    assert hw.glyph_bits("-") == 1 << 4  # g = Q4


def test_bar_bits_order():
    assert hw.bar_bits(0) == 0
    assert hw.bar_bits(1) == 1 << 7                     # 1段目 = Q7
    assert hw.bar_bits(2) == (1 << 7) | (1 << 6)
    assert hw.bar_bits(7) == 0b11111110                 # Q7〜Q1
    assert [hw.risk_to_bar(r) for r in (0, 4, 9)] == [0, 3, 7]


def test_shift_register_sends_q7_first():
    hw.use_mock_pins()
    sr = hw.ShiftRegister(**hw.SEG_SR)
    sent = []
    orig_on = sr.sck.on
    sr.sck.on = lambda: (sent.append(int(sr.ser.value)), orig_on())
    sr.write(0b10000001)  # Q7 と Q0
    assert sent == [1, 0, 0, 0, 0, 0, 0, 1]
    assert sr.value == 0b10000001
    sr.close()


def test_panel_show_risk_colors():
    hw.use_mock_pins()
    p = hw.Panel()
    p.show_risk(9)
    assert p.rgb.color == (1, 0, 0) and p.bar.value == hw.bar_bits(7) and p.seg.value == hw.glyph_bits("9")
    p.show_risk(5)
    assert tuple(round(c, 1) for c in p.rgb.color) == (1, 0.6, 0)
    p.show_risk(1)
    assert p.rgb.color == (0, 1, 0)
    p.close()


def test_button_short_press_and_hold():
    hw.use_mock_pins()
    events = []
    b = hw.NotifyButton(on_press=lambda: events.append("press"), on_hold=lambda: events.append("hold"), hold_time=0.1)
    pin = Device.pin_factory.pin(hw.NOTIFY_BUTTON)
    pin.drive_low(); pin.drive_high()          # 短押し (pull_up なので押す=LOW)
    import time
    pin.drive_low(); time.sleep(0.3); pin.drive_high()  # 長押し
    time.sleep(0.05)
    assert events == ["press", "hold"]
    b.close()


# ---------------------------------------------------------------- 番号判定
def test_normalize_and_mask():
    assert normalize("＋８１ ９０－１２３４－５６７８") == "09012345678"
    assert normalize("+1 (202) 555-0100") == "+12025550100"
    assert mask("050-1234-5678") == "0501*******"
    assert mask("090-1234-5678", show_last=2) == "090******78"


def test_number_rules(tmp_path):
    bl = tmp_path / "bl.csv"
    bl.write_text("# comment\nnumber,note\n03-1111-2222,テスト\n", encoding="utf-8")
    blacklist = load_blacklist(bl)
    assert check_number("0311112222", blacklist).kind == "blacklist"
    assert check_number("+86 10 1234 5678", {}).kind == "international"
    assert check_number("010-86-1234", {}).kind == "international"
    assert check_number("+81 3 1234 5678", {}).kind == "landline"   # +81 は国内
    assert check_number("050-1234-5678", {}).score == 0.5
    assert check_number("", {}).kind == "hidden"


# ---------------------------------------------------------------- 内容判定
def test_mask_pii_keeps_organizations():
    t = "警視庁の田中と申します。山田様の口座が犯罪に悪用されています。090-1234-5678まで連絡を。"
    m = mask_pii(t)
    assert "田中" not in m and "山田" not in m and "090" not in m
    assert "警視庁" in m and "口座が犯罪に悪用" in m


@pytest.mark.parametrize("text,scam", [
    ("こちら市役所です。医療費の還付金があります。本日中にATMで手続きしてください。", True),
    ("こちらはそうむしょうです お客様の電話は2時間後に停止します 1番を押してください", True),  # ASRノイズあり
    ("もしもし俺だけど、スマホ落としちゃって番号変わったから。誰にも言わないで。", True),
    ("您好，这里是DHL快递。您的包裹涉嫌违禁物品，请按1。", True),
    # whisper base の実際の出力 (還付金→乾吹金, 期限→機嫌 の誤変換あり)
    ("こちらは仕役所の保健燃金化です。医療費の乾吹金が28000円ございます。受け取り機嫌は本日までです。お近くのATMで手続きをお願いします。", True),
    ("こちらは桜四角リニックです。明日午後3時の5夜役の確認のお電話です。変更をご規模の場合は心量時間内にお電話ください。", False),
    ("さくら歯科です。明日午後3時のご予約の確認です。変更は診療時間内にお電話ください。", False),
    ("あ、もしもしお母さんだけど、週末そっちに行くね。また電話するね。", False),
])
def test_keyword_score(text, scam):
    r = keyword_score(text)
    assert (r.score >= 0.5) == scam, (r.score, r.reasons)
    if scam:
        assert r.phrases and all(p in text for p in r.phrases)


def test_risk_combine():
    assert combine(0.1, 0.0) == 0
    assert combine(0.1, 0.95) >= 8        # 内容だけで高リスク
    assert combine(1.0, 0.0, blacklisted=True) == 8
    assert combine(0.8, None) == 7        # 番号のみ: 国際電話
    assert [level(r) for r in (3, 4, 6, 7)] == ["green", "yellow", "yellow", "red"]


# ---------------------------------------------------------------- サーバー (音声なし)
def test_server_number_only_and_page():
    from fastapi.testclient import TestClient
    from checker import server
    with TestClient(server.app) as client:
        r = client.post("/check", data={"number": "+86 10 1234 5678"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["risk"] == 7 and "危険度 7/9" in body["message"]
        assert server.HW.panel.seg.value == hw.glyph_bits("7")   # 7セグに反映
        page = client.get("/").text
        assert "危険度 7/9" in page
        assert client.get("/api/results").json()[0]["number_kind"] == "international"


def test_server_token(monkeypatch):
    from fastapi.testclient import TestClient
    from checker import server
    monkeypatch.setattr(config, "CHECK_TOKEN", "secret")
    with TestClient(server.app) as client:
        assert client.post("/check", data={"number": "0312345678"}).status_code == 401
        assert client.post("/check", data={"number": "0312345678", "token": "secret"}).status_code == 200
        assert client.post("/check", data={"number": "0312345678"}, headers={"X-Token": "secret"}).status_code == 200


def test_keypad_flow():
    from fastapi.testclient import TestClient
    from checker import server
    import time
    with TestClient(server.app):
        h = server.HW
        for k in "05012345678":
            h.on_key(k)
        h.on_key("D")
        h.on_key("8")
        assert h.buffer == "05012345678"
        h.on_key("#")
        for _ in range(50):
            if h.last_result:
                break
            time.sleep(0.05)
        assert h.last_result["number_kind"] == "ip_phone" and h.last_result["source"] == "keypad"
        h.on_key("*")
        assert h.buffer == ""


def test_matches_hw_test_wiring():
    """部品テスト用の hw_test.py と本体のピン・割り当てが食い違っていないか (配線変更時の取り違え防止)。"""
    import hw_test as t
    assert (t.SEG_SER, t.SEG_RCK, t.SEG_SCK) == tuple(hw.SEG_SR.values())
    assert (t.BAR_SER, t.BAR_RCK, t.BAR_SCK) == tuple(hw.BAR_SR.values())
    assert (t.RGB_R, t.RGB_G, t.RGB_B) == tuple(hw.RGB_PINS.values())
    assert t.BUTTON_PIN == hw.NOTIFY_BUTTON
    assert tuple(t.KEY_ROWS) == hw.KEYPAD_ROWS and tuple(t.KEY_COLS) == hw.KEYPAD_COLS
    assert tuple(map(tuple, t.KEYS)) == hw.KEYPAD_KEYS
    assert t.SEG_TO_Q == hw.SEG_TO_Q
    assert {str(k): v for k, v in t.DIGIT_SEGS.items()} == {k: hw.GLYPHS[k] for k in "0123456789"}
    assert tuple(t.BAR_ORDER_Q) == hw.BAR_ORDER_Q
    assert [round(r * 7 / 9) for r in range(10)] == [hw.risk_to_bar(r) for r in range(10)]


def test_dotenv_strips_inline_comments(tmp_path, monkeypatch):
    """.env.example の「KEY=値   # 説明」形式を正しく読めるか (以前はコメントまで値に入っていた)。"""
    from checker.config import _load_dotenv
    for k in ("WHISPER_MODEL", "USE_HARDWARE", "Q1", "Q2", "URL"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "WHISPER_MODEL=small              # tiny / base / small\n"
        "USE_HARDWARE=1                   # 0 で GPIO を使わない\n"
        'Q1="a # not comment"   # comment\n'
        "Q2='x'\n"
        "URL=https://hooks.slack.com/services/T0/B0/abc#frag\n", encoding="utf-8")
    _load_dotenv(env)
    assert os.environ["WHISPER_MODEL"] == "small"
    assert os.environ["USE_HARDWARE"] == "1"
    assert os.environ["Q1"] == "a # not comment"
    assert os.environ["Q2"] == "x"
    assert os.environ["URL"].endswith("abc#frag")   # 空白なしの # は値の一部


def test_env_example_parses_cleanly(monkeypatch):
    """.env.example をそのままコピーした .env で、ハードウェア有効・Whisper small になること。"""
    from checker.config import ROOT, _load_dotenv, env_bool
    for k in ("WHISPER_MODEL", "USE_HARDWARE", "NOTIFY_THRESHOLD", "PORT", "KEEP_AUDIO"):
        monkeypatch.delenv(k, raising=False)
    _load_dotenv(ROOT / ".env.example")
    assert os.environ["WHISPER_MODEL"] == "small"
    assert env_bool("USE_HARDWARE") is True
    assert os.environ["NOTIFY_THRESHOLD"] == "7" and os.environ["PORT"] == "8000"


def test_find_busy_pins_reports_pin_in_use():
    hw.use_mock_pins()
    from gpiozero import DigitalOutputDevice
    d = DigitalOutputDevice(8)  # バーグラフ用 RCK を先に使用中にしておく
    busy = hw.find_busy_pins()
    assert any(b.startswith("GPIO8 ") and "SPI" in b for b in busy)
    assert len(busy) == 1
    d.close()
