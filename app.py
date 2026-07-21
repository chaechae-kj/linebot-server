from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "OK"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(data)
    return "OK"

if __name__ == "__main__":
    app.run()
