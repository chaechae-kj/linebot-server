from flask import Flask, request, Response, jsonify
import os

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（本番では DB に移す）
user_state = {}

# LINE のアクセストークン設定
# 環境変数か、コード内の定数として指定してください
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "")

def reply_message(reply_token, text):
    """返信メッセージを送信する関数"""
    if not LINE_ACCESS_TOKEN:
        print("⚠️ WARNING: LINE_ACCESS_TOKEN が設定されていません。開発環境ではトークンが必要ですが、\n   検証ボタンは動作せずエラーになる可能性があります。\n   (本番デプロイ時は必ず .env やシステム環境変数から読み込んでください)")
        return "OK" # トークンなしの場合は返す（実際には動かないが、ログを残すため）

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
    # リクエストを送信。成功すれば 200 を返す
    response = requests.post(url, headers=headers, json=body)
    
    # レスポンスのステータスコードを確認（デバッグ用）
    if response.status_code != 200:
        print(f"⚠️ LINE API 通信エラー (ステータス:{response.status_code})")

def normalize_text(text):
    """
    ユーザー入力テキストを正規化する関数
    "①" -> "1", "②" -> "2", "  " -> "" など
    """
    if not text:
        return ""
    
    # 全角数字や記号を半角数字に変換する簡単なマッピング
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
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json
    
    # ★重要：LINE の「接続確認」やエラーイベントは events が空または存在しないので即 200
    if not body or "events" not in body:
        return Response("OK", status=200)

    event = body["events"][0]
    
    # イベントの種類チェック（必要に応じて拡張）
    # ここでは simplicity を優先して全てのイベントを処理対象としますが、
    # 実際には "message" イベントのみが本番のメッセージ受信です。
    if event.get("type") != "message":
        return Response("OK", status=200)

    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    
    # メッセージ内容取得（画像の場合は None または別の処理が必要ですが、
    # 今回はテキストベースのフローを想定しています。
    # 画像が来た場合はユーザーが「なし」と入力するか、別途画像処理ロジックが必要です。）
    try:
        text = event["message"]["text"]
    except KeyError:
        # テキストメッセージが来なかった場合（画像だけの場合など）
        # 今回はフローの都合上、テキスト必須としてエラー処理します
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
            reply_message(reply_token, f"{payer_map[normalized_input]} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")
        else:
            # 数字以外の入力や、誤った選択肢の場合
            reply_message(reply_token, "1〜3（または①〜③）で選択してください。\n例：① または 1\n(画像送信前にはテキスト選択が必要です)")

    # ② 画像・備考入力処理 (簡略化のためテキストとして扱う)
    elif step == "image":
        # ここでは「なし」や「旅行」といったテキストも許容し、後で利用できるように保存します。
        # もし本当に画像ファイルを送ってきたら、その処理を追加する必要がありますが、
        # 今回の要件定義（レシート画像を貼り付けて → テキスト入力）との整合性を考えると、
        # ここはユーザーのテキスト入力をそのまま受け付けるのが自然です。
        user_state[user_id]["image"] = text 
        # 念のため空文字列なら「なし」と解釈させるなどロジック可依頼
        if not text or text.strip() == "":
             reply_message(reply_token, "料金を入力してください。\n(画像ファイル自体は送信できないため、備考として'なし'と入力してください)")
        else:
             reply_message(reply_token, f"※備考：{text}\n料金を入力してください。")
        
        user_state[user_id]["step"] = "amount"

    # ③ 金額入力処理
    elif step == "amount":
        # 数字かどうかチェック（正規表現や isdigit() を使う）
        if not text.isdigit():
            reply_message(reply_token, "数字で入力してください。\n例：5000")
            return Response("OK", status=200)
        
        user_state[user_id]["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")

    # ④ 用途入力処理（完了）
    elif step == "usage":
        user_state[user_id]["usage"] = text
        
        # データを一時保存用変数に移動し、辞書から削除（本番では DB  INSERT）
        data = user_state.pop(user_id, None)
        
        if data:
            summary = (
                f"以下の内容で入力完了しました。\n"
                f"【精算者】{data['payer']}\n"
                f"【画像備考】{data['image'] or 'なし'}\n"  # 空文字なら「なし」表示
                f"【料金】{data['amount']}円\n"
                f"【用途】{data['usage']}"
            )
            reply_message(reply_token, summary)
        
        # ステップのリセット（次の購入時に再利用するため）
        # user_state[user_id] = {"step": "payer"} 

    return Response("OK", status=200)

if __name__ == "__main__":
    # 開発環境用 (本番は gunicorn や nginx で動かす必要があります)
    import requests # 忘れずにインポートしてください！
    
    # テスト時にエラーが出ないよう、トークンがなくてもサーバーは立ち上がりますが、
    # 返信はできません。検証ボタンで「送信成功」だけを確認したい場合は OK です。
    app.run(debug=True, port=5000)
