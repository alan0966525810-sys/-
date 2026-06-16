"""
土木館教室與設備預約系統（Supabase 版）
========================
安裝：pip install streamlit pandas supabase
執行：streamlit run app.py

預設管理員帳號（學號）：admin
預設管理員密碼：admin123
預設系辦帳號（學號）：staff
預設系辦密碼：staff123
"""

import streamlit as st
import hashlib
import pandas as pd
import threading
import smtplib
import secrets
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date, time, timedelta
from supabase import create_client, Client

# ═══════════════════════════════════════════════════════════════
#  Supabase 連線
# ═══════════════════════════════════════════════════════════════

SUPABASE_URL = "https://tdkjdtztbgollvkiajmm.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRka2pkdHp0YmdvbGx2a2lham1tIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE1ODk3MTgsImV4cCI6MjA5NzE2NTcxOH0.jDx9frEvaPFZ5EXpgP1h0rXgTk_ve3nKfkIBh1e8WFw"

@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def sb():
    return get_supabase()

def sb_rows(table, query_fn=None):
    """執行查詢並回傳 list of dict"""
    q = sb().table(table).select("*")
    if query_fn:
        q = query_fn(q)
    res = q.execute()
    return res.data or []

def sb_insert(table, data):
    res = sb().table(table).insert(data).execute()
    return res.data

def sb_update(table, data, match):
    q = sb().table(table).update(data)
    for k, v in match.items():
        q = q.eq(k, v)
    return q.execute()

def sb_delete(table, match):
    q = sb().table(table).delete()
    for k, v in match.items():
        q = q.eq(k, v)
    return q.execute()

def sb_rpc(fn, params):
    return sb().rpc(fn, params).execute()

# ═══════════════════════════════════════════════════════════════
#  資料庫
# ═══════════════════════════════════════════════════════════════

