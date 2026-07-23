from flask import Flask, request, Response, jsonify
import os
import json
import time
try:
    import requests 
except ImportError:
    print("⚠️ エラー：requests ライブラリが見つかりません。\npip install requests を実行してください。")
    pass 

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書（ステップ、タイマー開始時刻）
user_state = {}

# LINE のアクセストークン設定（Render の環境変数 'LINE_ACCESS_TOKEN' から取得）
TOKEN_ENV = os.environ.get("LINE_ACCESS_TOKEN") 
if not TOKEN_ENV:
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
    except Exception:
        pass # 通信エラーは無視（サーバー落ちさせない）

    return Response("OK", status=200)

# ★★ データ公開エンドポイント ★★
@app.route("/expenses")
def get_expenses_json():
    filename = 'expenses_data.json'
    
    try:
        if not os.path.exists(filename):
            return jsonify([])
        
        with open(filename, mode='r', encoding='utf-8') as f:
            data = json.load(f)
            
        return Response(json.dumps(data), mimetype="application/json")
    except Exception:
        return jsonify([])

@app.route("/webhook", methods=["POST"])
def webhook():
    # JSON パース失敗をキャッチ
    try:
        body = request.get_json()
    except Exception:
        return Response("OK", status=200)

    if not body or "events" not in body or len(body["events"]) == 0:
        return Response("OK", status=200)

    event = body["events"][0]
    
    if event.get("type") != "message":
        return Response("OK", status=200)

    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    
    # メッセージ内容取得（画像の場合はテキストなしの場合あり）
    try:
        text = event["message"]["text"]
    except (KeyError, TypeError):
        return Response("OK", status=200)

    # ★★ 新規：トリガー「入力します」の検知 ★★
    if not text or "入力します" not in text:
        # ユーザーがチャット画面を開いてくれたら、最初の誘導メッセージを送信する
        user_state[user_id] = {"step": "payer", "timer_start": None}
        reply_message(reply_token, "家計簿に入力したいですか？\n『入力します』と書いてください。")
        return Response("OK", status=200)

    # 初期化（リセット）処理：ユーザーを辞書から消すか、新しい状態にする場合も考慮
    if user_id not in user_state:
        user_state[user_id] = {"step": "payer"}
    
    step = user_state[user_id]["step"]

    # ★★ 新規：タイマーの更新ロジック ★★
    # タイマーが既に動いている場合、その時間を更新（リセット）する
    if step != "initial":
        current_time = time.time()
        elapsed = current_time - user_state[user_id].get("timer_start", current_time)
        remaining = 30.0 - elapsed
        
        # 残り時間が 29 秒以下なら、タイマーが切れているとみなす（少しの猶予）
        if remaining < 29:
            cancel_reply(user_id, reply_token, "入力をキャンセルしました（時間切れ）。もう一度『入力します』から始めましょう。")
            return Response("OK", status=200)

    # ★★ 新規：タイマーの開始（30秒） ★★
    if step == "payer":
        user_state[user_id]["step"] = "payer"
        user_state[user_id]["timer_start"] = time.time() # タイマー開始
        
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

    elif step == "image":
        user_state[user_id]["image"] = text 
        # タイマーを更新
        user_state[user_id]["timer_start"] = time.time() 
        
        if not text or text.strip() == "":
            reply_message(reply_token, "料金を入力してください。\n(※画像ファイルはテキストとして扱えないため、備考欄に'なし'と入力してください)")
        else:
            reply_message(reply_token, f"※備考：{text}\n料金を入力してください。")
        
        user_state[user_id]["step"] = "amount"

    elif step == "amount":
        if not text.isdigit():
            # 数字以外（キャンセル用「0」など）の場合
            reply_message(reply_token, "数字で入力してください。\n例：5000")
            return Response("OK", status=200)
        
        # ★★ 新規：「0」が入力された場合のチェック ★★
        if text == "0":
            cancel_reply(user_id, reply_token, "入力をキャンセルしました（'0'と入力されました）。")
            return Response("OK", status=200)

        user_state[user_id]["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        
        # タイマーを更新
        user_state[user_id]["timer_start"] = time.time() 
        
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")

    elif step == "usage":
        user_state[user_id]["usage"] = text
        
        # ★★ 新規：「0」が入力された場合のチェック ★★
        if text == "0":
            cancel_reply(user_id, reply_token, "入力をキャンセルしました（'0'と入力されました）。")
            return Response("OK", status=200)

        data_to_save = {
            "payer": user_state[user_id].get("payer"),
            "image": user_state[user_id].get("image", ""),
            "amount": user_state[user_id].get("amount"),
            "usage": user_state[user_id].get("usage")
        }

        # JSON ファイルに書き込みロジック
        filename = 'expenses_data.json'
        try:
            if not os.path.exists(filename):
                with open(filename, mode='w', encoding='utf-8') as f:
                    json.dump([], f)
            
            with open(filename, mode='r', encoding='utf-8') as f:
                records = json.load(f)
            records.append(data_to_save)
            
            with open(filename, mode='w', encoding='utf-8') as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存エラー：{e}")

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

def cancel_reply(user_id, reply_token, message):
    """キャンセルメッセージを送信する関数"""
    # ステップを初期化して、ユーザーを次のリセット用に待機させる
    user_state[user_id] = {"step": "payer"} 

if __name__ == "__main__":
    # Render では gunicorn が使うため、この部分はコメントアウトするか削除することをお勧めします。
    pass 
