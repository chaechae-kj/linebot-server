from flask import Flask, request, Response, jsonify
import os
import json
try:
    import requests 
except ImportError:
    print("⚠️ エラー：requests ライブラリが見つかりません。\npip install requests を実行してください。")
    pass 

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書
user_state = {}

# LINE のアクセストークン設定（Render の環境変数 'LINE_ACCESS_TOKEN' から取得）
TOKEN_ENV = os.environ.get("LINE_ACCESS_TOKEN") 
if not TOKEN_ENV:
    # 本番運用時は必ず Render 設定でトークンを指定してください
    LINE_ACCESS_TOKEN = None 
else:
    LINE_ACCESS_TOKEN = TOKEN_ENV

def reply_message(reply_token, text):
    """返信メッセージを送信する関数"""
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
    try:
        requests.post(url, headers=headers, json=body)
    except Exception as e:
        # 通信エラーでもサーバーは落ちないよう無視（またはログ出力）
        # print(f"Reply failed (ignored): {e}") 
        return Response("OK", status=200)

@app.route("/", methods=["GET"])
def health():
    return Response("OK", status=200)

# ★★ データ公開エンドポイント ★★
@app.route("/expenses")
def get_expenses_json():
    """
    PC の統計処理用：保存されたデータを JSON 形式で返す API です。
    URL: https://あなたのアプリURL.onrender.com/expenses
    """
    filename = 'expenses_data.json'
    
    try:
        # ファイルが存在しない場合は空リストを返す
        if not os.path.exists(filename):
            return jsonify([])
        
        with open(filename, mode='r', encoding='utf-8') as f:
            data = json.load(f)
            
        return Response(
            json.dumps(data), 
            mimetype="application/json"
        )
    except Exception as e:
        print(f"JSON リードエラー：{e}")
        return jsonify([])

@app.route("/webhook", methods=["POST"])
def webhook():
    # JSON パース失敗をキャッチ
    try:
        body = request.get_json()
    except Exception:
        return Response("OK", status=200)

    # ★重要：イベントがない場合は即 200 (接続確認時など)
    if not body or "events" not in body:
        return Response("OK", status=200)
    
    events = body["events"]
    
    # イベントリストが空なら 200
    if len(events) == 0:
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
        # テキストメッセージが来なかった場合（画像だけの場合など）、処理をスキップ
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

    # ④ 用途入力処理（完了）＋ ★★ データ保存 ★★
    elif step == "usage":
        user_state[user_id]["usage"] = text
        
        # データ構造の作成
        data_to_save = {
            "payer": user_state[user_id].get("payer"),
            "image": user_state[user_id].get("image", ""),
            "amount": user_state[user_id].get("amount"),
            "usage": user_state[user_id].get("usage"),
            # 日時は保存しないか、必要なら追加してください
        }

        # JSON ファイルに書き込みロジック
        filename = 'expenses_data.json'
        try:
            # ファイルが存在しない場合は空リストで初期化
            if not os.path.exists(filename):
                with open(filename, mode='w', encoding='utf-8') as f:
                    json.dump([], f)
            
            # 既存データの読み込みと追加
            with open(filename, mode='r', encoding='utf-8') as f:
                records = json.load(f)
            records.append(data_to_save)
            
            # 書き戻し
            with open(filename, mode='w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存エラー：{e}")

        # ユーザーの状態リセット
        user_state.pop(user_id, None)

        if data_to_save:
            summary = (
                f"以下の内容で入力完了しました。\n"
                f"【精算者】{data_to_save['payer']}\n"
                f"【画像備考】{data_to_save['image'] or 'なし'}\n"  
                f"【料金】{data_to_save['amount']}円\n"
                f"【用途】{data_to_save['usage']}"
            )
            reply_message(reply_token, summary)

    return Response("OK", status=200)

# ★★ デプロイ時の注意 ★★
if __name__ == "__main__":
    # Render では gunicorn が使うため、この部分はコメントアウトするか削除することをお勧めします。
    # ローカルでのテスト用のみ有効にします。
    # app.run(debug=True, port=8000)
    pass 
