import os
import json
import random
import string
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "game.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
POSTER_FOLDER = os.path.join(BASE_DIR, "generated_posters")
QUESTIONS_FILE = os.path.join(BASE_DIR, "questions.json")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "couple-secret-key")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(POSTER_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["POSTER_FOLDER"] = POSTER_FOLDER


def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["choice_questions"], data["bonus_prompts"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT UNIQUE,
        p1_name TEXT,
        p2_name TEXT,
        p1_photo TEXT,
        p2_photo TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT,
        player_no INTEGER,
        question_id INTEGER,
        answer TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS bonus_text (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT,
        player_no INTEGER,
        prompt_id INTEGER,
        content TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_code TEXT UNIQUE,
        match_score INTEGER,
        bonus_score INTEGER,
        total_score INTEGER,
        summary TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


QUESTIONS, BONUS_PROMPTS = load_questions()
init_db()


def gen_room_code(length=6):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def save_photo(file_storage):
    if not file_storage or file_storage.filename == "":
        return ""
    ext = os.path.splitext(file_storage.filename)[1]
    fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}{ext}"
    path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    file_storage.save(path)
    return fname


def calc_result(room_code):
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT * FROM answers WHERE room_code=?", (room_code,))
    rows = c.fetchall()

    p1, p2 = {}, {}
    for r in rows:
        if r["player_no"] == 1:
            p1[r["question_id"]] = r["answer"]
        elif r["player_no"] == 2:
            p2[r["question_id"]] = r["answer"]

    match_score = 0
    for q in QUESTIONS:
        qid = q["id"]
        if p1.get(qid) and p2.get(qid) and p1[qid] == p2[qid]:
            match_score += 10

    c.execute("SELECT * FROM bonus_text WHERE room_code=?", (room_code,))
    b_rows = c.fetchall()
    non_empty = sum(1 for x in b_rows if (x["content"] or "").strip())
    bonus_score = min(40, non_empty * 7)

    total_score = match_score + bonus_score
    if total_score >= 85:
        summary = "灵魂伴侣级默契！你们彼此懂得很深，继续甜甜地走下去吧～"
    elif total_score >= 65:
        summary = "高默契情侣！你们已经非常合拍，再多一点表达会更完美～"
    elif total_score >= 45:
        summary = "稳定升温中！你们有很多共同点，也有值得探索的新空间～"
    else:
        summary = "潜力股情侣！默契需要时间培养，认真倾听会让爱更浓～"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("SELECT id FROM results WHERE room_code=?", (room_code,))
    old = c.fetchone()

    if old:
        c.execute("""
            UPDATE results
            SET match_score=?, bonus_score=?, total_score=?, summary=?, created_at=?
            WHERE room_code=?
        """, (match_score, bonus_score, total_score, summary, now, room_code))
    else:
        c.execute("""
            INSERT INTO results (room_code, match_score, bonus_score, total_score, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (room_code, match_score, bonus_score, total_score, summary, now))

    conn.commit()
    conn.close()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create", methods=["GET", "POST"])
def create_room():
    if request.method == "POST":
        p1_name = request.form.get("p1_name", "").strip()
        p2_name = request.form.get("p2_name", "").strip()

        if not p1_name or not p2_name:
            flash("请填写双方昵称")
            return redirect(url_for("create_room"))

        p1_photo = save_photo(request.files.get("p1_photo"))
        p2_photo = save_photo(request.files.get("p2_photo"))

        conn = get_conn()
        c = conn.cursor()

        room_code = gen_room_code()
        while True:
            c.execute("SELECT id FROM rooms WHERE room_code=?", (room_code,))
            if not c.fetchone():
                break
            room_code = gen_room_code()

        c.execute("""
            INSERT INTO rooms (room_code, p1_name, p2_name, p1_photo, p2_photo, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            room_code,
            p1_name,
            p2_name,
            p1_photo,
            p2_photo,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()

        return redirect(url_for("answer", room_code=room_code, player_no=1))

    return render_template("create_room.html")


@app.route("/join", methods=["GET", "POST"])
def join_room():
    if request.method == "POST":
        room_code = request.form.get("room_code", "").strip().upper()

        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM rooms WHERE room_code=?", (room_code,))
        room = c.fetchone()
        conn.close()

        if not room:
            flash("房间码不存在")
            return redirect(url_for("join_room"))

        return redirect(url_for("answer", room_code=room_code, player_no=2))

    return render_template("join_room.html")


@app.route("/answer/<room_code>/<int:player_no>", methods=["GET", "POST"])
def answer(room_code, player_no):
    if player_no not in [1, 2]:
        return "invalid player", 400

    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT * FROM rooms WHERE room_code=?", (room_code,))
    room = c.fetchone()
    if not room:
        conn.close()
        return "room not found", 404

    if request.method == "POST":
        c.execute("DELETE FROM answers WHERE room_code=? AND player_no=?", (room_code, player_no))
        c.execute("DELETE FROM bonus_text WHERE room_code=? AND player_no=?", (room_code, player_no))

        for q in QUESTIONS:
            val = request.form.get(f"q_{q['id']}", "")
            c.execute("""
                INSERT INTO answers (room_code, player_no, question_id, answer)
                VALUES (?, ?, ?, ?)
            """, (room_code, player_no, q["id"], val))

        for i, _ in enumerate(BONUS_PROMPTS, start=1):
            content = request.form.get(f"bonus_{i}", "")
            c.execute("""
                INSERT INTO bonus_text (room_code, player_no, prompt_id, content)
                VALUES (?, ?, ?, ?)
            """, (room_code, player_no, i, content))

        conn.commit()

        c.execute("SELECT COUNT(DISTINCT player_no) AS cnt FROM answers WHERE room_code=?", (room_code,))
        cnt = c.fetchone()["cnt"]
        conn.close()

        if cnt == 2:
            calc_result(room_code)
            return redirect(url_for("result", room_code=room_code))

        return redirect(url_for("waiting", room_code=room_code))

    conn.close()
    return render_template(
        "answer.html",
        room=room,
        room_code=room_code,
        player_no=player_no,
        questions=QUESTIONS,
        bonus_prompts=BONUS_PROMPTS
    )


@app.route("/waiting/<room_code>")
def waiting(room_code):
    return render_template("waiting.html", room_code=room_code)


@app.route("/api/room_status/<room_code>")
def room_status(room_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT player_no) AS cnt FROM answers WHERE room_code=?", (room_code,))
    cnt = c.fetchone()["cnt"]
    conn.close()
    return jsonify({"ready": cnt == 2})


@app.route("/result/<room_code>")
def result(room_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM rooms WHERE room_code=?", (room_code,))
    room = c.fetchone()
    c.execute("SELECT * FROM results WHERE room_code=?", (room_code,))
    rs = c.fetchone()
    conn.close()

    if not room:
        return "room not found", 404
    if not rs:
        return redirect(url_for("waiting", room_code=room_code))

    return render_template("result.html", room=room, rs=rs)


@app.route("/history")
def history():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT r.*, rm.p1_name, rm.p2_name
        FROM results r
        JOIN rooms rm ON r.room_code = rm.room_code
        ORDER BY r.id DESC
    """)
    data = c.fetchall()
    conn.close()
    return render_template("history.html", data=data)


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    app.run(debug=True)
