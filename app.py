"""
土木館教室與設備預約系統  v3.0
================================
安裝：pip install streamlit pandas
執行：streamlit run app.py

預設管理員帳號：admin / admin123
預設系辦帳號：staff / staff123
"""

import streamlit as st
import sqlite3
import hashlib
import secrets
import smtplib
import threading
import time as time_module
import pandas as pd
from datetime import datetime, date, time, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ═══════════════════════════════════════════════════════════════
#  資料庫
# ═══════════════════════════════════════════════════════════════

DB = 'civil_booking.db'

def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    db = conn()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS USER (
            user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT DEFAULT 'user',
            email       TEXT,
            identity    TEXT,
            student_id  TEXT UNIQUE,
            department  TEXT,
            phone       TEXT,
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS ROOM (
            room_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            description TEXT,
            capacity    INTEGER DEFAULT 0,
            is_active   INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS EQUIPMENT (
            equip_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            serial_number   TEXT,
            quantity        INTEGER DEFAULT 1,
            description     TEXT,
            is_active       INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS ROOM_BOOKING (
            booking_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            room_id         INTEGER,
            book_date       TEXT,
            start_time      TEXT,
            end_time        TEXT,
            purpose         TEXT,
            attendee_count  INTEGER DEFAULT 1,
            supervisor      TEXT,
            attendees       TEXT,
            status          TEXT DEFAULT 'pending',
            returned_at     TEXT,
            note            TEXT,
            reject_reason   TEXT,
            remind_sent     INTEGER DEFAULT 0,
            created_at      TEXT,
            FOREIGN KEY (user_id) REFERENCES USER(user_id),
            FOREIGN KEY (room_id) REFERENCES ROOM(room_id)
        );
        CREATE TABLE IF NOT EXISTS EQUIP_BOOKING (
            booking_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER,
            equip_id            INTEGER,
            book_date           TEXT,
            start_time          TEXT,
            end_time            TEXT,
            quantity_borrowed   INTEGER DEFAULT 1,
            purpose             TEXT,
            supervisor          TEXT,
            attendees           TEXT,
            status              TEXT DEFAULT 'pending',
            returned_at         TEXT,
            note                TEXT,
            reject_reason       TEXT,
            remind_sent         INTEGER DEFAULT 0,
            created_at          TEXT,
            FOREIGN KEY (user_id) REFERENCES USER(user_id),
            FOREIGN KEY (equip_id) REFERENCES EQUIPMENT(equip_id)
        );
        CREATE TABLE IF NOT EXISTS FIXED_COURSE (
            course_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id     INTEGER,
            weekday     INTEGER,
            start_time  TEXT,
            end_time    TEXT,
            title       TEXT,
            note        TEXT,
            FOREIGN KEY (room_id) REFERENCES ROOM(room_id)
        );
        CREATE TABLE IF NOT EXISTS BLACKLIST (
            bl_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER UNIQUE,
            reason      TEXT,
            added_by    INTEGER,
            added_at    TEXT,
            FOREIGN KEY (user_id) REFERENCES USER(user_id),
            FOREIGN KEY (added_by) REFERENCES USER(user_id)
        );
        CREATE TABLE IF NOT EXISTS SMTP_CONFIG (
            id          INTEGER PRIMARY KEY CHECK (id=1),
            host        TEXT DEFAULT '',
            port        INTEGER DEFAULT 587,
            username    TEXT DEFAULT '',
            password    TEXT DEFAULT '',
            use_tls     INTEGER DEFAULT 1,
            sender_name TEXT DEFAULT '土木館預約系統'
        );
        CREATE TABLE IF NOT EXISTS RESET_TOKEN (
            token_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            token       TEXT UNIQUE,
            expires_at  TEXT,
            used        INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES USER(user_id)
        );
    ''')

    # 遷移：補舊資料表缺少的欄位
    migrations = [
        ("USER",          "identity",         "TEXT"),
        ("USER",          "student_id",        "TEXT"),
        ("USER",          "department",        "TEXT"),
        ("USER",          "phone",             "TEXT"),
        ("ROOM",          "capacity",          "INTEGER DEFAULT 0"),
        ("EQUIPMENT",     "serial_number",     "TEXT"),
        ("EQUIPMENT",     "quantity",          "INTEGER DEFAULT 1"),
        ("ROOM_BOOKING",  "purpose",           "TEXT"),
        ("ROOM_BOOKING",  "returned_at",       "TEXT"),
        ("ROOM_BOOKING",  "attendee_count",    "INTEGER DEFAULT 1"),
        ("ROOM_BOOKING",  "supervisor",        "TEXT"),
        ("ROOM_BOOKING",  "attendees",         "TEXT"),
        ("ROOM_BOOKING",  "reject_reason",     "TEXT"),
        ("ROOM_BOOKING",  "remind_sent",       "INTEGER DEFAULT 0"),
        ("EQUIP_BOOKING", "purpose",           "TEXT"),
        ("EQUIP_BOOKING", "quantity_borrowed", "INTEGER DEFAULT 1"),
        ("EQUIP_BOOKING", "supervisor",        "TEXT"),
        ("EQUIP_BOOKING", "attendees",         "TEXT"),
        ("EQUIP_BOOKING", "reject_reason",     "TEXT"),
        ("EQUIP_BOOKING", "remind_sent",       "INTEGER DEFAULT 0"),
    ]
    for tbl, col, typ in migrations:
        try:
            db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
        except Exception:
            pass

    # 更新舊狀態值：原 confirmed → confirmed（教室），borrowed → confirmed（設備統一）
    # 新狀態機統一用 pending / confirmed / rejected / pending_return / returned / cancelled

    cur = db.cursor()
    # 預設管理員
    if not cur.execute("SELECT 1 FROM USER WHERE username='admin'").fetchone():
        cur.execute(
            "INSERT INTO USER (username,password,role,email,identity,student_id,department,phone,created_at)"
            " VALUES ('admin',?,'admin','admin@civil.edu','教職員','ADMIN001','系統管理','',?)",
            (hp('admin123'), nows())
        )
    # 預設系辦
    if not cur.execute("SELECT 1 FROM USER WHERE username='staff'").fetchone():
        cur.execute(
            "INSERT INTO USER (username,password,role,email,identity,student_id,department,phone,created_at)"
            " VALUES ('staff',?,'staff','staff@civil.edu','教職員','STAFF001','系辦','',?)",
            (hp('staff123'), nows())
        )
    # SMTP config
    if not cur.execute("SELECT 1 FROM SMTP_CONFIG WHERE id=1").fetchone():
        cur.execute("INSERT INTO SMTP_CONFIG (id) VALUES (1)")
    # 預設教室
    default_rooms = [
        ('土木 204', 30), ('土木 205', 40), ('土木 206', 50),
        ('土木 207', 30), ('土木 208', 20),
    ]
    for rname, cap in default_rooms:
        if not cur.execute("SELECT 1 FROM ROOM WHERE name=?", (rname,)).fetchone():
            cur.execute("INSERT INTO ROOM (name,capacity,is_active) VALUES (?,?,1)", (rname, cap))
    # 預設設備
    for ename, esn, eqty in [('筆電','NB-001',3), ('延長線','EX-001',5)]:
        if not cur.execute("SELECT 1 FROM EQUIPMENT WHERE name=?", (ename,)).fetchone():
            cur.execute("INSERT INTO EQUIPMENT VALUES (NULL,?,?,?,NULL,1)", (ename, esn, eqty))
    db.commit(); db.close()

def hp(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def nows():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ═══════════════════════════════════════════════════════════════
#  Email
# ═══════════════════════════════════════════════════════════════

def get_smtp_config():
    db = conn()
    row = db.execute("SELECT * FROM SMTP_CONFIG WHERE id=1").fetchone()
    db.close()
    return dict(row) if row else {}

def save_smtp_config(host, port, username, password, use_tls, sender_name):
    db = conn()
    db.execute(
        "UPDATE SMTP_CONFIG SET host=?,port=?,username=?,password=?,use_tls=?,sender_name=? WHERE id=1",
        (host, int(port), username, password, int(use_tls), sender_name)
    )
    db.commit(); db.close()

def send_email(to_addr, subject, body_html):
    """非阻塞發信，失敗只 log 不崩潰"""
    cfg = get_smtp_config()
    if not cfg.get('host') or not cfg.get('username'):
        return False, 'SMTP 尚未設定'
    def _send():
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From']    = f"{cfg['sender_name']} <{cfg['username']}>"
            msg['To']      = to_addr
            msg.attach(MIMEText(body_html, 'html', 'utf-8'))
            srv = smtplib.SMTP(cfg['host'], int(cfg['port']), timeout=10)
            if cfg['use_tls']:
                srv.starttls()
            srv.login(cfg['username'], cfg['password'])
            srv.sendmail(cfg['username'], [to_addr], msg.as_string())
            srv.quit()
        except Exception as e:
            print(f"[Email Error] {e}")
    threading.Thread(target=_send, daemon=True).start()
    return True, 'OK'

def email_booking_result(user_email, username, kind, item_name, book_date,
                          start_time, end_time, approved: bool, reason=''):
    action = '通過' if approved else '未通過'
    color  = '#2e7d32' if approved else '#c62828'
    subject = f"【土木館預約系統】{kind}預約審核{action}通知"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">
      <div style="background:{color};padding:16px;color:white">
        <h2 style="margin:0">預約審核{action}</h2>
      </div>
      <div style="padding:20px">
        <p>親愛的 <b>{username}</b>，您好：</p>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:6px;color:#555">類型</td><td><b>{kind}</b></td></tr>
          <tr style="background:#f9f9f9"><td style="padding:6px;color:#555">項目</td><td><b>{item_name}</b></td></tr>
          <tr><td style="padding:6px;color:#555">日期</td><td>{book_date}</td></tr>
          <tr style="background:#f9f9f9"><td style="padding:6px;color:#555">時段</td><td>{start_time} ~ {end_time}</td></tr>
          {'<tr><td style="padding:6px;color:#555">原因</td><td style="color:#c62828">'+reason+'</td></tr>' if reason else ''}
        </table>
        {'<p style="color:#2e7d32">✅ 您的預約已確認，請準時使用並記得歸還！</p>' if approved else '<p style="color:#c62828">❌ 如有疑問請聯繫系辦。</p>'}
      </div>
    </div>"""
    send_email(user_email, subject, body)

def email_reminder(user_email, username, kind, item_name, book_date,
                   start_time, end_time, remind_type):
    if remind_type == 'start':
        subject = f"【提醒】30 分鐘後開始使用 {item_name}"
        msg = f"您預約的 <b>{item_name}</b> 將於 30 分鐘後（{start_time}）開始，請準時前往！"
    else:
        subject = f"【提醒】請記得歸還 {item_name}"
        msg = f"您借用的 <b>{item_name}</b> 預計結束時間為 {end_time}，剩餘約 10 分鐘，請準備歸還。"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">
      <div style="background:#e65100;padding:16px;color:white"><h2 style="margin:0">⏰ 使用提醒</h2></div>
      <div style="padding:20px">
        <p>親愛的 <b>{username}</b>，</p>
        <p>{msg}</p>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="padding:6px;color:#555">類型</td><td>{kind}</td></tr>
          <tr style="background:#f9f9f9"><td style="padding:6px;color:#555">項目</td><td><b>{item_name}</b></td></tr>
          <tr><td style="padding:6px;color:#555">日期</td><td>{book_date}</td></tr>
          <tr style="background:#f9f9f9"><td style="padding:6px;color:#555">時段</td><td>{start_time} ~ {end_time}</td></tr>
        </table>
      </div>
    </div>"""
    send_email(user_email, subject, body)

def email_reset_password(user_email, username, token):
    subject = "【土木館預約系統】密碼重設"
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">
      <div style="background:#1565c0;padding:16px;color:white"><h2 style="margin:0">密碼重設</h2></div>
      <div style="padding:20px">
        <p>親愛的 <b>{username}</b>，</p>
        <p>您的密碼重設驗證碼為：</p>
        <div style="background:#f0f4ff;border-radius:6px;padding:14px;text-align:center;font-size:28px;font-weight:bold;letter-spacing:6px;color:#1565c0">{token}</div>
        <p style="color:#888;font-size:12px">此驗證碼將於 15 分鐘後失效。若非您本人操作請忽略此信。</p>
      </div>
    </div>"""
    send_email(user_email, subject, body)

# ═══════════════════════════════════════════════════════════════
#  提醒背景執行緒
# ═══════════════════════════════════════════════════════════════

def _reminder_worker():
    """每分鐘檢查一次，在開始前 30 分 / 結束前 10 分發提醒"""
    while True:
        try:
            now = datetime.now()
            db  = conn()
            # 教室提醒
            rows = db.execute("""
                SELECT rb.booking_id, rb.book_date, rb.start_time, rb.end_time,
                       rb.remind_sent, r.name AS item_name,
                       u.username, u.email
                FROM ROOM_BOOKING rb
                JOIN ROOM r ON rb.room_id=r.room_id
                JOIN USER u ON rb.user_id=u.user_id
                WHERE rb.status='confirmed' AND rb.remind_sent < 3
            """).fetchall()
            for row in rows:
                _check_remind(db, 'ROOM_BOOKING', dict(row), now, '教室')
            # 設備提醒
            rows = db.execute("""
                SELECT eb.booking_id, eb.book_date, eb.start_time, eb.end_time,
                       eb.remind_sent, e.name AS item_name,
                       u.username, u.email
                FROM EQUIP_BOOKING eb
                JOIN EQUIPMENT e ON eb.equip_id=e.equip_id
                JOIN USER u ON eb.user_id=u.user_id
                WHERE eb.status='confirmed' AND eb.remind_sent < 3
            """).fetchall()
            for row in rows:
                _check_remind(db, 'EQUIP_BOOKING', dict(row), now, '設備')
            db.close()
        except Exception as e:
            print(f"[Reminder Error] {e}")
        time_module.sleep(60)

def _check_remind(db, table, row, now, kind):
    if not row['email']:
        return
    start_dt = datetime.strptime(f"{row['book_date']} {row['start_time']}", '%Y-%m-%d %H:%M')
    end_dt   = datetime.strptime(f"{row['book_date']} {row['end_time']}",   '%Y-%m-%d %H:%M')
    sent     = row['remind_sent'] or 0
    bid      = row['booking_id']

    # 開始前 30 分（bit 1）
    if not (sent & 1) and timedelta(0) < start_dt - now <= timedelta(minutes=30):
        email_reminder(row['email'], row['username'], kind, row['item_name'],
                       row['book_date'], row['start_time'], row['end_time'], 'start')
        db.execute(f"UPDATE {table} SET remind_sent=remind_sent|1 WHERE booking_id=?", (bid,))
        db.commit()

    # 結束前 10 分（bit 2）
    if not (sent & 2) and timedelta(0) < end_dt - now <= timedelta(minutes=10):
        email_reminder(row['email'], row['username'], kind, row['item_name'],
                       row['book_date'], row['start_time'], row['end_time'], 'end')
        db.execute(f"UPDATE {table} SET remind_sent=remind_sent|2 WHERE booking_id=?", (bid,))
        db.commit()

# ═══════════════════════════════════════════════════════════════
#  Auth
# ═══════════════════════════════════════════════════════════════

def do_login(student_id, password):
    db = conn()
    row = db.execute(
        "SELECT * FROM USER WHERE student_id=? AND password=?",
        (student_id, hp(password))
    ).fetchone()
    db.close()
    return dict(row) if row else None

def do_register(fullname, password, email, phone, identity, student_id, department):
    if not fullname or not password or not email or not phone or not student_id or not department:
        return False, '所有必填欄位都必須填寫'
    db = conn()
    try:
        db.execute(
            "INSERT INTO USER (username,password,role,email,identity,student_id,department,phone,created_at)"
            " VALUES (?,?,'user',?,?,?,?,?,?)",
            (fullname, hp(password), email, identity, student_id, department, phone, nows())
        )
        db.commit(); db.close()
        return True, '註冊成功'
    except sqlite3.IntegrityError as e:
        db.close()
        if 'student_id' in str(e):
            return False, '此學號/員工編號已被註冊'
        return False, '此姓名帳號已存在，請換一個'

def update_profile(user_id, email, phone, identity, student_id, department):
    db = conn()
    db.execute(
        "UPDATE USER SET email=?,phone=?,identity=?,student_id=?,department=? WHERE user_id=?",
        (email, phone, identity, student_id, department, user_id)
    )
    db.commit()
    row = db.execute("SELECT * FROM USER WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return dict(row)

def change_password(user_id, old_pw, new_pw):
    db = conn()
    row = db.execute("SELECT password FROM USER WHERE user_id=?", (user_id,)).fetchone()
    if not row or row['password'] != hp(old_pw):
        db.close(); return False, '舊密碼錯誤'
    db.execute("UPDATE USER SET password=? WHERE user_id=?", (hp(new_pw), user_id))
    db.commit(); db.close(); return True, '密碼已更新'

# ── 忘記密碼 ──────────────────────────────────────────────────

def create_reset_token(student_id):
    db = conn()
    row = db.execute("SELECT * FROM USER WHERE student_id=?", (student_id,)).fetchone()
    if not row:
        db.close(); return False, '找不到此學號的帳號'
    user = dict(row)
    if not user.get('email'):
        db.close(); return False, '此帳號未設定 Email，請聯繫管理員重設'
    token = str(secrets.randbelow(900000) + 100000)  # 6 位數
    expires = (datetime.now() + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    db.execute("DELETE FROM RESET_TOKEN WHERE user_id=?", (user['user_id'],))
    db.execute(
        "INSERT INTO RESET_TOKEN (user_id,token,expires_at,used) VALUES (?,?,?,0)",
        (user['user_id'], token, expires)
    )
    db.commit(); db.close()
    email_reset_password(user['email'], user['username'], token)
    return True, user['email']

def verify_reset_token(student_id, token, new_pw):
    db = conn()
    row = db.execute(
        """SELECT rt.*, u.user_id FROM RESET_TOKEN rt
           JOIN USER u ON rt.user_id=u.user_id
           WHERE u.student_id=? AND rt.token=? AND rt.used=0""",
        (student_id, token)
    ).fetchone()
    if not row:
        db.close(); return False, '驗證碼錯誤或已使用'
    if datetime.now() > datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S'):
        db.close(); return False, '驗證碼已過期，請重新申請'
    db.execute("UPDATE USER SET password=? WHERE user_id=?", (hp(new_pw), row['user_id']))
    db.execute("UPDATE RESET_TOKEN SET used=1 WHERE token=?", (token,))
    db.commit(); db.close()
    return True, '密碼已重設，請重新登入'

# ═══════════════════════════════════════════════════════════════
#  黑名單
# ═══════════════════════════════════════════════════════════════

def is_blacklisted(user_id):
    db = conn()
    row = db.execute("SELECT reason FROM BLACKLIST WHERE user_id=?", (user_id,)).fetchone()
    db.close()
    return (True, row['reason']) if row else (False, '')

def add_blacklist(user_id, reason, added_by):
    db = conn()
    try:
        db.execute(
            "INSERT INTO BLACKLIST (user_id,reason,added_by,added_at) VALUES (?,?,?,?)",
            (user_id, reason, added_by, nows())
        )
        db.commit(); db.close(); return True, '已加入黑名單'
    except sqlite3.IntegrityError:
        db.execute("UPDATE BLACKLIST SET reason=?,added_by=?,added_at=? WHERE user_id=?",
                   (reason, added_by, nows(), user_id))
        db.commit(); db.close(); return True, '已更新黑名單原因'

def remove_blacklist(user_id):
    db = conn()
    db.execute("DELETE FROM BLACKLIST WHERE user_id=?", (user_id,))
    db.commit(); db.close()

def get_blacklist():
    db = conn()
    rows = db.execute("""
        SELECT bl.*, u.username, u.student_id, u.department,
               a.username AS added_by_name
        FROM BLACKLIST bl
        JOIN USER u ON bl.user_id=u.user_id
        JOIN USER a ON bl.added_by=a.user_id
        ORDER BY bl.added_at DESC
    """).fetchall()
    db.close()
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════════════════
#  Room DB
# ═══════════════════════════════════════════════════════════════

def get_rooms():
    db = conn()
    rows = db.execute("SELECT * FROM ROOM WHERE is_active=1 ORDER BY name").fetchall()
    db.close(); return [dict(r) for r in rows]

def room_conflict(room_id, book_date, start_time, end_time, exclude=None):
    db = conn()
    q = ("SELECT 1 FROM ROOM_BOOKING "
         "WHERE room_id=? AND book_date=? AND status IN ('confirmed','pending_return','pending') "
         "AND start_time < ? AND end_time > ?" +
         (" AND booking_id != ?" if exclude else ""))
    p = [room_id, book_date, end_time, start_time]
    if exclude: p.append(exclude)
    r = db.execute(q, p).fetchone()
    db.close(); return r is not None

def book_room(user_id, room_id, book_date, st_, et_, purpose,
              attendee_count, supervisor, attendees, note):
    if room_conflict(room_id, book_date, st_, et_):
        return False, '此時段已有人預約（含審核中），請選擇其他時段'
    db = conn()
    db.execute(
        "INSERT INTO ROOM_BOOKING"
        " (user_id,room_id,book_date,start_time,end_time,purpose,"
        "  attendee_count,supervisor,attendees,status,returned_at,note,remind_sent,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'pending',NULL,?,0,?)",
        (user_id, room_id, book_date, st_, et_, purpose,
         attendee_count, supervisor, attendees, note, nows())
    )
    db.commit(); db.close()
    return True, '申請已送出，請等候系辦審核（約 1-2 個工作天）'

def get_room_slots(room_id, book_date):
    db = conn()
    rows = db.execute("""SELECT rb.*, u.username FROM ROOM_BOOKING rb
        JOIN USER u ON rb.user_id=u.user_id
        WHERE rb.room_id=? AND rb.book_date=?
          AND rb.status IN ('confirmed','pending_return','pending')
        ORDER BY rb.start_time""", (room_id, book_date)).fetchall()
    db.close(); return [dict(r) for r in rows]

def get_user_room_bookings(user_id):
    db = conn()
    rows = db.execute("""SELECT rb.*, r.name AS room_name, r.capacity FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id WHERE rb.user_id=?
        ORDER BY rb.book_date DESC, rb.start_time DESC""", (user_id,)).fetchall()
    db.close(); return [dict(r) for r in rows]

def cancel_room(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE ROOM_BOOKING SET status='cancelled' WHERE booking_id=? AND user_id=? "
            "AND status IN ('pending','confirmed')", (booking_id, user_id))
    else:
        db.execute("UPDATE ROOM_BOOKING SET status='cancelled' WHERE booking_id=?", (booking_id,))
    db.commit(); db.close()

def approve_room(booking_id, approver_id):
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET status='confirmed' WHERE booking_id=? AND status='pending'",
        (booking_id,)
    )
    db.commit()
    row = db.execute(
        """SELECT rb.*, r.name AS room_name, u.email, u.username
           FROM ROOM_BOOKING rb JOIN ROOM r ON rb.room_id=r.room_id
           JOIN USER u ON rb.user_id=u.user_id WHERE rb.booking_id=?""",
        (booking_id,)
    ).fetchone()
    db.close()
    if row and row['email']:
        email_booking_result(row['email'], row['username'], '教室', row['room_name'],
                             row['book_date'], row['start_time'], row['end_time'], True)

def reject_room(booking_id, reason):
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET status='rejected', reject_reason=? WHERE booking_id=? AND status='pending'",
        (reason, booking_id)
    )
    db.commit()
    row = db.execute(
        """SELECT rb.*, r.name AS room_name, u.email, u.username
           FROM ROOM_BOOKING rb JOIN ROOM r ON rb.room_id=r.room_id
           JOIN USER u ON rb.user_id=u.user_id WHERE rb.booking_id=?""",
        (booking_id,)
    ).fetchone()
    db.close()
    if row and row['email']:
        email_booking_result(row['email'], row['username'], '教室', row['room_name'],
                             row['book_date'], row['start_time'], row['end_time'], False, reason)

def request_return_room(booking_id, user_id):
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET status='pending_return' WHERE booking_id=? AND user_id=? AND status='confirmed'",
        (booking_id, user_id)
    )
    db.commit(); db.close()

def confirm_return_room(booking_id):
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET status='returned', returned_at=? WHERE booking_id=? AND status='pending_return'",
        (nows(), booking_id)
    )
    db.commit(); db.close()

def return_room(booking_id):
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET status='returned', returned_at=? WHERE booking_id=?",
        (nows(), booking_id)
    )
    db.commit(); db.close()

def modify_room(booking_id, user_id, room_id, book_date, st_, et_,
                purpose, attendee_count, supervisor, attendees, note):
    if room_conflict(room_id, book_date, st_, et_, exclude=booking_id):
        return False, '此時段已有人預約'
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET book_date=?,start_time=?,end_time=?,purpose=?,"
        "attendee_count=?,supervisor=?,attendees=?,note=?,status='pending' "
        "WHERE booking_id=? AND user_id=?",
        (book_date, st_, et_, purpose, attendee_count, supervisor, attendees, note, booking_id, user_id)
    )
    db.commit(); db.close()
    return True, '已重新送出審核'

def all_room_bookings():
    db = conn()
    rows = db.execute("""SELECT rb.*, r.name AS room_name, r.capacity,
            u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id JOIN USER u ON rb.user_id=u.user_id
        ORDER BY rb.book_date DESC""").fetchall()
    db.close(); return [dict(r) for r in rows]

def pending_room_approvals():
    db = conn()
    rows = db.execute("""SELECT rb.*, r.name AS room_name, r.capacity,
            u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id JOIN USER u ON rb.user_id=u.user_id
        WHERE rb.status='pending' ORDER BY rb.created_at""").fetchall()
    db.close(); return [dict(r) for r in rows]

def pending_room_returns():
    db = conn()
    rows = db.execute("""SELECT rb.*, r.name AS room_name,
            u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id JOIN USER u ON rb.user_id=u.user_id
        WHERE rb.status='pending_return' ORDER BY rb.book_date DESC""").fetchall()
    db.close(); return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════════════════
#  Equipment DB
# ═══════════════════════════════════════════════════════════════

def get_equips():
    db = conn()
    rows = db.execute("SELECT * FROM EQUIPMENT WHERE is_active=1 ORDER BY name").fetchall()
    db.close(); return [dict(r) for r in rows]

def get_equip_available(equip_id, book_date, st_, et_, exclude=None):
    db = conn()
    total = db.execute("SELECT quantity FROM EQUIPMENT WHERE equip_id=?", (equip_id,)).fetchone()
    if not total:
        db.close(); return 0
    total_qty = total['quantity'] or 1
    q = ("SELECT COALESCE(SUM(quantity_borrowed),0) AS used FROM EQUIP_BOOKING "
         "WHERE equip_id=? AND book_date=? AND status IN ('confirmed','pending_return','pending') "
         "AND start_time < ? AND end_time > ?" + (" AND booking_id != ?" if exclude else ""))
    p = [equip_id, book_date, et_, st_]
    if exclude: p.append(exclude)
    used = db.execute(q, p).fetchone()['used'] or 0
    db.close()
    return max(0, total_qty - used)

def book_equip(user_id, equip_id, book_date, st_, et_, qty,
               purpose, supervisor, attendees, note):
    available = get_equip_available(equip_id, book_date, st_, et_)
    if available < qty:
        return False, f'此時段可借用數量不足（剩餘 {available} 件）'
    db = conn()
    db.execute(
        "INSERT INTO EQUIP_BOOKING"
        " (user_id,equip_id,book_date,start_time,end_time,quantity_borrowed,"
        "  purpose,supervisor,attendees,status,returned_at,note,remind_sent,created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,'pending',NULL,?,0,?)",
        (user_id, equip_id, book_date, st_, et_, qty,
         purpose, supervisor, attendees, note, nows())
    )
    db.commit(); db.close()
    return True, '申請已送出，請等候系辦審核（約 1-2 個工作天）'

def get_equip_slots(equip_id, book_date):
    db = conn()
    rows = db.execute("""SELECT eb.*, u.username FROM EQUIP_BOOKING eb
        JOIN USER u ON eb.user_id=u.user_id
        WHERE eb.equip_id=? AND eb.book_date=?
          AND eb.status IN ('confirmed','pending_return','pending')
        ORDER BY eb.start_time""", (equip_id, book_date)).fetchall()
    db.close(); return [dict(r) for r in rows]

def get_user_equip_bookings(user_id):
    db = conn()
    rows = db.execute("""SELECT eb.*, e.name AS equip_name, e.serial_number
        FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id WHERE eb.user_id=?
        ORDER BY eb.book_date DESC, eb.start_time DESC""", (user_id,)).fetchall()
    db.close(); return [dict(r) for r in rows]

def approve_equip(booking_id):
    db = conn()
    db.execute(
        "UPDATE EQUIP_BOOKING SET status='confirmed' WHERE booking_id=? AND status='pending'",
        (booking_id,)
    )
    db.commit()
    row = db.execute(
        """SELECT eb.*, e.name AS equip_name, u.email, u.username
           FROM EQUIP_BOOKING eb JOIN EQUIPMENT e ON eb.equip_id=e.equip_id
           JOIN USER u ON eb.user_id=u.user_id WHERE eb.booking_id=?""",
        (booking_id,)
    ).fetchone()
    db.close()
    if row and row['email']:
        email_booking_result(row['email'], row['username'], '設備', row['equip_name'],
                             row['book_date'], row['start_time'], row['end_time'], True)

def reject_equip(booking_id, reason):
    db = conn()
    db.execute(
        "UPDATE EQUIP_BOOKING SET status='rejected', reject_reason=? WHERE booking_id=? AND status='pending'",
        (reason, booking_id)
    )
    db.commit()
    row = db.execute(
        """SELECT eb.*, e.name AS equip_name, u.email, u.username
           FROM EQUIP_BOOKING eb JOIN EQUIPMENT e ON eb.equip_id=e.equip_id
           JOIN USER u ON eb.user_id=u.user_id WHERE eb.booking_id=?""",
        (booking_id,)
    ).fetchone()
    db.close()
    if row and row['email']:
        email_booking_result(row['email'], row['username'], '設備', row['equip_name'],
                             row['book_date'], row['start_time'], row['end_time'], False, reason)

def return_equip(booking_id):
    db = conn()
    db.execute(
        "UPDATE EQUIP_BOOKING SET status='returned', returned_at=? WHERE booking_id=?",
        (nows(), booking_id)
    )
    db.commit(); db.close()

def request_return_equip(booking_id, user_id):
    db = conn()
    db.execute(
        "UPDATE EQUIP_BOOKING SET status='pending_return' WHERE booking_id=? AND user_id=? AND status='confirmed'",
        (booking_id, user_id)
    )
    db.commit(); db.close()

def confirm_return_equip(booking_id):
    db = conn()
    db.execute(
        "UPDATE EQUIP_BOOKING SET status='returned', returned_at=? WHERE booking_id=? AND status='pending_return'",
        (nows(), booking_id)
    )
    db.commit(); db.close()

def cancel_equip(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE EQUIP_BOOKING SET status='cancelled' WHERE booking_id=? AND user_id=? "
            "AND status IN ('pending','confirmed')", (booking_id, user_id))
    else:
        db.execute("UPDATE EQUIP_BOOKING SET status='cancelled' WHERE booking_id=?", (booking_id,))
    db.commit(); db.close()

def all_equip_bookings():
    db = conn()
    rows = db.execute("""SELECT eb.*, e.name AS equip_name, e.serial_number,
            e.quantity AS total_qty, u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id JOIN USER u ON eb.user_id=u.user_id
        ORDER BY eb.book_date DESC""").fetchall()
    db.close(); return [dict(r) for r in rows]

def pending_equip_approvals():
    db = conn()
    rows = db.execute("""SELECT eb.*, e.name AS equip_name, e.serial_number,
            u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id JOIN USER u ON eb.user_id=u.user_id
        WHERE eb.status='pending' ORDER BY eb.created_at""").fetchall()
    db.close(); return [dict(r) for r in rows]

def pending_equip_returns():
    db = conn()
    rows = db.execute("""SELECT eb.*, e.name AS equip_name, e.serial_number,
            u.username, u.identity, u.department, u.student_id, u.phone, u.email
        FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id JOIN USER u ON eb.user_id=u.user_id
        WHERE eb.status='pending_return' ORDER BY eb.book_date DESC""").fetchall()
    db.close(); return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════════════════
#  Admin DB
# ═══════════════════════════════════════════════════════════════

def add_room(name, desc, capacity):
    db = conn()
    try:
        db.execute("INSERT INTO ROOM (name,description,capacity,is_active) VALUES (?,?,?,1)",
                   (name, desc, capacity))
        db.commit(); db.close(); return True, '新增成功'
    except sqlite3.IntegrityError:
        db.close(); return False, '此名稱已存在'

def update_room(room_id, name, desc, capacity):
    db = conn()
    db.execute("UPDATE ROOM SET name=?,description=?,capacity=? WHERE room_id=?",
               (name, desc, capacity, room_id))
    db.commit(); db.close()

def disable_room(room_id):
    db = conn(); db.execute("UPDATE ROOM SET is_active=0 WHERE room_id=?", (room_id,))
    db.commit(); db.close()

def add_equip(name, serial_number, quantity, desc):
    db = conn()
    db.execute("INSERT INTO EQUIPMENT VALUES (NULL,?,?,?,?,1)",
               (name, serial_number, quantity, desc))
    db.commit(); db.close(); return True, '新增成功'

def update_equip(equip_id, name, serial_number, quantity, desc):
    db = conn()
    db.execute("UPDATE EQUIPMENT SET name=?,serial_number=?,quantity=?,description=? WHERE equip_id=?",
               (name, serial_number, quantity, desc, equip_id))
    db.commit(); db.close()

def disable_equip(equip_id):
    db = conn(); db.execute("UPDATE EQUIPMENT SET is_active=0 WHERE equip_id=?", (equip_id,))
    db.commit(); db.close()

def get_all_users():
    db = conn()
    rows = db.execute(
        "SELECT user_id,username,role,email,identity,student_id,department,phone,created_at FROM USER ORDER BY created_at DESC"
    ).fetchall()
    db.close(); return [dict(r) for r in rows]

# ── Fixed Courses ──────────────────────────────────────────────

def get_fixed_courses(room_id):
    db = conn()
    rows = db.execute("SELECT * FROM FIXED_COURSE WHERE room_id=? ORDER BY weekday,start_time", (room_id,)).fetchall()
    db.close(); return [dict(r) for r in rows]

def add_fixed_course(room_id, weekday, start_time, end_time, title, note):
    db = conn()
    db.execute("INSERT INTO FIXED_COURSE (room_id,weekday,start_time,end_time,title,note) VALUES (?,?,?,?,?,?)",
               (room_id, weekday, start_time, end_time, title, note))
    db.commit(); db.close()

def delete_fixed_course(course_id):
    db = conn()
    db.execute("DELETE FROM FIXED_COURSE WHERE course_id=?", (course_id,))
    db.commit(); db.close()

def get_week_bookings(room_id, dates):
    db = conn()
    ph = ','.join('?' * len(dates))
    rows = db.execute(
        f"""SELECT rb.*, u.username FROM ROOM_BOOKING rb
            JOIN USER u ON rb.user_id=u.user_id
            WHERE rb.room_id=? AND rb.book_date IN ({ph})
              AND rb.status IN ('confirmed','pending_return','pending')
            ORDER BY rb.book_date, rb.start_time""",
        [room_id] + dates
    ).fetchall()
    db.close(); return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

SL = {
    'pending':        '⏳ 審核中',
    'confirmed':      '✅ 已確認',
    'rejected':       '❌ 已拒絕',
    'cancelled':      '🚫 已取消',
    'pending_return': '🔔 申請歸還中',
    'returned':       '📦 已歸還',
}

ROLE_LABEL = {
    'admin': '🔑 管理員',
    'staff': '🏢 系辦人員',
    'user':  '👤 一般使用者',
}

IDENTITY_OPTIONS = ['學生', '研究生', '教職員', '其他']

ROOM_PURPOSES = ['課程上課','自習讀書','小組討論','專題會議','社團活動','研究使用','考試','其他']
EQUIP_PURPOSES = ['課程使用','專題研究','社團活動','個人使用','其他']

BLACKLIST_REASONS = [
    '無正當理由未在時間內歸還鑰匙',
    '人數與申請嚴重不符',
    '器材損壞未告知',
    '未經批准轉借他人',
    '其他違規行為',
]

WEEKDAY_ZH = ['週一','週二','週三','週四','週五','週六','週日']

# ═══════════════════════════════════════════════════════════════
#  週課表渲染（共用）
# ═══════════════════════════════════════════════════════════════

def render_room_calendar(room, week_offset_key='week_offset', compact=False):
    today = date.today()
    if week_offset_key not in st.session_state:
        st.session_state[week_offset_key] = 0

    cp, cc, cn = st.columns([1, 2, 1])
    if cp.button('◀', key=f'prev_{week_offset_key}', help='上週'):
        st.session_state[week_offset_key] -= 1; st.rerun()
    if cn.button('▶', key=f'next_{week_offset_key}', help='下週'):
        st.session_state[week_offset_key] += 1; st.rerun()
    if cc.button('📅 回本週', key=f'cur_{week_offset_key}', use_container_width=True):
        st.session_state[week_offset_key] = 0; st.rerun()

    offset     = st.session_state[week_offset_key]
    mon        = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    week_dates = [mon + timedelta(days=i) for i in range(7)]
    week_strs  = [str(d) for d in week_dates]
    st.caption(f"{week_dates[0].strftime('%Y/%m/%d')} ～ {week_dates[6].strftime('%Y/%m/%d')}")

    bookings  = get_week_bookings(room['room_id'], week_strs)
    fixed_crs = get_fixed_courses(room['room_id'])

    bk_by_date = {d: [] for d in week_strs}
    for b in bookings: bk_by_date[b['book_date']].append(b)

    fc_by_day = {i: [] for i in range(7)}
    for fc in fixed_crs: fc_by_day[fc['weekday']].append(fc)

    HOUR_START  = 7; HOUR_END = 22; SLOT_MIN = 30
    total_slots = (HOUR_END - HOUR_START) * (60 // SLOT_MIN)

    def t2s(t):
        h, m = map(int, t.split(':')[:2])
        return (h - HOUR_START) * (60 // SLOT_MIN) + m // SLOT_MIN

    def s2l(s):
        tm = HOUR_START * 60 + s * SLOT_MIN
        return f"{tm//60:02d}:{tm%60:02d}"

    COL_W = 68 if compact else 100
    ROW_H = 18 if compact else 20
    TW    = 42; total_h = total_slots * ROW_H; HDR = 36

    CF = ('#1e3a5f','#d6e8ff'); CB = ('#3b1f00','#ffe8c0')
    CP2 = ('#4a0060','#f0d6ff'); CPEND = ('#5c3a00','#fff3cd')
    CT = '#fffbe6'; CWE = '#f8f8f8'; CN2 = '#ffffff'; CBRD = '#dde1e7'

    def blk(top, h, bg, fg, lbl, sub=''):
        s = f"<div style='font-size:9px;opacity:.75;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{sub}</div>" if sub else ''
        return (f"<div style='position:absolute;top:{top}px;left:1px;right:1px;height:{h-2}px;"
                f"background:{bg};color:{fg};border-radius:3px;padding:2px 4px;"
                f"font-size:10px;font-weight:600;overflow:hidden;z-index:2;"
                f"box-shadow:0 1px 2px rgba(0,0,0,.12)'>"
                f"<div style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{lbl}</div>{s}</div>")

    taxis = ''.join(
        f"<div style='position:absolute;top:{s*ROW_H}px;left:0;width:{TW}px;"
        f"font-size:9px;color:#999;text-align:right;padding-right:5px;line-height:1'>{s2l(s)}</div>"
        for s in range(0, total_slots + 1, 2)
    )

    parts = [f"""<div style='display:flex;font-family:sans-serif;
        border:1px solid {CBRD};border-radius:8px;overflow:hidden;width:100%;box-sizing:border-box'>
      <div style='flex:0 0 {TW}px;background:#f5f6f8;border-right:1px solid {CBRD}'>
        <div style='height:{HDR}px;border-bottom:1px solid {CBRD}'></div>
        <div style='position:relative;height:{total_h}px'>{taxis}</div>
      </div>"""]

    for i, (d, ds) in enumerate(zip(week_dates, week_strs)):
        is_today = (d == today); is_we = (i >= 5)
        bg0 = CT if is_today else (CWE if is_we else CN2)
        brd = '2px solid #f0a500' if is_today else f'1px solid {CBRD}'
        dc  = '#e67e00' if is_today else ('#aaa' if is_we else '#333')

        blks = []
        for fc in fc_by_day[i]:
            s = max(0, t2s(fc['start_time'])); e = min(total_slots, t2s(fc['end_time']))
            if e > s: blks.append(blk(s*ROW_H,(e-s)*ROW_H,CF[1],CF[0],fc['title'],f"{fc['start_time']}~{fc['end_time']}"))
        for b in bk_by_date.get(ds, []):
            s = max(0, t2s(b['start_time'])); e = min(total_slots, t2s(b['end_time']))
            if e > s:
                if b['status'] == 'pending_return':    bg2,fg2,l = CP2[1],CP2[0],f"🔔{b['username']}"
                elif b['status'] == 'pending':         bg2,fg2,l = CPEND[1],CPEND[0],f"⏳{b['username']}"
                else:                                  bg2,fg2,l = CB[1],CB[0],f"📌{b['username']}"
                blks.append(blk(s*ROW_H,(e-s)*ROW_H,bg2,fg2,l,b.get('purpose') or ''))

        grid = ''.join(f"<div style='position:absolute;top:{s*ROW_H}px;left:0;right:0;height:1px;background:{CBRD};opacity:.5'></div>" for s in range(0,total_slots+1,2))
        parts.append(f"""
      <div style='flex:1;min-width:{COL_W}px;border-left:{brd};box-sizing:border-box'>
        <div style='height:{HDR}px;background:{"#fff8e1" if is_today else bg0};display:flex;flex-direction:column;
                    align-items:center;justify-content:center;border-bottom:1px solid {CBRD}'>
          <div style='font-size:11px;font-weight:700;color:{dc}'>週{WEEKDAY_ZH[i][1]}</div>
          <div style='font-size:10px;color:#999'>{d.month}/{d.day}</div>
        </div>
        <div style='position:relative;height:{total_h}px;background:{bg0}'>{grid}{''.join(blks)}</div>
      </div>""")

    parts.append("</div>")
    st.markdown(f"<div style='overflow-x:auto'>{''.join(parts)}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;font-size:11px'>"
        f"<span style='background:{CF[1]};color:{CF[0]};padding:1px 7px;border-radius:3px;font-weight:600'>固定課程</span>"
        f"<span style='background:{CPEND[1]};color:{CPEND[0]};padding:1px 7px;border-radius:3px;font-weight:600'>⏳ 審核中</span>"
        f"<span style='background:{CB[1]};color:{CB[0]};padding:1px 7px;border-radius:3px;font-weight:600'>📌 已確認</span>"
        f"<span style='background:{CP2[1]};color:{CP2[0]};padding:1px 7px;border-radius:3px;font-weight:600'>🔔 申請歸還中</span>"
        "</div>", unsafe_allow_html=True
    )

# ═══════════════════════════════════════════════════════════════
#  頁面
# ═══════════════════════════════════════════════════════════════

def page_login():
    st.markdown("<h1 style='text-align:center'>🏛️ 土木館預約系統</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#64748B'>Civil Engineering Building Reservation System</p>", unsafe_allow_html=True)
    st.divider()

    col = st.columns([1, 2, 1])[1]
    with col:
        tab_login, tab_reg, tab_forgot = st.tabs(['🔐 登入 Login', '📝 註冊 Register', '🔑 忘記密碼'])

        # ── 登入 ──
        with tab_login:
            with st.form('lf'):
                sid = st.text_input('學號 / 員工編號 (Student / Staff ID)')
                pw  = st.text_input('密碼 (Password)', type='password')
                if st.form_submit_button('登入 Login', use_container_width=True):
                    user = do_login(sid, pw)
                    if user:
                        bl, bl_reason = is_blacklisted(user['user_id'])
                        if bl:
                            st.error(f'⛔ 您已被列入黑名單，無法登入。\n原因：{bl_reason}\n請聯繫系辦。')
                        else:
                            st.session_state.user = user
                            st.session_state.page = 'query'
                            st.rerun()
                    else:
                        st.error('學號或密碼錯誤')
            st.caption('管理員：admin / admin123　｜　系辦：staff / staff123（學號登入）')

        # ── 註冊 ──
        with tab_reg:
            with st.form('rf'):
                st.markdown("**帳號資訊 Account Info**")
                nu   = st.text_input('姓名（Name）*')
                sid2 = st.text_input('學號 / 員工編號（Student/Staff ID）*')
                ne   = st.text_input('Email *')
                np_  = st.text_input('密碼（Password）*', type='password')
                np2  = st.text_input('確認密碼（Confirm Password）*', type='password')
                st.markdown("**個人資料 Personal Info**")
                identity   = st.selectbox('身份（Identity）*', IDENTITY_OPTIONS)
                department = st.text_input('系所 / 單位（Department）*')
                phone      = st.text_input('聯絡電話（Phone）*')
                if st.form_submit_button('建立帳號 Create Account', use_container_width=True):
                    if np_ != np2:
                        st.error('兩次密碼不一致')
                    else:
                        ok, msg = do_register(nu, np_, ne, phone, identity, sid2, department)
                        st.success(msg + '，請以學號登入') if ok else st.error(msg)

        # ── 忘記密碼 ──
        with tab_forgot:
            st.info('輸入您的學號，系統將發送 6 位數驗證碼至您的 Email。')
            step = st.session_state.get('forgot_step', 1)

            if step == 1:
                with st.form('fp1'):
                    fsid = st.text_input('學號 / 員工編號')
                    if st.form_submit_button('發送驗證碼', use_container_width=True):
                        ok, msg = create_reset_token(fsid)
                        if ok:
                            st.session_state.forgot_sid  = fsid
                            st.session_state.forgot_step = 2
                            st.success(f'驗證碼已寄至 {msg}（請檢查垃圾郵件）')
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                with st.form('fp2'):
                    token   = st.text_input('輸入驗證碼（6位數）')
                    new_pw  = st.text_input('新密碼', type='password')
                    new_pw2 = st.text_input('確認新密碼', type='password')
                    if st.form_submit_button('重設密碼', use_container_width=True):
                        if new_pw != new_pw2:
                            st.error('兩次密碼不一致')
                        else:
                            ok, msg = verify_reset_token(st.session_state.forgot_sid, token, new_pw)
                            if ok:
                                st.success(msg)
                                st.session_state.forgot_step = 1
                                st.rerun()
                            else:
                                st.error(msg)
                if st.button('← 重新發送'):
                    st.session_state.forgot_step = 1; st.rerun()


def page_query():
    st.header('🔍 查詢可用時間')
    tab1, tab2 = st.tabs(['🏫 教室週課表', '🔧 設備查詢'])

    with tab1:
        rooms = get_rooms()
        if not rooms: st.info('目前沒有教室資料'); return
        rm_map = {r['name']: r for r in rooms}
        sel = st.selectbox('選擇教室', list(rm_map.keys()), key='qr_sel')
        room = rm_map[sel]
        if room.get('capacity'):
            st.caption(f"容納人數：{room['capacity']} 人")
        render_room_calendar(room, week_offset_key='qr_week')

    with tab2:
        equips = get_equips()
        if not equips: st.info('目前沒有設備資料'); return
        eq_map = {e['name']: e for e in equips}
        sel = st.selectbox('選擇設備', list(eq_map.keys()), key='qe_sel')
        d   = st.date_input('日期', value=date.today(), key='qe_d')
        equip = eq_map[sel]
        c1,c2,c3 = st.columns(3)
        c1.metric('設備編號', equip['serial_number'] or '—')
        c2.metric('總數量', equip['quantity'] or 1)
        c3.metric('說明', equip['description'] or '—')
        slots = get_equip_slots(equip['equip_id'], str(d))
        if slots:
            st.info(f'📦  {d}  借用狀況：')
            for s in slots:
                qty = s.get('quantity_borrowed') or 1
                st.markdown(f"- `{s['start_time']} ~ {s['end_time']}`　{s['username']}　×{qty}　{SL.get(s['status'],s['status'])}")
        else:
            st.success(f'✅  {d}  此設備無人借用，全部 {equip["quantity"] or 1} 件可借')


def _booking_form(user, rooms, equips):
    """教室和設備預約的表單邏輯"""
    tab1, tab2 = st.tabs(['🏫 預約教室', '🔧 借用設備'])

    with tab1:
        if not rooms:
            st.info('目前沒有教室資料'); return
        rm_map = {r['name']: r for r in rooms}
        sel_room = st.selectbox('選擇教室', list(rm_map.keys()), key='br_sel')
        room = rm_map[sel_room]

        col_cal, col_form = st.columns([3, 2], gap='large')
        with col_cal:
            st.markdown(f"##### 📅 {sel_room} — 本週課表")
            if room.get('capacity'):
                st.caption(f"容納人數：{room['capacity']} 人")
            render_room_calendar(room, week_offset_key='br_week', compact=True)

        with col_form:
            st.markdown("##### ✏️ 填寫預約資訊")
            st.info('⚠️ 預約需提前 1-2 個工作天送出，系辦審核通過後才算成功。')
            with st.form('br'):
                bd  = st.date_input('日期', value=date.today())
                c1, c2 = st.columns(2)
                st_ = c1.time_input('開始時間', value=time(9, 0))
                et_ = c2.time_input('結束時間', value=time(10, 0))
                purpose = st.selectbox('使用用途 *', ROOM_PURPOSES)
                purpose_other = st.text_input('若選「其他」請說明')
                cap = room.get('capacity') or 0
                cap_hint = f'（此教室容納 {cap} 人）' if cap else ''
                attendee_count = st.number_input(
                    f'使用人數 * {cap_hint}',
                    min_value=1, max_value=max(cap, 200) if cap else 200,
                    value=1, step=1
                )
                supervisor = st.text_input('指導老師（Supervisor）*')
                attendees  = st.text_area('使用人員名單（Attendees，可用逗號分隔）', height=80)
                note = st.text_input('備註（選填）')
                if st.form_submit_button('📨 送出預約申請', use_container_width=True):
                    if st_ >= et_:
                        st.error('結束時間必須晚於開始時間')
                    elif cap and attendee_count > cap:
                        st.error(f'使用人數（{attendee_count}）超過教室容量（{cap}），請選較大的教室')
                    elif cap and attendee_count < cap * 0.15 and attendee_count < 5:
                        st.warning(f'⚠️ 使用人數（{attendee_count}）遠少於教室容量（{cap}），建議改訂較小的教室，否則可能影響審核。')
                        st.form_submit_button  # let them reread warning
                    elif not supervisor:
                        st.error('請填寫指導老師')
                    else:
                        fp = purpose_other if purpose == '其他' and purpose_other else purpose
                        ok, msg = book_room(user['user_id'], room['room_id'],
                                            str(bd), str(st_)[:5], str(et_)[:5],
                                            fp, int(attendee_count), supervisor, attendees, note)
                        st.success(f'✅ {msg}') if ok else st.error(msg)
                        if ok: st.balloons()

    with tab2:
        if not equips:
            st.info('目前沒有設備資料'); return
        eq_map = {e['name']: e for e in equips}
        sel_name = st.selectbox('設備', list(eq_map.keys()), key='be_sel_preview')
        ep = eq_map[sel_name]
        ic = st.columns(3)
        ic[0].metric('設備編號', ep['serial_number'] or '—')
        ic[1].metric('總數量', ep['quantity'] or 1)
        ic[2].metric('說明', ep['description'] or '—')
        st.info('⚠️ 借用需提前 1-2 個工作天送出，系辦審核通過後才算成功。')
        with st.form('be'):
            equip_names = list(eq_map.keys())
            sel = st.selectbox('確認設備', equip_names, index=equip_names.index(sel_name), key='be_sel_form')
            equip = eq_map[sel]
            bd   = st.date_input('日期', value=date.today(), key='be_d')
            c1, c2 = st.columns(2)
            st_ = c1.time_input('開始時間', value=time(9, 0), key='be_st')
            et_ = c2.time_input('結束時間', value=time(10, 0), key='be_et')
            mq  = equip['quantity'] or 1
            qty = st.number_input(f'借用數量（最多 {mq} 件）', min_value=1, max_value=mq, value=1, step=1)
            purpose = st.selectbox('使用用途 *', EQUIP_PURPOSES, key='be_purpose')
            purpose_other = st.text_input('若選「其他」請說明', key='be_po')
            supervisor = st.text_input('指導老師（Supervisor）*', key='be_sv')
            attendees  = st.text_area('使用人員名單（Attendees）', height=60, key='be_att')
            note = st.text_input('備註（選填）', key='be_note')
            if st.form_submit_button('📨 送出借用申請', use_container_width=True):
                if st_ >= et_:
                    st.error('結束時間必須晚於開始時間')
                elif not supervisor:
                    st.error('請填寫指導老師')
                else:
                    fp = purpose_other if purpose == '其他' and purpose_other else purpose
                    ok, msg = book_equip(user['user_id'], equip['equip_id'],
                                         str(bd), str(st_)[:5], str(et_)[:5],
                                         int(qty), fp, supervisor, attendees, note)
                    st.success(f'✅ {msg}') if ok else st.error(msg)
                    if ok: st.balloons()


def page_book():
    st.header('📋 預約教室 / 借用設備')
    user = st.session_state.user
    if not user.get('student_id') or not user.get('department') or not user.get('email') or not user.get('phone'):
        st.warning('⚠️ 請先至「👤 個人資料」頁面補齊學號、系所、Email 及電話，才能進行預約。')
        return
    rooms  = get_rooms()
    equips = get_equips()
    _booking_form(user, rooms, equips)


def page_records():
    """合併歷史紀錄 + 我的紀錄"""
    st.header('📚 我的預約紀錄')
    user = st.session_state.user
    tab1, tab2 = st.tabs(['🏫 教室', '🔧 設備'])

    with tab1:
        bks = get_user_room_bookings(user['user_id'])
        # 狀態篩選
        status_filter = st.multiselect(
            '篩選狀態', list(SL.values()),
            default=list(SL.values()), key='rf_r'
        )
        shown = [b for b in bks if SL.get(b['status'], b['status']) in status_filter]
        if not shown:
            st.info('無符合條件的記錄')
        for b in shown:
            sl = SL.get(b['status'], b['status'])
            label = f"{b['room_name']}　{b['book_date']}　{b['start_time']}~{b['end_time']}　{sl}"
            with st.expander(label):
                c1, c2 = st.columns(2)
                c1.write(f"**用途：** {b.get('purpose') or '—'}")
                c1.write(f"**使用人數：** {b.get('attendee_count') or '—'}")
                c1.write(f"**指導老師：** {b.get('supervisor') or '—'}")
                c2.write(f"**使用人員：** {b.get('attendees') or '—'}")
                c2.write(f"**備註：** {b.get('note') or '—'}")
                c2.write(f"**建立時間：** {b['created_at']}")
                if b.get('returned_at'):
                    c2.write(f"**歸還時間：** {b['returned_at']}")
                if b.get('reject_reason'):
                    st.error(f"拒絕原因：{b['reject_reason']}")

                if b['status'] == 'confirmed':
                    ca, cb, cc = st.columns(3)
                    if ca.button('🔔 申請歸還', key=f"rr_{b['booking_id']}"):
                        request_return_room(b['booking_id'], user['user_id']); st.rerun()
                    if cb.button('❌ 取消', key=f"cr_{b['booking_id']}"):
                        cancel_room(b['booking_id'], user['user_id']); st.rerun()
                    if cc.button('✏️ 修改', key=f"mr_{b['booking_id']}"):
                        st.session_state[f'mod_r_{b["booking_id"]}'] = True

                elif b['status'] == 'pending':
                    st.info('⏳ 等待系辦審核中')
                    if st.button('❌ 撤回申請', key=f"cr_{b['booking_id']}"):
                        cancel_room(b['booking_id'], user['user_id']); st.rerun()

                elif b['status'] == 'pending_return':
                    st.info('🔔 歸還申請已送出，待系辦確認')
                    if st.button('↩️ 撤回歸還申請', key=f"ur_{b['booking_id']}"):
                        db = conn()
                        db.execute("UPDATE ROOM_BOOKING SET status='confirmed' WHERE booking_id=? AND user_id=?",
                                   (b['booking_id'], user['user_id']))
                        db.commit(); db.close(); st.rerun()

                if st.session_state.get(f'mod_r_{b["booking_id"]}'):
                    rooms = get_rooms()
                    rm_map = {r['name']: r for r in rooms}
                    with st.form(f'mf_r_{b["booking_id"]}'):
                        nd = st.date_input('新日期', value=date.fromisoformat(b['book_date']))
                        mc1, mc2 = st.columns(2)
                        ns = mc1.time_input('新開始', value=time.fromisoformat(b['start_time']))
                        ne_t = mc2.time_input('新結束', value=time.fromisoformat(b['end_time']))
                        cur_p = b.get('purpose') or ROOM_PURPOSES[0]
                        pidx = ROOM_PURPOSES.index(cur_p) if cur_p in ROOM_PURPOSES else len(ROOM_PURPOSES)-1
                        np_s = st.selectbox('用途', ROOM_PURPOSES, index=pidx)
                        np_o = st.text_input('若選「其他」請說明', value=cur_p if cur_p not in ROOM_PURPOSES else '')
                        n_ac = st.number_input('使用人數', min_value=1, value=b.get('attendee_count') or 1)
                        n_sv = st.text_input('指導老師', value=b.get('supervisor') or '')
                        n_at = st.text_area('使用人員名單', value=b.get('attendees') or '', height=60)
                        nn   = st.text_input('備註', value=b.get('note') or '')
                        if st.form_submit_button('確認修改（重新送審）'):
                            fp = np_o if np_s == '其他' and np_o else np_s
                            ok, msg = modify_room(b['booking_id'], user['user_id'],
                                                  b['room_id'], str(nd),
                                                  str(ns)[:5], str(ne_t)[:5],
                                                  fp, int(n_ac), n_sv, n_at, nn)
                            if ok:
                                st.success(msg)
                                st.session_state.pop(f'mod_r_{b["booking_id"]}', None)
                                st.rerun()
                            else:
                                st.error(msg)

    with tab2:
        bks = get_user_equip_bookings(user['user_id'])
        status_filter2 = st.multiselect(
            '篩選狀態', list(SL.values()),
            default=list(SL.values()), key='rf_e'
        )
        shown = [b for b in bks if SL.get(b['status'], b['status']) in status_filter2]
        if not shown:
            st.info('無符合條件的記錄')
        for b in shown:
            sl = SL.get(b['status'], b['status'])
            qty = b.get('quantity_borrowed') or 1
            label = (f"{b['equip_name']}（{b.get('serial_number') or '—'}）"
                     f"　×{qty}　{b['book_date']}　{b['start_time']}~{b['end_time']}　{sl}")
            with st.expander(label):
                c1, c2 = st.columns(2)
                c1.write(f"**設備編號：** {b.get('serial_number') or '—'}")
                c1.write(f"**借用數量：** {qty} 件")
                c1.write(f"**用途：** {b.get('purpose') or '—'}")
                c1.write(f"**指導老師：** {b.get('supervisor') or '—'}")
                c2.write(f"**使用人員：** {b.get('attendees') or '—'}")
                c2.write(f"**備註：** {b.get('note') or '—'}")
                c2.write(f"**建立時間：** {b['created_at']}")
                if b.get('returned_at'):
                    c2.write(f"**歸還時間：** {b['returned_at']}")
                if b.get('reject_reason'):
                    st.error(f"拒絕原因：{b['reject_reason']}")

                if b['status'] == 'confirmed':
                    ca, cb = st.columns(2)
                    if ca.button('🔔 申請歸還', key=f"re_{b['booking_id']}"):
                        request_return_equip(b['booking_id'], user['user_id']); st.rerun()
                    if cb.button('❌ 取消', key=f"ce_{b['booking_id']}"):
                        cancel_equip(b['booking_id'], user['user_id']); st.rerun()
                elif b['status'] == 'pending':
                    st.info('⏳ 等待系辦審核中')
                    if st.button('❌ 撤回申請', key=f"ce_{b['booking_id']}"):
                        cancel_equip(b['booking_id'], user['user_id']); st.rerun()
                elif b['status'] == 'pending_return':
                    st.info('🔔 歸還申請已送出，待系辦確認')
                    if st.button('↩️ 撤回歸還申請', key=f"ue_{b['booking_id']}"):
                        db = conn()
                        db.execute("UPDATE EQUIP_BOOKING SET status='confirmed' WHERE booking_id=? AND user_id=?",
                                   (b['booking_id'], user['user_id']))
                        db.commit(); db.close(); st.rerun()


def page_profile():
    st.header('👤 個人資料')
    user = st.session_state.user

    st.info(f"帳號：**{user['username']}**　｜　角色：{ROLE_LABEL.get(user['role'], '?')}　｜　學號：{user.get('student_id') or '未設定'}")

    tab_p, tab_pw = st.tabs(['✏️ 編輯資料', '🔒 修改密碼'])

    with tab_p:
        with st.form('pf'):
            email      = st.text_input('Email *', value=user.get('email') or '')
            phone      = st.text_input('聯絡電話（Phone）*', value=user.get('phone') or '')
            identity   = st.selectbox('身份', IDENTITY_OPTIONS,
                index=IDENTITY_OPTIONS.index(user['identity']) if user.get('identity') in IDENTITY_OPTIONS else 0)
            student_id = st.text_input('學號 / 員工編號 *', value=user.get('student_id') or '')
            department = st.text_input('系所 / 單位 *', value=user.get('department') or '')
            if st.form_submit_button('💾 儲存', use_container_width=True):
                if not email or not phone or not student_id or not department:
                    st.error('Email、電話、學號、系所皆為必填')
                else:
                    updated = update_profile(user['user_id'], email, phone, identity, student_id, department)
                    st.session_state.user = updated
                    st.success('✅ 已更新'); st.rerun()

    with tab_pw:
        with st.form('cpf'):
            old_pw = st.text_input('舊密碼', type='password')
            new_pw = st.text_input('新密碼', type='password')
            new_pw2 = st.text_input('確認新密碼', type='password')
            if st.form_submit_button('更新密碼', use_container_width=True):
                if new_pw != new_pw2:
                    st.error('兩次密碼不一致')
                else:
                    ok, msg = change_password(user['user_id'], old_pw, new_pw)
                    st.success(msg) if ok else st.error(msg)


def _render_approve_section(pending_r, pending_e):
    """審核區塊（系辦+管理員共用）"""
    st.subheader(f'🔔 待審核 — 教室（{len(pending_r)}）')
    if not pending_r:
        st.success('無待審核教室申請')
    for b in pending_r:
        with st.expander(f"[教室] {b['room_name']}　{b['book_date']} {b['start_time']}~{b['end_time']}　👤 {b['username']}"):
            c1, c2 = st.columns(2)
            c1.write(f"**姓名：** {b['username']}"); c1.write(f"**身份：** {b.get('identity') or '—'}")
            c1.write(f"**系所：** {b.get('department') or '—'}"); c1.write(f"**學號：** {b.get('student_id') or '—'}")
            c2.write(f"**電話：** {b.get('phone') or '—'}"); c2.write(f"**Email：** {b.get('email') or '—'}")
            c2.write(f"**容量：** {b.get('capacity') or '—'}　**人數：** {b.get('attendee_count') or '—'}")
            cap = b.get('capacity') or 0; ac = b.get('attendee_count') or 1
            if cap and ac < cap * 0.15 and ac < 5:
                st.warning(f'⚠️ 使用人數（{ac}）遠少於容量（{cap}），請注意')
            st.write(f"**用途：** {b.get('purpose') or '—'}　**指導老師：** {b.get('supervisor') or '—'}")
            st.write(f"**使用人員：** {b.get('attendees') or '—'}")
            ca, cb = st.columns(2)
            if ca.button('✅ 核准', key=f"apr_{b['booking_id']}", type='primary'):
                approve_room(b['booking_id'], st.session_state.user['user_id'])
                st.success('已核准並通知申請人'); st.rerun()
            rj_r = cb.text_input('拒絕原因', key=f"rjr_{b['booking_id']}")
            if cb.button('❌ 拒絕', key=f"rj_{b['booking_id']}"):
                reject_room(b['booking_id'], rj_r or '系辦未說明原因')
                st.warning('已拒絕並通知申請人'); st.rerun()

    st.divider()
    st.subheader(f'🔔 待審核 — 設備（{len(pending_e)}）')
    if not pending_e:
        st.success('無待審核設備申請')
    for b in pending_e:
        qty = b.get('quantity_borrowed') or 1
        with st.expander(f"[設備] {b['equip_name']}（{b.get('serial_number') or '—'}）×{qty}　{b['book_date']}　👤 {b['username']}"):
            c1, c2 = st.columns(2)
            c1.write(f"**姓名：** {b['username']}"); c1.write(f"**學號：** {b.get('student_id') or '—'}")
            c1.write(f"**系所：** {b.get('department') or '—'}"); c2.write(f"**電話：** {b.get('phone') or '—'}")
            c2.write(f"**Email：** {b.get('email') or '—'}"); c2.write(f"**借用數量：** {qty} 件")
            st.write(f"**用途：** {b.get('purpose') or '—'}　**指導老師：** {b.get('supervisor') or '—'}")
            st.write(f"**使用人員：** {b.get('attendees') or '—'}")
            ca, cb = st.columns(2)
            if ca.button('✅ 核准', key=f"ape_{b['booking_id']}", type='primary'):
                approve_equip(b['booking_id'])
                st.success('已核准並通知申請人'); st.rerun()
            rj_r2 = cb.text_input('拒絕原因', key=f"rjre_{b['booking_id']}")
            if cb.button('❌ 拒絕', key=f"rje_{b['booking_id']}"):
                reject_equip(b['booking_id'], rj_r2 or '系辦未說明原因')
                st.warning('已拒絕並通知申請人'); st.rerun()


def page_staff():
    st.header('🏢 系辦管理台')
    pend_r = pending_room_approvals()
    pend_e = pending_equip_approvals()
    ret_r  = pending_room_returns()
    ret_e  = pending_equip_returns()
    total  = len(pend_r) + len(pend_e) + len(ret_r) + len(ret_e)
    if total:
        st.error(f'🔔 共 **{total}** 筆待處理（審核：{len(pend_r)+len(pend_e)}　歸還確認：{len(ret_r)+len(ret_e)}）')
    else:
        st.success('✅ 目前沒有待處理項目')

    tabs = st.tabs(['🔔 待審核', '📦 待確認歸還', '📋 所有教室預約', '🔧 所有設備借用'])

    with tabs[0]:
        _render_approve_section(pend_r, pend_e)

    with tabs[1]:
        st.subheader(f'待確認教室歸還（{len(ret_r)}）')
        if not ret_r: st.info('無')
        for b in ret_r:
            with st.expander(f"[教室] {b['room_name']}　{b['book_date']}　👤 {b['username']}"):
                st.write(f"**電話：** {b.get('phone') or '—'}　**Email：** {b.get('email') or '—'}")
                ca, cb = st.columns(2)
                if ca.button('✅ 確認已歸還', key=f"cfr_{b['booking_id']}", type='primary'):
                    confirm_return_room(b['booking_id']); st.rerun()
                if cb.button('❌ 退回申請', key=f"rtr_{b['booking_id']}"):
                    db2 = conn()
                    db2.execute("UPDATE ROOM_BOOKING SET status='confirmed' WHERE booking_id=?", (b['booking_id'],))
                    db2.commit(); db2.close(); st.rerun()

        st.divider()
        st.subheader(f'待確認設備歸還（{len(ret_e)}）')
        if not ret_e: st.info('無')
        for b in ret_e:
            with st.expander(f"[設備] {b['equip_name']}　{b['book_date']}　👤 {b['username']}"):
                st.write(f"**電話：** {b.get('phone') or '—'}　**Email：** {b.get('email') or '—'}")
                ca, cb = st.columns(2)
                if ca.button('✅ 確認已歸還', key=f"cfe_{b['booking_id']}", type='primary'):
                    confirm_return_equip(b['booking_id']); st.rerun()
                if cb.button('❌ 退回申請', key=f"rte_{b['booking_id']}"):
                    db2 = conn()
                    db2.execute("UPDATE EQUIP_BOOKING SET status='confirmed' WHERE booking_id=?", (b['booking_id'],))
                    db2.commit(); db2.close(); st.rerun()

    with tabs[2]:
        bks = all_room_bookings()
        if not bks: st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id','username','identity','department','student_id','phone',
                                     'room_name','book_date','start_time','end_time',
                                     'attendee_count','supervisor','purpose','status','returned_at','note']]
            df.columns = ['ID','姓名','身份','系所','學號','電話','教室','日期','開始','結束','人數','老師','用途','狀態','歸還時間','備註']
            df['狀態'] = df['狀態'].map(lambda x: SL.get(x, x))
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[3]:
        bks = all_equip_bookings()
        if not bks: st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id','username','identity','department','student_id','phone',
                                     'equip_name','serial_number','book_date','start_time','end_time',
                                     'quantity_borrowed','supervisor','purpose','status','returned_at']]
            df.columns = ['ID','姓名','身份','系所','學號','電話','設備','設備編號','日期','開始','結束','數量','老師','用途','狀態','歸還時間']
            df['狀態'] = df['狀態'].map(lambda x: SL.get(x, x))
            st.dataframe(df, use_container_width=True, hide_index=True)


def page_admin():
    st.header('⚙️ 管理員後台')
    tabs = st.tabs(['🏫 管理教室', '🔧 管理設備', '🔔 審核 & 歸還', '👥 使用者', '⛔ 黑名單', '📧 SMTP 設定'])

    with tabs[0]:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader('新增教室')
            with st.form('ar'):
                nm  = st.text_input('教室名稱 *')
                cap = st.number_input('容納人數 *', min_value=1, value=30, step=1)
                ds  = st.text_input('說明（選填）')
                if st.form_submit_button('新增', use_container_width=True):
                    ok, msg = add_room(nm, ds, int(cap))
                    st.success(msg) if ok else st.error(msg)
                    if ok: st.rerun()
        with col2:
            st.subheader('現有教室')
            for r in get_rooms():
                with st.expander(f"🏫 {r['name']}（容量：{r.get('capacity') or '—'}）"):
                    with st.form(f"er_{r['room_id']}"):
                        nn = st.text_input('名稱', value=r['name'])
                        nc = st.number_input('容量', min_value=1, value=r.get('capacity') or 1)
                        nd = st.text_input('說明', value=r.get('description') or '')
                        ca, cb = st.columns(2)
                        if ca.form_submit_button('💾 儲存'):
                            update_room(r['room_id'], nn, nd, int(nc)); st.success('已更新'); st.rerun()
                        if cb.form_submit_button('🚫 停用'):
                            disable_room(r['room_id']); st.rerun()

        st.divider()
        st.subheader('📅 管理固定課程')
        rooms_fc = get_rooms()
        if rooms_fc:
            fc_sel = st.selectbox('選擇教室', [r['name'] for r in rooms_fc], key='fc_rm')
            fc_room = next(r for r in rooms_fc if r['name'] == fc_sel)
            with st.form('add_fc'):
                c1, c2, c3 = st.columns(3)
                fc_wd = c1.selectbox('星期', WEEKDAY_ZH)
                fc_st = c2.time_input('開始', value=time(8,0))
                fc_et = c3.time_input('結束', value=time(10,0))
                fc_ttl = st.text_input('課程名稱 *')
                fc_nt  = st.text_input('備註')
                if st.form_submit_button('➕ 新增'):
                    if not fc_ttl: st.error('請填課程名稱')
                    elif fc_st >= fc_et: st.error('時間錯誤')
                    else:
                        add_fixed_course(fc_room['room_id'], WEEKDAY_ZH.index(fc_wd),
                                         str(fc_st)[:5], str(fc_et)[:5], fc_ttl, fc_nt)
                        st.success('已新增'); st.rerun()
            for fc in get_fixed_courses(fc_room['room_id']):
                r1, r2, r3 = st.columns([2,4,1])
                r1.write(f"**{WEEKDAY_ZH[fc['weekday']]}** {fc['start_time']}～{fc['end_time']}")
                r2.write(f"📘 {fc['title']}" + (f"　{fc['note']}" if fc.get('note') else ''))
                if r3.button('🗑️', key=f"dfc_{fc['course_id']}"):
                    delete_fixed_course(fc['course_id']); st.rerun()

    with tabs[1]:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader('新增設備')
            with st.form('ae'):
                nm  = st.text_input('設備名稱 *')
                sn  = st.text_input('設備編號（如 NB-001）')
                qty = st.number_input('數量 *', min_value=1, value=1)
                ds  = st.text_input('說明')
                if st.form_submit_button('新增', use_container_width=True):
                    if not nm: st.error('請填設備名稱')
                    else:
                        ok, msg = add_equip(nm, sn, int(qty), ds)
                        st.success(msg) if ok else st.error(msg)
                        if ok: st.rerun()
        with col2:
            st.subheader('現有設備')
            for e in get_equips():
                with st.expander(f"🔧 {e['name']}（{e.get('serial_number') or '—'}）×{e['quantity'] or 1}"):
                    with st.form(f"ee_{e['equip_id']}"):
                        nn = st.text_input('名稱', value=e['name'])
                        ns = st.text_input('編號', value=e.get('serial_number') or '')
                        nq = st.number_input('數量', min_value=1, value=e['quantity'] or 1)
                        nd = st.text_input('說明', value=e.get('description') or '')
                        ca, cb = st.columns(2)
                        if ca.form_submit_button('💾 儲存'):
                            update_equip(e['equip_id'], nn, ns, int(nq), nd); st.success('已更新'); st.rerun()
                        if cb.form_submit_button('🚫 停用'):
                            disable_equip(e['equip_id']); st.rerun()

    with tabs[2]:
        pend_r = pending_room_approvals()
        pend_e = pending_equip_approvals()
        _render_approve_section(pend_r, pend_e)
        st.divider()
        st.subheader('強制操作')
        c1, c2 = st.columns(2)
        bid1 = c1.number_input('教室預約 ID 強制歸還', min_value=1, step=1, key='adm_rr')
        if c1.button('強制歸還教室'):
            return_room(int(bid1)); st.success('已歸還'); st.rerun()
        bid2 = c2.number_input('設備借用 ID 強制歸還', min_value=1, step=1, key='adm_re')
        if c2.button('強制歸還設備'):
            return_equip(int(bid2)); st.success('已歸還'); st.rerun()

    with tabs[3]:
        users = get_all_users()
        df = pd.DataFrame(users)[['username','role','identity','student_id','department','phone','email','created_at']]
        df.columns = ['姓名','角色','身份','學號/員工編號','系所/單位','電話','Email','註冊時間']
        df['角色'] = df['角色'].map(lambda x: ROLE_LABEL.get(x, x))
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()
        st.subheader('🔧 變更角色')
        unames = [u['username'] for u in users if u['username'] not in ('admin',)]
        if unames:
            tc1, tc2, tc3 = st.columns(3)
            tu = tc1.selectbox('選擇使用者', unames, key='role_tgt')
            cur_r = next((u['role'] for u in users if u['username'] == tu), 'user')
            nr = tc2.selectbox('設定角色', ['user','staff','admin'],
                               index=['user','staff','admin'].index(cur_r) if cur_r in ['user','staff','admin'] else 0,
                               format_func=lambda x: ROLE_LABEL.get(x, x), key='role_new')
            if tc3.button('💾 更新', use_container_width=True):
                db2 = conn()
                db2.execute("UPDATE USER SET role=? WHERE username=?", (nr, tu))
                db2.commit(); db2.close()
                st.success(f'已將 {tu} 設為 {ROLE_LABEL.get(nr)}'); st.rerun()

    with tabs[4]:
        st.subheader('⛔ 黑名單管理')
        st.caption('黑名單使用者將無法登入系統。')
        bl_list = get_blacklist()
        if bl_list:
            for bl in bl_list:
                with st.expander(f"⛔ {bl['username']}（{bl.get('student_id') or '—'}）　{bl['department'] or '—'}"):
                    st.write(f"**違規原因：** {bl['reason']}")
                    st.write(f"**加入時間：** {bl['added_at']}　**加入者：** {bl['added_by_name']}")
                    if st.button('✅ 移除黑名單', key=f"rbl_{bl['bl_id']}"):
                        remove_blacklist(bl['user_id']); st.rerun()
        else:
            st.info('目前黑名單為空')
        st.divider()
        st.subheader('新增黑名單')
        users_for_bl = [u for u in get_all_users() if u['role'] == 'user']
        bl_ids = {b['user_id'] for b in bl_list}
        users_not_bl = [u for u in users_for_bl if u['user_id'] not in bl_ids]
        if users_not_bl:
            with st.form('add_bl'):
                bl_target = st.selectbox(
                    '選擇使用者',
                    [f"{u['username']}（{u.get('student_id') or '—'}）" for u in users_not_bl]
                )
                bl_reason_sel = st.selectbox('違規原因', BLACKLIST_REASONS)
                bl_reason_other = st.text_input('若選「其他」請說明')
                if st.form_submit_button('⛔ 加入黑名單', use_container_width=True):
                    idx = [f"{u['username']}（{u.get('student_id') or '—'}）" for u in users_not_bl].index(bl_target)
                    target_uid = users_not_bl[idx]['user_id']
                    reason = bl_reason_other if bl_reason_sel == '其他違規行為' and bl_reason_other else bl_reason_sel
                    ok, msg = add_blacklist(target_uid, reason, st.session_state.user['user_id'])
                    st.success(msg) if ok else st.error(msg)
                    if ok: st.rerun()

    with tabs[5]:
        st.subheader('📧 SMTP 郵件設定')
        cfg = get_smtp_config()
        with st.form('smtp_form'):
            host        = st.text_input('SMTP 主機', value=cfg.get('host') or '', placeholder='smtp.gmail.com')
            port        = st.number_input('連接埠', value=cfg.get('port') or 587, min_value=1, max_value=65535)
            username    = st.text_input('帳號（寄件 Email）', value=cfg.get('username') or '')
            password    = st.text_input('密碼 / App Password', value=cfg.get('password') or '', type='password')
            use_tls     = st.checkbox('使用 TLS（STARTTLS）', value=bool(cfg.get('use_tls', 1)))
            sender_name = st.text_input('寄件人名稱', value=cfg.get('sender_name') or '土木館預約系統')
            if st.form_submit_button('💾 儲存 SMTP 設定', use_container_width=True):
                save_smtp_config(host, port, username, password, use_tls, sender_name)
                st.success('✅ SMTP 設定已儲存')

        st.divider()
        st.subheader('測試寄信')
        test_to = st.text_input('測試收件 Email')
        if st.button('📨 發送測試信'):
            ok2, msg2 = send_email(test_to, '【土木館預約系統】測試信',
                                   '<p>✅ SMTP 設定正常，此為測試信件。</p>')
            if ok2: st.success('已送出（請查收，可能需要幾秒）')
            else:   st.error(msg2)


# ═══════════════════════════════════════════════════════════════
#  主程式
# ═══════════════════════════════════════════════════════════════

_reminder_started = False

def main():
    global _reminder_started

    st.set_page_config(
        page_title='土木館預約系統',
        page_icon='🏛️',
        layout='wide',
        initial_sidebar_state='expanded'
    )
    init_db()

    # 啟動提醒背景執行緒（只啟動一次）
    if not _reminder_started:
        threading.Thread(target=_reminder_worker, daemon=True).start()
        _reminder_started = True

    if 'user' not in st.session_state:
        page_login(); return

    user     = st.session_state.user
    is_adm   = user['role'] == 'admin'
    is_staff = user['role'] in ('admin', 'staff')

    with st.sidebar:
        st.markdown(f"### 👤 {user['username']}")
        st.caption(ROLE_LABEL.get(user['role'], '?'))
        if user.get('department'):
            st.caption(f"🏢 {user.get('identity','')}　{user['department']}")
        if user.get('student_id'):
            st.caption(f"🪪 {user['student_id']}")
        st.divider()

        if is_staff:
            pend = (len(pending_room_approvals()) + len(pending_equip_approvals()) +
                    len(pending_room_returns())   + len(pending_equip_returns()))
            if pend:
                st.warning(f'🔔 {pend} 筆待處理')

        nav = {
            '🔍 查詢可用時間': 'query',
            '📋 預約 / 借用':  'book',
            '📚 我的紀錄':     'records',
            '👤 個人資料':     'profile',
        }
        if is_staff:
            nav['🏢 系辦管理台'] = 'staff'
        if is_adm:
            nav['⚙️ 管理員後台'] = 'admin'

        if 'page' not in st.session_state:
            st.session_state.page = 'query'

        for label, key in nav.items():
            if st.button(label, use_container_width=True,
                         type='primary' if st.session_state.page == key else 'secondary'):
                st.session_state.page = key; st.rerun()

        st.divider()
        if st.button('🚪 登出', use_container_width=True):
            st.session_state.clear(); st.rerun()

    page_map = {
        'query':   page_query,
        'book':    page_book,
        'records': page_records,
        'profile': page_profile,
        'staff':   page_staff,
        'admin':   page_admin,
    }
    page_map.get(st.session_state.get('page', 'query'), page_query)()


if __name__ == '__main__':
    main()