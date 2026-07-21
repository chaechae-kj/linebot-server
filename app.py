from flask import Flask, request, Response, jsonify
import os
import json
# requests は必須ライブラリです。pip install requests でインストールしてください
try:
    import requests 
except ImportError:
    print("⚠️ エラー：requests ライブラリが見つかりません。\n   ターミナルで 'pip install requests' を実行してください。")

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（本番では DB に移す）
# 検証環境でも動作させるためにグローバルに初期化しておきます
user_state = {}

# LINE のアクセストークン設定
# ※重要：検証ボタンではトークンが有効期限切れになっていることも多々あります。
# もしこれでエラーが出る場合は、LINE Developers から新しいアクセストークンを取得してください。
# (環境変数から取るのがベストですが、一時的にはここに書き換えても OK です)
LINE_ACCESS_TOKEN = "YPKNsFLF+o3aSlKEEt3da3FE4CgG8vRfNiO6z6Ha5i6Lg9DVAly6n8EWumFNqOqW4skWE66fFG5VeQKi3UU2NnzGUD86uIcVoOyIDRKi7b+YDcIlN5DQ39UFyc/uHr+SeYFGlUb42WsQpz8pATr6GQdB04t89/1O/w1cDnyilFU="

def reply_message(reply_token, text):
    """返信メッセージを送信する関数（エラーが起きないよう厳密に処理）"""
    # 安全のため、トークンがない場合は何も返さない（エラーを出させない）
    if not LINE_ACCESS_TOKEN:
        return Response("OK", status=200) 

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
    # 送信
    try:
        requests.post(url, headers=headers, json=body)
    except Exception as e:
        # ネットワークエラーなども無視して 200 を返す（LINE 側は成功として扱われる）
        pass

def normalize_text(text):
    """文字列を正規化する関数"""
    if not text:
        return ""
    
    full_to_half_map = {
        '①': '1', '②': '2', '③': '3',
        '1️⃣': '1', '2️⃣': '2', '3️⃣': '3' 
    }
    
    normalized = ""
    for char in text.strip():
        if char in full_to_half_map:
            normalized += full_to_half_map[char]
        else:
            normalized += char
            
    return normalized

@app.route("/", methods=["GET"])
def health():
    return Response("OK", status=200)

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json()
    except Exception:
        # JSON 解析失敗の場合は即終了（ただし 200 必須）
        return Response("OK", status=200)

    # ★最重要：イベントが存在しない場合（接続確認など）は即 200
    if not body or "events" not in body:
        return Response("OK", status=200)

    event = body["events"][0]
    
    # メッセージイベント以外は無視（ただし 200 返す）
    if event.get("type") != "message":
        return Response("OK", status=200)

    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    
    # テキスト取得（画像だけの場合などは例外が発生するため try-catch で囲む）
    try:
        text = event["message"]["text"]
    except (KeyError, TypeError):
        # 画像のみ送られてきた場合や、システムメッセージなどはテキストなし
        # その場合は即次のステップか終了するか判断する必要があるが、
        # 今回は「テキスト必須」という仕様なので、エラー処理として 200 を返す。
        # (画像入力フローの改善は後述)
        return Response("OK", status=200)

    # ユーザーの状態管理初期化・更新
    if user_id not in user_state:
        user_state[user_id] = {"step": "payer"}
    
    step = user_state[user_id]["step"]
    
    # ① 精算者選択処理
    if step == "payer":
        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        normalized_input = normalize_text(text)
        
        if normalized_input in payer_map:
            user_state[user_id]["payer"] = payer_map[normalized_input]
            user_state[user_id]["step"] = "image"
            # 画像入力指示
            reply_message(reply_token, f"{payer_map[normalized_input]} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")
        else:
            # 誤った選択肢の場合、優しく誘導
            reply_message(reply_token, "1〜3（または①〜③）で選択してください。\n例：① または 1\n(画像送信前にはテキスト選択が必要です)")

    # ② 画像・備考入力処理
    elif step == "image":
        user_state[user_id]["image"] = text 
        
        if not text or text.strip() == "":
            # 「なし」と入力された場合
            reply_message(reply_token, "料金を入力してください。\n(※画像はテキストとして受け付けられないため、備考欄に'なし'と入力しました)")
        else:
            # 何か文字が入力された場合
            reply_message(reply_token, f"※備考：{text}\n料金を入力してください。")
        
        user_state[user_id]["step"] = "amount"

    # ③ 金額入力処理
    elif step == "amount":
        if not text.isdigit():
            reply_message(reply_token, "数字で入力してください。\n例：5000")
            return Response("OK", status=200)
        
        user_state[user_id]["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")

    # ④ 用途入力処理（完了）
    elif step == "usage":
        user_state[user_id]["usage"] = text
        
        # データを辞書から取り出して、本番ではここで DB 保存を行います。
        data = user_state.pop(user_id, None)
        
        if data:
            summary = (
                f"以下の内容で入力完了しました。\n"
                f"【精算者】{data['payer']}\n"
                f"【画像備考】{data['image'] or 'なし'}\n"  
                f"【料金】{data['amount']}円\n"
                f"【用途】{data['usage']}"
            )
            reply_message(reply_token, summary)
        
        # 完了後、次の購入用に初期化（本番なら DB に保存した後なので安全）
        if user_id in user_state:
            del user_state[user_id]

    return Response("OK", status=200)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
