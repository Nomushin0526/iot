"""APIキーが無い環境向けのオフライン生成器 (03_generate_synthetic.py --backend template)。

カテゴリごとに「冒頭 / 本題 / 行動要求 / 締め」のスロットを組み合わせ、
機関名・金額・期限・話し方を乱数で差し替えてバリエーションを作る。
LLM生成に比べ表現の多様性は低いので、本番データはLLMバックエンドでの生成を推奨。
"""
import random

# ---------------------------------------------------------------- 共通スロット
JA_AMOUNTS = ["1万2千円", "2万8千円", "3万5千円", "4万3千円", "5万6千円", "8万円", "12万4千円", "28万円", "39万8千円", "50万円"]
JA_DEADLINE = ["本日中", "本日17時まで", "2時間以内", "本日午後3時まで", "明日の正午まで", "24時間以内", "今日の夕方まで"]
JA_SURNAMES = ["田中", "佐藤", "鈴木", "高橋", "伊藤", "渡辺", "山本", "中村", "小林", "加藤", "吉田", "山田", "松本", "井上", "木村", "林", "清水", "森", "池田", "橋本"]
BUTTONS = ["1", "2", "9", "0", "1番", "9番", "0番"]

FILLERS = ["えーと、", "あの、", "えっと、", "あー、", "んー、", ""]


def pick(rng, xs):
    return rng.choice(xs)


def styleize_ja(rng, text, style):
    """話し方スタイルの味付け。"""
    if style == "焦った口調":
        text = text.replace("ください。", "ください！", 1)
        text = pick(rng, ["もしもし、もしもし？", "あ、もしもし、", "もしもし！"]) + text
    elif style == "威圧的":
        text = text + pick(rng, ["必ず連絡するように。", "これは最終通告です。", "無視した場合の責任は負いかねます。", ""])
    elif style == "機械音声風":
        text = text + pick(rng, ["繰り返します。" + text.split("。")[0] + "。", "この電話は自動音声でお送りしています。", ""])
    return text


# ================================================================ label 1
def gen_auto_voice_gov(rng, lang, style):
    org = pick(rng, ["総務省", "総務省総合通信局", "NTT東日本", "NTT西日本", "NTTファイナンス", "NTTドコモ", "KDDI", "ソフトバンク",
                     "東京電力エナジーパートナー", "関西電力", "中部電力", "電気通信管理センター", "国民生活センター", "日本通信事業者協会"])
    intro = pick(rng, [f"こちらは{org}です。", f"{org}からの重要なお知らせです。", f"{org}よりご案内いたします。", f"こちらは{org}の自動音声サービスです。"])
    body = pick(rng, [
        f"お客様の電話番号は{pick(rng, ['2時間後', '本日中', '1時間後', '本日18時'])}に利用停止となります。",
        f"お客様のご利用料金に{pick(rng, JA_AMOUNTS)}の未納がございます。",
        "お客様の回線が不正に利用されている可能性があり、まもなくすべての通話が停止されます。",
        f"{pick(rng, ['電気料金', '通信料金', '電話料金'])}のお支払いが確認できておりません。{pick(rng, JA_DEADLINE)}に送電と通信を停止いたします。",
        "あなたの携帯電話番号が犯罪に使用された疑いがあるため、本日中に回線を停止します。",
        "お客様の契約に重大な問題が見つかりました。このままでは法的手続きに移行します。",
    ])
    act = pick(rng, [f"詳しくお聞きになりたい方は{pick(rng, BUTTONS)}を押してください。", f"オペレーターにおつなぎする場合は{pick(rng, BUTTONS)}を押してください。",
                     f"停止を解除するには{pick(rng, BUTTONS)}を押して担当者とお話しください。", f"異議がある場合は{pick(rng, BUTTONS)}を押してください。"])
    return styleize_ja(rng, intro + body + act, style)


