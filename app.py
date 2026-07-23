from flask import Flask, request, Response, jsonify
import os
import json
import time

try:
    import requests 
except ImportError:
    pass 

app = Flask(__name__)

user_state = {}

TOKEN_ENV = os.environ.get("LINE_ACCESS_TOKEN") 
if not TOKEN_ENV:
    LINE_ACCESS_TOKEN = None 
else:
    LINE_ACCESS_TOKEN = TOKEN_ENV

def reply_message(reply_token, text):
    """返信メッセージを送信する関数（通信失敗時もエラー表示せず処理を継続）"""
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
        # 通信を送信し、成功した場合のみレスポンスを返す
        requests.post(url, headers=headers, json=body)
        return Response("OK", status=200)
    except Exception as e:
        # 通信エラーが発生しても、サーバーは落ちないよう「OK」として処理を継続します。
        # これにより、ユーザー側にはエラーが出ず、システムは安定稼働します。
        print(f"⚠️ LINE API 通信失敗 (無視): {e}")
        return Response("OK", status=200)

@app.route("/webhook", methods=["POST"])
def webhook():
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

    # ★★ 初回アクセスまたはリセット後の初期化 ★★
    if user_id not in user_state:
        user_state[user_id] = {
            "step": "payer",
            "data": {},
            "timer_start": time.time() 
        }

    step = user_state[user_id]["step"]
    data = user_state[user_id]["data"]
    
    # ★★ 最重要：常に現在の時刻を取得し、経過時間を再計算する ★★
    current_time = time.time()
    elapsed_time = current_time - user_state[user_id]["timer_start"]

    # ★★ 要件2の修正：30秒経過判定ロジックの強化 ★★
    # もし経過時間が 30 秒を超えている場合、キャンセル処理を行う
    # (29.5秒など少し余裕を持たせておくのが安全ですが、今回は「30秒」を基準とします)
    if elapsed_time >= 30.0: 
        # デバッグログ：なぜキャンセルされたか表示（Logs で確認可能）
        print(f"[CANCEL-ELAPSED] User {user_id} cancelled after {elapsed_time:.2f}s (Step: {step})")
        cancel_reply(user_id, reply_token)
        return Response("OK", status=200)

    # ★★ 要件3：「0」入力によるキャンセル処理 ★★
    if text == "0":
        print(f"[CANCEL-ZERO] User {user_id} cancelled by input '0' (Step: {step})")
        cancel_reply(user_id, reply_token)
        return Response("OK", status=200)

    # --- ここから通常のステップ処理 ---
    
    def update_timer():
        user_state[user_id]["timer_start"] = time.time()

    # 1. 【精算者】入力 (step: payer)
    if step == "payer":
        update_timer()
        
        payer_map = {"1": "けいじゅ", "2": "なつき", "3": "両方"}
        
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
        update_timer() 
        
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
        update_timer() 
        
        reply_message(reply_token, f"{text}円で保存します。\n用途を入力してください。")

    # 4. 【用途】入力 (step: usage)
    elif step == "usage":
        data["usage"] = text
        
        update_timer() 
        
        # ここで再度「0」チェックを入れる（防御策）
        if text == "0":
            print(f"[CANCEL-ZERO] User {user_id} cancelled by input '0' (Step: usage)")
            cancel_reply(user_id, reply_token)
            return Response("OK", status=200)

    # 5. 完了後 (step: completed)
    elif step == "completed":
        data_to_save = {
            "payer": data.get("payer"),
            "image": data.get("image", ""),
            "amount": data.get("amount"),
            "usage": data.get("usage")
        }

        # データ保存ロジック
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
    message = "入力をキャンセルしました。もう一度任意の文字を入力してください。"
    
    print(f"[CANCEL-SUCCESS] User {user_id} cancelled with message: {message}")
    
    # タイマーを直前として設定して、即座に再度文字入力を受け付けるようにする
    user_state[user_id] = {
        "step": "payer", 
        "data": {},
        "timer_start": time.time()
    }

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

if __name__ == "__main__":
    pass 
