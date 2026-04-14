import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from datetime import datetime, date, time

# ═══════════════════════════════════════════════════════════════
#  資料庫
# ═══════════════════════════════════════════════════════════════

DB = 'civil_booking.db'


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def hp(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def nows():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def ensure_column(db, table, column, col_type):
    cols = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db():
    db = conn()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS USER (
            user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            role       TEXT DEFAULT 'user',
            identity   TEXT,
            student_id TEXT,
            department TEXT,
            phone      TEXT,
            email      TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS ROOM (
            room_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active   INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS EQUIPMENT (
            equip_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            is_active   INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS ROOM_BOOKING (
            booking_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            room_id      INTEGER,
            book_date    TEXT,
            start_time   TEXT,
            end_time     TEXT,
            purpose      TEXT,
            status       TEXT DEFAULT 'confirmed',
            note         TEXT,
            created_at   TEXT,
            finished_at  TEXT,
            FOREIGN KEY (user_id) REFERENCES USER(user_id),
            FOREIGN KEY (room_id) REFERENCES ROOM(room_id)
        );
        CREATE TABLE IF NOT EXISTS EQUIP_BOOKING (
            booking_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            equip_id    INTEGER,
            book_date   TEXT,
            start_time  TEXT,
            end_time    TEXT,
            status      TEXT DEFAULT 'borrowed',
            returned_at TEXT,
            note        TEXT,
            created_at  TEXT,
            FOREIGN KEY (user_id) REFERENCES USER(user_id),
            FOREIGN KEY (equip_id) REFERENCES EQUIPMENT(equip_id)
        );
    ''')

    # 若舊資料庫沒有新欄位，這裡自動補上
    ensure_column(db, 'USER', 'identity', 'TEXT')
    ensure_column(db, 'USER', 'student_id', 'TEXT')
    ensure_column(db, 'USER', 'department', 'TEXT')
    ensure_column(db, 'USER', 'phone', 'TEXT')
    ensure_column(db, 'ROOM_BOOKING', 'purpose', 'TEXT')
    ensure_column(db, 'ROOM_BOOKING', 'finished_at', 'TEXT')

    cur = db.cursor()
    if not cur.execute("SELECT 1 FROM USER WHERE username='admin'").fetchone():
        cur.execute(
            "INSERT INTO USER VALUES (NULL,'admin',?,'admin',NULL,?)",
            (hp('admin123'), nows())
        )

    for r in ['土木 204', '土木 205', '土木 206', '土木 207', '土木 208']:
        if not cur.execute("SELECT 1 FROM ROOM WHERE name=?", (r,)).fetchone():
            cur.execute("INSERT INTO ROOM VALUES (NULL,?,NULL,1)", (r,))

    for e in ['筆電', '延長線']:
        if not cur.execute("SELECT 1 FROM EQUIPMENT WHERE name=?", (e,)).fetchone():
            cur.execute("INSERT INTO EQUIPMENT VALUES (NULL,?,NULL,1)", (e,))

    db.commit()
    db.close()


# ── Auth ──────────────────────────────────────────────────────

def do_login(username, password):
    db = conn()
    row = db.execute(
        "SELECT * FROM USER WHERE username=? AND password=?",
        (username, hp(password))
    ).fetchone()
    db.close()
    return dict(row) if row else None


def do_register(username, password, identity, student_id, department, phone, email):
    db = conn()
    try:
        db.execute(
            "INSERT INTO USER VALUES (NULL,?,?,'user',?,?,?,?,?,?)",
            (username, hp(password), identity, student_id, department, phone, email, nows())
        )
        db.commit()
        db.close()
        return True, '註冊成功'
    except sqlite3.IntegrityError:
        db.close()
        return False, '此帳號已存在'


# ── Room ──────────────────────────────────────────────────────

def get_rooms():
    db = conn()
    rows = db.execute("SELECT * FROM ROOM WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


def room_conflict(room_id, book_date, start_time, end_time, exclude=None):
    db = conn()
    q = (
        "SELECT 1 FROM ROOM_BOOKING "
        "WHERE room_id=? AND book_date=? AND status='confirmed' "
        "AND start_time < ? AND end_time > ?" +
        (" AND booking_id != ?" if exclude else "")
    )
    p = [room_id, book_date, end_time, start_time]
    if exclude:
        p.append(exclude)
    r = db.execute(q, p).fetchone()
    db.close()
    return r is not None


def book_room(user_id, room_id, book_date, st_, et_, purpose, note):
    if room_conflict(room_id, book_date, st_, et_):
        return False, '此時段已有人預約，請選擇其他時段'
    db = conn()
    db.execute(
        "INSERT INTO ROOM_BOOKING VALUES (NULL,?,?,?,?,?,?,?, ?,NULL)",
        (user_id, room_id, book_date, st_, et_, purpose, 'confirmed', note, nows())
    )
    db.commit()
    db.close()
    return True, '預約成功'


def get_room_slots(room_id, book_date):
    db = conn()
    rows = db.execute(
        """SELECT rb.*, u.username FROM ROOM_BOOKING rb
        JOIN USER u ON rb.user_id=u.user_id
        WHERE rb.room_id=? AND rb.book_date=? AND rb.status='confirmed'
        ORDER BY rb.start_time""",
        (room_id, book_date)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_user_room_bookings(user_id):
    db = conn()
    rows = db.execute(
        """SELECT rb.*, r.name AS room_name FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id WHERE rb.user_id=?
        ORDER BY rb.book_date DESC, rb.start_time DESC""",
        (user_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def cancel_room(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE ROOM_BOOKING SET status='cancelled' WHERE booking_id=? AND user_id=?",
            (booking_id, user_id)
        )
    else:
        db.execute(
            "UPDATE ROOM_BOOKING SET status='cancelled' WHERE booking_id=?",
            (booking_id,)
        )
    db.commit()
    db.close()


def finish_room(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE ROOM_BOOKING SET status='finished', finished_at=? WHERE booking_id=? AND user_id=? AND status='confirmed'",
            (nows(), booking_id, user_id)
        )
    else:
        db.execute(
            "UPDATE ROOM_BOOKING SET status='finished', finished_at=? WHERE booking_id=? AND status='confirmed'",
            (nows(), booking_id)
        )
    db.commit()
    db.close()


def modify_room(booking_id, user_id, room_id, book_date, st_, et_, purpose, note):
    if room_conflict(room_id, book_date, st_, et_, exclude=booking_id):
        return False, '此時段已有人預約'
    db = conn()
    db.execute(
        "UPDATE ROOM_BOOKING SET book_date=?,start_time=?,end_time=?,purpose=?,note=? WHERE booking_id=? AND user_id=?",
        (book_date, st_, et_, purpose, note, booking_id, user_id)
    )
    db.commit()
    db.close()
    return True, '修改成功'


def all_room_bookings():
    db = conn()
    rows = db.execute(
        """SELECT rb.*, r.name AS room_name, u.username FROM ROOM_BOOKING rb
        JOIN ROOM r ON rb.room_id=r.room_id JOIN USER u ON rb.user_id=u.user_id
        ORDER BY rb.book_date DESC, rb.start_time DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ── Equipment ─────────────────────────────────────────────────

def get_equips():
    db = conn()
    rows = db.execute("SELECT * FROM EQUIPMENT WHERE is_active=1 ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


def book_equip(user_id, equip_id, book_date, st_, et_, note):
    db = conn()
    db.execute(
        "INSERT INTO EQUIP_BOOKING VALUES (NULL,?,?,?,?,?,'borrowed',NULL,?,?)",
        (user_id, equip_id, book_date, st_, et_, note, nows())
    )
    db.commit()
    db.close()
    return True, '借用成功'


def get_equip_slots(equip_id, book_date):
    db = conn()
    rows = db.execute(
        """SELECT eb.*, u.username FROM EQUIP_BOOKING eb
        JOIN USER u ON eb.user_id=u.user_id
        WHERE eb.equip_id=? AND eb.book_date=? AND eb.status='borrowed'
        ORDER BY eb.start_time""",
        (equip_id, book_date)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_user_equip_bookings(user_id):
    db = conn()
    rows = db.execute(
        """SELECT eb.*, e.name AS equip_name FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id WHERE eb.user_id=?
        ORDER BY eb.book_date DESC, eb.start_time DESC""",
        (user_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def return_equip(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE EQUIP_BOOKING SET status='returned',returned_at=? WHERE booking_id=? AND user_id=? AND status='borrowed'",
            (nows(), booking_id, user_id)
        )
    else:
        db.execute(
            "UPDATE EQUIP_BOOKING SET status='returned',returned_at=? WHERE booking_id=? AND status='borrowed'",
            (nows(), booking_id)
        )
    db.commit()
    db.close()


def cancel_equip(booking_id, user_id=None):
    db = conn()
    if user_id:
        db.execute(
            "UPDATE EQUIP_BOOKING SET status='cancelled' WHERE booking_id=? AND user_id=?",
            (booking_id, user_id)
        )
    else:
        db.execute(
            "UPDATE EQUIP_BOOKING SET status='cancelled' WHERE booking_id=?",
            (booking_id,)
        )
    db.commit()
    db.close()


def all_equip_bookings():
    db = conn()
    rows = db.execute(
        """SELECT eb.*, e.name AS equip_name, u.username FROM EQUIP_BOOKING eb
        JOIN EQUIPMENT e ON eb.equip_id=e.equip_id JOIN USER u ON eb.user_id=u.user_id
        ORDER BY eb.book_date DESC, eb.start_time DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ── Admin ─────────────────────────────────────────────────────

def add_room(name, desc):
    db = conn()
    try:
        db.execute("INSERT INTO ROOM VALUES (NULL,?,?,1)", (name, desc))
        db.commit()
        db.close()
        return True, '新增成功'
    except sqlite3.IntegrityError:
        db.close()
        return False, '此名稱已存在'


def add_equip(name, desc):
    db = conn()
    db.execute("INSERT INTO EQUIPMENT VALUES (NULL,?,?,1)", (name, desc))
    db.commit()
    db.close()
    return True, '新增成功'


def disable_room(room_id):
    db = conn()
    db.execute("UPDATE ROOM SET is_active=0 WHERE room_id=?", (room_id,))
    db.commit()
    db.close()


def disable_equip(equip_id):
    db = conn()
    db.execute("UPDATE EQUIPMENT SET is_active=0 WHERE equip_id=?", (equip_id,))
    db.commit()
    db.close()


def get_all_users():
    db = conn()
    rows = db.execute(
        "SELECT user_id,username,role,identity,student_id,department,phone,email,created_at FROM USER ORDER BY created_at DESC"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# ── Status labels ──────────────────────────────────────────────

SL = {
    'confirmed': '✅ 已預約',
    'cancelled': '❌ 已取消',
    'finished': '🏁 已完成使用',
    'borrowed': '📦 借用中',
    'returned': '✅ 已歸還'
}


# ═══════════════════════════════════════════════════════════════
#  頁面
# ═══════════════════════════════════════════════════════════════

def page_login():
    st.markdown("<h1 style='text-align:center'>🏛️ 土木館預約系統</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#64748B'>教室與設備預約管理</p>", unsafe_allow_html=True)
    st.divider()

    col = st.columns([1, 2, 1])[1]
    with col:
        tab1, tab2 = st.tabs(['🔐 登入', '📝 註冊'])

        with tab1:
            with st.form('lf'):
                u = st.text_input('帳號')
                p = st.text_input('密碼', type='password')
                if st.form_submit_button('登入', use_container_width=True):
                    user = do_login(u, p)
                    if user:
                        st.session_state.user = user
                        st.session_state.page = 'query'
                        st.rerun()
                    else:
                        st.error('帳號或密碼錯誤')
            st.caption('管理員帳號：admin ｜ 密碼：admin123')

        with tab2:
            with st.form('rf'):
                nu = st.text_input('帳號')
                ni = st.text_input('身份（例如：學生 / 老師 / 助教）')
                ns = st.text_input('學號')
                nd = st.text_input('系所')
                nph = st.text_input('電話')
                ne = st.text_input('Email（選填）')
                np_ = st.text_input('密碼', type='password')
                np2 = st.text_input('確認密碼', type='password')
                if st.form_submit_button('建立帳號', use_container_width=True):
                    if not nu or not np_ or not ni or not ns or not nd or not nph:
                        st.error('帳號、身份、學號、系所、電話與密碼為必填')
                    elif np_ != np2:
                        st.error('兩次密碼不一致')
                    else:
                        ok, msg = do_register(nu, np_, ni, ns, nd, nph, ne)
                        st.success(msg + '，請登入') if ok else st.error(msg)


def page_query():
    st.header('🔍 查詢可用時間')
    tab1, tab2 = st.tabs(['教室', '設備'])

    with tab1:
        rooms = get_rooms()
        if not rooms:
            st.info('目前沒有教室資料')
            return
        rm = {r['name']: r['room_id'] for r in rooms}
        sel = st.selectbox('選擇教室', list(rm.keys()), key='qr_sel')
        d = st.date_input('日期', value=date.today(), key='qr_d')
        slots = get_room_slots(rm[sel], str(d))
        if slots:
            st.warning(f'⚠️  {d}  已預約時段：')
            for s in slots:
                st.markdown(f"- `{s['start_time']} ~ {s['end_time']}`　預約者：**{s['username']}**")
        else:
            st.success(f'✅  {d}  整天無人預約，可自由預約')

    with tab2:
        equips = get_equips()
        if not equips:
            st.info('目前沒有設備資料')
            return
        eq = {e['name']: e['equip_id'] for e in equips}
        sel = st.selectbox('選擇設備', list(eq.keys()), key='qe_sel')
        d = st.date_input('日期', value=date.today(), key='qe_d')
        slots = get_equip_slots(eq[sel], str(d))
        if slots:
            st.info(f'📦  {d}  借用中：')
            for s in slots:
                st.markdown(f"- `{s['start_time']} ~ {s['end_time']}`　借用者：**{s['username']}**")
        else:
            st.success(f'✅  {d}  此設備無人借用')


def page_book():
    st.header('📋 預約教室 / 借用設備')
    user = st.session_state.user
    tab1, tab2 = st.tabs(['🏫 預約教室', '🔧 借用設備'])

    with tab1:
        rooms = get_rooms()
        if not rooms:
            st.info('目前沒有教室資料')
        else:
            rm = {r['name']: r['room_id'] for r in rooms}
            with st.form('br'):
                sel = st.selectbox('教室', list(rm.keys()))
                bd = st.date_input('日期', value=date.today())
                c1, c2 = st.columns(2)
                st_ = c1.time_input('開始時間', value=time(9, 0))
                et_ = c2.time_input('結束時間', value=time(10, 0))
                purpose = st.text_input('使用用途（例如：專題討論、課輔、自習、會議）')
                note = st.text_input('備註（選填）')
                if st.form_submit_button('✅ 確認預約', use_container_width=True):
                    if st_ >= et_:
                        st.error('結束時間必須晚於開始時間')
                    elif not purpose:
                        st.error('請填寫使用用途')
                    else:
                        ok, msg = book_room(
                            user['user_id'], rm[sel], str(bd), str(st_)[:5], str(et_)[:5], purpose, note
                        )
                        if ok:
                            st.success(f'✅ {msg}！{sel}　{bd}　{str(st_)[:5]} ~ {str(et_)[:5]}')
                            st.balloons()
                        else:
                            st.error(msg)

    with tab2:
        equips = get_equips()
        if not equips:
            st.info('目前沒有設備資料')
        else:
            eq = {e['name']: e['equip_id'] for e in equips}
            with st.form('be'):
                sel = st.selectbox('設備', list(eq.keys()))
                bd = st.date_input('日期', value=date.today(), key='be_d')
                c1, c2 = st.columns(2)
                st_ = c1.time_input('開始時間', value=time(9, 0), key='be_st')
                et_ = c2.time_input('結束時間', value=time(10, 0), key='be_et')
                note = st.text_input('備註（選填）', key='be_note')
                if st.form_submit_button('✅ 確認借用', use_container_width=True):
                    if st_ >= et_:
                        st.error('結束時間必須晚於開始時間')
                    else:
                        ok, msg = book_equip(
                            user['user_id'], eq[sel], str(bd), str(st_)[:5], str(et_)[:5], note
                        )
                        st.success(f'✅ {msg}！{sel}　{bd}　{str(st_)[:5]} ~ {str(et_)[:5]}')
                        st.balloons()


def page_my():
    st.header('📌 我的預約記錄')
    user = st.session_state.user
    tab1, tab2 = st.tabs(['🏫 教室預約', '🔧 設備借用'])

    with tab1:
        bks = get_user_room_bookings(user['user_id'])
        if not bks:
            st.info('目前沒有教室預約記錄')
        for b in bks:
            label = f"{b['room_name']}　{b['book_date']}　{b['start_time']}~{b['end_time']}　{SL.get(b['status'], b['status'])}"
            with st.expander(label):
                st.write(f"**用途：** {b.get('purpose') or '無'}")
                st.write(f"**備註：** {b['note'] or '無'}")
                st.write(f"**建立時間：** {b['created_at']}")
                if b.get('finished_at'):
                    st.write(f"**完成時間：** {b['finished_at']}")

                if b['status'] == 'confirmed':
                    c1, c2, c3 = st.columns(3)

                    if c1.button('🏁 完成使用', key=f"fr{b['booking_id']}"):
                        finish_room(b['booking_id'], user['user_id'])
                        st.success('教室已完成使用')
                        st.rerun()

                    if c2.button('❌ 取消預約', key=f"cr{b['booking_id']}"):
                        cancel_room(b['booking_id'], user['user_id'])
                        st.rerun()

                    if c3.button('✏️ 修改預約', key=f"mr{b['booking_id']}"):
                        st.session_state[f'mod_{b["booking_id"]}'] = True

                    if st.session_state.get(f'mod_{b["booking_id"]}'):
                        with st.form(f'mf_{b["booking_id"]}'):
                            nd = st.date_input('新日期', value=date.fromisoformat(b['book_date']))
                            c1, c2 = st.columns(2)
                            ns = c1.time_input('新開始', value=time.fromisoformat(b['start_time']))
                            ne = c2.time_input('新結束', value=time.fromisoformat(b['end_time']))
                            npurpose = st.text_input('使用用途', value=b.get('purpose') or '')
                            nn = st.text_input('備註', value=b['note'] or '')
                            if st.form_submit_button('確認修改'):
                                if ns >= ne:
                                    st.error('結束時間必須晚於開始時間')
                                elif not npurpose:
                                    st.error('請填寫使用用途')
                                else:
                                    ok, msg = modify_room(
                                        b['booking_id'],
                                        user['user_id'],
                                        b['room_id'],
                                        str(nd),
                                        str(ns)[:5],
                                        str(ne)[:5],
                                        npurpose,
                                        nn
                                    ),
                                        str(ns)[:5], str(ne)[:5], npurpose, nn
                                    ),
                                        str(ns)[:5], str(ne)[:5], nn
                                    )
                                    if ok:
                                        st.success(msg)
                                        st.session_state.pop(f'mod_{b["booking_id"]}', None)
                                        st.rerun()
                                    else:
                                        st.error(msg)

    with tab2:
        bks = get_user_equip_bookings(user['user_id'])
        if not bks:
            st.info('目前沒有設備借用記錄')
        for b in bks:
            label = f"{b['equip_name']}　{b['book_date']}　{b['start_time']}~{b['end_time']}　{SL.get(b['status'], b['status'])}"
            with st.expander(label):
                st.write(f"**備註：** {b['note'] or '無'}")
                st.write(f"**借出時間：** {b['created_at']}")
                if b['returned_at']:
                    st.write(f"**歸還時間：** {b['returned_at']}")

                if b['status'] == 'borrowed':
                    c1, c2 = st.columns(2)
                    if c1.button('📦 歸還設備', key=f"ret{b['booking_id']}"):
                        return_equip(b['booking_id'], user['user_id'])
                        st.success('已歸還，謝謝！')
                        st.rerun()
                    if c2.button('❌ 取消借用', key=f"ce{b['booking_id']}"):
                        cancel_equip(b['booking_id'], user['user_id'])
                        st.rerun()


def page_history():
    st.header('📚 歷史借閱紀錄')
    user = st.session_state.user
    tab1, tab2 = st.tabs(['🏫 教室記錄', '🔧 設備記錄'])

    with tab1:
        bks = get_user_room_bookings(user['user_id'])
        if not bks:
            st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['room_name', 'book_date', 'start_time', 'end_time', 'purpose', 'status', 'finished_at', 'note', 'created_at']]
            df.columns = ['教室', '日期', '開始', '結束', '用途', '狀態', '完成時間', '備註', '建立時間']
            df['狀態'] = df['狀態'].map(SL).fillna(df['狀態'])
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tab2:
        bks = get_user_equip_bookings(user['user_id'])
        if not bks:
            st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['equip_name', 'book_date', 'start_time', 'end_time', 'status', 'returned_at', 'note']]
            df.columns = ['設備', '日期', '開始', '結束', '狀態', '歸還時間', '備註']
            df['狀態'] = df['狀態'].map(SL).fillna(df['狀態'])
            st.dataframe(df, use_container_width=True, hide_index=True)


def page_admin():
    st.header('⚙️ 管理員後台')
    tabs = st.tabs(['🏫 管理教室', '🔧 管理設備', '📋 所有教室預約', '📦 所有設備借用', '👥 使用者列表'])

    with tabs[0]:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader('新增教室')
            with st.form('ar'):
                nm = st.text_input('教室名稱')
                ds = st.text_input('說明（選填）')
                if st.form_submit_button('新增', use_container_width=True):
                    ok, msg = add_room(nm, ds)
                    st.success(msg) if ok else st.error(msg)
                    if ok:
                        st.rerun()
        with col2:
            st.subheader('現有教室')
            for r in get_rooms():
                c1, c2 = st.columns([3, 1])
                c1.write(f"🏫 {r['name']}")
                if c2.button('停用', key=f"dr{r['room_id']}"):
                    disable_room(r['room_id'])
                    st.rerun()

    with tabs[1]:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader('新增設備')
            with st.form('ae'):
                nm = st.text_input('設備名稱')
                ds = st.text_input('說明（選填）')
                if st.form_submit_button('新增', use_container_width=True):
                    ok, msg = add_equip(nm, ds)
                    st.success(msg) if ok else st.error(msg)
                    if ok:
                        st.rerun()
        with col2:
            st.subheader('現有設備')
            for e in get_equips():
                c1, c2 = st.columns([3, 1])
                c1.write(f"🔧 {e['name']}")
                if c2.button('停用', key=f"de{e['equip_id']}"):
                    disable_equip(e['equip_id'])
                    st.rerun()

    with tabs[2]:
        bks = all_room_bookings()
        if not bks:
            st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id', 'username', 'room_name', 'book_date', 'start_time', 'end_time', 'purpose', 'status', 'finished_at', 'note']]
            df.columns = ['ID', '使用者', '教室', '日期', '開始', '結束', '用途', '狀態', '完成時間', '備註']
            df['狀態'] = df['狀態'].map(SL).fillna(df['狀態'])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                bid_cancel = st.number_input('輸入預約 ID 取消', min_value=1, step=1, key='admin_cancel_r')
                if st.button('取消此預約'):
                    cancel_room(int(bid_cancel))
                    st.success('已取消')
                    st.rerun()
            with c2:
                bid_finish = st.number_input('輸入預約 ID 完成使用', min_value=1, step=1, key='admin_finish_r')
                if st.button('將教室標記為完成使用'):
                    finish_room(int(bid_finish))
                    st.success('已標記完成')
                    st.rerun()

    with tabs[3]:
        bks = all_equip_bookings()
        if not bks:
            st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id', 'username', 'equip_name', 'book_date', 'start_time', 'end_time', 'status', 'returned_at']]
            df.columns = ['ID', '使用者', '設備', '日期', '開始', '結束', '狀態', '歸還時間']
            df['狀態'] = df['狀態'].map(SL).fillna(df['狀態'])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.divider()
            bid = st.number_input('輸入借用 ID 強制歸還', min_value=1, step=1, key='admin_ret_e')
            if st.button('強制歸還'):
                return_equip(int(bid))
                st.success('已歸還')
                st.rerun()

    with tabs[4]:
        users = get_all_users()
        df = pd.DataFrame(users)[['username', 'role', 'identity', 'student_id', 'department', 'phone', 'email', 'created_at']]
        df.columns = ['帳號', '角色', '身份', '學號', '系所', '電話', 'Email', '註冊時間']
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_er():
    st.header('📊 ER Model  —  資料庫實體關聯圖')

    st.markdown("""
```
USER      ||--o{  ROOM_BOOKING   : 預約
USER      ||--o{  EQUIP_BOOKING  : 借用
ROOM      ||--o{  ROOM_BOOKING   : 被預約
EQUIPMENT ||--o{  EQUIP_BOOKING  : 被借用
```
""")

    st.divider()
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown("#### 👤 USER（使用者）")
        st.table(pd.DataFrame([
            ['user_id', 'INTEGER', 'PK 主鍵'],
            ['username', 'TEXT', '帳號（唯一）'],
            ['password', 'TEXT', '密碼雜湊'],
            ['role', 'TEXT', 'user / admin'],
            ['identity', 'TEXT', '身份'],
            ['student_id', 'TEXT', '學號'],
            ['department', 'TEXT', '系所'],
            ['phone', 'TEXT', '電話'],
            ['email', 'TEXT', '電子信箱'],
            ['created_at', 'TEXT', '註冊時間'],
        ], columns=['欄位', '型別', '說明']))

        st.markdown("#### 🏫 ROOM（教室）")
        st.table(pd.DataFrame([
            ['room_id', 'INTEGER', 'PK 主鍵'],
            ['name', 'TEXT', '教室名稱'],
            ['description', 'TEXT', '說明'],
            ['is_active', 'INTEGER', '是否啟用'],
        ], columns=['欄位', '型別', '說明']))

    with c2:
        st.markdown("#### 🔧 EQUIPMENT（設備）")
        st.table(pd.DataFrame([
            ['equip_id', 'INTEGER', 'PK 主鍵'],
            ['name', 'TEXT', '設備名稱'],
            ['description', 'TEXT', '說明'],
            ['is_active', 'INTEGER', '是否啟用'],
        ], columns=['欄位', '型別', '說明']))

    with c3:
        st.markdown("#### 📋 ROOM_BOOKING（教室預約）")
        st.table(pd.DataFrame([
            ['booking_id', 'INTEGER', 'PK 主鍵'],
            ['user_id', 'INTEGER', 'FK → USER'],
            ['room_id', 'INTEGER', 'FK → ROOM'],
            ['book_date', 'TEXT', '預約日期'],
            ['start_time', 'TEXT', '開始時間'],
            ['end_time', 'TEXT', '結束時間'],
            ['purpose', 'TEXT', '使用用途'],
            ['status', 'TEXT', 'confirmed / finished / cancelled'],
            ['note', 'TEXT', '備註'],
            ['created_at', 'TEXT', '建立時間'],
            ['finished_at', 'TEXT', '完成時間'],
        ], columns=['欄位', '型別', '說明']))

        st.markdown("#### 📦 EQUIP_BOOKING（設備借用）")
        st.table(pd.DataFrame([
            ['booking_id', 'INTEGER', 'PK 主鍵'],
            ['user_id', 'INTEGER', 'FK → USER'],
            ['equip_id', 'INTEGER', 'FK → EQUIPMENT'],
            ['book_date', 'TEXT', '借用日期'],
            ['start_time', 'TEXT', '開始時間'],
            ['end_time', 'TEXT', '結束時間'],
            ['status', 'TEXT', 'borrowed / returned / cancelled'],
            ['returned_at', 'TEXT', '歸還時間'],
            ['note', 'TEXT', '備註'],
            ['created_at', 'TEXT', '建立時間'],
        ], columns=['欄位', '型別', '說明']))


# ═══════════════════════════════════════════════════════════════
#  主程式
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title='土木館預約系統',
        page_icon='🏛️',
        layout='wide',
        initial_sidebar_state='expanded'
    )
    init_db()

    if 'user' not in st.session_state:
        page_login()
        return

    user = st.session_state.user
    is_adm = user['role'] == 'admin'

    with st.sidebar:
        st.markdown(f"### 👤 {user['username']}")
        st.caption('🔑 管理員' if is_adm else '👤 一般使用者')
        st.divider()

        nav = {
            '🔍 查詢可用時間': 'query',
            '📋 預約 / 借用': 'book',
            '📌 我的記錄': 'my',
            '📚 歷史紀錄': 'history',
            '📊 ER Model': 'er',
        }
        if is_adm:
            nav['⚙️ 管理員後台'] = 'admin'

        if 'page' not in st.session_state:
            st.session_state.page = 'query'

        for label, key in nav.items():
            if st.button(
                label,
                use_container_width=True,
                type='primary' if st.session_state.page == key else 'secondary'
            ):
                st.session_state.page = key
                st.rerun()

        st.divider()
        if st.button('🚪 登出', use_container_width=True):
            st.session_state.clear()
            st.rerun()

    page_map = {
        'query': page_query,
        'book': page_book,
        'my': page_my,
        'history': page_history,
        'er': page_er,
        'admin': page_admin,
    }
    page_map.get(st.session_state.get('page', 'query'), page_query)()


if __name__ == '__main__':
    main()
