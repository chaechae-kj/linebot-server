from flask import Flask, request

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（本番はDBにする）
user_state = {}

@app.route("/", methods=["GET"])
def health():
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json
    event = body["events"][0]
    user_id = event["source"]["userId"]

    # 初回メッセージ → 入力開始
    if user_id not in user_state:
        user_state[user_id] = {"step": "payer"}
        return reply("精算者を入力してください。\n①けいじゅ\n②なつき\n③両方")

    step = user_state[user_id]["step"]
    text = event["message"]["text"]

    # ① 精算者選択
    if step == "payer":
        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        if text not in payer_map:
            return reply("1〜3で選択してください。")
        user_state[user_id]["payer"] = payer_map[text]
        user_state[user_id]["step"] = "image"
        return reply(f"{payer_map[text]} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")

    # ② 画像入力
    if step == "image":
        user_state[user_id]["image"] = text  # 本番は画像URL保存
        user_state[user_id]["step"] = "amount"
        return reply("料金を入力してください。")

    # ③ 金額入力
    if step == "amount":
        if not text.isdigit():
            return reply("数字で入力してください。")
        user_state[user_id]["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        return reply(f"{text}円で保存します。\n用途を入力してください。")

    # ④ 用途入力
    if step == "usage":
        user_state[user_id]["usage"] = text

        # ここでDB保存（本番）
        data = user_state[user_id]
        user_state.pop(user_id)

        return reply(
            f"以下の内容で入力完了しました。\n"
            f"【精算者】{data['payer']}\n"
            f"【画像】{data['image']}\n"
            f"【料金】{data['amount']}円\n"
            f"【用途】{data['usage']}"
        )

    return reply("エラーが発生しました。")

def reply(text):
    # Render では print がログに出るだけなので、LINE返信は後で実装する
    print("BOT返信:", text)
    return "OK"