def gen_intl_scam(rng, lang, style):
    if lang == "zh":
        org = pick(rng, ["中国驻日本大使馆", "中国领事馆", "出入境管理局", "DHL快递", "顺丰国际物流", "EMS国际快递", "国际海关", "联邦快递"])
        body = pick(rng, [
            "您有一份重要文件需要尽快领取，逾期将被退回。",
            "您有一个国际包裹因涉嫌违禁物品被海关扣留。",
            "您的签证存在异常记录，将在今天内被注销。",
            "您的护照涉嫌一起跨国洗钱案件。",
            f"您寄出的包裹中发现{pick(rng, ['多本护照', '多张银行卡', '违禁药品'])}，已被查扣。",
            "您的身份信息被他人冒用，已经涉嫌一起诈骗案件。",
        ])
        act = pick(rng, [f"查询请按{pick(rng, ['1', '9', '0'])}。", f"请立即按{pick(rng, ['1', '9', '0'])}转人工客服处理。",
                         f"请按{pick(rng, ['0', '1'])}与办案人员联系，否则将移交警方。", "请尽快回电，否则后果自负。"])
        return f"{pick(rng, ['您好，', '重要通知，', ''])}这里是{org}。{body}{act}"
    org = pick(rng, ["the Immigration Bureau", "the Chinese Embassy", "DHL Express", "FedEx International", "the Customs Office", "the Tokyo Immigration Services Agency", "Amazon Security"])
    body = pick(rng, [
        "Your residence status has been suspended due to irregularities.",
        "Your parcel has been held at customs because it contains illegal items.",
        "There is an urgent document waiting for you that must be collected within 24 hours.",
        "Your passport has been linked to an international money laundering case.",
        "Your visa will be cancelled today unless you verify your information.",
        f"An unauthorized charge of {pick(rng, ['$399', '$1,250', '¥98,000', '$799'])} was detected on your account.",
    ])
    act = pick(rng, [f"Press {pick(rng, ['1', '9', '0'])} now to speak with an officer.",
                     f"To avoid legal action, press {pick(rng, ['1', '9'])} immediately.",
                     "Please call back immediately, or a warrant will be issued.",
                     f"Press {pick(rng, ['1', '0'])} for more information."])
    return f"{pick(rng, ['This is an important message from ', 'Hello, this is ', 'Urgent notice from '])}{org}. {body} {act}"


def gen_refund(rng, lang, style):
    org = pick(rng, ["市役所の保険年金課", "区役所の介護保険課", "税務署の還付金担当", "年金事務所", "協会けんぽ", "社会保険事務所", "市役所の福祉課", "町役場の健康保険課"])
    name = pick(rng, JA_SURNAMES)
    intro = pick(rng, [f"もしもし、こちら{org}の{name}と申します。", f"こんにちは、{org}の{name}です。", f"{org}の者です。", f"あ、もしもし、{org}です。"])
    body = pick(rng, [
        f"医療費の還付金が{pick(rng, JA_AMOUNTS)}ございまして、受け取り期限が{pick(rng, JA_DEADLINE)}となっております。",
        f"保険料の払い戻しが{pick(rng, JA_AMOUNTS)}ありまして、以前に書類をお送りしたんですが期限が過ぎてしまっています。",
        f"年金の未払い分が{pick(rng, JA_AMOUNTS)}見つかりましたのでご連絡しました。",
        f"過去5年分の医療費の過払い金が見つかりました。",
        "給付金の申請がまだのようでしたのでお電話しました。",
    ])
    act = pick(rng, ["手続きはお近くのATMで簡単にできますので、携帯電話を持ってATMに行っていただき、こちらにお電話ください。",
                     "キャッシュカードをお持ちのうえ、こちらの番号に折り返しお電話ください。",
                     "受け取りには口座の確認が必要ですので、お使いの銀行名とあわせてご連絡ください。",
                     f"至急、担当の{pick(rng, JA_SURNAMES)}までご連絡ください。"])
    return styleize_ja(rng, intro + body + act, style)