def hp(pw): return hashlib.sha256(pw.encode()).hexdigest()
def nows(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def init_db():
    """確保預設資料存在（Supabase 版，資料表由 schema.sql 建立）"""
    s = sb()
    # 預設管理員
    existing = s.table('USER').select('user_id').eq('student_id','admin').execute().data
    if not existing:
        s.table('USER').insert({
            'fullname':'管理員','password':hp('admin123'),'role':'admin',
            'email':'admin@civil.edu','identity':'教職員','student_id':'admin',
            'department':'系辦','phone':'0000000000','created_at':nows()
        }).execute()
    else:
        s.table('USER').update({'password':hp('admin123'),'role':'admin'}).eq('student_id','admin').execute()

    existing = s.table('USER').select('user_id').eq('student_id','staff').execute().data
    if not existing:
        s.table('USER').insert({
            'fullname':'系辦人員','password':hp('staff123'),'role':'staff',
            'email':'staff@civil.edu','identity':'教職員','student_id':'staff',
            'department':'系辦','phone':'0000000000','created_at':nows()
        }).execute()
    else:
        s.table('USER').update({'password':hp('staff123'),'role':'staff'}).eq('student_id','staff').execute()

    # 預設教室
    for rname, cap in [('土木 204',40),('土木 205',30),('土木 206',20),('土木 207',15),('土木 208',10)]:
        ex = s.table('ROOM').select('room_id').eq('name', rname).execute().data
        if not ex:
            s.table('ROOM').insert({'name':rname,'capacity':cap,'is_active':1}).execute()

    # 預設設備
    for ename, esn, eqty in [('筆電','NB-001',3),('延長線','EX-001',5)]:
        ex = s.table('EQUIPMENT').select('equip_id').eq('name', ename).execute().data
        if not ex:
            s.table('EQUIPMENT').insert({'name':ename,'serial_number':esn,'quantity':eqty,'is_active':1}).execute()

    # SMTP 設定
    ex = s.table('SMTP_CONFIG').select('id').eq('id',1).execute().data
    if not ex:
        s.table('SMTP_CONFIG').insert({'id':1}).execute()


# ═══════════════════════════════════════════════════════════════
#  SMTP / Email
# ═══════════════════════════════════════════════════════════════

def get_smtp_config():
    rows = sb().table('SMTP_CONFIG').select('*').eq('id',1).execute().data
    return rows[0] if rows else {}

def save_smtp_config(host, port, username, password, sender_name, use_tls):
    sb().table('SMTP_CONFIG').update({
        'host':host,'port':port,'username':username,'password':password,
        'sender_name':sender_name,'use_tls':1 if use_tls else 0,'updated_at':nows()
    }).eq('id',1).execute()

def send_email(to_addr, subject, body_html):
    """發送 HTML 郵件，失敗靜默回傳 False"""
    cfg = get_smtp_config()
    if not cfg.get('host') or not cfg.get('username'):
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"{cfg.get('sender_name','土木館預約系統')} <{cfg['username']}>"
        msg['To']      = to_addr
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        server = smtplib.SMTP(cfg['host'], int(cfg.get('port', 587)), timeout=10)
        if cfg.get('use_tls', 1):
            server.starttls()
        server.login(cfg['username'], cfg['password'])
        server.sendmail(cfg['username'], [to_addr], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

def send_email_async(to_addr, subject, body_html):
    t = threading.Thread(target=send_email, args=(to_addr, subject, body_html), daemon=True)
    t.start()

def email_booking_approved(user, room_or_equip_name, book_date, start_time, end_time, kind='教室'):
    body = f"""
    <h2>✅ 預約審核通過</h2>
    <p>親愛的 {user['fullname']}，您的{kind}預約已通過審核。</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse'>
      <tr><td><b>{kind}</b></td><td>{room_or_equip_name}</td></tr>
      <tr><td><b>日期</b></td><td>{book_date}</td></tr>
      <tr><td><b>時間</b></td><td>{start_time} ~ {end_time}</td></tr>
    </table>
    <p>請記得準時使用，並於結束後完成歸還流程。</p>
    """
    send_email_async(user['email'], f'【土木館】{kind}預約審核通過 - {book_date}', body)

def email_booking_rejected(user, room_or_equip_name, book_date, start_time, end_time, reason, kind='教室'):
    body = f"""
    <h2>❌ 預約未通過</h2>
    <p>親愛的 {user['fullname']}，您的{kind}預約未通過審核。</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse'>
      <tr><td><b>{kind}</b></td><td>{room_or_equip_name}</td></tr>
      <tr><td><b>日期</b></td><td>{book_date}</td></tr>
      <tr><td><b>時間</b></td><td>{start_time} ~ {end_time}</td></tr>
      <tr><td><b>原因</b></td><td>{reason or '未說明'}</td></tr>
    </table>
    <p>如有疑問請洽系辦。</p>
    """
    send_email_async(user['email'], f'【土木館】{kind}預約未通過 - {book_date}', body)

def email_reminder(user, room_or_equip_name, book_date, start_time, end_time, kind, msg_type):
    if msg_type == 'start':
        subject = f'【土木館】提醒：{kind}即將開始使用 - {book_date} {start_time}'
        body = f"""
        <h2>⏰ 使用提醒</h2>
        <p>親愛的 {user['fullname']}，您預約的{kind}將在 <b>30 分鐘後</b>開始。</p>
        <p><b>{room_or_equip_name}</b> · {book_date} · {start_time} ~ {end_time}</p>
        <p>請準時前往，如需取消請至系統操作。</p>
        """
    else:
        subject = f'【土木館】提醒：{kind}即將到期歸還 - {book_date} {end_time}'
        body = f"""
        <h2>🔔 歸還提醒</h2>
        <p>親愛的 {user['fullname']}，您預約的{kind}將在 <b>10 分鐘後</b>到期。</p>
        <p><b>{room_or_equip_name}</b> · {book_date} · {start_time} ~ {end_time}</p>
        <p>請記得完成歸還流程。</p>
        """
    send_email_async(user['email'], subject, body)

def email_reset_password(to_addr, fullname, token):
    body = f"""
    <h2>🔑 密碼重設</h2>
    <p>親愛的 {fullname}，我們收到您的密碼重設申請。</p>
    <p>您的重設驗證碼為：<b style='font-size:24px;letter-spacing:4px'>{token}</b></p>
    <p>此驗證碼將於 <b>30 分鐘</b>後失效。</p>
    <p>如非本人操作，請忽略此信。</p>
    """
    send_email_async(to_addr, '【土木館】密碼重設驗證碼', body)

# ═══════════════════════════════════════════════════════════════
#  背景提醒執行緒
# ═══════════════════════════════════════════════════════════════

def _reminder_loop():
    import time as ttime
    while True:
        try:
            _check_reminders()
            _check_overdue()
            _auto_lift_blacklist()
            _auto_clear_probation()
        except Exception as e:
            print(f"[REMINDER ERROR] {e}")
        ttime.sleep(60)

def _check_overdue():
    now = datetime.now()
    s   = sb()
    for tbl, kind, item_join in [
        ('ROOM_BOOKING',  '教室', 'ROOM(name),USER(fullname,email,user_id)'),
        ('EQUIP_BOOKING', '設備', 'EQUIPMENT(name),USER(fullname,email,user_id)'),
    ]:
        item_key = 'ROOM' if tbl=='ROOM_BOOKING' else 'EQUIPMENT'
        rows = s.table(tbl).select(f'*,{item_join}').eq('status','confirmed').execute().data or []
        for r in rows:
            try:
                item_name = r.get(item_key,{}).get('name','')
                u_info    = r.get('USER',{}) or {}
                fullname  = u_info.get('fullname','')
                email     = u_info.get('email','')
                uid       = u_info.get('user_id', r.get('user_id'))
                dt_end    = datetime.strptime(f"{r['book_date']} {r['end_time']}", '%Y-%m-%d %H:%M')
                overdue   = (now - dt_end).total_seconds()
                if overdue <= 0: continue
                if overdue >= 7200 and not r.get('overdue_warned'):
                    body = f"<h2>⚠️ 逾期未歸還警告</h2><p>{fullname}，您的{kind} <b>{item_name}</b> 已超過結束時間 2 小時未歸還。請立即辦理歸還。</p>"
                    send_email_async(email, '【土木館】⚠️ 逾期未歸還警告', body)
                    s.table(tbl).update({'overdue_warned':1}).eq('booking_id', r['booking_id']).execute()
                if overdue >= 14400 and not r.get('overdue_flagged'):
                    # 檢查是否已有紀錄
                    ex = s.table('SUSPECT_LOG').select('log_id').eq('booking_id', r['booking_id']).execute().data
                    if not ex:
                        s.table('SUSPECT_LOG').insert({'user_id':uid,'booking_id':r['booking_id'],'kind':kind,'flagged_at':nows(),'notified':1}).execute()
                    s.table(tbl).update({'overdue_flagged':1}).eq('booking_id', r['booking_id']).execute()
                    staff_rows = s.table('USER').select('email').in_('role',['staff','admin']).execute().data or []
                    for st in staff_rows:
                        if st.get('email'):
                            body_staff = f"<h2>🚨 疑似違規通知</h2><p>{fullname} 的{kind} <b>{item_name}</b> 已超過結束時間 4 小時仍未歸還。</p>"
                            send_email_async(st['email'], f'【土木館】🚨 疑似違規 - {fullname}', body_staff)
            except Exception:
                pass

def _auto_lift_blacklist():
    now = nows()
    s   = sb()
    expired = s.table('BLACKLIST').select('*, USER(fullname,student_id,email)').eq('is_permanent',0).not_.is_('expire_at',None).is_('lifted_at',None).lte('expire_at', now).execute().data or []
    for bl in expired:
        u_info    = bl.get('USER',{}) or {}
        probation = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
        s.table('BLACKLIST').update({'lifted_at':now,'probation_until':probation}).eq('bl_id', bl['bl_id']).execute()
        s.table('USER').update({'probation_until':probation}).eq('user_id', bl['user_id']).execute()
        body = f"<h2>✅ 黑名單自動解除</h2><p>{u_info.get('fullname','')}，您的限制已到期解除，進入 60 天觀察期至 {probation[:10]}。</p>"
        send_email_async(u_info.get('email',''), '【土木館】帳號限制自動解除', body)
        staff_rows = s.table('USER').select('email').in_('role',['staff','admin']).execute().data or []
        for st in staff_rows:
            if st.get('email'):
                send_email_async(st['email'], f'【土木館】黑名單自動解除 - {u_info.get("fullname","")}',
                                 f"<p>{u_info.get('fullname','')}（{u_info.get('student_id','')}）黑名單已到期解除，進入觀察期。</p>")

def _auto_clear_probation():
    now = nows()
    sb().table('USER').update({'probation_until': None}).not_.is_('probation_until',None).lte('probation_until', now).execute()

def _check_reminders():
    now = datetime.now()
    s   = sb()
    # 教室提醒
    rb_rows = s.table('ROOM_BOOKING').select('*, ROOM(name), USER(fullname,email)').eq('status','confirmed').execute().data or []
    for r in rb_rows:
        try:
            room_name = r.get('ROOM',{}).get('name','') or r.get('room_name','')
            u_info    = r.get('USER',{}) or {}
            dt_start  = datetime.strptime(f"{r['book_date']} {r['start_time']}", '%Y-%m-%d %H:%M')
            dt_end    = datetime.strptime(f"{r['book_date']} {r['end_time']}",   '%Y-%m-%d %H:%M')
            diff_s    = (dt_start - now).total_seconds()
            diff_e    = (dt_end   - now).total_seconds()
            user      = {'fullname': u_info.get('fullname',''), 'email': u_info.get('email','')}
            if 0 < diff_s <= 1800 and not r.get('notified_start'):
                email_reminder(user, room_name, r['book_date'], r['start_time'], r['end_time'], '教室', 'start')
                s.table('ROOM_BOOKING').update({'notified_start':1}).eq('booking_id', r['booking_id']).execute()
            if 0 < diff_e <= 600 and not r.get('notified_end'):
                email_reminder(user, room_name, r['book_date'], r['start_time'], r['end_time'], '教室', 'end')
                s.table('ROOM_BOOKING').update({'notified_end':1}).eq('booking_id', r['booking_id']).execute()
        except Exception:
            pass
    # 設備提醒
    eb_rows = s.table('EQUIP_BOOKING').select('*, EQUIPMENT(name), USER(fullname,email)').eq('status','confirmed').execute().data or []
    for r in eb_rows:
        try:
            equip_name = r.get('EQUIPMENT',{}).get('name','') or r.get('equip_name','')
            u_info     = r.get('USER',{}) or {}
            dt_start   = datetime.strptime(f"{r['book_date']} {r['start_time']}", '%Y-%m-%d %H:%M')
            dt_end     = datetime.strptime(f"{r['book_date']} {r['end_time']}",   '%Y-%m-%d %H:%M')
            diff_s     = (dt_start - now).total_seconds()
            diff_e     = (dt_end   - now).total_seconds()
            user       = {'fullname': u_info.get('fullname',''), 'email': u_info.get('email','')}
            if 0 < diff_s <= 1800 and not r.get('notified_start'):
                email_reminder(user, equip_name, r['book_date'], r['start_time'], r['end_time'], '設備', 'start')
                s.table('EQUIP_BOOKING').update({'notified_start':1}).eq('booking_id', r['booking_id']).execute()
            if 0 < diff_e <= 600 and not r.get('notified_end'):
                email_reminder(user, equip_name, r['book_date'], r['start_time'], r['end_time'], '設備', 'end')
                s.table('EQUIP_BOOKING').update({'notified_end':1}).eq('booking_id', r['booking_id']).execute()
        except Exception:
            pass

def start_reminder_thread():
    if 'reminder_started' not in st.session_state:
        t = threading.Thread(target=_reminder_loop, daemon=True)
        t.start()
        st.session_state.reminder_started = True

# ═══════════════════════════════════════════════════════════════
#  Auth
# ═══════════════════════════════════════════════════════════════

def do_login(student_id, password):
    rows = sb().table('USER').select('*').eq('student_id', student_id).eq('password', hp(password)).execute().data
    return rows[0] if rows else None

def do_register(fullname, password, email, identity, student_id, department, phone):
    ex = sb().table('USER').select('user_id').eq('student_id', student_id).execute().data
    if ex:
        return False, '此學號已被註冊，請確認或聯絡系辦'
    sb().table('USER').insert({
        'fullname':fullname,'password':hp(password),'role':'user','email':email,
        'identity':identity,'student_id':student_id,'department':department,
        'phone':phone,'created_at':nows()
    }).execute()
    return True, '註冊成功'

def update_profile(user_id, fullname, email, identity, student_id, department, phone):
    ex = sb().table('USER').select('user_id').eq('student_id', student_id).neq('user_id', user_id).execute().data
    if ex:
        return False, None
    sb().table('USER').update({
        'fullname':fullname,'email':email,'identity':identity,
        'student_id':student_id,'department':department,'phone':phone
    }).eq('user_id', user_id).execute()
    rows = sb().table('USER').select('*').eq('user_id', user_id).execute().data
    return True, rows[0] if rows else None

def request_reset(student_id):
    rows = sb().table('USER').select('*').eq('student_id', student_id).execute().data
    if not rows:
        return False, '查無此學號'
    user   = rows[0]
    token  = str(secrets.randbelow(900000) + 100000)
    expiry = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    sb().table('USER').update({'reset_token':token,'reset_expiry':expiry}).eq('student_id', student_id).execute()
    ok = send_email(user['email'], '【土木館】密碼重設驗證碼',
                    f"<p>驗證碼：<b style='font-size:24px'>{token}</b>（30 分鐘內有效）</p>")
    return (True, '驗證碼已寄至您的 Email') if ok else (False, '驗證碼產生成功但 Email 寄送失敗')

def do_reset_password(student_id, token, new_pw):
    rows = sb().table('USER').select('*').eq('student_id', student_id).execute().data
    if not rows: return False, '查無此學號'
    u = rows[0]
    if u.get('reset_token') != token: return False, '驗證碼錯誤'
    if u.get('reset_expiry') and datetime.strptime(u['reset_expiry'], '%Y-%m-%d %H:%M:%S') < datetime.now():
        return False, '驗證碼已過期'
    sb().table('USER').update({'password':hp(new_pw),'reset_token':None,'reset_expiry':None}).eq('student_id', student_id).execute()
    return True, '密碼重設成功，請重新登入'

# ═══════════════════════════════════════════════════════════════
#  Blacklist
# ═══════════════════════════════════════════════════════════════

TIER_DAYS = {1: 30, 2: 90}

def is_blacklisted(user_id):
    rows = sb().table('BLACKLIST').select('*').eq('user_id', user_id).execute().data
    if not rows: return False
    bl = rows[0]
    if bl.get('is_permanent'): return True
    if bl.get('expire_at') and datetime.strptime(bl['expire_at'], '%Y-%m-%d %H:%M:%S') > datetime.now():
        return True
    return False

def get_blacklist_entry(user_id):
    rows = sb().table('BLACKLIST').select('*').eq('user_id', user_id).execute().data
    return rows[0] if rows else None

def get_blacklist():
    rows = sb().table('BLACKLIST').select('*, USER!BLACKLIST_user_id_fkey(fullname,student_id,department,violation_count,probation_until), added_by_user:USER!BLACKLIST_added_by_fkey(fullname)').execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        u = r.get('USER') or {}
        flat['fullname']        = u.get('fullname','')
        flat['student_id']      = u.get('student_id','')
        flat['department']      = u.get('department','')
        flat['violation_count'] = u.get('violation_count',0)
        flat['probation_until'] = u.get('probation_until')
        added = r.get('added_by_user') or {}
        flat['added_by_name']   = added.get('fullname','')
        result.append(flat)
    return result

def get_probation_users():
    now  = nows()
    rows = sb().table('USER').select('*').not_.is_('probation_until', None).gt('probation_until', now).execute().data or []
    return rows

def add_blacklist(user_id, reason, added_by, is_permanent=False):
    u_rows = sb().table('USER').select('violation_count').eq('user_id', user_id).execute().data
    cnt    = ((u_rows[0].get('violation_count') or 0) + 1) if u_rows else 1
    if is_permanent or cnt >= 3:
        tier, perm, expire = 3, 1, None
    else:
        tier   = cnt
        perm   = 0
        days   = TIER_DAYS.get(tier, 30)
        expire = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    ex = sb().table('BLACKLIST').select('bl_id').eq('user_id', user_id).execute().data
    data = {'user_id':user_id,'reason':reason,'tier':tier,'is_permanent':perm,
            'added_by':added_by,'added_at':nows(),'expire_at':expire}
    if ex:
        sb().table('BLACKLIST').update(data).eq('user_id', user_id).execute()
    else:
        sb().table('BLACKLIST').insert(data).execute()
    sb().table('USER').update({'violation_count':cnt}).eq('user_id', user_id).execute()
    _notify_blacklist(user_id, tier, perm, expire, reason)
    return True

def _notify_blacklist(user_id, tier, is_permanent, expire_at, reason):
    rows = sb().table('USER').select('email,fullname').eq('user_id', user_id).execute().data
    if not rows: return
    r   = rows[0]
    dur = '永久停權' if is_permanent else f"至 {expire_at[:10]}"
    body = f"<h2>⛔ 帳號列入黑名單</h2><p>{r['fullname']}，因違規（{reason}）列入第 {tier} 級黑名單，限制期間：{dur}。如有疑問請洽系辦。</p>"
    send_email_async(r['email'], '【土木館】帳號限制通知', body)

def remove_blacklist(user_id, lifted_by_auto=False):
    probation = (datetime.now() + timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
    sb().table('BLACKLIST').update({'lifted_at':nows(),'probation_until':probation}).eq('user_id', user_id).execute()
    sb().table('USER').update({'probation_until':probation}).eq('user_id', user_id).execute()
    rows = sb().table('USER').select('email,fullname').eq('user_id', user_id).execute().data
    if rows:
        r    = rows[0]
        body = f"<h2>✅ 限制解除</h2><p>{r['fullname']}，您的帳號限制已解除，進入 60 天觀察期至 {probation[:10]}。</p>"
        send_email_async(r['email'], '【土木館】帳號限制解除', body)

def get_suspect_logs():
    rows = sb().table('SUSPECT_LOG').select('*, USER(fullname,student_id,department,email,phone)').eq('resolved', 0).execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        u = r.get('USER') or {}
        flat['fullname']   = u.get('fullname','')
        flat['student_id'] = u.get('student_id','')
        flat['department'] = u.get('department','')
        flat['email']      = u.get('email','')
        flat['phone']      = u.get('phone','')
        result.append(flat)
    return result

def resolve_suspect(log_id):
    sb().table('SUSPECT_LOG').update({'resolved':1}).eq('log_id', log_id).execute()

# ═══════════════════════════════════════════════════════════════
#  Rooms
# ═══════════════════════════════════════════════════════════════

def get_rooms():
    return sb().table('ROOM').select('*').eq('is_active',1).order('name').execute().data or []

def add_room(name, capacity, desc):
    ex = sb().table('ROOM').select('room_id').eq('name', name).execute().data
    if ex: return False, '此名稱已存在'
    sb().table('ROOM').insert({'name':name,'capacity':capacity,'description':desc,'is_active':1}).execute()
    return True, '新增成功'

def update_room(room_id, name, capacity, desc):
    sb().table('ROOM').update({'name':name,'capacity':capacity,'description':desc}).eq('room_id', room_id).execute()

def disable_room(room_id):
    sb().table('ROOM').update({'is_active':0}).eq('room_id', room_id).execute()

def room_conflict(room_id, book_date, start_time, end_time, exclude=None):
    rows = sb().table('ROOM_BOOKING').select('booking_id').eq('room_id', room_id).eq('book_date', book_date).in_('status',['confirmed','pending_return','pending']).lt('start_time', end_time).gt('end_time', start_time).execute().data or []
    if exclude:
        rows = [r for r in rows if r['booking_id'] != exclude]
    return len(rows) > 0

def book_room(user_id, room_id, book_date, st_, et_, attendee_count, supervisor, attendees, purpose, note):
    if is_blacklisted(user_id): return False, '您目前在黑名單中，無法進行預約，請洽系辦'
    if room_conflict(room_id, book_date, st_, et_): return False, '此時段已有人預約（含審核中），請選擇其他時段'
    rm_rows = sb().table('ROOM').select('capacity').eq('room_id', room_id).execute().data
    if rm_rows:
        cap = rm_rows[0].get('capacity') or 0
        if cap > 0 and attendee_count > cap: return False, f'使用人數（{attendee_count}）超過教室容量（{cap}）'
    sb().table('ROOM_BOOKING').insert({
        'user_id':user_id,'room_id':room_id,'book_date':book_date,'start_time':st_,'end_time':et_,
        'attendee_count':attendee_count,'supervisor':supervisor,'attendees':attendees,
        'purpose':purpose,'status':'pending','note':note,'created_at':nows()
    }).execute()
    return True, '預約申請已送出，待系辦審核（通常 1-2 個工作天）'

def get_room_slots(room_id, book_date):
    rows = sb().table('ROOM_BOOKING').select('*, USER(fullname)').eq('room_id', room_id).eq('book_date', book_date).in_('status',['confirmed','pending_return','pending']).order('start_time').execute().data or []
    result = []
    for r in rows:
        flat = dict(r); u = r.get('USER') or {}; flat['fullname'] = u.get('fullname','')
        result.append(flat)
    return result

def get_user_room_bookings(user_id):
    rows = sb().table('ROOM_BOOKING').select('*, ROOM(name,capacity)').eq('user_id', user_id).order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r); rm = r.get('ROOM') or {}
        flat['room_name'] = rm.get('name',''); flat['capacity'] = rm.get('capacity',0)
        result.append(flat)
    return result

def _get_room_booking_with_user(booking_id):
    rows = sb().table('ROOM_BOOKING').select('*, ROOM(name), USER(email,fullname)').eq('booking_id', booking_id).execute().data
    if not rows: return None
    r = rows[0]; flat = dict(r)
    flat['room_name'] = (r.get('ROOM') or {}).get('name','')
    flat['email']     = (r.get('USER') or {}).get('email','')
    flat['fullname']  = (r.get('USER') or {}).get('fullname','')
    return flat

def approve_room(booking_id):
    sb().table('ROOM_BOOKING').update({'status':'confirmed'}).eq('booking_id', booking_id).execute()
    r = _get_room_booking_with_user(booking_id)
    if r:
        email_booking_approved({'fullname':r['fullname'],'email':r['email']}, r['room_name'], r['book_date'], r['start_time'], r['end_time'], '教室')

def reject_room(booking_id, reason):
    sb().table('ROOM_BOOKING').update({'status':'rejected','reject_reason':reason}).eq('booking_id', booking_id).execute()
    r = _get_room_booking_with_user(booking_id)
    if r:
        email_booking_rejected({'fullname':r['fullname'],'email':r['email']}, r['room_name'], r['book_date'], r['start_time'], r['end_time'], reason, '教室')

def cancel_room(booking_id, user_id=None):
    q = sb().table('ROOM_BOOKING').update({'status':'cancelled'}).eq('booking_id', booking_id)
    if user_id: q = q.eq('user_id', user_id)
    q.execute()

def request_return_room(booking_id, user_id):
    sb().table('ROOM_BOOKING').update({'status':'pending_return'}).eq('booking_id', booking_id).eq('user_id', user_id).eq('status','confirmed').execute()

def confirm_return_room(booking_id):
    sb().table('ROOM_BOOKING').update({'status':'returned','returned_at':nows()}).eq('booking_id', booking_id).eq('status','pending_return').execute()

def return_room_force(booking_id):
    sb().table('ROOM_BOOKING').update({'status':'returned','returned_at':nows()}).eq('booking_id', booking_id).in_('status',['confirmed','pending_return']).execute()

def modify_room(booking_id, user_id, room_id, book_date, st_, et_, attendee_count, supervisor, attendees, purpose, note):
    if room_conflict(room_id, book_date, st_, et_, exclude=booking_id): return False, '此時段已有人預約'
    sb().table('ROOM_BOOKING').update({
        'book_date':book_date,'start_time':st_,'end_time':et_,'attendee_count':attendee_count,
        'supervisor':supervisor,'attendees':attendees,'purpose':purpose,'note':note,'status':'pending'
    }).eq('booking_id', booking_id).eq('user_id', user_id).execute()
    return True, '修改成功（已重新送審）'

def all_room_bookings():
    rows = sb().table('ROOM_BOOKING').select('*, ROOM(name,capacity), USER(fullname,identity,department,student_id,phone,email)').order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        rm   = r.get('ROOM') or {}; u = r.get('USER') or {}
        flat['room_name']  = rm.get('name',''); flat['capacity'] = rm.get('capacity',0)
        flat['fullname']   = u.get('fullname',''); flat['identity']   = u.get('identity','')
        flat['department'] = u.get('department',''); flat['student_id'] = u.get('student_id','')
        flat['phone']      = u.get('phone',''); flat['email']      = u.get('email','')
        result.append(flat)
    return result

def pending_room_reviews():
    rows = sb().table('ROOM_BOOKING').select('*, ROOM(name,capacity), USER(fullname,identity,department,student_id,phone,email)').eq('status','pending').order('created_at').execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        rm   = r.get('ROOM') or {}; u = r.get('USER') or {}
        flat['room_name']  = rm.get('name',''); flat['capacity']   = rm.get('capacity',0)
        flat['fullname']   = u.get('fullname',''); flat['identity']   = u.get('identity','')
        flat['department'] = u.get('department',''); flat['student_id'] = u.get('student_id','')
        flat['phone']      = u.get('phone',''); flat['email']      = u.get('email','')
        result.append(flat)
    return result

def pending_room_returns():
    rows = sb().table('ROOM_BOOKING').select('*, ROOM(name), USER(fullname,identity,department,student_id,phone,email)').eq('status','pending_return').order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        flat['room_name']  = (r.get('ROOM') or {}).get('name','')
        u = r.get('USER') or {}
        flat['fullname']   = u.get('fullname',''); flat['identity']   = u.get('identity','')
        flat['department'] = u.get('department',''); flat['student_id'] = u.get('student_id','')
        flat['phone']      = u.get('phone',''); flat['email']      = u.get('email','')
        result.append(flat)
    return result

# ═══════════════════════════════════════════════════════════════
#  Equipment
# ═══════════════════════════════════════════════════════════════

def get_equips():
    return sb().table('EQUIPMENT').select('*').eq('is_active',1).order('name').execute().data or []

def add_equip(name, serial_number, quantity, desc):
    sb().table('EQUIPMENT').insert({'name':name,'serial_number':serial_number,'quantity':quantity,'description':desc,'is_active':1}).execute()
    return True, '新增成功'

def update_equip(equip_id, name, serial_number, quantity, desc):
    sb().table('EQUIPMENT').update({'name':name,'serial_number':serial_number,'quantity':quantity,'description':desc}).eq('equip_id', equip_id).execute()

def disable_equip(equip_id):
    sb().table('EQUIPMENT').update({'is_active':0}).eq('equip_id', equip_id).execute()

def get_equip_available(equip_id, book_date, st_, et_, exclude=None):
    eq_rows = sb().table('EQUIPMENT').select('quantity').eq('equip_id', equip_id).execute().data
    if not eq_rows: return 0
    total_qty = eq_rows[0].get('quantity') or 1
    rows = sb().table('EQUIP_BOOKING').select('quantity_borrowed,booking_id').eq('equip_id', equip_id).eq('book_date', book_date).in_('status',['confirmed','pending_return','pending']).lt('start_time', et_).gt('end_time', st_).execute().data or []
    if exclude:
        rows = [r for r in rows if r['booking_id'] != exclude]
    used = sum(r.get('quantity_borrowed') or 1 for r in rows)
    return max(0, total_qty - used)

def book_equip(user_id, equip_id, book_date, st_, et_, qty, supervisor, attendees, purpose, note):
    if is_blacklisted(user_id): return False, '您目前在黑名單中，無法進行借用，請洽系辦'
    available = get_equip_available(equip_id, book_date, st_, et_)
    if available < qty: return False, f'此時段可借用數量不足（剩餘 {available} 件）'
    sb().table('EQUIP_BOOKING').insert({
        'user_id':user_id,'equip_id':equip_id,'book_date':book_date,'start_time':st_,'end_time':et_,
        'quantity_borrowed':qty,'supervisor':supervisor,'attendees':attendees,
        'purpose':purpose,'status':'pending','note':note,'created_at':nows()
    }).execute()
    return True, '借用申請已送出，待系辦審核（通常 1-2 個工作天）'

def get_equip_slots(equip_id, book_date):
    rows = sb().table('EQUIP_BOOKING').select('*, USER(fullname)').eq('equip_id', equip_id).eq('book_date', book_date).in_('status',['confirmed','pending_return','pending']).order('start_time').execute().data or []
    result = []
    for r in rows:
        flat = dict(r); flat['fullname'] = (r.get('USER') or {}).get('fullname','')
        result.append(flat)
    return result

def get_user_equip_bookings(user_id):
    rows = sb().table('EQUIP_BOOKING').select('*, EQUIPMENT(name,serial_number,quantity)').eq('user_id', user_id).order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r); eq = r.get('EQUIPMENT') or {}
        flat['equip_name']    = eq.get('name','')
        flat['serial_number'] = eq.get('serial_number','')
        flat['total_qty']     = eq.get('quantity',1)
        result.append(flat)
    return result

def _get_equip_booking_with_user(booking_id):
    rows = sb().table('EQUIP_BOOKING').select('*, EQUIPMENT(name), USER(email,fullname)').eq('booking_id', booking_id).execute().data
    if not rows: return None
    r = rows[0]; flat = dict(r)
    flat['equip_name'] = (r.get('EQUIPMENT') or {}).get('name','')
    flat['email']      = (r.get('USER') or {}).get('email','')
    flat['fullname']   = (r.get('USER') or {}).get('fullname','')
    return flat

def approve_equip(booking_id):
    sb().table('EQUIP_BOOKING').update({'status':'confirmed'}).eq('booking_id', booking_id).execute()
    r = _get_equip_booking_with_user(booking_id)
    if r:
        email_booking_approved({'fullname':r['fullname'],'email':r['email']}, r['equip_name'], r['book_date'], r['start_time'], r['end_time'], '設備')

def reject_equip(booking_id, reason):
    sb().table('EQUIP_BOOKING').update({'status':'rejected','reject_reason':reason}).eq('booking_id', booking_id).execute()
    r = _get_equip_booking_with_user(booking_id)
    if r:
        email_booking_rejected({'fullname':r['fullname'],'email':r['email']}, r['equip_name'], r['book_date'], r['start_time'], r['end_time'], reason, '設備')

def cancel_equip(booking_id, user_id=None):
    q = sb().table('EQUIP_BOOKING').update({'status':'cancelled'}).eq('booking_id', booking_id)
    if user_id: q = q.eq('user_id', user_id)
    q.execute()

def request_return_equip(booking_id, user_id):
    sb().table('EQUIP_BOOKING').update({'status':'pending_return'}).eq('booking_id', booking_id).eq('user_id', user_id).eq('status','confirmed').execute()

def confirm_return_equip(booking_id):
    sb().table('EQUIP_BOOKING').update({'status':'returned','returned_at':nows()}).eq('booking_id', booking_id).eq('status','pending_return').execute()

def return_equip_force(booking_id):
    sb().table('EQUIP_BOOKING').update({'status':'returned','returned_at':nows()}).eq('booking_id', booking_id).in_('status',['confirmed','pending_return']).execute()

def all_equip_bookings():
    rows = sb().table('EQUIP_BOOKING').select('*, EQUIPMENT(name,serial_number,quantity), USER(fullname,identity,department,student_id,phone,email)').order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        eq   = r.get('EQUIPMENT') or {}; u = r.get('USER') or {}
        flat['equip_name']    = eq.get('name',''); flat['serial_number'] = eq.get('serial_number','')
        flat['total_qty']     = eq.get('quantity',1)
        flat['fullname']      = u.get('fullname',''); flat['identity']      = u.get('identity','')
        flat['department']    = u.get('department',''); flat['student_id']    = u.get('student_id','')
        flat['phone']         = u.get('phone',''); flat['email']         = u.get('email','')
        result.append(flat)
    return result

def pending_equip_reviews():
    rows = sb().table('EQUIP_BOOKING').select('*, EQUIPMENT(name,serial_number), USER(fullname,identity,department,student_id,phone,email)').eq('status','pending').order('created_at').execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        eq   = r.get('EQUIPMENT') or {}; u = r.get('USER') or {}
        flat['equip_name']    = eq.get('name',''); flat['serial_number']  = eq.get('serial_number','')
        flat['fullname']      = u.get('fullname',''); flat['identity']      = u.get('identity','')
        flat['department']    = u.get('department',''); flat['student_id']    = u.get('student_id','')
        flat['phone']         = u.get('phone',''); flat['email']         = u.get('email','')
        result.append(flat)
    return result

def pending_equip_returns():
    rows = sb().table('EQUIP_BOOKING').select('*, EQUIPMENT(name,serial_number), USER(fullname,identity,department,student_id,phone,email)').eq('status','pending_return').order('book_date', desc=True).execute().data or []
    result = []
    for r in rows:
        flat = dict(r)
        eq   = r.get('EQUIPMENT') or {}; u = r.get('USER') or {}
        flat['equip_name']    = eq.get('name',''); flat['serial_number']  = eq.get('serial_number','')
        flat['fullname']      = u.get('fullname',''); flat['identity']      = u.get('identity','')
        flat['department']    = u.get('department',''); flat['student_id']    = u.get('student_id','')
        flat['phone']         = u.get('phone',''); flat['email']         = u.get('email','')
        result.append(flat)
    return result

# ═══════════════════════════════════════════════════════════════
#  Fixed Courses
# ═══════════════════════════════════════════════════════════════

def get_fixed_courses(room_id):
    return sb().table('FIXED_COURSE').select('*').eq('room_id', room_id).order('weekday').order('start_time').execute().data or []

def add_fixed_course(room_id, weekday, start_time, end_time, title, note):
    sb().table('FIXED_COURSE').insert({'room_id':room_id,'weekday':weekday,'start_time':start_time,'end_time':end_time,'title':title,'note':note}).execute()

def delete_fixed_course(course_id):
    sb().table('FIXED_COURSE').delete().eq('course_id', course_id).execute()

def get_week_bookings(room_id, dates):
    rows = sb().table('ROOM_BOOKING').select('*, USER(fullname)').eq('room_id', room_id).in_('book_date', dates).in_('status',['confirmed','pending_return','pending']).order('book_date').order('start_time').execute().data or []
    result = []
    for r in rows:
        flat = dict(r); flat['fullname'] = (r.get('USER') or {}).get('fullname','')
        result.append(flat)
    return result

# ═══════════════════════════════════════════════════════════════
#  Users (admin)
# ═══════════════════════════════════════════════════════════════

def get_all_users():
    return sb().table('USER').select('user_id,fullname,role,email,identity,student_id,department,phone,created_at,violation_count,probation_until').order('created_at', desc=True).execute().data or []

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

SL = {
    'pending':        '⏳ 審核中',
    'confirmed':      '✅ 已確認',
    'rejected':       '❌ 未通過',
    'cancelled':      '🚫 已取消',
    'pending_return': '🔔 申請歸還中',
    'returned':       '📦 已歸還',
}
SL_COLOR = {
    'pending':        '#fff3cd',
    'confirmed':      '#d4edda',
    'rejected':       '#f8d7da',
    'cancelled':      '#e2e3e5',
    'pending_return': '#d6d0f5',
    'returned':       '#cce5ff',
}
ROLE_LABEL = {'admin':'🔑 管理員','staff':'🏢 系辦人員','user':'👤 一般使用者'}
IDENTITY_OPTIONS = ['學生','研究生','教職員','其他']
ROOM_PURPOSES  = ['課程上課','自習讀書','小組討論','專題會議','社團活動','研究使用','考試','其他']
EQUIP_PURPOSES = ['課程使用','專題研究','社團活動','個人使用','其他']
WEEKDAY_ZH     = ['週一','週二','週三','週四','週五','週六','週日']
BL_REASONS     = ['無正當理由未在時間內歸還鑰匙','人數與登記嚴重不符','器材損壞未告知','惡意重複佔用','其他']

# ═══════════════════════════════════════════════════════════════
#  週課表（共用渲染函式）
# ═══════════════════════════════════════════════════════════════

def render_room_calendar(room, week_offset_key='week_offset', compact=False):
    today = date.today()
    if week_offset_key not in st.session_state:
        st.session_state[week_offset_key] = 0
    cp, cc, cn = st.columns([1, 2, 1])
    if cp.button('◀ 上週', key=f'prev_{week_offset_key}'):
        st.session_state[week_offset_key] -= 1; st.rerun()
    if cn.button('下週 ▶', key=f'next_{week_offset_key}'):
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

    HS, HE, SM = 7, 22, 30
    total_slots = (HE - HS) * (60 // SM)
    def t2s(t):
        h,m = map(int,t.split(':')[:2])
        return (h-HS)*(60//SM)+m//SM
    def slbl(s):
        tm=HS*60+s*SM; return f"{tm//60:02d}:{tm%60:02d}"

    CW = 72 if compact else 110
    RH = 18 if compact else 20
    TW = 44; TH = total_slots*RH; HDR = 36
    CF=('#1e3a5f','#d6e8ff'); CB=('#3b1f00','#ffe8c0')
    CP2=('#4a0060','#f0d6ff'); CPN=('#5a3a00','#fff0c0')
    CTOD='#fffbe6'; CWK='#f8f8f8'; CN2='#ffffff'; CBDR='#dde1e7'

    def blk(top,h,bg,fg,lbl,sub=''):
        s=(f"<div style='font-size:9px;opacity:.75;overflow:hidden;text-overflow:ellipsis;"
           f"white-space:nowrap'>{sub}</div>") if sub else ''
        return (f"<div style='position:absolute;top:{top}px;left:1px;right:1px;height:{h-2}px;"
                f"background:{bg};color:{fg};border-radius:3px;padding:2px 4px;font-size:10px;"
                f"font-weight:600;overflow:hidden;z-index:2;box-shadow:0 1px 2px rgba(0,0,0,.12)'>"
                f"<div style='overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{lbl}</div>{s}</div>")

    taxis=''.join(
        f"<div style='position:absolute;top:{s*RH}px;left:0;width:{TW}px;font-size:9px;"
        f"color:#999;text-align:right;padding-right:5px;line-height:1'>{slbl(s)}</div>"
        for s in range(0,total_slots+1,2))

    parts=[f"""<div style='display:flex;font-family:sans-serif;
        border:1px solid {CBDR};border-radius:8px;overflow:hidden;width:100%;box-sizing:border-box'>
      <div style='flex:0 0 {TW}px;background:#f5f6f8;border-right:1px solid {CBDR}'>
        <div style='height:{HDR}px;border-bottom:1px solid {CBDR}'></div>
        <div style='position:relative;height:{TH}px'>{taxis}</div>
      </div>"""]

    for i,(d,ds) in enumerate(zip(week_dates,week_strs)):
        is_today=(d==today); is_wk=(i>=5)
        bg=CTOD if is_today else (CWK if is_wk else CN2)
        bdr='2px solid #f0a500' if is_today else f'1px solid {CBDR}'
        hbg='#fff8e1' if is_today else bg
        dc='#e67e00' if is_today else ('#aaa' if is_wk else '#333')
        blist=[]
        for fc in fc_by_day[i]:
            s=max(0,t2s(fc['start_time'])); e=min(total_slots,t2s(fc['end_time']))
            if e>s: blist.append(blk(s*RH,(e-s)*RH,CF[1],CF[0],fc['title'],f"{fc['start_time']}~{fc['end_time']}"))
        for b in bk_by_date.get(ds,[]):
            s=max(0,t2s(b['start_time'])); e=min(total_slots,t2s(b['end_time']))
            if e>s:
                if b['status']=='pending_return': bg2,fg2,lbl=CP2[1],CP2[0],f"🔔{b['fullname']}"
                elif b['status']=='pending':       bg2,fg2,lbl=CPN[1],CPN[0],f"⏳{b['fullname']}"
                else:                              bg2,fg2,lbl=CB[1],CB[0],f"📌{b['fullname']}"
                blist.append(blk(s*RH,(e-s)*RH,bg2,fg2,lbl,b.get('purpose') or ''))
        grid=''.join(f"<div style='position:absolute;top:{s*RH}px;left:0;right:0;height:1px;"
                     f"background:{CBDR};opacity:.5'></div>" for s in range(0,total_slots+1,2))
        parts.append(f"""
      <div style='flex:1;min-width:{CW}px;border-left:{bdr};box-sizing:border-box'>
        <div style='height:{HDR}px;background:{hbg};display:flex;flex-direction:column;
                    align-items:center;justify-content:center;border-bottom:1px solid {CBDR}'>
          <div style='font-size:11px;font-weight:700;color:{dc}'>{'一二三四五六日'[i]}</div>
          <div style='font-size:10px;color:#999'>{d.month}/{d.day}</div>
        </div>
        <div style='position:relative;height:{TH}px;background:{bg}'>{grid}{''.join(blist)}</div>
      </div>""")

    parts.append("</div>")
    st.markdown(f"<div style='overflow-x:auto'>{''.join(parts)}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;font-size:11px'>"
        f"<span style='background:{CF[1]};color:{CF[0]};padding:1px 7px;border-radius:3px;font-weight:600'>固定課程</span>"
        f"<span style='background:{CB[1]};color:{CB[0]};padding:1px 7px;border-radius:3px;font-weight:600'>📌 已確認</span>"
        f"<span style='background:{CPN[1]};color:{CPN[0]};padding:1px 7px;border-radius:3px;font-weight:600'>⏳ 審核中</span>"
        f"<span style='background:{CP2[1]};color:{CP2[0]};padding:1px 7px;border-radius:3px;font-weight:600'>🔔 申請歸還</span>"
        "</div>", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  頁面
# ═══════════════════════════════════════════════════════════════

def page_login():
    st.markdown("<h1 style='text-align:center'>🏛️ 土木館預約系統</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align:center;color:#64748B'>教室與設備預約管理</p>", unsafe_allow_html=True)
    st.divider()

    col = st.columns([1,2,1])[1]
    with col:
        tab1, tab2, tab3 = st.tabs(['🔐 登入', '📝 註冊', '🔑 忘記密碼'])

        with tab1:
            with st.form('lf'):
                sid = st.text_input('學號（Student ID）')
                pw  = st.text_input('密碼（Password）', type='password')
                if st.form_submit_button('登入 / Login', use_container_width=True):
                    user = do_login(sid, pw)
                    if user:
                        st.session_state.user = user
                        st.session_state.page = 'query'
                        st.rerun()
                    else:
                        st.error('學號或密碼錯誤 / Invalid student ID or password')
            st.caption('管理員：admin / admin123　系辦：staff / staff123')

        with tab2:
            with st.form('rf'):
                st.markdown("**帳號資訊 / Account Info**")
                c1,c2 = st.columns(2)
                nu  = c1.text_input('姓名（Name）*')
                ne  = c2.text_input('Email *')
                c1b,c2b = st.columns(2)
                np_ = c1b.text_input('密碼（Password）*', type='password')
                np2 = c2b.text_input('確認密碼（Confirm Password）*', type='password')
                st.markdown("**個人資料 / Personal Info**")
                c1c,c2c = st.columns(2)
                identity   = c1c.selectbox('身份（Identity）*', IDENTITY_OPTIONS)
                student_id = c2c.text_input('學號（Student ID）*')
                c1d,c2d = st.columns(2)
                department = c1d.text_input('系所/單位（Department）*')
                phone      = c2d.text_input('電話（Phone）*')
                if st.form_submit_button('建立帳號 / Register', use_container_width=True):
                    if not all([nu, ne, np_, student_id, department, phone]):
                        st.error('所有標 * 欄位均為必填 / All * fields are required')
                    elif np_ != np2:
                        st.error('兩次密碼不一致 / Passwords do not match')
                    elif '@' not in ne:
                        st.error('請輸入有效的 Email / Please enter a valid email')
                    else:
                        ok, msg = do_register(nu, np_, ne, identity, student_id, department, phone)
                        st.success(msg + '，請登入') if ok else st.error(msg)

        with tab3:
            step = st.session_state.get('reset_step', 1)
            if step == 1:
                with st.form('rq'):
                    sid_r = st.text_input('輸入學號（Student ID）')
                    if st.form_submit_button('發送驗證碼', use_container_width=True):
                        ok, msg = request_reset(sid_r)
                        if ok:
                            st.session_state.reset_step   = 2
                            st.session_state.reset_sid    = sid_r
                            st.success(msg); st.rerun()
                        else:
                            st.error(msg)
            elif step == 2:
                with st.form('rp'):
                    token  = st.text_input('驗證碼（6位數字）')
                    new_pw = st.text_input('新密碼', type='password')
                    new_pw2= st.text_input('確認新密碼', type='password')
                    if st.form_submit_button('重設密碼', use_container_width=True):
                        if new_pw != new_pw2:
                            st.error('密碼不一致')
                        else:
                            ok, msg = do_reset_password(st.session_state.reset_sid, token, new_pw)
                            if ok:
                                st.success(msg)
                                for k in ['reset_step','reset_sid']:
                                    st.session_state.pop(k,None)
                                st.rerun()
                            else:
                                st.error(msg)
                if st.button('↩ 重新輸入學號'):
                    st.session_state.reset_step = 1; st.rerun()


def page_query():
    st.header('🔍 查詢可用時間')
    tab1, tab2 = st.tabs(['🏫 教室週課表', '🔧 設備查詢'])
    with tab1:
        rooms = get_rooms()
        if not rooms: st.info('目前沒有教室資料'); return
        rm_map   = {r['name']: r for r in rooms}
        sel_room = st.selectbox('選擇教室', list(rm_map.keys()), key='qr_sel')
        render_room_calendar(rm_map[sel_room], week_offset_key='qr_week')
    with tab2:
        equips = get_equips()
        if not equips: st.info('目前沒有設備資料'); return
        eq_map = {e['name']: e for e in equips}
        sel    = st.selectbox('選擇設備', list(eq_map.keys()), key='qe_sel')
        d      = st.date_input('日期', value=date.today(), key='qe_d')
        equip  = eq_map[sel]
        c1,c2,c3 = st.columns(3)
        c1.metric('設備編號', equip['serial_number'] or '—')
        c2.metric('總數量',   equip['quantity'] or 1)
        c3.metric('說明',     equip['description'] or '—')
        slots = get_equip_slots(equip['equip_id'], str(d))
        if slots:
            st.info(f'📦  {d}  借用/審核中：')
            for s in slots:
                qty = s.get('quantity_borrowed') or 1
                st.markdown(f"- `{s['start_time']} ~ {s['end_time']}`　{s['fullname']}　×{qty}　{SL.get(s['status'],s['status'])}")
        else:
            st.success(f'✅  {d}  此設備無人借用，全部 {equip["quantity"] or 1} 件可借')


def page_book():
    st.header('📋 預約教室 / 借用設備')
    user = st.session_state.user

    if is_blacklisted(user['user_id']):
        st.error('⛔ 您目前在黑名單中，無法進行預約或借用。請洽系辦了解詳情。')
        return

    if not user.get('student_id') or not user.get('department'):
        st.warning('⚠️ 請先至「👤 個人資料」填寫完整資料才能預約。')

    st.info('📢 預約需經系辦審核，請提早 **1-2 個工作天** 送出申請，不接受臨時預約。', icon='ℹ️')

    tab1, tab2 = st.tabs(['🏫 預約教室', '🔧 借用設備'])

    # ── 教室 ──────────────────────────────────────────────────
    with tab1:
        rooms = get_rooms()
        if not rooms: st.info('目前沒有教室資料')
        else:
            rm_map   = {r['name']: r for r in rooms}
            sel_room = st.selectbox('選擇教室', list(rm_map.keys()), key='br_sel')
            room     = rm_map[sel_room]

            # 顯示容量提示
            cap = room.get('capacity') or 0
            if cap > 0:
                st.caption(f'🏫 {sel_room}　容納人數上限：**{cap} 人**')

            col_cal, col_form = st.columns([3, 2], gap='large')
            with col_cal:
                st.markdown(f"##### 📅 {sel_room} — 課表")
                render_room_calendar(room, week_offset_key='br_week', compact=True)

            with col_form:
                st.markdown("##### ✏️ 填寫預約資訊")
                with st.form('br'):
                    bd  = st.date_input('日期 *', value=date.today())
                    c1,c2 = st.columns(2)
                    st_ = c1.time_input('開始時間 *', value=time(9,0))
                    et_ = c2.time_input('結束時間 *', value=time(10,0))
                    max_cap = cap if cap > 0 else 200
                    att_cnt = st.number_input(f'使用人數 * （上限 {max_cap} 人）',
                                              min_value=1, max_value=max_cap, value=1, step=1)
                    supervisor = st.text_input('指導老師（Supervisor）')
                    attendees  = st.text_input('使用人員名單（Attendees，逗號分隔）')
                    purpose    = st.selectbox('使用用途 *', ROOM_PURPOSES)
                    pur_other  = st.text_input('若「其他」請說明')
                    note       = st.text_input('備註')
                    if st.form_submit_button('📨 送出預約申請', use_container_width=True):
                        if st_ >= et_:
                            st.error('結束時間必須晚於開始時間')
                        else:
                            fp = pur_other if purpose=='其他' and pur_other else purpose
                            ok, msg = book_room(user['user_id'], room['room_id'],
                                                str(bd), str(st_)[:5], str(et_)[:5],
                                                int(att_cnt), supervisor, attendees, fp, note)
                            st.success(msg) if ok else st.error(msg)

    # ── 設備 ──────────────────────────────────────────────────
    with tab2:
        equips = get_equips()
        if not equips: st.info('目前沒有設備資料')
        else:
            eq_map   = {e['name']: e for e in equips}
            sel_name = st.selectbox('設備', list(eq_map.keys()), key='be_sel_preview')
            eq_prev  = eq_map[sel_name]
            ic1,ic2,ic3 = st.columns(3)
            ic1.metric('設備編號', eq_prev['serial_number'] or '—')
            ic2.metric('總數量',   eq_prev['quantity'] or 1)
            ic3.metric('說明',     eq_prev['description'] or '—')

            with st.form('be'):
                eq_names = list(eq_map.keys())
                sel_eq   = st.selectbox('確認設備', eq_names,
                                        index=eq_names.index(sel_name), key='be_sel_form')
                equip    = eq_map[sel_eq]
                bd       = st.date_input('日期 *', value=date.today(), key='be_d')
                c1,c2    = st.columns(2)
                st_      = c1.time_input('開始時間 *', value=time(9,0), key='be_st')
                et_      = c2.time_input('結束時間 *', value=time(10,0), key='be_et')
                max_qty  = equip['quantity'] or 1
                qty      = st.number_input(f'借用數量（最多 {max_qty} 件）',
                                           min_value=1, max_value=max_qty, value=1, step=1, key='be_qty')
                supervisor = st.text_input('指導老師（Supervisor）', key='be_sup')
                attendees  = st.text_input('使用人員名單（Attendees）', key='be_att')
                purpose    = st.selectbox('使用用途 *', EQUIP_PURPOSES, key='be_pur')
                pur_other  = st.text_input('若「其他」請說明', key='be_pur_o')
                note       = st.text_input('備註', key='be_note')
                if st.form_submit_button('📨 送出借用申請', use_container_width=True):
                    if st_ >= et_:
                        st.error('結束時間必須晚於開始時間')
                    else:
                        fp = pur_other if purpose=='其他' and pur_other else purpose
                        ok, msg = book_equip(user['user_id'], equip['equip_id'],
                                             str(bd), str(st_)[:5], str(et_)[:5],
                                             int(qty), supervisor, attendees, fp, note)
                        st.success(msg) if ok else st.error(msg)


def page_records():
    """歷史紀錄 + 我的預約合併頁"""
    st.header('📚 我的預約紀錄')
    user = st.session_state.user

    tab1, tab2 = st.tabs(['🏫 教室預約', '🔧 設備借用'])

    # ── 教室 ──────────────────────────────────────────────────
    with tab1:
        bks = get_user_room_bookings(user['user_id'])
        if not bks:
            st.info('尚無教室預約紀錄')
        else:
            # 狀態篩選
            status_opts = ['全部'] + list(SL.values())
            sel_status  = st.selectbox('篩選狀態', status_opts, key='rec_r_status')
            inv_sl = {v: k for k,v in SL.items()}
            filtered = bks if sel_status == '全部' else \
                       [b for b in bks if b['status'] == inv_sl.get(sel_status)]

            for b in filtered:
                st_lbl = SL.get(b['status'], b['status'])
                bg_col = SL_COLOR.get(b['status'], '#fff')
                label  = (f"{b['room_name']}　{b['book_date']}　"
                          f"{b['start_time']}~{b['end_time']}　{st_lbl}")
                with st.expander(label):
                    c1,c2 = st.columns(2)
                    c1.markdown(f"**教室：** {b['room_name']}")
                    c1.markdown(f"**日期：** {b['book_date']}")
                    c1.markdown(f"**時間：** {b['start_time']} ~ {b['end_time']}")
                    c1.markdown(f"**使用人數：** {b.get('attendee_count') or '—'}")
                    c2.markdown(f"**狀態：** {st_lbl}")
                    c2.markdown(f"**用途：** {b.get('purpose') or '—'}")
                    c2.markdown(f"**指導老師：** {b.get('supervisor') or '—'}")
                    c2.markdown(f"**使用人員：** {b.get('attendees') or '—'}")
                    if b.get('reject_reason'):
                        st.error(f"❌ 未通過原因：{b['reject_reason']}")
                    if b.get('returned_at'):
                        st.success(f"✅ 歸還時間：{b['returned_at']}")
                    if b.get('note'):
                        st.caption(f"備註：{b['note']}")
                    st.caption(f"申請時間：{b['created_at']}")

                    # 操作按鈕
                    if b['status'] == 'confirmed':
                        ca,cb,cc = st.columns(3)
                        if ca.button('🔔 申請歸還', key=f"rr{b['booking_id']}"):
                            request_return_room(b['booking_id'], user['user_id'])
                            st.success('歸還申請已送出'); st.rerun()
                        if cb.button('❌ 取消', key=f"cr{b['booking_id']}"):
                            cancel_room(b['booking_id'], user['user_id']); st.rerun()
                        if cc.button('✏️ 修改', key=f"mr{b['booking_id']}"):
                            st.session_state[f'mod_r_{b["booking_id"]}'] = True

                        if st.session_state.get(f'mod_r_{b["booking_id"]}'):
                            with st.form(f'mrf_{b["booking_id"]}'):
                                nd = st.date_input('新日期', value=date.fromisoformat(b['book_date']))
                                mc1,mc2 = st.columns(2)
                                ns = mc1.time_input('新開始', value=time.fromisoformat(b['start_time']))
                                ne = mc2.time_input('新結束', value=time.fromisoformat(b['end_time']))
                                rm_rooms = get_rooms()
                                rm_map   = {r['name']: r for r in rm_rooms}
                                cap      = rm_map.get(b['room_name'],{}).get('capacity',200) or 200
                                na_cnt   = st.number_input('使用人數', min_value=1, max_value=cap,
                                                           value=b.get('attendee_count') or 1)
                                n_sup    = st.text_input('指導老師', value=b.get('supervisor') or '')
                                n_att    = st.text_input('使用人員', value=b.get('attendees') or '')
                                cur_p    = b.get('purpose') or ROOM_PURPOSES[0]
                                pidx     = ROOM_PURPOSES.index(cur_p) if cur_p in ROOM_PURPOSES else len(ROOM_PURPOSES)-1
                                n_pur    = st.selectbox('用途', ROOM_PURPOSES, index=pidx)
                                n_po     = st.text_input('若「其他」說明', value=cur_p if cur_p not in ROOM_PURPOSES else '')
                                n_note   = st.text_input('備註', value=b.get('note') or '')
                                if st.form_submit_button('確認修改（重新送審）'):
                                    if ns >= ne: st.error('時間錯誤')
                                    else:
                                        fp = n_po if n_pur=='其他' and n_po else n_pur
                                        ok, msg = modify_room(b['booking_id'], user['user_id'],
                                                              b['room_id'], str(nd),
                                                              str(ns)[:5], str(ne)[:5],
                                                              int(na_cnt), n_sup, n_att, fp, n_note)
                                        if ok:
                                            st.success(msg)
                                            st.session_state.pop(f'mod_r_{b["booking_id"]}', None)
                                            st.rerun()
                                        else: st.error(msg)

                    elif b['status'] == 'pending':
                        if st.button('❌ 撤回申請', key=f"wdr{b['booking_id']}"):
                            cancel_room(b['booking_id'], user['user_id']); st.rerun()

                    elif b['status'] == 'pending_return':
                        st.info('🔔 歸還申請待系辦確認中...')
                        if st.button('↩️ 撤回歸還申請', key=f"unrr{b['booking_id']}"):
                            sb().table('ROOM_BOOKING').update({'status':'confirmed'}).eq('booking_id', b['booking_id']).eq('user_id', user['user_id']).execute()
                            st.rerun()

    # ── 設備 ──────────────────────────────────────────────────
    with tab2:
        bks = get_user_equip_bookings(user['user_id'])
        if not bks:
            st.info('尚無設備借用紀錄')
        else:
            status_opts = ['全部'] + list(SL.values())
            sel_status  = st.selectbox('篩選狀態', status_opts, key='rec_e_status')
            inv_sl = {v: k for k,v in SL.items()}
            filtered = bks if sel_status == '全部' else \
                       [b for b in bks if b['status'] == inv_sl.get(sel_status)]

            for b in filtered:
                qty    = b.get('quantity_borrowed') or 1
                st_lbl = SL.get(b['status'], b['status'])
                label  = (f"{b['equip_name']}　#{b.get('serial_number') or '—'}　×{qty}　"
                          f"{b['book_date']}　{b['start_time']}~{b['end_time']}　{st_lbl}")
                with st.expander(label):
                    c1,c2 = st.columns(2)
                    c1.markdown(f"**設備：** {b['equip_name']}")
                    c1.markdown(f"**設備編號：** {b.get('serial_number') or '—'}")
                    c1.markdown(f"**借用數量：** {qty} 件")
                    c1.markdown(f"**日期：** {b['book_date']}")
                    c2.markdown(f"**狀態：** {st_lbl}")
                    c2.markdown(f"**時間：** {b['start_time']} ~ {b['end_time']}")
                    c2.markdown(f"**用途：** {b.get('purpose') or '—'}")
                    c2.markdown(f"**指導老師：** {b.get('supervisor') or '—'}")
                    if b.get('reject_reason'):
                        st.error(f"❌ 未通過原因：{b['reject_reason']}")
                    if b.get('returned_at'):
                        st.success(f"✅ 歸還時間：{b['returned_at']}")
                    st.caption(f"申請時間：{b['created_at']}")

                    if b['status'] == 'confirmed':
                        ca,cb = st.columns(2)
                        if ca.button('🔔 申請歸還', key=f"re{b['booking_id']}"):
                            request_return_equip(b['booking_id'], user['user_id'])
                            st.success('歸還申請已送出'); st.rerun()
                        if cb.button('❌ 取消', key=f"ce{b['booking_id']}"):
                            cancel_equip(b['booking_id'], user['user_id']); st.rerun()

                    elif b['status'] == 'pending':
                        if st.button('❌ 撤回申請', key=f"wde{b['booking_id']}"):
                            cancel_equip(b['booking_id'], user['user_id']); st.rerun()

                    elif b['status'] == 'pending_return':
                        st.info('🔔 歸還申請待系辦確認中...')
                        if st.button('↩️ 撤回歸還申請', key=f"unre{b['booking_id']}"):
                            sb().table('EQUIP_BOOKING').update({'status':'confirmed'}).eq('booking_id', b['booking_id']).eq('user_id', user['user_id']).execute()
                            st.rerun()


def page_profile():
    st.header('👤 個人資料')
    user = st.session_state.user
    st.info(f"帳號：**{user['fullname']}**（{user['student_id']}）　角色：{ROLE_LABEL.get(user['role'],'—')}")

    if is_blacklisted(user['user_id']):
        bl = get_blacklist_entry(user['user_id'])
        if bl:
            if bl.get('is_permanent'):
                st.error(f"⛔ 您目前在黑名單中（永久停權）。原因：{bl.get('reason','—')}。如有疑問請洽系辦。")
            else:
                st.error(f"⛔ 您目前在黑名單中，限制至 {bl.get('expire_at','—')[:10]}。"
                         f"原因：{bl.get('reason','—')}。如有疑問請洽系辦。")
        else:
            st.error('⛔ 您目前在黑名單中，如有疑問請洽系辦。')
    elif user.get('probation_until') and user['probation_until'] > nows():
        st.warning(f"👁 您目前在觀察期中（至 {user['probation_until'][:10]}），"
                   f"請遵守使用規範，觀察期內再違規將直接升級懲處。")

    with st.form('profile_form'):
        c1,c2 = st.columns(2)
        fullname   = c1.text_input('姓名（Name）*', value=user.get('fullname') or '')
        email      = c2.text_input('Email *',       value=user.get('email')    or '')
        c1b,c2b    = st.columns(2)
        identity   = c1b.selectbox('身份', IDENTITY_OPTIONS,
                                   index=IDENTITY_OPTIONS.index(user['identity'])
                                   if user.get('identity') in IDENTITY_OPTIONS else 0)
        student_id = c2b.text_input('學號（Student ID）*', value=user.get('student_id') or '')
        c1c,c2c    = st.columns(2)
        department = c1c.text_input('系所/單位 *', value=user.get('department') or '')
        phone      = c2c.text_input('電話 *',      value=user.get('phone')      or '')
        if st.form_submit_button('💾 儲存', use_container_width=True):
            if not all([fullname, email, student_id, department, phone]):
                st.error('姓名、Email、學號、系所、電話均為必填')
            elif '@' not in email:
                st.error('請輸入有效的 Email')
            else:
                ok, updated = update_profile(user['user_id'], fullname, email, identity,
                                             student_id, department, phone)
                if ok:
                    st.session_state.user = updated
                    st.success('✅ 個人資料已更新'); st.rerun()
                else:
                    st.error('此學號已被其他帳號使用')


def page_staff():
    st.header('🏢 系辦管理台')
    pr  = pending_room_reviews()
    pe  = pending_equip_reviews()
    prr = pending_room_returns()
    per = pending_equip_returns()
    tot = len(pr)+len(pe)+len(prr)+len(per)
    if tot: st.error(f'🔔 有 **{tot}** 筆待處理事項')
    else:   st.success('✅ 目前無待處理事項')

    suspects = get_suspect_logs()
    probn    = get_probation_users()
    if suspects: st.warning(f'🚨 有 **{len(suspects)}** 筆疑似違規待處理')

    tabs = st.tabs(['⏳ 待審核', '🔔 待確認歸還', '🚨 疑似違規', '👁 觀察期名單', '📋 所有教室預約', '📦 所有設備借用'])

    # ── 待審核 ────────────────────────────────────────────────
    with tabs[0]:
        st.subheader(f'🏫 教室待審核（{len(pr)} 筆）')
        if not pr: st.info('無待審核教室預約')
        for b in pr:
            with st.expander(f"{b['room_name']}　{b['book_date']}　{b['start_time']}~{b['end_time']}　👤 {b['fullname']}"):
                c1,c2 = st.columns(2)
                c1.markdown(f"**姓名：** {b['fullname']}")
                c1.markdown(f"**學號：** {b['student_id']}")
                c1.markdown(f"**系所：** {b['department']}")
                c1.markdown(f"**身份：** {b['identity']}")
                c2.markdown(f"**電話：** {b['phone']}")
                c2.markdown(f"**Email：** {b['email']}")
                c2.markdown(f"**使用人數：** {b.get('attendee_count')}　（容量：{b.get('capacity') or '未設定'}）")
                c2.markdown(f"**用途：** {b.get('purpose') or '—'}")
                if b.get('supervisor'): st.markdown(f"**指導老師：** {b['supervisor']}")
                if b.get('attendees'):  st.markdown(f"**使用人員：** {b['attendees']}")
                if b.get('note'):       st.caption(f"備註：{b['note']}")
                ca,cb,reject_col = st.columns([1,1,2])
                if ca.button('✅ 審核通過', key=f"apr{b['booking_id']}", type='primary'):
                    approve_room(b['booking_id']); st.success('已通過'); st.rerun()
                reason_input = reject_col.text_input('拒絕原因', key=f"rjr_txt_{b['booking_id']}")
                if cb.button('❌ 拒絕', key=f"rjr{b['booking_id']}"):
                    reject_room(b['booking_id'], reason_input); st.warning('已拒絕'); st.rerun()

        st.divider()
        st.subheader(f'🔧 設備待審核（{len(pe)} 筆）')
        if not pe: st.info('無待審核設備借用')
        for b in pe:
            qty = b.get('quantity_borrowed') or 1
            with st.expander(f"{b['equip_name']}　×{qty}　{b['book_date']}　{b['start_time']}~{b['end_time']}　👤 {b['fullname']}"):
                c1,c2 = st.columns(2)
                c1.markdown(f"**姓名：** {b['fullname']}")
                c1.markdown(f"**學號：** {b['student_id']}")
                c1.markdown(f"**系所：** {b['department']}")
                c2.markdown(f"**電話：** {b['phone']}")
                c2.markdown(f"**Email：** {b['email']}")
                c2.markdown(f"**設備編號：** {b.get('serial_number') or '—'}")
                c2.markdown(f"**用途：** {b.get('purpose') or '—'}")
                if b.get('supervisor'): st.markdown(f"**指導老師：** {b['supervisor']}")
                if b.get('attendees'):  st.markdown(f"**使用人員：** {b['attendees']}")
                ca,cb,reject_col = st.columns([1,1,2])
                if ca.button('✅ 審核通過', key=f"ape{b['booking_id']}", type='primary'):
                    approve_equip(b['booking_id']); st.success('已通過'); st.rerun()
                reason_input = reject_col.text_input('拒絕原因', key=f"rje_txt_{b['booking_id']}")
                if cb.button('❌ 拒絕', key=f"rje{b['booking_id']}"):
                    reject_equip(b['booking_id'], reason_input); st.warning('已拒絕'); st.rerun()

    # ── 待確認歸還 ────────────────────────────────────────────
    with tabs[1]:
        st.subheader(f'🏫 待確認教室歸還（{len(prr)} 筆）')
        if not prr: st.info('無待確認')
        for b in prr:
            with st.expander(f"{b['room_name']}　{b['book_date']}　{b['start_time']}~{b['end_time']}　👤 {b['fullname']}"):
                c1,c2 = st.columns(2)
                c1.markdown(f"**學號：** {b['student_id']}　**電話：** {b['phone']}")
                c2.markdown(f"**Email：** {b['email']}")
                ca,cb = st.columns(2)
                if ca.button('✅ 確認已歸還', key=f"cfr{b['booking_id']}", type='primary'):
                    confirm_return_room(b['booking_id']); st.success('已確認'); st.rerun()
                if cb.button('❌ 退回申請', key=f"rjrr{b['booking_id']}"):
                    sb().table('ROOM_BOOKING').update({'status':'confirmed'}).eq('booking_id', b['booking_id']).execute()
                    st.warning('已退回'); st.rerun()

        st.divider()
        st.subheader(f'🔧 待確認設備歸還（{len(per)} 筆）')
        if not per: st.info('無待確認')
        for b in per:
            with st.expander(f"{b['equip_name']}　{b['book_date']}　👤 {b['fullname']}"):
                c1,c2 = st.columns(2)
                c1.markdown(f"**學號：** {b['student_id']}　**電話：** {b['phone']}")
                c2.markdown(f"**Email：** {b['email']}")
                ca,cb = st.columns(2)
                if ca.button('✅ 確認已歸還', key=f"cfe{b['booking_id']}", type='primary'):
                    confirm_return_equip(b['booking_id']); st.success('已確認'); st.rerun()
                if cb.button('❌ 退回申請', key=f"rjer{b['booking_id']}"):
                    sb().table('EQUIP_BOOKING').update({'status':'confirmed'}).eq('booking_id', b['booking_id']).execute()
                    st.warning('已退回'); st.rerun()

    # ── 疑似違規 ──────────────────────────────────────────────
    with tabs[2]:
        st.subheader(f'🚨 疑似違規清單（{len(suspects)} 筆）')
        st.caption('以下使用者的預約超過結束時間 4 小時仍未辦理歸還，請實際確認後決定是否加入黑名單。')
        if not suspects:
            st.info('目前無疑似違規紀錄')
        for s in suspects:
            with st.expander(f"🚨 {s['fullname']}（{s['student_id']}）　{s['kind']}　{s['flagged_at'][:16]}"):
                c1,c2 = st.columns(2)
                c1.markdown(f"**姓名：** {s['fullname']}")
                c1.markdown(f"**學號：** {s['student_id']}")
                c1.markdown(f"**系所：** {s['department']}")
                c2.markdown(f"**電話：** {s['phone']}")
                c2.markdown(f"**Email：** {s['email']}")
                c2.markdown(f"**類型：** {s['kind']}　預約編號：{s['booking_id']}")
                ca, cb = st.columns(2)
                if ca.button('✅ 確認無違規（關閉）', key=f"slok{s['log_id']}"):
                    resolve_suspect(s['log_id']); st.success('已標記為無違規'); st.rerun()
                bl_reason = cb.text_input('加入黑名單原因', key=f"slreason{s['log_id']}")
                if st.button('⛔ 確認違規並加入黑名單', key=f"slbl{s['log_id']}", type='primary'):
                    add_blacklist(s['user_id'], bl_reason or '逾期未歸還',
                                  st.session_state.user['user_id'])
                    resolve_suspect(s['log_id'])
                    st.success(f"已將 {s['fullname']} 加入黑名單"); st.rerun()

    # ── 觀察期名單 ────────────────────────────────────────────
    with tabs[3]:
        st.subheader(f'👁 觀察期名單（{len(probn)} 人）')
        st.caption('這些使用者已解除黑名單但仍在 60 天觀察期中，若再違規將直接升級懲處。')
        if not probn:
            st.info('目前無使用者在觀察期')
        for u in probn:
            bl = get_blacklist_entry(u['user_id'])
            tier_str = f"第 {bl['tier']} 級" if bl else '—'
            probation_end = u.get('probation_until','')[:10] if u.get('probation_until') else '—'
            st.markdown(
                f"**{u['fullname']}**（{u['student_id']}）　{u['department']}　"
                f"觀察期至 **{probation_end}**　前次違規等級：{tier_str}"
            )

    # ── 所有教室預約 ──────────────────────────────────────────
    with tabs[4]:
        bks = all_room_bookings()
        if not bks: st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id','fullname','identity','department','student_id',
                                     'phone','email','room_name','book_date','start_time','end_time',
                                     'attendee_count','supervisor','purpose','status','returned_at','note']]
            df.columns = ['ID','姓名','身份','系所','學號','電話','Email',
                          '教室','日期','開始','結束','人數','指導老師','用途','狀態','歸還時間','備註']
            df['狀態'] = df['狀態'].map(lambda x: SL.get(x,x))
            st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 所有設備借用 ──────────────────────────────────────────
    with tabs[5]:
        bks = all_equip_bookings()
        if not bks: st.info('無記錄')
        else:
            df = pd.DataFrame(bks)[['booking_id','fullname','identity','department','student_id',
                                     'phone','email','equip_name','serial_number','book_date',
                                     'start_time','end_time','quantity_borrowed','purpose','status','returned_at']]
            df.columns = ['ID','姓名','身份','系所','學號','電話','Email',
                          '設備','編號','日期','開始','結束','借用數量','用途','狀態','歸還時間']
            df['狀態'] = df['狀態'].map(lambda x: SL.get(x,x))
            st.dataframe(df, use_container_width=True, hide_index=True)


def page_admin():
    st.header('⚙️ 管理員後台')
    tabs = st.tabs(['🏫 管理教室','🔧 管理設備','👥 使用者','⛔ 黑名單','📧 SMTP 設定'])

    # ── 管理教室 ──────────────────────────────────────────────
    with tabs[0]:
        c1,c2 = st.columns(2)
        with c1:
            st.subheader('新增教室')
            with st.form('ar'):
                nm  = st.text_input('教室名稱 *')
                cap = st.number_input('容納人數 *', min_value=1, value=20, step=1)
                ds  = st.text_input('說明')
                if st.form_submit_button('新增', use_container_width=True):
                    ok, msg = add_room(nm, int(cap), ds)
                    st.success(msg) if ok else st.error(msg)
                    if ok: st.rerun()
        with c2:
            st.subheader('現有教室')
            for r in get_rooms():
                with st.expander(f"🏫 {r['name']}（容量 {r.get('capacity') or '未設定'} 人）"):
                    with st.form(f"edit_room_{r['room_id']}"):
                        n_name = st.text_input('名稱', value=r['name'])
                        n_cap  = st.number_input('容量', min_value=1,
                                                 value=r.get('capacity') or 1, step=1)
                        n_desc = st.text_input('說明', value=r.get('description') or '')
                        ca,cb  = st.columns(2)
                        if ca.form_submit_button('💾 儲存'):
                            update_room(r['room_id'], n_name, int(n_cap), n_desc)
                            st.success('已更新'); st.rerun()
                        if cb.form_submit_button('🚫 停用'):
                            disable_room(r['room_id']); st.rerun()

        st.divider()
        st.subheader('📅 管理固定課程')
        rm_list = get_rooms()
        if rm_list:
            fc_sel  = st.selectbox('選擇教室', [r['name'] for r in rm_list], key='fc_rm')
            fc_room = next(r for r in rm_list if r['name']==fc_sel)
            with st.form('add_fc'):
                c1,c2,c3 = st.columns(3)
                fc_wd  = c1.selectbox('星期', WEEKDAY_ZH)
                fc_st  = c2.time_input('開始', value=time(8,0))
                fc_et  = c3.time_input('結束', value=time(10,0))
                fc_ttl = st.text_input('課程名稱 *')
                fc_nt  = st.text_input('備註')
                if st.form_submit_button('➕ 新增', use_container_width=True):
                    if not fc_ttl: st.error('請填課程名稱')
                    elif fc_st >= fc_et: st.error('時間錯誤')
                    else:
                        add_fixed_course(fc_room['room_id'], WEEKDAY_ZH.index(fc_wd),
                                         str(fc_st)[:5], str(fc_et)[:5], fc_ttl, fc_nt)
                        st.success('已新增'); st.rerun()
            for fc in get_fixed_courses(fc_room['room_id']):
                cc1,cc2,cc3 = st.columns([2,3,1])
                cc1.write(f"**{WEEKDAY_ZH[fc['weekday']]}** {fc['start_time']}~{fc['end_time']}")
                cc2.write(f"📘 {fc['title']}" + (f"　*{fc['note']}*" if fc.get('note') else ''))
                if cc3.button('🗑️', key=f"dfc{fc['course_id']}"):
                    delete_fixed_course(fc['course_id']); st.rerun()

    # ── 管理設備 ──────────────────────────────────────────────
    with tabs[1]:
        c1,c2 = st.columns(2)
        with c1:
            st.subheader('新增設備')
            with st.form('ae'):
                nm  = st.text_input('設備名稱 *')
                sn  = st.text_input('設備編號')
                qty = st.number_input('數量 *', min_value=1, value=1, step=1)
                ds  = st.text_input('說明')
                if st.form_submit_button('新增', use_container_width=True):
                    ok, msg = add_equip(nm, sn, int(qty), ds)
                    st.success(msg) if ok else st.error(msg)
                    if ok: st.rerun()
        with c2:
            st.subheader('現有設備')
            for e in get_equips():
                with st.expander(f"🔧 {e['name']}　#{e['serial_number'] or '—'}　×{e['quantity'] or 1}"):
                    with st.form(f"edit_eq_{e['equip_id']}"):
                        n_nm  = st.text_input('名稱', value=e['name'])
                        n_sn  = st.text_input('編號', value=e['serial_number'] or '')
                        n_qty = st.number_input('數量', min_value=1, value=e['quantity'] or 1, step=1)
                        n_ds  = st.text_input('說明', value=e['description'] or '')
                        ca,cb = st.columns(2)
                        if ca.form_submit_button('💾 儲存'):
                            update_equip(e['equip_id'], n_nm, n_sn, int(n_qty), n_ds)
                            st.success('已更新'); st.rerun()
                        if cb.form_submit_button('🚫 停用'):
                            disable_equip(e['equip_id']); st.rerun()

    # ── 使用者管理 ────────────────────────────────────────────
    with tabs[2]:
        users = get_all_users()
        df = pd.DataFrame(users)[['fullname','student_id','role','identity',
                                   'department','phone','email','created_at']]
        df.columns = ['姓名','學號','角色','身份','系所','電話','Email','註冊時間']
        df['角色'] = df['角色'].map(lambda x: ROLE_LABEL.get(x,x))
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader('變更角色')
        unames = {u['fullname']+f"（{u['student_id']}）": u for u in users if u['student_id'] != 'admin'}
        if unames:
            c1,c2,c3 = st.columns(3)
            tu_label = c1.selectbox('選擇使用者', list(unames.keys()), key='role_tgt')
            tu       = unames[tu_label]
            roles    = ['user','staff','admin']
            cur_idx  = roles.index(tu['role']) if tu['role'] in roles else 0
            new_role = c2.selectbox('角色', roles, index=cur_idx, key='role_new',
                                    format_func=lambda x: ROLE_LABEL.get(x,x))
            if c3.button('💾 更新', use_container_width=True):
                sb().table('USER').update({'role':new_role}).eq('user_id', tu['user_id']).execute()
                st.success(f"已將 {tu['fullname']} 設為 {ROLE_LABEL.get(new_role)}")
                st.rerun()

    # ── 黑名單 ────────────────────────────────────────────────
    with tabs[3]:
        st.subheader('⛔ 黑名單管理')
        st.caption('違規等級：第1級 30天 → 第2級 90天 → 第3級 永久停權。解除後有 60 天觀察期，觀察期內再違規直接升一級。')

        # 新增黑名單
        with st.form('add_bl'):
            all_users = get_all_users()
            non_bl = {u['fullname']+f"（{u['student_id']}）": u
                      for u in all_users if not is_blacklisted(u['user_id'])
                      and u['student_id'] not in ('admin','staff')}
            if non_bl:
                c1,c2 = st.columns([2,3])
                bl_tgt     = c1.selectbox('選擇使用者', list(non_bl.keys()), key='bl_tgt')
                bl_rsn_sel = c2.selectbox('違規原因', BL_REASONS, key='bl_rsn_sel')
                bl_rsn_other = st.text_input('若「其他」請說明', key='bl_rsn_other')
                is_perm    = st.checkbox('強制永久停權（不論違規次數）', key='bl_perm')
                if st.form_submit_button('⛔ 加入黑名單', use_container_width=True):
                    final_reason = bl_rsn_other if bl_rsn_sel=='其他' and bl_rsn_other else bl_rsn_sel
                    tgt_user = non_bl[bl_tgt]
                    add_blacklist(tgt_user['user_id'], final_reason,
                                  st.session_state.user['user_id'], is_permanent=is_perm)
                    st.success(f"已將 {tgt_user['fullname']} 加入黑名單"); st.rerun()
            else:
                st.info('目前無可加入黑名單的使用者')
                st.form_submit_button('確認', disabled=True)

        # 黑名單列表
        bl_list = get_blacklist()
        if bl_list:
            st.markdown(f"**目前黑名單（{len(bl_list)} 人）**")
            for bl in bl_list:
                if bl.get('is_permanent'):
                    status_str = '🔴 永久停權'
                elif bl.get('expire_at'):
                    status_str = f"🟡 限制至 {bl['expire_at'][:10]}"
                else:
                    status_str = '—'
                prob_str = f"　觀察期至 {bl['probation_until'][:10]}" if bl.get('probation_until') else ''
                viol_cnt = bl.get('violation_count') or 1
                with st.expander(
                    f"⛔ {bl['fullname']}（{bl['student_id']}）　{bl['department']}　"
                    f"第{bl.get('tier',1)}級　{status_str}{prob_str}"
                ):
                    st.markdown(f"**違規原因：** {bl['reason']}")
                    st.markdown(f"**累積違規次數：** {viol_cnt} 次")
                    st.markdown(f"**加入者：** {bl['added_by_name']}　**加入時間：** {bl['added_at']}")
                    if bl.get('lifted_at'):
                        st.markdown(f"**解除時間：** {bl['lifted_at']}")
                    c1,c2 = st.columns(2)
                    if c1.button('✅ 手動解除', key=f"rmbl{bl['bl_id']}"):
                        remove_blacklist(bl['user_id']); st.success('已解除，進入觀察期'); st.rerun()
                    if not bl.get('is_permanent'):
                        if c2.button('🔒 升為永久停權', key=f"permbl{bl['bl_id']}"):
                            sb().table('BLACKLIST').update({'is_permanent':1,'tier':3,'expire_at':None}).eq('bl_id', bl['bl_id']).execute()
                            st.warning('已升為永久停權'); st.rerun()
        else:
            st.info('目前黑名單為空')

    # ── SMTP 設定 ──────────────────────────────────────────────
    with tabs[4]:
        st.subheader('📧 Email / SMTP 設定')
        st.caption('設定後系統將可發送審核通知、提醒信、忘記密碼等郵件。建議使用 Gmail App Password。')
        cfg = get_smtp_config()
        with st.form('smtp_form'):
            c1,c2 = st.columns(2)
            s_host = c1.text_input('SMTP 主機', value=cfg.get('host') or 'smtp.gmail.com')
            s_port = c2.number_input('連接埠', value=int(cfg.get('port') or 587), step=1)
            c1b,c2b = st.columns(2)
            s_user = c1b.text_input('帳號（寄件人 Email）', value=cfg.get('username') or '')
            s_pw   = c2b.text_input('密碼 / App Password', value=cfg.get('password') or '', type='password')
            s_name = st.text_input('寄件人名稱', value=cfg.get('sender_name') or '土木館預約系統')
            s_tls  = st.checkbox('使用 TLS (STARTTLS)', value=bool(cfg.get('use_tls', 1)))
            if st.form_submit_button('💾 儲存 SMTP 設定', use_container_width=True):
                save_smtp_config(s_host, int(s_port), s_user, s_pw, s_name, s_tls)
                st.success('✅ SMTP 設定已儲存')

        st.divider()
        st.subheader('🧪 測試郵件')
        test_to = st.text_input('測試收件 Email')
        if st.button('📨 發送測試信'):
            ok = send_email(test_to, '【土木館】測試郵件',
                            '<p>✅ 恭喜！SMTP 設定正確，系統可以正常發送郵件。</p>')
            st.success('發送成功！') if ok else st.error('發送失敗，請檢查 SMTP 設定。')


def page_er():
    st.header('📊 ER Model — 資料庫實體關聯圖')
    st.markdown("""
```
USER      ||--o{  ROOM_BOOKING   : 預約
USER      ||--o{  EQUIP_BOOKING  : 借用
USER      ||--o{  BLACKLIST      : 被列入
ROOM      ||--o{  ROOM_BOOKING   : 被預約
ROOM      ||--o{  FIXED_COURSE   : 固定課程
EQUIPMENT ||--o{  EQUIP_BOOKING  : 被借用
```
""")
    st.divider()
    c1,c2,c3 = st.columns(3)
    with c1:
        st.markdown("#### 👤 USER")
        st.table(pd.DataFrame([
            ['user_id','INTEGER','PK'],['fullname','TEXT','姓名'],
            ['password','TEXT','密碼雜湊'],['role','TEXT','user/staff/admin'],
            ['email','TEXT','Email（必填）'],['identity','TEXT','身份'],
            ['student_id','TEXT','學號（唯一）'],['department','TEXT','系所'],
            ['phone','TEXT','電話（必填）'],['reset_token','TEXT','密碼重設 Token'],
            ['created_at','TEXT','註冊時間'],
        ],columns=['欄位','型別','說明']))

        st.markdown("#### 🏫 ROOM")
        st.table(pd.DataFrame([
            ['room_id','INTEGER','PK'],['name','TEXT','教室名稱'],
            ['capacity','INTEGER','容納人數'],['description','TEXT','說明'],
            ['is_active','INTEGER','是否啟用'],
        ],columns=['欄位','型別','說明']))

        st.markdown("#### ⛔ BLACKLIST")
        st.table(pd.DataFrame([
            ['bl_id','INTEGER','PK'],['user_id','INTEGER','FK→USER'],
            ['reason','TEXT','違規原因'],['added_by','INTEGER','FK→USER（操作者）'],
            ['added_at','TEXT','加入時間'],
        ],columns=['欄位','型別','說明']))

    with c2:
        st.markdown("#### 🔧 EQUIPMENT")
        st.table(pd.DataFrame([
            ['equip_id','INTEGER','PK'],['name','TEXT','設備名稱'],
            ['serial_number','TEXT','設備編號'],['quantity','INTEGER','總數量'],
            ['description','TEXT','說明'],['is_active','INTEGER','是否啟用'],
        ],columns=['欄位','型別','說明']))

        st.markdown("#### 📅 FIXED_COURSE")
        st.table(pd.DataFrame([
            ['course_id','INTEGER','PK'],['room_id','INTEGER','FK→ROOM'],
            ['weekday','INTEGER','0=週一…6=週日'],['start_time','TEXT','開始'],
            ['end_time','TEXT','結束'],['title','TEXT','課程名稱'],['note','TEXT','備註'],
        ],columns=['欄位','型別','說明']))

    with c3:
        st.markdown("#### 📋 ROOM_BOOKING")
        st.table(pd.DataFrame([
            ['booking_id','INTEGER','PK'],['user_id','INTEGER','FK→USER'],
            ['room_id','INTEGER','FK→ROOM'],['book_date','TEXT','日期'],
            ['start_time','TEXT','開始'],['end_time','TEXT','結束'],
            ['attendee_count','INTEGER','使用人數'],['supervisor','TEXT','指導老師'],
            ['attendees','TEXT','使用人員'],['purpose','TEXT','用途'],
            ['status','TEXT','pending/confirmed/rejected/cancelled/pending_return/returned'],
            ['returned_at','TEXT','歸還時間'],['reject_reason','TEXT','拒絕原因'],
            ['notified_start','INTEGER','開始提醒已發'],['notified_end','INTEGER','結束提醒已發'],
            ['created_at','TEXT','建立時間'],
        ],columns=['欄位','型別','說明']))

        st.markdown("#### 📦 EQUIP_BOOKING")
        st.table(pd.DataFrame([
            ['booking_id','INTEGER','PK'],['user_id','INTEGER','FK→USER'],
            ['equip_id','INTEGER','FK→EQUIPMENT'],['book_date','TEXT','日期'],
            ['start_time','TEXT','開始'],['end_time','TEXT','結束'],
            ['quantity_borrowed','INTEGER','借用數量'],['supervisor','TEXT','指導老師'],
            ['attendees','TEXT','使用人員'],['purpose','TEXT','用途'],
            ['status','TEXT','pending/confirmed/rejected/cancelled/pending_return/returned'],
            ['returned_at','TEXT','歸還時間'],['reject_reason','TEXT','拒絕原因'],
            ['notified_start','INTEGER','開始提醒已發'],['notified_end','INTEGER','結束提醒已發'],
            ['created_at','TEXT','建立時間'],
        ],columns=['欄位','型別','說明']))


# ═══════════════════════════════════════════════════════════════
#  主程式
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(page_title='土木館預約系統', page_icon='🏛️',
                       layout='wide', initial_sidebar_state='expanded')
    try:
        init_db()
    except Exception as e:
        st.error(f"資料庫初始化失敗：{e}")
        return
    start_reminder_thread()

    if 'user' not in st.session_state:
        page_login(); return

    user     = st.session_state.user
    is_adm   = user['role'] == 'admin'
    is_staff = user['role'] in ('admin','staff')

    with st.sidebar:
        st.markdown(f"### 👤 {user['fullname']}")
        st.caption(ROLE_LABEL.get(user['role'],'—'))
        if user.get('department'):
            st.caption(f"🏢 {user.get('identity','')}　{user['department']}")
        st.caption(f"🪪 {user.get('student_id','')}")
        st.divider()

        if is_staff:
            tot = (len(pending_room_reviews()) + len(pending_equip_reviews()) +
                   len(pending_room_returns()) + len(pending_equip_returns()))
            if tot: st.warning(f'🔔 {tot} 筆待處理')

        if is_blacklisted(user['user_id']):
            st.error('⛔ 黑名單中')

        nav = {
            '🔍 查詢時間':   'query',
            '📋 預約/借用':  'book',
            '📚 我的紀錄':   'records',
            '👤 個人資料':   'profile',
            '📊 ER Model':   'er',
        }
        if is_staff: nav['🏢 系辦管理台'] = 'staff'
        if is_adm:   nav['⚙️ 管理員後台'] = 'admin'

        if 'page' not in st.session_state:
            st.session_state.page = 'query'

        for label, key in nav.items():
            if st.button(label, use_container_width=True,
                         type='primary' if st.session_state.page==key else 'secondary'):
                st.session_state.page = key; st.rerun()

        st.divider()
        if st.button('🚪 登出', use_container_width=True):
            st.session_state.clear(); st.rerun()

    page_map = {
        'query':   page_query,
        'book':    page_book,
        'records': page_records,
        'profile': page_profile,
        'er':      page_er,
        'staff':   page_staff,
        'admin':   page_admin,
    }
    page_map.get(st.session_state.get('page','query'), page_query)()


if __name__ == '__main__':
    main()
