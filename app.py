from flask import Flask, request, Response, jsonify
import os
try:
    import requests 
except ImportError:
    print("requests module not found. Installing...")
    # Render では通常 pip install requests が事前に行われていますが、念のため。
    pass 

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（本番では DB に移す）
user_state = {}

# LINE のアクセストークン設定
# Render の Environment Variables で 'LINE_ACCESS_TOKEN' を設定していることを確認してください
TOKEN_ENV = os.environ.get("LINE_ACCESS_TOKEN") 
if not TOKEN_ENV:
    # 環境変数がなければ起動時エラーになりにくくするためにデバッグトークンを置くか、ここは空にします。
    # 検証ボタンを使う場合は、Render の設定でトークンを設定するか、ここで代入してください。
    LINE_ACCESS_TOKEN = "YOUR_TOKEN_HERE" 
else:
    LINE_ACCESS_TOKEN = TOKEN_ENV

def reply_message(reply_token, text):
    """返信メッセージを送信する関数"""
    if not LINE_ACCESS_TOKEN:
        # トークンがない場合は何もしない（200 返却）
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
    try:
        requests.post(url, headers=headers, json=body)
    except Exception as e:
        # 通信エラーでもサーバーは落ちないよう無視（またはログ出力）
        print(f"Reply failed (ignored): {e}")

@app.route("/", methods=["GET"])
def health():
    return Response("OK", status=200)

@app.route("/webhook", methods=["POST"])
def webhook():
    # ★最重要：JSON パース失敗をキャッチ
    try:
        body = request.get_json()
    except Exception as e:
        # JSON が来なかったら 200 で OK 返す（接続確認用）
        return Response("OK", status=200)

    # ★最重要：events リストが空なら即終了（接続確認時など）
    if not body or "events" not in body:
        return Response("OK", status=200)
    
    events = body["events"]
    
    # ★エラー回避：イベントリストが空なら 200
    if len(events) == 0:
        print("[Debug] No events found. Returning OK.")
        return Response("OK", status=200)

    event = events[0]
    
    # メッセージイベント以外は無視（ただし 200 返却）
    if event.get("type") != "message":
        return Response("OK", status=200)

    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    
    # メッセージ内容取得（画像の場合はテキストなしの場合あり）
    try:
        text = event["message"]["text"]
    except (KeyError, TypeError):
        # テキストメッセージが来なかった場合（画像だけの場合など）
        # 今回は「テキスト必須」という前提なので、処理をスキップして 200 を返す
        return Response("OK", status=200)

    # ユーザーの状態管理初期化・更新
    if user_id not in user_state:
        user_state[user_id] = {"step": "payer"}
    
    step = user_state[user_id]["step"]
    
    # ① 精算者選択処理
    if step == "payer":
        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        
        # 入力テキストを正規化（① -> 1 など）
        normalized_input = ""
        for char in text.strip():
            if char == '①': normalized_input += "1"
            elif char == '②': normalized_input += "2"
            elif char == '③': normalized_input += "3"
            else: normalized_input += char
        
        if normalized_input in payer_map:
            user_state[user_id]["payer"] = payer_map[normalized_input]
            user_state[user_id]["step"] = "image"
            reply_message(reply_token, f"{payer_map[normalized_input]} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")
        else:
            # 誤った選択肢の場合
            reply_message(reply_token, "1〜3（または①〜③）で選択してください。\n例：① または 1\n(画像送信前にはテキスト選択が必要です)")

    # ② 画像・備考入力処理
    elif step == "image":
        user_state[user_id]["image"] = text 
        
        if not text or text.strip() == "":
            reply_message(reply_token, "料金を入力してください。\n(※画像ファイルはテキストとして扱えないため、備考欄に'なし'と入力してください)")
        else:
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
        
        # ステップのリセット（次の購入時に再利用するため、辞書から消去済みなので OK）

    return Response("OK", status=200)

if __name__ == "__main__":
    # Render では gunicorn が使うので debug=True は外すのが推奨ですが、
    # ローカルテスト時は有効にします。Render でデプロイする際はこれを変更するか、
    # requirements.txt に gunicorn を入れて動かしてください。
    app.run(debug=False, port=8000)