def gen_fake_police(rng, lang, style):
    who = pick(rng, [f"警視庁捜査二課の{pick(rng, JA_SURNAMES)}", f"{pick(rng, ['大阪府警', '神奈川県警', '愛知県警', '福岡県警'])}の{pick(rng, JA_SURNAMES)}",
                     f"法律事務所の弁護士、{pick(rng, JA_SURNAMES)}", "民事訴訟管理センター", "警察庁のサイバー犯罪対策課", "金融庁の監督局",
                     "Amazonカスタマーセンター", "法務省管轄の訴訟窓口", "債権回収センター"])
    intro = pick(rng, [f"こちら{who}です。", f"{who}と申します。", f"{who}からのご連絡です。"])
    body = pick(rng, [
        "あなた名義の口座が詐欺グループに悪用されていることが判明しました。このままですとあなたも共犯として扱われる可能性があります。",
        "逮捕した犯人があなたのキャッシュカードを所持していました。カードの交換が必要です。",
        f"有料サイトの未払い料金{pick(rng, JA_AMOUNTS)}について、運営会社から訴訟の依頼を受けております。",
        "お客様に対して訴訟が提起されました。明日、裁判所への出頭が必要となります。",
        "あなたの携帯電話が詐欺事件に使われ、逮捕状が出ています。",
        "お客様の預金が不正に引き出される危険があります。資産を保護するため指定の口座へ移していただく必要があります。",
        f"お客様のアカウントで{pick(rng, JA_AMOUNTS)}の不正購入がありました。キャンセルには電子マネーの購入が必要です。",
    ])
    act = pick(rng, [f"{pick(rng, JA_DEADLINE)}に折り返しご連絡ください。", f"{pick(rng, JA_DEADLINE)}にご連絡がない場合、法的措置を取ります。",
                     "このことは家族にも口外しないでください。至急ご連絡を。", "取り下げの相談は担当窓口までお電話ください。"])
    return styleize_ja(rng, intro + body + act, style)


def gen_relative(rng, lang, style):
    call = pick(rng, ["母さん", "お母さん", "父さん", "お父さん", "おばあちゃん", "おじいちゃん", "ばあちゃん"])
    me = pick(rng, ["俺だけど", "俺、俺", "僕だよ", "私だけど", f"{pick(rng, ['たかし', 'けんじ', 'ゆうすけ', 'まさる', 'ひろし'])}だけど"])
    intro = f"{pick(rng, FILLERS)}もしもし、{call}？{me}。"
    body = pick(rng, [
        "スマホ落としちゃってさ、番号変わったから。この番号登録しといて。",
        "風邪ひいて声変だけど、新しい番号から掛けてる。",
        f"会社のお金が入ったカバンを電車に置き忘れちゃって、今日中に{pick(rng, ['300万円', '500万円', '150万円', '200万円'])}必要なんだ。",
        "ちょっとトラブルになっちゃって、示談金が必要なんだよ。",
        "事故を起こしちゃって、今警察にいるの。",
        f"株で損しちゃって、今日中に{pick(rng, ['100万円', '250万円', '80万円'])}払わないとまずいんだ。",
        "携帯壊れて新しくしたから、前の番号はもう使えないから消しといて。",
    ])
    act = pick(rng, ["急ぎで相談したいことがあるから、折り返してくれる？", "誰にも言わないで、すぐ電話して。", "上司の人が代わりに取りに行くから、お金用意しといて。",
                     "相手の弁護士さんから電話がいくから、言われたとおりにして。", "あとでまた電話する。", "明日ちょっと頼みたいことがあるんだ。"])
    return intro + body + act


