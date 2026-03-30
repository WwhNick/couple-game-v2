import os
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

if __name__ == "__main__":
    print(">>> 正在运行文件:", os.path.abspath(__file__))
    print(">>> 当前工作目录:", os.getcwd())
    app.run(debug=True, port=5001)
