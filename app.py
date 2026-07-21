from flask import Flask, request
import requests
import os

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（本番はDBにする）
user_state = {}

LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")

def reply_message(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    body = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": text}
        ]
    }
    requests.post(url, headers=headers, json=body)

@app.route("/", methods=["GET"])
def health():
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json

    # ★LINEの「接続確認」は events が無いので即200を返す（最重要）
    if "events" not in body:
        return "OK"

    event = body["events"][0]
    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    text = event["message"]["text"]

    # 初回メッセージ → 入力開始
    if user_id not in user_state:
        user_state[user_id] = {"step": "payer"}
        reply_message(reply_token, "精算者を入力してください。\n①けいじゅ\n②なつき\n③両方")
        return "OK"

    step = user_state[user_id]["step"]

    # ① 精算者選択
    if step == "payer":
        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        if text not in payer_map:
            reply_message(reply_token, "1〜3で選択してください。")
            return "OK"
        user_state[user_id]["payer"] = payer_map[text]
        user_state[user_id]["step"] = "image"
        reply_message(reply_token, f"{payer_map[text]} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")
        return "OK"

    # ② 画像入力
    if step == "image":
        user_state[user_id]["image"] = text
        user_state[user_id]["step"] = "amount"
        reply_message(reply_token, "料金を入力してください。")
        return "OK"

    # ③ 金額入力
    if step == "amount":
        if not text.isdigit():
            reply_message(reply_token, "数字で入力してください。")
            return "OK"
        user_state[user_id]["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")
        return "OK"

    # ④ 用途入力
    if step == "usage":
        user_state[user_id]["usage"] = text

        data = user_state[user_id]
        user_state.pop(user_id)

        reply_message(
            reply_token,
            f"以下の内容で入力完了しました。\n"
            f"【精算者】{data['payer']}\n"
            f"【画像】{data['image']}\n"
            f"【料金】{data['amount']}円\n"
            f"【用途】{data['usage']}"
        )
        return "OK"

    return "OK"