# ================================================================ label 0
def gen_normal_auto(rng, lang, style):
    if lang == "en":
        org = pick(rng, ["Greenwood Dental", "City General Hospital", "Sunrise Hair Salon", "Tokyo Gas", "Yamato Transport", "Lakeside Veterinary Clinic"])
        body = pick(rng, [f"You have an appointment scheduled for {pick(rng, ['Monday', 'Tuesday', 'Thursday', 'Friday'])} at {pick(rng, ['10 AM', '2:30 PM', '4 PM'])}.",
                          "We attempted to deliver your package today but no one was home.",
                          "Your routine safety inspection is scheduled for next week."])
        act = pick(rng, ["If you need to reschedule, please call our office during business hours.", "To confirm, press 1. To reschedule, press 2.",
                         "You can request redelivery on our website."])
        return f"This is an automated {pick(rng, ['reminder', 'message', 'notice'])} from {org}. {body} {act} Thank you."
    if lang == "zh":
        org = pick(rng, ["樱花牙科诊所", "市立中央医院", "叶子美发沙龙", "大和运输", "东京燃气"])
        body = pick(rng, [f"提醒您{pick(rng, ['明天', '后天', '本周五'])}{pick(rng, ['上午十点', '下午三点', '下午两点半'])}有预约。", "您的包裹今天因无人在家未能送达。", "下周将进行燃气安全检查。"])
        act = pick(rng, ["如需更改时间，请在营业时间内来电。", "确认预约请按1，更改请按2。", "可通过官网申请再次配送。"])
        return f"您好，这里是{org}。{body}{act}谢谢。"
    when = f"{pick(rng, ['明日', '明後日', '今週金曜日', '来週月曜日', '12月3日'])}、{pick(rng, ['午前10時', '午前11時半', '午後2時', '午後3時', '午後4時半'])}"
    # (機関候補, 本題, 行動) を場面ごとに整合させる
    scenes = [
        (["さくら歯科クリニック", "ひかり眼科", "スマイル皮膚科", "あおば整骨院", "みどり動物病院", "市立中央病院"],
         [f"{when}のご予約の確認のお電話です。", "先日の検査結果がそろいましたので、次回の外来でご説明いたします。", "定期検診の時期が近づいておりますのでご案内いたします。"],
         ["ご予約の変更をご希望の場合は、診療時間内にお電話ください。", "ご予約を確定する場合は1を、変更をご希望の場合は2を押してください。", "キャンセルの場合は前日までにご連絡をお願いいたします。"]),
        (["ヘアサロンリーフ", "ネイルサロンルナ", "フィットネスクラブあおぞら"],
         [f"{when}からのご予約を承っております。", "ご予約いただいていたメニューの確認のご連絡です。"],
         ["キャンセルの場合は前日までにご連絡をお願いいたします。", "ご変更はアプリまたはお電話で承ります。"]),
        (["ヤマト運輸", "佐川急便", "日本郵便"],
         ["お荷物をお届けに伺いましたが、ご不在でしたので持ち帰りました。", "お預かりしているお荷物の保管期限が近づいております。"],
         ["再配達のご依頼は、不在連絡票に記載の番号またはウェブサイトからお願いいたします。", "再配達をご希望の場合は1を押してください。"]),
        (["東京ガス", "大阪ガス", "東邦ガス"],
         [f"法定の定期保安点検のご案内です。{pick(rng, ['来週火曜日の午前中', '今月25日の午後', '来週木曜日'])}に係員がお伺いします。"],
         ["ご都合が悪い場合はお手元のはがきに記載の番号までご連絡ください。", "点検は無料です。ご協力をお願いいたします。"]),
        (["水道局", "市の上下水道部"],
         [f"{pick(rng, ['明日午前9時から正午まで', '明後日の午後1時から4時まで'])}、配水管工事のため断水いたします。", "メーターの検針にお伺いしましたがご不在でした。"],
         ["ご不便をおかけしますが、ご協力をお願いいたします。", "詳しくは市のホームページをご覧ください。"]),
        (["〇〇市防災行政情報", "市役所の防災課"],
         ["本日午後、大雨警報が発表されました。今後の情報に注意してください。", "明日、地域の防災訓練を実施いたします。"],
         ["早めの避難行動を心がけてください。", "詳しくは市のホームページをご覧ください。"]),
    ]
    orgs, bodies, acts = pick(rng, scenes)
    org = pick(rng, orgs)
    intro = pick(rng, [f"こちらは{org}です。", f"{org}の自動音声によるご案内です。", f"{org}からのお知らせです。"])
    return intro + pick(rng, bodies) + pick(rng, acts)


EN_NAMES = ["Sarah", "Tom", "Emily", "David", "Mark", "Lisa", "James", "Rachel", "Kevin", "Olivia", "Daniel", "Grace"]
ZH_SURNAMES = ["王", "李", "张", "陈", "刘", "杨", "赵", "黄", "周", "吴"]


