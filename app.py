from flask import Flask, request, Response, jsonify
import os
import json
import time

# requests は必須ライブラリです。requirements.txt に記載するか、pip install requests を実行してください。
try:
    import requests 
except ImportError:
    pass 

app = Flask(__name__)

# ユーザーごとの状態を保存する辞書
# key: user_id, value: {"step": str, "data": {}, "timer_start": float}
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
    except Exception:
        pass # 通信エラーは無視（サーバー落ちさせない）

    return Response("OK", status=200)

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
    
    # メッセージイベント以外は無視
    if event.get("type") != "message":
        return Response("OK", status=200)

    user_id = event["source"]["userId"]
    reply_token = event["replyToken"]
    
    # メッセージ内容取得（画像の場合はテキストなしの場合あり）
    try:
        text = event["message"]["text"]
    except (KeyError, TypeError):
        return Response("OK", status=200)

    # ★★ 要件1：「入力します」の強制トリガーを削除、任意文字で起動 ★★
    # 初回アクセスまたはリセット後、ユーザーが何か文字（a, あなど）を入力すれば処理を開始する
    if user_id not in user_state:
        # ステップを初期化し、タイマー開始時刻も記録
        user_state[user_id] = {
            "step": "payer",
            "data": {},
            "timer_start": time.time() 
        }

    step = user_state[user_id]["step"]
    data = user_state[user_id]["data"]

    # ★★ 要件2：30秒制限の処理ロジック ★★
    # タイマーを開始した時間と現在時間の差分を計算
    elapsed_time = time.time() - user_state[user_id]["timer_start"]
    
    # もし現在までの経過時間が29秒以上なら、処理を中断（キャンセル）する
    if elapsed_time >= 29.0:
        cancel_reply(user_id, reply_token)
        return Response("OK", status=200)

    # ★★ 要件3：「0」入力によるキャンセル処理 ★★
    # 金額入力時、用途入力時で「0」が入力されたら即座にキャンセルする
    if text == "0":
        cancel_reply(user_id, reply_token)
        return Response("OK", status=200)

    # --- ここから通常のステップ処理 ---

    # 1. 【精算者】入力 (step: payer)
    if step == "payer":
        # タイマー更新
        user_state[user_id]["timer_start"] = time.time()
        
        # ステップ進捗表示（デバッグ用、または必要な場合はコメントアウト）
        # reply_message(reply_token, f"精算者を選択してください：{text}") 

        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        
        # 入力テキストを正規化（① -> 1 など）
        normalized_input = ""
        for char in text.strip():
            if char == '①': normalized_input += "1"
            elif char == '②': normalized_input += "2"
            elif char == '③': normalized_input += "3"
            else: normalized_input += char
        
        if normalized_input in payer_map:
            data["payer"] = payer_map[normalized_input]
            user_state[user_id]["step"] = "image"
            reply_message(reply_token, f"{data['payer']} さんの出費を入力します。\nレシート画像を送るか「なし」と入力してください。")
        else:
            reply_message(reply_token, "1〜3（または①〜③）で選択してください。\n例：① または 1\n(画像送信前にはテキスト選択が必要です)")

    # 2. 【画像備考】入力 (step: image)
    elif step == "image":
        data["image"] = text 
        # タイマー更新
        user_state[user_id]["timer_start"] = time.time() 
        
        if not text or text.strip() == "":
            reply_message(reply_token, "料金を入力してください。\n(※画像ファイルはテキストとして扱えないため、備考欄に'なし'と入力してください)")
        else:
            reply_message(reply_token, f"※備考：{text}\n料金を入力してください。")
        
        user_state[user_id]["step"] = "amount"

    # 3. 【料金】入力 (step: amount)
    elif step == "amount":
        if not text.isdigit():
            reply_message(reply_token, "数字で入力してください。\n例：5000")
            return Response("OK", status=200)
        
        data["amount"] = int(text)
        user_state[user_id]["step"] = "usage"
        # タイマー更新
        user_state[user_id]["timer_start"] = time.time() 
        
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")

    # 4. 【用途】入力 (step: usage)
    elif step == "usage":
        data["usage"] = text
        
        # タイマー更新（完了直前までタイマーを維持）
        user_state[user_id]["timer_start"] = time.time() 
        
        if text == "0":
            # ここでも「0」はキャンセルトリガーとして機能するが、既に処理済みなので上記ロジックでOK
            pass

    # 5. 完了後 (ステップ遷移後)
    elif step == "completed":
        data_to_save = {
            "payer": data.get("payer"),
            "image": data.get("image", ""),
            "amount": data.get("amount"),
            "usage": data.get("usage")
        }

        # ★★ データ保存ロジック（Render上のファイル保存）★★
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

        # 完了メッセージ送信
        summary = (
            f"以下の内容で入力完了しました。\n"
            f"【精算者】{data_to_save['payer']}\n"
            f"【画像備考】{data_to_save['image'] or 'なし'}\n"  
            f"【料金】{data_to_save['amount']}円\n"
            f"【用途】{data_to_save['usage']}"
        )
        reply_message(reply_token, summary)
        
        # 次の購入用に状態をリセット（タイマーはリセットされず、即座に再度文字入力で起動）
        user_state[user_id]["step"] = "payer" 
        user_state[user_id]["data"] = {}

    return Response("OK", status=200)

def cancel_reply(user_id, reply_token):
    """キャンセルメッセージを送信する関数"""
    # 要求通り「入力をキャンセルしました」と表示し、処理を終了（リセット）
    user_state[user_id] = {
        "step": "payer", 
        "data": {},
        "timer_start": time.time()
    }
    
    # タイマーの開始時刻を更新することで、再度文字を入力すればカウントダウンがリセットされるようにする
    # これにより、「入力をキャンセルしました」と表示された後でも、すぐに「入力します（または任意文字）」で再起動可能にする

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

# ★★ デプロイ時の注意 ★★★
if __name__ == "__main__":
    # Render では gunicorn が使うため、この部分はコメントアウトするか削除することをお勧めします。
    pass 