def gen_normal_business(rng, lang, style):
    if lang == "en":
        org = pick(rng, ["the Hilton Tokyo", "Park Hotel", "ABC Realty", "the property management office", "Sakura Language School",
                         "the international school", "Global Bank's Shibuya branch", "the HR department at Nexus Japan", "City Insurance"])
        intro = pick(rng, [f"Hi, this is {pick(rng, EN_NAMES)} from {org}.", f"Hello, {pick(rng, EN_NAMES)} calling from {org}.", f"Good afternoon, this is {pick(rng, EN_NAMES)} at {org}."])
        body = pick(rng, ["I'm calling to confirm your reservation for next weekend.", "I wanted to follow up on your lease renewal.",
                          "We received your documents, but one signature is missing.", "Your class schedule for next month is ready.",
                          "I'm calling about the interview you had with us last week.", "Your new card is ready to be picked up at the branch.",
                          "Your policy renewal is coming up at the end of the month."])
        act = pick(rng, ["Please give us a call back when you have a moment.", "No rush, just call me back when it's convenient.",
                         "You can also reply by email if that's easier.", "Our office is open until 6 PM on weekdays.", "Thank you, and have a great day."])
        return f"{intro} {body} {act}"
    if lang == "zh":
        org = pick(rng, ["房屋中介", "樱花日语学校", "旅行社", "物业管理处", "银行涩谷分行", "公司人事部", "保险公司", "孩子的学校"])
        intro = pick(rng, [f"您好，我是{org}的{pick(rng, ZH_SURNAMES)}{pick(rng, ['经理', '老师', '先生', '女士'])}。", f"您好，这里是{org}。"])
        body = pick(rng, ["关于您上周看的那套房子，房东已经同意了您的价格。", "关于您下个月的课程，有一点需要确认。", "您预订的行程已经确定了。",
                          "您提交的材料里少了一个签名。", "上周面试的结果出来了，想跟您说一下。", "您的新卡已经到了，可以来分行领取。", "下个月要进行楼道清扫，请留意通知。"])
        act = pick(rng, ["请您方便的时候回个电话。", "不着急，有空回电就行。", "也可以通过邮件联系我们。", "我们工作日营业到晚上六点。谢谢。"])
        return intro + body + act
    name = pick(rng, JA_SURNAMES)
    scenes = [
        (["みずほ銀行渋谷支店", "三井住友銀行新宿支店", "ゆうちょ銀行", "りそな銀行"],
         ["先日お申し込みいただいた住宅ローンの件で、書類について確認したい点がございます。", "新しいキャッシュカードのご用意ができましたので、窓口でお受け取りください。",
          "ご提出いただいた書類に一部記入漏れがございました。"]),
        (["東京海上日動", "損保ジャパン", "日本生命の担当"],
         ["自動車保険の更新時期が近づいておりますので、ご案内書類をお送りしました。", "先日ご相談いただいたプランの見積もりができました。"]),
        (["グリーン不動産管理", "さくら住宅管理"],
         ["来月、マンションの排水管清掃を予定しております。詳細はポストのお知らせをご確認ください。", "賃貸契約の更新書類をお送りしましたのでご確認ください。"]),
        (["ひまわり小学校", "さくら保育園", "あおば中学校"],
         ["明日の遠足の件で、持ち物について一点お伝えしたいことがありまして。", "お子さんが少し熱っぽいようですので、お迎えについてご相談させてください。"]),
        (["株式会社アオバの採用担当", "ミライ商事の人事部"],
         ["先日は面接にお越しいただきありがとうございました。選考結果についてお伝えしたくお電話いたしました。"]),
        (["ABC自動車整備", "トヨタモビリティの整備担当"],
         ["お預かりしているお車の車検が完了しました。明日以降いつでもお引き取りいただけます。"]),
        (["区立図書館", "市民体育館"],
         ["ご予約いただいていた本が準備できました。", "ご予約いただいた施設の利用時間についてご確認のお電話です。"]),
        (["市役所の市民課", "かもめ税理士事務所"],
         ["ご提出いただいた書類に一部記入漏れがございました。", "確定申告の書類の件で確認したい点がございます。"]),
    ]
    orgs, bodies = pick(rng, scenes)
    org = pick(rng, orgs)
    intro = pick(rng, [f"お世話になっております。{org}の{name}です。", f"いつもお世話になっております。{org}の{name}と申します。", f"もしもし、{org}の{name}です。"])
    act = pick(rng, ["お手すきの際にご連絡いただけますでしょうか。", "ご不明な点があればご連絡ください。", "また改めてお電話いたします。失礼いたします。",
                     "営業時間内にお電話いただければ幸いです。", "お手数ですが折り返しお電話いただけますか。よろしくお願いします。"])
    return intro + pick(rng, bodies) + act


def gen_normal_personal(rng, lang, style):
    if lang == "en":
        who = pick(rng, ["Mike", "Anna", "Chris", "Kate", "Mom", "Dad", "your sister", "Ben from work", "Jenny"])
        body = pick(rng, ["just calling to see if you're still up for dinner on Friday.", "the movie this weekend got moved to Sunday.",
                          "I left your umbrella at the front door.", "nothing urgent, just wanted to say hi.", "happy birthday! Hope you're having a good day.",
                          "I'm running a bit late, so let's meet at seven instead.", "did you get the photos I sent?", "the meeting tomorrow was moved to the afternoon."])
        act = pick(rng, ["Let me know when you get this.", "Call me back when you're free.", "Talk soon.", "Text me, okay? Bye.", "Anyway, see you later."])
        return f"{pick(rng, ['Hey', 'Hi', 'Hey there'])}, it's {who}. {pick(rng, ['Um, ', 'Uh, ', 'So, ', ''])}{body} {act}"
    if lang == "zh":
        who = pick(rng, ["小李", "小王", "老张", "阿明", "妈妈", "爸爸", "你姐", "同事小陈"])
        body = pick(rng, ["周末的聚会改到周日了", "明天的饭局取消了", "你上次借的书我放你门口了", "也没什么事，就是问问你最近怎么样",
                          "生日快乐呀", "我可能要晚到半小时", "明天开会改到下午了", "给你寄了点吃的，明天应该到"])
        act = pick(rng, ["回头给我回个电话。", "有空打给我。", "看到消息回我一下。", "就这样，拜拜。"])
        return f"喂，是我，{who}。{pick(rng, ['那个，', '嗯，', '就是，', ''])}{body}，{act}"
    who = pick(rng, ["お母さんだけど", "お父さんです", "おばあちゃんだよ", "田中です", "健太だけど", "隣の山田です", "美咲です", "ゆうこだよー", "鈴木です、同じ部署の"])
    intro = f"{pick(rng, ['あ、もしもし、', 'もしもし、', 'もしもしー、'])}{pick(rng, FILLERS)}{who}。"
    body = pick(rng, [
        "週末そっちに行く件なんだけど、土曜日のお昼ぐらいに着くと思うから。",
        "来週の飲み会の店決まったから、またLINEで送っとくね。",
        "昨日借りた傘返したいんだけど、今日の夜家にいる？",
        "畑で取れた野菜を送ったから、明日あたり届くと思うよ。",
        "回覧板お届けしようと思ったんですけど、お留守みたいなのでポストに入れておきますね。",
        "さっき電話もらったみたいでごめんね、ちょっと運転中で出られなかった。",
        "明日病院の付き添いの件、やっぱり10時でお願いできるかな。",
        "明日の会議資料、共有フォルダに入れておきました。",
        "誕生日おめでとう！また今度ご飯でも行こうね。",
    ])
    act = pick(rng, ["また電話するね。", "あとで連絡ちょうだい。", "じゃあまたね。", "都合悪かったら連絡ください。", "後で掛け直すね。", "失礼します。"])
    return intro + body + act


GENERATORS = {
    "auto_voice_gov": gen_auto_voice_gov,
    "intl_scam_zh_en": gen_intl_scam,
    "refund_scam": gen_refund,
    "fake_police_billing": gen_fake_police,
    "relative_scam": gen_relative,
    "normal_auto_voice": gen_normal_auto,
    "normal_business": gen_normal_business,
    "normal_personal": gen_normal_personal,
}


def generate(category, lang, style, n, rng):
    gen = GENERATORS[category]
    return [gen(rng, lang, style) for _ in range(n)]
