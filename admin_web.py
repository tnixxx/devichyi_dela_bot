import secrets
from datetime import datetime, timedelta

STAR_TO_USD = 0.013
USD_TO_RUB = 89.0
STAR_TO_RUB = STAR_TO_USD * USD_TO_RUB  # ≈ 1.16 руб за звезду

from fastapi import FastAPI, Form, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from database import create_pool
import hashlib
import base64
import os
from dotenv import load_dotenv
import subprocess
import csv
from io import StringIO
import re

load_dotenv()

app = FastAPI()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
if not ADMIN_PASSWORD_HASH:
    raise RuntimeError("ADMIN_PASSWORD_HASH not set in .env file")

SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
_signer = URLSafeTimedSerializer(SESSION_SECRET)
SESSION_MAX_AGE = 60 * 60 * 8  # 8 часов

def make_session_token() -> str:
    return _signer.dumps("admin")

def verify_session_token(token: str) -> bool:
    try:
        _signer.loads(token, max_age=SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False

def get_session(request: Request):
    token = request.cookies.get("session")
    if not token or not verify_session_token(token):
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return token

def make_csrf_token(session_token: str) -> str:
    import hmac
    return hmac.new(SESSION_SECRET.encode(), session_token.encode(), "sha256").hexdigest()[:32]

async def check_csrf(request: Request):
    session = request.cookies.get("session", "")
    form = await request.form()
    token = form.get("csrf_token", "")
    import hmac
    expected = hmac.new(SESSION_SECRET.encode(), session.encode(), "sha256").hexdigest()[:32]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="CSRF validation failed")

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        method_part, salt_b64, key_b64 = stored_hash.split('$')
        parts = method_part.split(':')
        iterations = int(parts[2])
        salt = base64.b64decode(salt_b64)
        key = base64.b64decode(key_b64)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
        return new_key == key
    except Exception:
        return False

def validate_phone(phone: str) -> bool:
    if not phone:
        return True
    pattern = r'^(\+7|8)?[\s\-]?\(?[0-9]{3}\)?[\s\-]?[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{2}$'
    return bool(re.match(pattern, phone))

@app.on_event("startup")
async def startup():
    app.state.pool = await create_pool()
    async with app.state.pool.acquire() as conn:
        await conn.execute("ALTER TABLE masters ADD COLUMN IF NOT EXISTS phone TEXT")
        await conn.execute("ALTER TABLE masters ADD COLUMN IF NOT EXISTS notes TEXT")
        await conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_method TEXT")
        await conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_status TEXT DEFAULT 'pending'")
        await conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS total_price DECIMAL(10,2)")
        await conn.execute("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()")

@app.on_event("shutdown")
async def shutdown():
    await app.state.pool.close()

@app.get("/")
async def root():
    return RedirectResponse(url="/admin")

# ─────────────────────────────────────────────────────────────────────────────
# BASE TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────
BASE_HTML = """<!DOCTYPE html>
<html lang="ru" data-theme="light" data-bs-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Девичьи дела — {title}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{
  --bg:#f0f2f8;--sb:#191c2e;--sb-t:#8896b3;
  --sb-abg:rgba(101,91,240,.16);--sb-abar:#655bf0;
  --card:#fff;--cb:#e4e6f0;--tx:#1a1d2e;--mu:#6b7280;
  --bdr:#e4e6f0;--acc:#655bf0;--acc2:#4f46e5;
  --sh:0 1px 3px rgba(0,0,0,.06);--sh2:0 4px 16px rgba(0,0,0,.09);
  --inp:#f7f8fc;
}
[data-theme="dark"]{
  --bg:#0d0f1a;--sb:#111320;--card:#181a2b;--cb:#242640;
  --tx:#e4e8f8;--mu:#7b82a8;--bdr:#242640;
  --sh:0 1px 4px rgba(0,0,0,.5);--sh2:0 4px 20px rgba(0,0,0,.6);
  --inp:#111320;
}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:var(--bg);color:var(--tx);display:flex;min-height:100vh;font-size:14px}

/* SIDEBAR */
.sb{width:228px;min-height:100vh;background:var(--sb);position:fixed;top:0;left:0;
    display:flex;flex-direction:column;z-index:200;transition:transform .25s}
.sb-brand{padding:18px 16px 14px;display:flex;align-items:center;gap:10px;
          border-bottom:1px solid rgba(255,255,255,.05);text-decoration:none}
.sb-logo{width:34px;height:34px;background:var(--acc);border-radius:9px;
         display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0}
.sb-name{font-size:13.5px;font-weight:700;color:#fff;line-height:1.2}
.sb-sub{font-size:10px;color:var(--sb-t)}
.nav-sec{padding:10px 0 2px}
.nav-lbl{padding:4px 16px 5px;font-size:9.5px;font-weight:700;letter-spacing:.1em;
         text-transform:uppercase;color:rgba(136,150,179,.4)}
.nav-a{display:flex;align-items:center;gap:9px;padding:8.5px 16px;color:var(--sb-t);
       text-decoration:none;font-size:13.5px;position:relative;transition:.15s}
.nav-a:hover{color:#fff;background:rgba(255,255,255,.04)}
.nav-a.on{color:#fff;background:var(--sb-abg)}
.nav-a.on::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
                  background:var(--sb-abar);border-radius:0 3px 3px 0}
.nav-a i{font-size:15px;width:18px;text-align:center;flex-shrink:0}
.sb-foot{margin-top:auto;padding:12px;border-top:1px solid rgba(255,255,255,.05);
         display:flex;flex-direction:column;gap:4px}
.th-btn{display:flex;align-items:center;gap:8px;padding:8px 10px;border:none;
        background:rgba(255,255,255,.05);color:var(--sb-t);border-radius:8px;
        cursor:pointer;font-size:13px;width:100%;transition:.15s}
.th-btn:hover{background:rgba(255,255,255,.1);color:#fff}

/* LAYOUT */
.main{margin-left:228px;flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{position:sticky;top:0;z-index:100;background:var(--card);
        border-bottom:1px solid var(--bdr);padding:0 24px;height:56px;
        display:flex;align-items:center;justify-content:space-between;box-shadow:var(--sh)}
.tb-title{font-size:15.5px;font-weight:600}
.pg{padding:22px 24px}

/* CARDS */
.card{background:var(--card)!important;border:1px solid var(--cb)!important;border-radius:12px;box-shadow:var(--sh)}
.card-header{background:transparent!important;border-bottom:1px solid var(--cb)!important;
             padding:12px 18px;font-weight:600;font-size:13.5px;color:var(--tx)}
.card-body{padding:18px}

/* KPI */
.kpi{background:var(--card);border:1px solid var(--cb);border-radius:12px;padding:18px;box-shadow:var(--sh);transition:.15s}
.kpi:hover{transform:translateY(-2px);box-shadow:var(--sh2)}
.kpi-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;
          justify-content:center;font-size:18px;margin-bottom:12px}
.kpi-val{font-size:26px;font-weight:700;line-height:1;margin-bottom:3px}
.kpi-lbl{font-size:11px;color:var(--mu);font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.kpi-sub{font-size:11.5px;color:var(--mu);margin-top:4px}
.kpi-purple .kpi-icon{background:rgba(101,91,240,.12);color:var(--acc)}
.kpi-purple .kpi-val{color:var(--acc)}
.kpi-green  .kpi-icon{background:rgba(16,185,129,.12);color:#10b981}
.kpi-green  .kpi-val{color:#10b981}
.kpi-blue   .kpi-icon{background:rgba(59,130,246,.12);color:#3b82f6}
.kpi-blue   .kpi-val{color:#3b82f6}
.kpi-amber  .kpi-icon{background:rgba(245,158,11,.12);color:#f59e0b}
.kpi-amber  .kpi-val{color:#f59e0b}
.kpi-red    .kpi-icon{background:rgba(239,68,68,.12);color:#ef4444}
.kpi-red    .kpi-val{color:#ef4444}

/* DATA TABLE */
.tbl-wrap{background:var(--card);border:1px solid var(--cb);border-radius:12px;box-shadow:var(--sh);overflow:hidden}
.table-responsive{overflow-x:auto}
.dt{width:100%;border-collapse:collapse}
.dt thead th{padding:10px 14px;font-size:10.5px;font-weight:700;text-transform:uppercase;
             letter-spacing:.07em;color:var(--mu);border-bottom:1px solid var(--bdr);
             white-space:nowrap;background:transparent}
.dt thead th a{color:var(--mu);text-decoration:none}
.dt thead th a:hover{color:var(--tx)}
.dt tbody td{padding:11px 14px;border-bottom:1px solid var(--bdr);color:var(--tx);
             font-size:13.5px;vertical-align:middle}
.dt tbody tr:last-child td{border-bottom:none}
.dt tbody tr:hover td{background:rgba(101,91,240,.03)}
[data-theme="dark"] .dt tbody tr:hover td{background:rgba(101,91,240,.08)}
.dt a{color:var(--acc);text-decoration:none}
.dt a:hover{text-decoration:underline}
.dt-toolbar{padding:13px 18px;display:flex;align-items:center;gap:10px;
            flex-wrap:wrap;border-bottom:1px solid var(--bdr)}

/* BADGES */
.sbadge{display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.s-pending{background:#fef3c7;color:#92400e}
.s-paid{background:#d1fae5;color:#065f46}
.s-completed{background:#dbeafe;color:#1e40af}
.s-cancelled{background:#fee2e2;color:#991b1b}
.s-active{background:#d1fae5;color:#065f46}
.s-blocked{background:#fee2e2;color:#991b1b}
[data-theme="dark"] .s-pending{background:rgba(251,191,36,.12);color:#fbbf24}
[data-theme="dark"] .s-paid{background:rgba(74,222,128,.12);color:#4ade80}
[data-theme="dark"] .s-completed{background:rgba(96,165,250,.12);color:#60a5fa}
[data-theme="dark"] .s-cancelled{background:rgba(248,113,113,.12);color:#f87171}
[data-theme="dark"] .s-active{background:rgba(74,222,128,.12);color:#4ade80}
[data-theme="dark"] .s-blocked{background:rgba(248,113,113,.12);color:#f87171}

/* FILTER / PERIOD BAR */
.filter-bar{background:var(--card);border:1px solid var(--cb);border-radius:12px;
            padding:14px 18px;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.period-bar{background:var(--card);border:1px solid var(--cb);border-radius:12px;
            padding:12px 18px;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}

/* FORMS */
.form-control,.form-select{background:var(--inp)!important;border-color:var(--bdr)!important;color:var(--tx)!important;border-radius:8px!important}
.form-control:focus,.form-select:focus{border-color:var(--acc)!important;
  box-shadow:0 0 0 3px rgba(101,91,240,.15)!important;background:var(--card)!important}
label,.form-label{color:var(--mu);font-size:12.5px;font-weight:500}

/* BUTTONS */
.btn{border-radius:8px;font-size:13px}
.btn-sm{font-size:12px;padding:4px 10px;border-radius:6px}
.btn-primary{background:var(--acc)!important;border-color:var(--acc)!important;color:#fff!important}
.btn-primary:hover{background:var(--acc2)!important;border-color:var(--acc2)!important}
.btn-outline-primary{color:var(--acc)!important;border-color:var(--acc)!important}
.btn-outline-primary:hover{background:var(--acc)!important;color:#fff!important}
.btn-outline-secondary{color:var(--mu)!important;border-color:var(--bdr)!important}
.btn-outline-secondary:hover{background:var(--bdr)!important;color:var(--tx)!important}

/* ACTION LINKS */
.act{display:inline-flex;align-items:center;gap:3px;padding:3px 9px;border-radius:6px;
     font-size:11.5px;text-decoration:none;font-weight:500;transition:.15s;white-space:nowrap}
.act-edit{background:rgba(101,91,240,.1);color:var(--acc)}
.act-edit:hover{background:var(--acc);color:#fff}
.act-del{background:rgba(239,68,68,.1);color:#ef4444}
.act-del:hover{background:#ef4444;color:#fff}
.act-ok{background:rgba(16,185,129,.1);color:#059669}
.act-ok:hover{background:#059669;color:#fff}
.act-sec{background:rgba(107,114,128,.1);color:#6b7280}
.act-sec:hover{background:#6b7280;color:#fff}

/* PAGE HEADER */
.ph{margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.ph h2{font-size:20px;font-weight:700;margin:0}

/* MODALS */
.modal-content{background:var(--card)!important;border-color:var(--cb)!important;color:var(--tx)!important}
.modal-header{border-bottom-color:var(--bdr)!important}
.modal-footer{border-top-color:var(--bdr)!important}
[data-theme="dark"] .btn-close{filter:invert(1)}

/* LOGS */
#logContent{background:var(--inp);color:var(--tx);border:1px solid var(--bdr)!important;
            border-radius:8px;padding:14px;font-size:12px;height:500px;overflow-y:scroll}

/* MOBILE */
.sb-ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:190}
@media(max-width:860px){
  .sb{transform:translateX(-100%)}
  .sb.show{transform:none}
  .sb-ov.show{display:block}
  .main{margin-left:0}
  .pg{padding:14px}
  .topbar{padding:0 14px}
}
</style>
<script>(function(){var t=localStorage.getItem('theme')||'light';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-bs-theme',t);})();</script>
</head>
<body>
<div class="sb-ov" id="sbOv" onclick="closeSB()"></div>

<aside class="sb" id="sidebar">
  <a href="/admin" class="sb-brand">
    <div class="sb-logo">💅</div>
    <div><div class="sb-name">Девичьи дела</div><div class="sb-sub">Администрирование</div></div>
  </a>
  <div class="nav-sec">
    <div class="nav-lbl">Аналитика</div>
    <a href="/admin" class="nav-a {p_dashboard}"><i class="bi bi-grid-1x2-fill"></i> Дашборд</a>
    <a href="/admin/finance" class="nav-a {p_finance}"><i class="bi bi-bar-chart-fill"></i> Финансы</a>
    <a href="/admin/analytics" class="nav-a {p_analytics}"><i class="bi bi-person-lines-fill"></i> Поведение</a>
  </div>
  <div class="nav-sec">
    <div class="nav-lbl">Управление</div>
    <a href="/admin/bookings" class="nav-a {p_bookings}"><i class="bi bi-calendar2-check-fill"></i> Брони</a>
    <a href="/admin/masters" class="nav-a {p_masters}"><i class="bi bi-people-fill"></i> Мастера</a>
    <a href="/admin/workspaces" class="nav-a {p_workspaces}"><i class="bi bi-building-fill"></i> Рабочие места</a>
  </div>
  <div class="nav-sec">
    <div class="nav-lbl">Система</div>
    <a href="/admin/mailings" class="nav-a {p_mailings}"><i class="bi bi-megaphone-fill"></i> Рассылки</a>
    <a href="/admin/logs" class="nav-a {p_logs}"><i class="bi bi-terminal-fill"></i> Логи</a>
  </div>
  <div class="sb-foot">
    <button class="th-btn" onclick="toggleTheme()">
      <i id="themeIcon" class="bi bi-moon-stars-fill"></i>
      <span id="themeLabel">Тёмная тема</span>
    </button>
    <form method="post" action="/logout" style="margin:0">
      <button type="submit" class="nav-a" style="color:#f87171;padding:8px 10px;border-radius:8px;margin:0;border:none;background:transparent;width:100%;cursor:pointer">
        <i class="bi bi-box-arrow-left"></i> Выйти
      </button>
    </form>
  </div>
</aside>

<div class="main">
  <header class="topbar">
    <div class="d-flex align-items-center gap-2">
      <button class="btn btn-sm d-lg-none p-1" onclick="openSB()" style="background:transparent;border:none;color:var(--mu)">
        <i class="bi bi-list" style="font-size:20px"></i>
      </button>
      <span class="tb-title">{title}</span>
    </div>
  </header>
  <div class="pg">{content}</div>
</div>

<!-- MODALS -->
<div class="modal fade" id="masterInfoModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Информация о мастере</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <p><strong>Имя:</strong> <span id="modalMasterName"></span></p>
      <p><strong>Telegram ID:</strong> <span id="modalMasterTelegram"></span></p>
      <p><strong>Телефон:</strong> <span id="modalMasterPhone"></span></p>
      <p><strong>Заметки:</strong> <span id="modalMasterNotes"></span></p>
      <p><strong>Статус:</strong> <span id="modalMasterStatus"></span></p>
      <input type="hidden" id="modalMasterId">
      <button id="modalBlockBtn" class="btn btn-warning btn-sm" onclick="blockMaster(document.getElementById('modalMasterId').value)">Заблокировать</button>
      <button id="modalUnblockBtn" class="btn btn-success btn-sm" onclick="unblockMaster(document.getElementById('modalMasterId').value)">Разблокировать</button>
    </div>
  </div></div>
</div>

<div class="modal fade" id="editMasterModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Редактировать мастера</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <input type="hidden" id="editMasterId">
      <div class="mb-3"><label class="form-label">Имя</label><input type="text" id="editMasterName" class="form-control"></div>
      <div class="mb-3"><label class="form-label">Телефон</label><input type="text" id="editMasterPhone" class="form-control"></div>
      <div class="mb-3"><label class="form-label">Заметки</label><textarea id="editMasterNotes" class="form-control" rows="3"></textarea></div>
      <button class="btn btn-primary" onclick="saveMasterEdit()">Сохранить</button>
    </div>
  </div></div>
</div>

<div class="modal fade" id="addMasterModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Добавить мастера</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <form action="/admin/masters/add" method="post" onsubmit="return validatePhoneForm()">
        <div class="mb-3"><label class="form-label">Имя</label><input type="text" name="full_name" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Телефон</label><input type="text" name="phone" class="form-control"></div>
        <div class="mb-3"><label class="form-label">Заметки</label><textarea name="notes" class="form-control" rows="3"></textarea></div>
        <button type="submit" class="btn btn-primary">Сохранить</button>
        <button type="button" class="btn btn-outline-secondary ms-2" data-bs-dismiss="modal">Отмена</button>
      </form>
    </div>
  </div></div>
</div>

<div class="modal fade" id="addBookingModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Добавить бронь вручную</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <form action="/admin/bookings/add" method="post">
        <div class="mb-3"><label class="form-label">Мастер</label><select name="master_id" class="form-control" required>___MASTER_OPTIONS___</select></div>
        <div class="mb-3"><label class="form-label">Место</label><select name="workspace_id" class="form-control" required>___WORKSPACE_OPTIONS___</select></div>
        <div class="mb-3"><label class="form-label">Начало</label><input type="datetime-local" name="start_time" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Конец</label><input type="datetime-local" name="end_time" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Стоимость (руб)</label><input type="number" step="0.01" name="total_price" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Статус</label>
          <select name="status" class="form-control">
            <option value="paid">Оплачено</option><option value="pending">Ожидает оплаты</option>
            <option value="cancelled">Отменена</option><option value="completed">Завершена</option>
          </select>
        </div>
        <button type="submit" class="btn btn-primary">Сохранить</button>
        <button type="button" class="btn btn-outline-secondary ms-2" data-bs-dismiss="modal">Отмена</button>
      </form>
    </div>
  </div></div>
</div>

<div class="modal fade" id="editBookingModal" tabindex="-1">
  <div class="modal-dialog"><div class="modal-content">
    <div class="modal-header"><h5 class="modal-title">Редактировать бронь</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
    <div class="modal-body">
      <form id="editBookingForm" method="post">
        <div class="mb-3"><label class="form-label">Мастер</label><select name="master_id" class="form-control" required>___MASTER_OPTIONS___</select></div>
        <div class="mb-3"><label class="form-label">Место</label><select name="workspace_id" class="form-control" required>___WORKSPACE_OPTIONS___</select></div>
        <div class="mb-3"><label class="form-label">Начало</label><input type="datetime-local" name="start_time" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Конец</label><input type="datetime-local" name="end_time" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Стоимость</label><input type="number" step="0.01" name="total_price" class="form-control" required></div>
        <div class="mb-3"><label class="form-label">Статус</label>
          <select name="status" class="form-control">
            <option value="paid">Оплачено</option><option value="pending">Ожидает оплаты</option>
            <option value="cancelled">Отменена</option><option value="completed">Завершена</option>
          </select>
        </div>
        <input type="hidden" name="booking_id" id="editBookingId">
        <button type="submit" class="btn btn-primary">Сохранить</button>
        <button type="button" class="btn btn-outline-secondary ms-2" data-bs-dismiss="modal">Отмена</button>
      </form>
    </div>
  </div></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const _csrf='{csrf_token}';
document.addEventListener('DOMContentLoaded',function(){
  document.querySelectorAll('form[method="post"],form[method="POST"]').forEach(function(f){
    if(!f.querySelector('input[name="csrf_token"]')){
      var h=document.createElement('input');
      h.type='hidden';h.name='csrf_token';h.value=_csrf;f.appendChild(h);
    }
  });
});
function applyTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  document.documentElement.setAttribute('data-bs-theme',t);
  localStorage.setItem('theme',t);
  var ic=document.getElementById('themeIcon'),lb=document.getElementById('themeLabel');
  if(t==='dark'){ic.className='bi bi-sun-fill';lb.textContent='Светлая тема';}
  else{ic.className='bi bi-moon-stars-fill';lb.textContent='Тёмная тема';}
}
function toggleTheme(){applyTheme(localStorage.getItem('theme')==='dark'?'light':'dark');}
document.addEventListener('DOMContentLoaded',function(){applyTheme(localStorage.getItem('theme')||'light');});

function openSB(){document.getElementById('sidebar').classList.add('show');document.getElementById('sbOv').classList.add('show');}
function closeSB(){document.getElementById('sidebar').classList.remove('show');document.getElementById('sbOv').classList.remove('show');}

async function showMasterInfo(id){
  const d=await(await fetch(`/admin/master_info/${id}`)).json();
  document.getElementById('modalMasterId').value=id;
  document.getElementById('modalMasterName').innerText=d.full_name||'—';
  document.getElementById('modalMasterTelegram').innerText=d.telegram_id;
  document.getElementById('modalMasterPhone').innerText=d.phone||'—';
  document.getElementById('modalMasterNotes').innerText=d.notes||'—';
  document.getElementById('modalMasterStatus').innerHTML=d.is_blocked
    ?'<span class="sbadge s-blocked">Заблокирован</span>'
    :'<span class="sbadge s-active">Активен</span>';
  document.getElementById('modalBlockBtn').style.display=d.is_blocked?'none':'inline-block';
  document.getElementById('modalUnblockBtn').style.display=d.is_blocked?'inline-block':'none';
  new bootstrap.Modal(document.getElementById('masterInfoModal')).show();
}
async function blockMaster(id){await fetch(`/admin/masters/block/${id}`);location.reload();}
async function unblockMaster(id){await fetch(`/admin/masters/unblock/${id}`);location.reload();}
async function editMaster(id){
  const d=await(await fetch(`/admin/master_info/${id}`)).json();
  document.getElementById('editMasterId').value=id;
  document.getElementById('editMasterName').value=d.full_name||'';
  document.getElementById('editMasterPhone').value=d.phone||'';
  document.getElementById('editMasterNotes').value=d.notes||'';
  new bootstrap.Modal(document.getElementById('editMasterModal')).show();
}
async function saveMasterEdit(){
  const id=document.getElementById('editMasterId').value;
  const full_name=document.getElementById('editMasterName').value;
  const phone=document.getElementById('editMasterPhone').value;
  const notes=document.getElementById('editMasterNotes').value;
  if(phone&&!/^(\\+7|8)?[\\s\\-]?\\(?[0-9]{3}\\)?[\\s\\-]?[0-9]{3}[\\s\\-]?[0-9]{2}[\\s\\-]?[0-9]{2}$/.test(phone)){
    alert('Введите корректный российский номер телефона');return;
  }
  const r=await fetch(`/admin/masters/edit_ajax/${id}`,{method:'POST',
    headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams({full_name,phone,notes,csrf_token:_csrf})});
  if(r.ok)location.reload();else alert('Ошибка при сохранении');
}

async function editBooking(id){
  const d=await(await fetch(`/admin/bookings/get/${id}`)).json();
  document.getElementById('editBookingId').value=id;
  document.querySelector('#editBookingModal select[name="master_id"]').value=d.master_id;
  document.querySelector('#editBookingModal select[name="workspace_id"]').value=d.workspace_id;
  document.querySelector('#editBookingModal input[name="start_time"]').value=d.start_time.slice(0,16);
  document.querySelector('#editBookingModal input[name="end_time"]').value=d.end_time.slice(0,16);
  document.querySelector('#editBookingModal input[name="total_price"]').value=d.total_price;
  document.querySelector('#editBookingModal select[name="status"]').value=d.status;
  new bootstrap.Modal(document.getElementById('editBookingModal')).show();
}
document.addEventListener('DOMContentLoaded',function(){
  var f=document.getElementById('editBookingForm');
  if(f)f.onsubmit=async function(e){
    e.preventDefault();
    var id=document.getElementById('editBookingId').value;
    var r=await fetch(`/admin/bookings/edit/${id}`,{method:'POST',body:new FormData(f)});
    if(r.ok)location.reload();else alert('Ошибка при редактировании');
  };
});

function fmtPhone(v){
  var d=v.replace(/\\D/g,'');
  if(!d.length)return'';
  if(d.startsWith('8'))d='7'+d.slice(1);
  if(!d.startsWith('7'))d='7'+d;
  if(d.length>11)d=d.slice(0,11);
  if(d.length===11)return`+7 (${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7,9)}-${d.slice(9,11)}`;
  var p='+7';
  if(d.length>1)p+=` (${d.slice(1,Math.min(4,d.length))}`;
  if(d.length>4)p+=`) ${d.slice(4,Math.min(7,d.length))}`;
  if(d.length>7)p+=`-${d.slice(7,Math.min(9,d.length))}`;
  if(d.length>9)p+=`-${d.slice(9,11)}`;
  return p;
}
function attachPhone(el){
  if(!el)return;
  el.addEventListener('input',function(){
    var s=this.selectionStart,raw=this.value,fmt=fmtPhone(raw);
    if(fmt!==raw){this.value=fmt;this.setSelectionRange(s+fmt.length-raw.length,s+fmt.length-raw.length);}
  });
  el.addEventListener('blur',function(){if(this.value.trim())this.value=fmtPhone(this.value);});
}
function validatePhoneForm(){
  var f=document.querySelector('#addMasterModal input[name="phone"]');
  if(!f)return true;
  var v=f.value.trim();
  if(!v)return true;
  if(!/^(\\+7|8)?[\\s\\-]?\\(?[0-9]{3}\\)?[\\s\\-]?[0-9]{3}[\\s\\-]?[0-9]{2}[\\s\\-]?[0-9]{2}$/.test(v)){
    alert('Введите корректный российский номер телефона');return false;
  }
  return true;
}
document.addEventListener('DOMContentLoaded',function(){
  attachPhone(document.querySelector('#addMasterModal input[name="phone"]'));
  attachPhone(document.getElementById('editMasterPhone'));
  var am=document.getElementById('addMasterModal');
  if(am)am.addEventListener('shown.bs.modal',function(){attachPhone(document.querySelector('#addMasterModal input[name="phone"]'));});
  var em=document.getElementById('editMasterModal');
  if(em)em.addEventListener('shown.bs.modal',function(){
    var f=document.getElementById('editMasterPhone');
    attachPhone(f);if(f&&f.value)f.value=fmtPhone(f.value);
  });
});
</script>
</body>
</html>
"""

_ALL_PAGES = ["dashboard", "finance", "analytics", "bookings", "masters", "workspaces", "mailings", "logs"]

def render(title: str, content: str,
           masters_options_html: str = "", workspaces_options_html: str = "",
           page: str = "", auth_token: str = "") -> HTMLResponse:
    csrf = make_csrf_token(auth_token) if auth_token else ""
    html = BASE_HTML.replace("{title}", title).replace("{content}", content)
    html = html.replace("{csrf_token}", csrf)
    for p in _ALL_PAGES:
        html = html.replace(f"{{p_{p}}}", "on" if page == p else "")
    html = html.replace("___MASTER_OPTIONS___", masters_options_html)
    html = html.replace("___WORKSPACE_OPTIONS___", workspaces_options_html)
    return HTMLResponse(html)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def admin_index(auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        counts = await conn.fetch("SELECT status, COUNT(*) FROM bookings GROUP BY status")
        status_counts = {r['status']: r['count'] for r in counts}
        top = await conn.fetch("""
            SELECT w.name, COUNT(b.id) as count
            FROM bookings b JOIN workspaces w ON b.workspace_id = w.id
            GROUP BY w.id ORDER BY count DESC LIMIT 5
        """)
        last_14_days = []
        for i in range(13, -1, -1):
            day = datetime.now().date() - timedelta(days=i)
            cnt = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE DATE(start_time) = $1", day)
            last_14_days.append({"date": day.strftime("%d.%m"), "count": cnt})
        pending   = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='pending'")
        paid      = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='paid'")
        completed = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='completed'")
        cancelled = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='cancelled'")
        revenue_stars = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE payment_method='stars' AND status IN ('paid','completed')")
        revenue_rub   = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE (payment_method IS NULL OR payment_method!='stars') AND status IN ('paid','completed')")

    top_html = "".join(
        f'<div class="d-flex align-items-center justify-content-between py-1 border-bottom">'
        f'<span style="font-size:13.5px">{row["name"]}</span>'
        f'<span class="sbadge s-completed">{row["count"]} броней</span></div>'
        for row in top
    ) or '<span class="text-muted">Нет данных</span>'

    content = f"""
<div class="ph"><h2>Дашборд</h2></div>
<div class="row g-3 mb-4">
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-amber">
      <div class="kpi-icon"><i class="bi bi-hourglass-split"></i></div>
      <div class="kpi-val">{pending}</div><div class="kpi-lbl">Ожидают оплаты</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-green">
      <div class="kpi-icon"><i class="bi bi-check-circle-fill"></i></div>
      <div class="kpi-val">{paid}</div><div class="kpi-lbl">Оплачено</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-blue">
      <div class="kpi-icon"><i class="bi bi-flag-fill"></i></div>
      <div class="kpi-val">{completed}</div><div class="kpi-lbl">Завершено</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-red">
      <div class="kpi-icon"><i class="bi bi-x-circle-fill"></i></div>
      <div class="kpi-val">{cancelled}</div><div class="kpi-lbl">Отменено</div>
    </div>
  </div>
</div>
<div class="row g-3 mb-4">
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-green">
      <div class="kpi-icon"><i class="bi bi-star-fill"></i></div>
      <div class="kpi-val">⭐ {int(revenue_stars)}</div><div class="kpi-lbl">Выручка Stars</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-purple">
      <div class="kpi-icon"><i class="bi bi-currency-exchange"></i></div>
      <div class="kpi-val">{int(revenue_rub)} ₽</div><div class="kpi-lbl">Выручка (руб)</div>
    </div>
  </div>
  <div class="col-xl-6">
    <div class="card h-100">
      <div class="card-header"><i class="bi bi-trophy me-1"></i>Загрузка мест (топ‑5)</div>
      <div class="card-body">{top_html}</div>
    </div>
  </div>
</div>
<div class="row g-3 mb-3">
  <div class="col-md-4">
    <div class="card">
      <div class="card-header">Статусы броней</div>
      <div class="card-body"><canvas id="statusChart" style="max-height:210px"></canvas></div>
    </div>
  </div>
  <div class="col-md-8">
    <div class="card">
      <div class="card-header">Топ рабочих мест</div>
      <div class="card-body"><canvas id="topChart" style="max-height:210px"></canvas></div>
    </div>
  </div>
</div>
<div class="row g-3">
  <div class="col-12">
    <div class="card">
      <div class="card-header">Брони по дням (14 дней)</div>
      <div class="card-body"><canvas id="dailyChart" style="max-height:140px"></canvas></div>
    </div>
  </div>
</div>
<script>
(function(){{
  var dk=document.documentElement.getAttribute('data-theme')==='dark';
  var gc=dk?'rgba(255,255,255,.06)':'rgba(0,0,0,.05)';
  var tc=dk?'#7b82a8':'#6b7280';
  new Chart(document.getElementById('statusChart'),{{type:'doughnut',
    data:{{labels:{[s for s in status_counts.keys()]},datasets:[{{data:{[status_counts[s] for s in status_counts.keys()]},
    backgroundColor:['#f59e0b','#10b981','#3b82f6','#ef4444'],borderWidth:0}}]}},
    options:{{responsive:true,maintainAspectRatio:false,cutout:'62%',
      plugins:{{legend:{{position:'bottom',labels:{{color:tc,boxWidth:11,padding:10}}}}}}}}
  }});
  new Chart(document.getElementById('topChart'),{{type:'bar',
    data:{{labels:{[row['name'] for row in top]},datasets:[{{label:'Брони',
    data:{[row['count'] for row in top]},backgroundColor:'rgba(101,91,240,.75)',borderRadius:6,borderWidth:0}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      scales:{{y:{{beginAtZero:true,grid:{{color:gc}},ticks:{{color:tc}}}},x:{{grid:{{display:false}},ticks:{{color:tc}}}}}},
      plugins:{{legend:{{display:false}}}}}}
  }});
  new Chart(document.getElementById('dailyChart'),{{type:'line',
    data:{{labels:{[d['date'] for d in last_14_days]},datasets:[{{label:'Брони',
    data:{[d['count'] for d in last_14_days]},borderColor:'#10b981',
    backgroundColor:'rgba(16,185,129,.1)',tension:.3,fill:true,pointRadius:3,pointBackgroundColor:'#10b981'}}]}},
    options:{{responsive:true,maintainAspectRatio:false,
      scales:{{y:{{beginAtZero:true,grid:{{color:gc}},ticks:{{color:tc}}}},x:{{grid:{{display:false}},ticks:{{color:tc}}}}}},
      plugins:{{legend:{{display:false}}}}}}
  }});
}})();
</script>
"""
    return render("Дашборд", content, page="dashboard", auth_token=auth)


@app.get("/health")
async def health_check():
    return JSONResponse({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# WORKSPACES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/workspaces", response_class=HTMLResponse)
async def list_workspaces(request: Request, auth=Depends(get_session)):
    sort = request.query_params.get('sort', 'id')
    order = request.query_params.get('order', 'asc')
    name_filter = request.query_params.get('name', '').strip()
    category_filter = request.query_params.get('category', '')

    if order not in ('asc', 'desc'):
        order = 'asc'
    allowed_sort = ['id', 'name', 'category', 'price_per_hour', 'price_per_hour_stars',
                    'price_per_day', 'price_per_day_stars', 'price_per_multi_day', 'price_per_multi_day_stars']
    if sort not in allowed_sort:
        sort = 'id'

    query = "SELECT * FROM workspaces WHERE 1=1"
    params = []
    if name_filter:
        query += " AND name ILIKE $" + str(len(params)+1)
        params.append(f"%{name_filter}%")
    if category_filter:
        query += " AND category = $" + str(len(params)+1)
        params.append(category_filter)
    query += f" ORDER BY {sort} {order}"

    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    def sl(field):
        o = 'desc' if sort == field and order == 'asc' else 'asc'
        return f"/admin/workspaces?sort={field}&order={o}&name={name_filter}&category={category_filter}"

    table_rows = "".join(f"""
<tr>
  <td>{row['id']}</td><td><strong>{row['name']}</strong></td><td>{row['category']}</td>
  <td>{row['price_per_hour']}</td><td>{row['price_per_hour_stars'] or 0}</td>
  <td>{row['price_per_day']}</td><td>{row['price_per_day_stars'] or 0}</td>
  <td>{row['price_per_multi_day']}</td><td>{row['price_per_multi_day_stars'] or 0}</td>
  <td>
    <a href='/admin/workspaces/edit/{row['id']}' class='act act-edit me-1'>✏ Ред.</a>
    <a href='/admin/workspaces/delete/{row['id']}' class='act act-del' onclick="return confirm('Удалить?')">✕ Удалить</a>
  </td>
</tr>""" for row in rows)

    filter_html = f"""
<div class="filter-bar">
  <div><label class="form-label">Название</label><input type="text" id="nf" value="{name_filter}" class="form-control" placeholder="Поиск..." style="min-width:180px"></div>
  <div><label class="form-label">Категория</label>
    <select id="cf" class="form-control" style="min-width:180px">
      <option value="">Все</option>
      <option value="couch_202" {'selected' if category_filter=='couch_202' else ''}>🛏 Кушетки 202</option>
      <option value="dressing_202" {'selected' if category_filter=='dressing_202' else ''}>🎭 Гримерки 202</option>
      <option value="dressing_201" {'selected' if category_filter=='dressing_201' else ''}>🎭 Гримерки 201</option>
      <option value="hairdresser_201" {'selected' if category_filter=='hairdresser_201' else ''}>💺 Кресла 201</option>
    </select>
  </div>
  <div class="d-flex gap-2 align-self-end">
    <button class="btn btn-primary btn-sm" onclick="window.location.href='/admin/workspaces?name='+encodeURIComponent(document.getElementById('nf').value)+'&category='+document.getElementById('cf').value">Применить</button>
    <a href="/admin/workspaces" class="btn btn-outline-secondary btn-sm">Сбросить</a>
  </div>
</div>"""

    content = f"""
<div class="ph">
  <h2>Рабочие места</h2>
  <div class="d-flex gap-2">
    <a href='/admin/workspaces/add' class='btn btn-primary btn-sm'><i class="bi bi-plus-lg me-1"></i>Добавить</a>
    <a href='/admin/export/workspaces' class='btn btn-outline-secondary btn-sm'><i class="bi bi-download me-1"></i>CSV</a>
  </div>
</div>
{filter_html}
<div class="tbl-wrap">
  <div class="table-responsive">
    <table class="dt">
      <thead><tr>
        <th><a href="{sl('id')}">ID</a></th>
        <th><a href="{sl('name')}">Название</a></th>
        <th><a href="{sl('category')}">Категория</a></th>
        <th><a href="{sl('price_per_hour')}">Час (руб)</a></th>
        <th><a href="{sl('price_per_hour_stars')}">Час (⭐)</a></th>
        <th><a href="{sl('price_per_day')}">День (руб)</a></th>
        <th><a href="{sl('price_per_day_stars')}">День (⭐)</a></th>
        <th><a href="{sl('price_per_multi_day')}">Мультидень (руб)</a></th>
        <th><a href="{sl('price_per_multi_day_stars')}">Мультидень (⭐)</a></th>
        <th>Действия</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>"""
    return render("Рабочие места", content, page="workspaces", auth_token=auth)


@app.get("/admin/workspaces/add", response_class=HTMLResponse)
async def add_workspace_form(auth=Depends(get_session)):
    content = """
<div class="ph"><h2>Добавить место</h2></div>
<div class="card" style="max-width:640px">
  <div class="card-body">
    <form method="post">
      <div class="mb-3"><label class="form-label">Название</label><input type="text" name="name" class="form-control" required></div>
      <div class="mb-3"><label class="form-label">Описание</label><textarea name="description" class="form-control"></textarea></div>
      <div class="mb-3"><label class="form-label">Категория</label>
        <select name="category" class="form-control">
          <option value="couch_202">🛏 Кушетки 202</option>
          <option value="dressing_202">🎭 Гримерки 202</option>
          <option value="dressing_201">🎭 Гримерки 201</option>
          <option value="hairdresser_201">💺 Кресла 201</option>
        </select>
      </div>
      <div class="row g-3">
        <div class="col-md-6"><label class="form-label">Цена почасовая (руб)</label><input type="number" name="price_per_hour" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Цена почасовая (⭐)</label><input type="number" step="0.01" name="price_per_hour_stars" class="form-control" value="0"></div>
        <div class="col-md-6"><label class="form-label">Цена на день (руб)</label><input type="number" name="price_per_day" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Цена на день (⭐)</label><input type="number" step="0.01" name="price_per_day_stars" class="form-control" value="0"></div>
        <div class="col-md-6"><label class="form-label">Многодневная (руб/сутки)</label><input type="number" name="price_per_multi_day" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Многодневная (⭐)</label><input type="number" step="0.01" name="price_per_multi_day_stars" class="form-control" value="0"></div>
      </div>
      <div class="mb-3 mt-3"><label class="form-label">Фото 1 (file_id)</label><input type="text" name="image_url_1" class="form-control"></div>
      <div class="mb-3"><label class="form-label">Фото 2</label><input type="text" name="image_url_2" class="form-control"></div>
      <div class="mb-3"><label class="form-label">Фото 3</label><input type="text" name="image_url_3" class="form-control"></div>
      <button type="submit" class="btn btn-primary">Сохранить</button>
      <a href="/admin/workspaces" class="btn btn-outline-secondary ms-2">Отмена</a>
    </form>
  </div>
</div>"""
    return render("Добавить место", content, page="workspaces", auth_token=auth)


@app.post("/admin/workspaces/add")
async def add_workspace(
    name: str = Form(...), description: str = Form(""), category: str = Form(...),
    price_per_hour: int = Form(...), price_per_day: int = Form(...), price_per_multi_day: int = Form(...),
    price_per_hour_stars: float = Form(0), price_per_day_stars: float = Form(0),
    price_per_multi_day_stars: float = Form(0),
    image_url_1: str = Form(""), image_url_2: str = Form(""), image_url_3: str = Form(""),
    auth=Depends(get_session), _csrf=Depends(check_csrf)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO workspaces (name, description, category, price_per_hour, price_per_day,
            price_per_multi_day, price_per_hour_stars, price_per_day_stars, price_per_multi_day_stars,
            image_url_1, image_url_2, image_url_3)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        """, name, description, category, price_per_hour, price_per_day, price_per_multi_day,
           price_per_hour_stars, price_per_day_stars, price_per_multi_day_stars,
           image_url_1, image_url_2, image_url_3)
    return RedirectResponse(url="/admin/workspaces", status_code=303)


@app.get("/admin/workspaces/edit/{wid}", response_class=HTMLResponse)
async def edit_workspace_form(request: Request, wid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM workspaces WHERE id = $1", wid)
        if not row:
            raise HTTPException(404)
    content = f"""
<div class="ph"><h2>Редактировать место</h2></div>
<div class="card" style="max-width:640px">
  <div class="card-body">
    <form method="post">
      <div class="mb-3"><label class="form-label">Название</label><input type="text" name="name" class="form-control" value="{row['name']}" required></div>
      <div class="mb-3"><label class="form-label">Описание</label><textarea name="description" class="form-control">{row['description'] or ''}</textarea></div>
      <div class="mb-3"><label class="form-label">Категория</label>
        <select name="category" class="form-control">
          <option value="couch_202" {'selected' if row['category']=='couch_202' else ''}>🛏 Кушетки 202</option>
          <option value="dressing_202" {'selected' if row['category']=='dressing_202' else ''}>🎭 Гримерки 202</option>
          <option value="dressing_201" {'selected' if row['category']=='dressing_201' else ''}>🎭 Гримерки 201</option>
          <option value="hairdresser_201" {'selected' if row['category']=='hairdresser_201' else ''}>💺 Кресла 201</option>
        </select>
      </div>
      <div class="row g-3">
        <div class="col-md-6"><label class="form-label">Цена почасовая (руб)</label><input type="number" name="price_per_hour" class="form-control" value="{row['price_per_hour']}" required></div>
        <div class="col-md-6"><label class="form-label">Цена почасовая (⭐)</label><input type="number" step="0.01" name="price_per_hour_stars" class="form-control" value="{row['price_per_hour_stars'] or 0}"></div>
        <div class="col-md-6"><label class="form-label">Цена на день (руб)</label><input type="number" name="price_per_day" class="form-control" value="{row['price_per_day']}" required></div>
        <div class="col-md-6"><label class="form-label">Цена на день (⭐)</label><input type="number" step="0.01" name="price_per_day_stars" class="form-control" value="{row['price_per_day_stars'] or 0}"></div>
        <div class="col-md-6"><label class="form-label">Многодневная (руб/сутки)</label><input type="number" name="price_per_multi_day" class="form-control" value="{row['price_per_multi_day']}" required></div>
        <div class="col-md-6"><label class="form-label">Многодневная (⭐)</label><input type="number" step="0.01" name="price_per_multi_day_stars" class="form-control" value="{row['price_per_multi_day_stars'] or 0}"></div>
      </div>
      <div class="mb-3 mt-3"><label class="form-label">Фото 1</label><input type="text" name="image_url_1" class="form-control" value="{row['image_url_1'] or ''}"></div>
      <div class="mb-3"><label class="form-label">Фото 2</label><input type="text" name="image_url_2" class="form-control" value="{row['image_url_2'] or ''}"></div>
      <div class="mb-3"><label class="form-label">Фото 3</label><input type="text" name="image_url_3" class="form-control" value="{row['image_url_3'] or ''}"></div>
      <button type="submit" class="btn btn-primary">Сохранить</button>
      <a href="/admin/workspaces" class="btn btn-outline-secondary ms-2">Отмена</a>
    </form>
  </div>
</div>"""
    return render("Редактировать место", content, page="workspaces", auth_token=auth)


@app.post("/admin/workspaces/edit/{wid}")
async def edit_workspace(
    wid: int, name: str = Form(...), description: str = Form(""), category: str = Form(...),
    price_per_hour: int = Form(...), price_per_day: int = Form(...), price_per_multi_day: int = Form(...),
    price_per_hour_stars: float = Form(0), price_per_day_stars: float = Form(0),
    price_per_multi_day_stars: float = Form(0),
    image_url_1: str = Form(""), image_url_2: str = Form(""), image_url_3: str = Form(""),
    auth=Depends(get_session), _csrf=Depends(check_csrf)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            UPDATE workspaces SET name=$1,description=$2,category=$3,price_per_hour=$4,price_per_day=$5,
            price_per_multi_day=$6,price_per_hour_stars=$7,price_per_day_stars=$8,
            price_per_multi_day_stars=$9,image_url_1=$10,image_url_2=$11,image_url_3=$12
            WHERE id=$13
        """, name, description, category, price_per_hour, price_per_day, price_per_multi_day,
           price_per_hour_stars, price_per_day_stars, price_per_multi_day_stars,
           image_url_1, image_url_2, image_url_3, wid)
    return RedirectResponse(url="/admin/workspaces", status_code=303)


@app.get("/admin/workspaces/delete/{wid}")
async def delete_workspace(wid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("DELETE FROM workspaces WHERE id = $1", wid)
    return RedirectResponse(url="/admin/workspaces", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# BOOKINGS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/bookings", response_class=HTMLResponse)
async def list_bookings(request: Request, auth=Depends(get_session)):
    filter_text      = request.query_params.get('filter', '').strip()
    sort             = request.query_params.get('sort', 'created_at')
    order            = request.query_params.get('order', 'desc')
    status_filter    = request.query_params.get('status', '')
    workspace_id_filter = request.query_params.get('workspace_id', '')

    if order not in ('asc', 'desc'):
        order = 'desc'
    allowed_sort = ['created_at', 'start_time', 'end_time', 'workspace_name', 'type',
                    'hours', 'days', 'master_name', 'price', 'total_price', 'id', 'status']
    if sort not in allowed_sort:
        sort = 'created_at'

    sql_sort_map = {
        'created_at':    'b.created_at',
        'start_time':    'b.start_time',
        'end_time':      'b.end_time',
        'workspace_name':'w.name',
        'type':          "CASE WHEN b.start_time::date=b.end_time::date AND (b.end_time-b.start_time)<interval'11 hours' THEN 'Почасовая' WHEN b.start_time::date=b.end_time::date THEN 'На день' ELSE 'На несколько дней' END",
        'hours':         'EXTRACT(EPOCH FROM (b.end_time-b.start_time))/3600',
        'days':          'EXTRACT(DAY FROM (b.end_time-b.start_time))',
        'master_name':   'm.full_name',
        'price':         "CASE WHEN b.start_time::date=b.end_time::date AND (b.end_time-b.start_time)<interval'11 hours' THEN w.price_per_hour WHEN b.start_time::date=b.end_time::date THEN w.price_per_day ELSE w.price_per_multi_day END",
        'total_price':   'b.total_price',
        'id':            'b.id',
        'status':        'b.status',
    }
    order_by = f"{sql_sort_map[sort]} {order}"

    query = """
        SELECT b.*, m.full_name as master_name, m.id as master_id, w.name as workspace_name,
               w.price_per_hour, w.price_per_day, w.price_per_multi_day,
               CASE
                 WHEN b.start_time::date=b.end_time::date AND (b.end_time-b.start_time)<interval'11 hours' THEN 'Почасовая'
                 WHEN b.start_time::date=b.end_time::date AND (b.end_time-b.start_time)>=interval'11 hours' THEN 'На день'
                 ELSE 'На несколько дней'
               END as type,
               EXTRACT(EPOCH FROM (b.end_time-b.start_time))/3600 as hours,
               EXTRACT(DAY FROM (b.end_time-b.start_time)) as days
        FROM bookings b JOIN masters m ON b.master_id=m.id JOIN workspaces w ON b.workspace_id=w.id
        WHERE 1=1
    """
    params = []
    if filter_text:
        query += " AND (m.full_name ILIKE $1 OR w.name ILIKE $1 OR CAST(b.id AS TEXT) ILIKE $1)"
        params.append(f"%{filter_text}%")
    if status_filter:
        query += f" AND b.status = ${len(params)+1}"
        params.append(status_filter)
    if workspace_id_filter:
        query += f" AND b.workspace_id = ${len(params)+1}"
        params.append(int(workspace_id_filter))
    query += f" ORDER BY {order_by}"

    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        masters    = await conn.fetch("SELECT id, full_name FROM masters ORDER BY full_name")
        workspaces = await conn.fetch("SELECT id, name FROM workspaces ORDER BY name")

    master_options    = "".join(f"<option value='{m['id']}'>{m['full_name']}</option>" for m in masters)
    workspace_options = "".join(f"<option value='{w['id']}'>{w['name']}</option>" for w in workspaces)

    STATUS_BADGES = {
        'pending':   "<span class='sbadge s-pending'>Ожидает оплаты</span>",
        'paid':      "<span class='sbadge s-paid'>Оплачено</span>",
        'completed': "<span class='sbadge s-completed'>Завершена</span>",
        'cancelled': "<span class='sbadge s-cancelled'>Отменена</span>",
    }

    table_rows = ""
    for row in rows:
        created_fmt = row['created_at'].strftime('%d.%m.%y %H:%M') if row['created_at'] else ''
        start_fmt   = row['start_time'].strftime('%d.%m.%y %H:%M') if row['start_time'] else ''
        end_fmt     = row['end_time'].strftime('%d.%m.%y %H:%M') if row['end_time'] else ''
        status_html = STATUS_BADGES.get(row['status'], row['status'])
        if row['type'] == 'Почасовая':
            price_unit = row['price_per_hour'] or 0
        elif row['type'] == 'На день':
            price_unit = row['price_per_day'] or 0
        else:
            price_unit = row['price_per_multi_day'] or 0
        total_price = row['total_price'] if row['total_price'] else (
            price_unit * (row['hours'] or 0) if row['type'] == 'Почасовая' else price_unit * (row['days'] or 1))
        hours_val = int(row['hours']) if row['hours'] else 0
        days_val  = int(row['days']) if row['days'] else 1
        master_link = f"<a href='#' onclick='showMasterInfo({row['master_id']}); return false;'>{row['master_name']}</a>"
        actions = ""
        if row['status'] == 'pending':
            actions += f"<a href='/admin/bookings/confirm/{row['id']}' class='act act-ok me-1'>✓</a>"
        if row['status'] != 'cancelled':
            actions += f"<a href='/admin/bookings/cancel/{row['id']}' class='act act-del me-1'>✕</a>"
        if row['status'] != 'completed':
            actions += f"<a href='/admin/bookings/complete/{row['id']}' class='act act-sec'>⚑</a>"
        table_rows += f"""
<tr class='booking-row' ondblclick='editBooking({row['id']})'>
  <td style="color:var(--mu);font-size:12px">{created_fmt}</td>
  <td>{start_fmt}</td><td>{end_fmt}</td>
  <td><strong>{row['workspace_name']}</strong></td>
  <td><span style="font-size:12px;color:var(--mu)">{row['type']}</span></td>
  <td>{hours_val}ч</td><td>{days_val}д</td>
  <td>{master_link}</td>
  <td>{price_unit}</td><td><strong>{int(total_price) if total_price else '—'}</strong></td>
  <td style="color:var(--mu);font-size:12px">{row['id']}</td>
  <td>{status_html}</td>
  <td>{actions}</td>
</tr>"""

    def sl(field):
        o = 'desc' if sort == field and order == 'asc' else 'asc'
        return f"/admin/bookings?sort={field}&order={o}&filter={filter_text}&status={status_filter}&workspace_id={workspace_id_filter}"

    filter_html = f"""
<div class="filter-bar">
  <div><label class="form-label">Поиск</label><input type="text" id="fi" value="{filter_text}" class="form-control" placeholder="Мастер, место, ID…" style="min-width:180px"></div>
  <div><label class="form-label">Статус</label>
    <select id="sf" class="form-control">
      <option value="">Все</option>
      <option value="pending" {'selected' if status_filter=='pending' else ''}>Ожидает оплаты</option>
      <option value="paid" {'selected' if status_filter=='paid' else ''}>Оплачено</option>
      <option value="completed" {'selected' if status_filter=='completed' else ''}>Завершена</option>
      <option value="cancelled" {'selected' if status_filter=='cancelled' else ''}>Отменена</option>
    </select>
  </div>
  <div><label class="form-label">Место</label>
    <select id="wf" class="form-control">
      <option value="">Все</option>
      {''.join(f'<option value="{w["id"]}" {"selected" if workspace_id_filter==str(w["id"]) else ""}>{w["name"]}</option>' for w in workspaces)}
    </select>
  </div>
  <div class="d-flex gap-2 align-self-end">
    <button class="btn btn-primary btn-sm" onclick="window.location.href='/admin/bookings?filter='+encodeURIComponent(document.getElementById('fi').value)+'&status='+document.getElementById('sf').value+'&workspace_id='+document.getElementById('wf').value">Применить</button>
    <a href="/admin/bookings" class="btn btn-outline-secondary btn-sm">Сбросить</a>
    <button class="btn btn-primary btn-sm" data-bs-toggle="modal" data-bs-target="#addBookingModal"><i class="bi bi-plus-lg"></i></button>
    <a href="/admin/export/bookings" class="btn btn-outline-secondary btn-sm"><i class="bi bi-download"></i></a>
  </div>
</div>"""

    content = f"""
<div class="ph"><h2>Бронирования</h2></div>
{filter_html}
<div class="tbl-wrap">
  <div class="table-responsive">
    <table class="dt">
      <thead><tr>
        <th><a href="{sl('created_at')}">Создана</a></th>
        <th><a href="{sl('start_time')}">Начало</a></th>
        <th><a href="{sl('end_time')}">Конец</a></th>
        <th><a href="{sl('workspace_name')}">Место</a></th>
        <th><a href="{sl('type')}">Тип</a></th>
        <th><a href="{sl('hours')}">Часы</a></th>
        <th><a href="{sl('days')}">Дни</a></th>
        <th><a href="{sl('master_name')}">Мастер</a></th>
        <th><a href="{sl('price')}">Цена</a></th>
        <th><a href="{sl('total_price')}">Итого</a></th>
        <th><a href="{sl('id')}">ID</a></th>
        <th><a href="{sl('status')}">Статус</a></th>
        <th>Действия</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>"""
    return render("Брони", content, master_options, workspace_options, page="bookings", auth_token=auth)


@app.post("/admin/bookings/add")
async def add_booking_manual(master_id: int = Form(...), workspace_id: int = Form(...),
                             start_time: str = Form(...), end_time: str = Form(...),
                             total_price: float = Form(...), status: str = Form(...),
                             auth=Depends(get_session), _csrf=Depends(check_csrf)):
    start = datetime.fromisoformat(start_time)
    end   = datetime.fromisoformat(end_time)
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bookings (master_id, workspace_id, start_time, end_time, status,
            payment_method, payment_status, total_price, created_at)
            VALUES ($1,$2,$3,$4,$5,'manual','paid',$6,now())
        """, master_id, workspace_id, start, end, status, total_price)
    return RedirectResponse(url="/admin/bookings", status_code=303)


@app.get("/admin/bookings/confirm/{bid}")
async def confirm_booking(bid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='paid',payment_status='paid' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)


@app.get("/admin/bookings/cancel/{bid}")
async def cancel_booking(bid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='cancelled' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)


@app.get("/admin/bookings/complete/{bid}")
async def complete_booking(bid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='completed' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)


@app.get("/admin/bookings/get/{bid}")
async def get_booking_json(bid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id,master_id,workspace_id,start_time,end_time,total_price,status FROM bookings WHERE id=$1", bid)
        if not row:
            raise HTTPException(404)
        return JSONResponse({"id": row['id'], "master_id": row['master_id'],
                             "workspace_id": row['workspace_id'],
                             "start_time": row['start_time'].isoformat(),
                             "end_time": row['end_time'].isoformat(),
                             "total_price": float(row['total_price']),
                             "status": row['status']})


@app.post("/admin/bookings/edit/{bid}")
async def edit_booking(bid: int, master_id: int = Form(...), workspace_id: int = Form(...),
                       start_time: str = Form(...), end_time: str = Form(...),
                       total_price: float = Form(...), status: str = Form(...),
                       auth=Depends(get_session), _csrf=Depends(check_csrf)):
    start = datetime.fromisoformat(start_time)
    end   = datetime.fromisoformat(end_time)
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            UPDATE bookings SET master_id=$1,workspace_id=$2,start_time=$3,end_time=$4,total_price=$5,status=$6
            WHERE id=$7
        """, master_id, workspace_id, start, end, total_price, status, bid)
    return JSONResponse({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# MAILINGS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/mailings", response_class=HTMLResponse)
async def mailings_list(request: Request, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM mailings ORDER BY created_at DESC")

    STATUS_M = {
        'pending': "<span class='sbadge s-pending'>Ожидает</span>",
        'sent':    "<span class='sbadge s-paid'>Отправлена</span>",
        'failed':  "<span class='sbadge s-cancelled'>Ошибка</span>",
    }
    table_rows = "".join(f"""
<tr>
  <td>{row['id']}</td>
  <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row['text'][:80]}{'…' if len(row['text'])>80 else ''}</td>
  <td>{row['scheduled_at'].strftime('%d.%m.%Y %H:%M') if row['scheduled_at'] else '<span class="sbadge s-completed">Сейчас</span>'}</td>
  <td>{STATUS_M.get(row['status'], row['status'])}</td>
  <td><a href="/admin/mailings/delete/{row['id']}" class="act act-del" onclick="return confirm('Удалить?')">✕ Удалить</a></td>
</tr>""" for row in rows)

    content = f"""
<div class="ph">
  <h2>Рассылки</h2>
  <a href="/admin/mailings/add" class="btn btn-primary btn-sm"><i class="bi bi-plus-lg me-1"></i>Создать</a>
</div>
<div class="tbl-wrap">
  <div class="table-responsive">
    <table class="dt">
      <thead><tr><th>ID</th><th>Текст</th><th>Время отправки</th><th>Статус</th><th>Действия</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>"""
    return render("Рассылки", content, page="mailings", auth_token=auth)


@app.get("/admin/mailings/add", response_class=HTMLResponse)
async def add_mailing_form(auth=Depends(get_session)):
    content = """
<div class="ph"><h2>Создать рассылку</h2></div>
<div class="card" style="max-width:600px">
  <div class="card-body">
    <form method="post">
      <div class="mb-3"><label class="form-label">Текст сообщения</label><textarea name="text" class="form-control" rows="5" required></textarea></div>
      <div class="mb-3"><label class="form-label">Кнопки (текст;callback_data, каждая с новой строки)</label>
        <textarea name="buttons" class="form-control" rows="3" placeholder="Подтвердить;confirm&#10;Отмена;cancel"></textarea>
      </div>
      <div class="mb-3"><label class="form-label">Отправить (пусто = немедленно)</label>
        <input type="datetime-local" name="scheduled_at" class="form-control">
      </div>
      <button type="submit" class="btn btn-primary">Создать</button>
      <a href="/admin/mailings" class="btn btn-outline-secondary ms-2">Отмена</a>
    </form>
  </div>
</div>"""
    return render("Создать рассылку", content, page="mailings", auth_token=auth)


@app.post("/admin/mailings/add")
async def add_mailing(text: str = Form(...), buttons: str = Form(""),
                      scheduled_at: str = Form(""), auth=Depends(get_session), _csrf=Depends(check_csrf)):
    import json
    buttons_json = None
    if buttons.strip():
        btn_list = []
        for line in buttons.strip().split('\n'):
            if ';' in line:
                label, data = line.split(';', 1)
                btn_list.append({'label': label.strip(), 'callback_data': data.strip()})
            else:
                btn_list.append({'label': line.strip(), 'callback_data': line.strip()})
        buttons_json = json.dumps(btn_list)
    scheduled = datetime.fromisoformat(scheduled_at) if scheduled_at else None
    async with app.state.pool.acquire() as conn:
        await conn.execute("INSERT INTO mailings (text, buttons, scheduled_at, status) VALUES ($1,$2,$3,'pending')",
                           text, buttons_json, scheduled)
    return RedirectResponse(url="/admin/mailings", status_code=303)


@app.get("/admin/mailings/delete/{mid}")
async def delete_mailing(mid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("DELETE FROM mailings WHERE id = $1", mid)
    return RedirectResponse(url="/admin/mailings", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# MASTERS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/masters", response_class=HTMLResponse)
async def list_masters(request: Request, auth=Depends(get_session)):
    sort         = request.query_params.get('sort', 'id')
    order        = request.query_params.get('order', 'asc')
    name_filter  = request.query_params.get('name', '').strip()
    phone_filter = request.query_params.get('phone', '').strip()

    if order not in ('asc', 'desc'):
        order = 'asc'
    allowed_sort = ['id', 'full_name', 'telegram_id', 'created_at']
    if sort not in allowed_sort:
        sort = 'id'

    query = "SELECT * FROM masters WHERE 1=1"
    params = []
    if name_filter:
        query += " AND full_name ILIKE $" + str(len(params)+1)
        params.append(f"%{name_filter}%")
    if phone_filter:
        query += " AND phone ILIKE $" + str(len(params)+1)
        params.append(f"%{phone_filter}%")
    query += f" ORDER BY {sort} {order}"

    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    def sl(field):
        o = 'desc' if sort == field and order == 'asc' else 'asc'
        return f"/admin/masters?sort={field}&order={o}&name={name_filter}&phone={phone_filter}"

    table_rows = "".join(f"""
<tr>
  <td style="color:var(--mu);font-size:12px">{row['id']}</td>
  <td><strong>{row['full_name'] or ''}</strong></td>
  <td style="color:var(--mu);font-size:12px">{row['telegram_id']}</td>
  <td>{row['phone'] or ''}</td>
  <td style="color:var(--mu);font-size:12px">{row['created_at'].strftime('%d.%m.%Y %H:%M') if row['created_at'] else ''}</td>
  <td>{"<span class='sbadge s-active'>Активен</span>" if not row['is_blocked'] else "<span class='sbadge s-blocked'>Заблокирован</span>"}</td>
  <td>
    <button class='act act-edit me-1' onclick='editMaster({row["id"]})'>✏ Ред.</button>
    {'<a href="/admin/masters/block/'+str(row["id"])+'" class="act act-sec">Блок</a>' if not row['is_blocked'] else '<a href="/admin/masters/unblock/'+str(row["id"])+'" class="act act-ok">Разблок</a>'}
  </td>
</tr>""" for row in rows)

    filter_html = f"""
<div class="filter-bar">
  <div><label class="form-label">Имя</label><input type="text" id="nf" value="{name_filter}" class="form-control" placeholder="Поиск по имени…" style="min-width:180px"></div>
  <div><label class="form-label">Телефон</label><input type="text" id="pf" value="{phone_filter}" class="form-control" placeholder="Поиск по телефону…" style="min-width:180px"></div>
  <div class="d-flex gap-2 align-self-end">
    <button class="btn btn-primary btn-sm" onclick="window.location.href='/admin/masters?name='+encodeURIComponent(document.getElementById('nf').value)+'&phone='+encodeURIComponent(document.getElementById('pf').value)">Применить</button>
    <a href="/admin/masters" class="btn btn-outline-secondary btn-sm">Сбросить</a>
  </div>
</div>"""

    content = f"""
<div class="ph">
  <h2>Мастера</h2>
  <div class="d-flex gap-2">
    <button class='btn btn-primary btn-sm' data-bs-toggle='modal' data-bs-target='#addMasterModal'><i class="bi bi-plus-lg me-1"></i>Добавить</button>
    <a href='/admin/export/masters' class='btn btn-outline-secondary btn-sm'><i class="bi bi-download me-1"></i>CSV</a>
  </div>
</div>
{filter_html}
<div class="tbl-wrap">
  <div class="table-responsive">
    <table class="dt">
      <thead><tr>
        <th><a href="{sl('id')}">ID</a></th>
        <th><a href="{sl('full_name')}">Имя</a></th>
        <th><a href="{sl('telegram_id')}">Telegram ID</a></th>
        <th>Телефон</th>
        <th><a href="{sl('created_at')}">Регистрация</a></th>
        <th>Статус</th>
        <th>Действия</th>
      </tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</div>"""
    return render("Мастера", content, page="masters", auth_token=auth)


@app.post("/admin/masters/add")
async def add_master(full_name: str = Form(...), phone: str = Form(None),
                     notes: str = Form(None), auth=Depends(get_session), _csrf=Depends(check_csrf)):
    if phone and not validate_phone(phone):
        return HTMLResponse("<script>alert('Некорректный номер телефона'); window.history.back();</script>")
    async with app.state.pool.acquire() as conn:
        last_id = await conn.fetchval("SELECT COALESCE(MIN(telegram_id), 0) FROM masters WHERE telegram_id < 0")
        new_telegram_id = (last_id - 1) if last_id < 0 else -1
        await conn.execute("INSERT INTO masters (telegram_id, full_name, phone, notes, created_at) VALUES ($1,$2,$3,$4,now())",
                           new_telegram_id, full_name, phone, notes)
    return RedirectResponse(url="/admin/masters", status_code=303)


@app.get("/admin/masters/block/{mid}")
async def block_master(mid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET is_blocked=true WHERE id=$1", mid)
    return RedirectResponse(url="/admin/masters", status_code=303)


@app.get("/admin/masters/unblock/{mid}")
async def unblock_master(mid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET is_blocked=false WHERE id=$1", mid)
    return RedirectResponse(url="/admin/masters", status_code=303)


@app.get("/admin/master_info/{mid}")
async def master_info(mid: int, auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id,full_name,telegram_id,phone,notes,is_blocked FROM masters WHERE id=$1", mid)
        if not row:
            raise HTTPException(404)
        return JSONResponse(dict(row))


@app.post("/admin/masters/edit_ajax/{mid}")
async def edit_master_ajax(mid: int, full_name: str = Form(None),
                           phone: str = Form(None), notes: str = Form(None),
                           auth=Depends(get_session), _csrf=Depends(check_csrf)):
    if phone and not validate_phone(phone):
        return JSONResponse({"success": False, "error": "Некорректный номер телефона"}, status_code=400)
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET full_name=$1,phone=$2,notes=$3 WHERE id=$4",
                           full_name, phone, notes, mid)
    return JSONResponse({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# FINANCE
# ─────────────────────────────────────────────────────────────────────────────
def parse_period(params):
    from datetime import date
    today  = date.today()
    period = params.get('period', '')
    from_str = params.get('from', '')
    to_str   = params.get('to', '')

    if period == 'month':
        d_from = today.replace(day=1)
        d_to   = today
        return (datetime.combine(d_from, datetime.min.time()),
                datetime.combine(d_to, datetime.max.time().replace(microsecond=0)),
                'month', d_from.isoformat(), d_to.isoformat())
    elif period == 'prev_month':
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return (datetime.combine(first_prev, datetime.min.time()),
                datetime.combine(last_prev, datetime.max.time().replace(microsecond=0)),
                'prev_month', first_prev.isoformat(), last_prev.isoformat())
    elif period == 'year':
        d_from = today.replace(month=1, day=1)
        d_to   = today
        return (datetime.combine(d_from, datetime.min.time()),
                datetime.combine(d_to, datetime.max.time().replace(microsecond=0)),
                'year', d_from.isoformat(), d_to.isoformat())
    elif from_str and to_str:
        try:
            d_from = datetime.fromisoformat(from_str)
            d_to   = datetime.fromisoformat(to_str).replace(hour=23, minute=59, second=59)
            return (d_from, d_to, 'custom', from_str, to_str)
        except ValueError:
            pass
    return (None, None, 'all', '', '')


@app.get("/admin/finance", response_class=HTMLResponse)
async def finance(request: Request, auth=Depends(get_session)):
    date_from, date_to, active_period, from_str, to_str = parse_period(request.query_params)

    async with app.state.pool.acquire() as conn:
        if date_from:
            stars_total = await conn.fetchval(
                "SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE payment_method='stars' AND status IN ('paid','completed') AND created_at BETWEEN $1 AND $2",
                date_from, date_to)
            rub_total = await conn.fetchval(
                "SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE (payment_method IS NULL OR payment_method!='stars') AND status IN ('paid','completed') AND created_at BETWEEN $1 AND $2",
                date_from, date_to)
            bookings_count = await conn.fetchrow("""
                SELECT COUNT(*) FILTER (WHERE status IN ('paid','completed')) as paid_count,
                       COUNT(*) FILTER (WHERE status='completed') as completed_count,
                       COUNT(*) FILTER (WHERE status='cancelled') as cancelled_count
                FROM bookings WHERE created_at BETWEEN $1 AND $2""", date_from, date_to)
            masters_stats = await conn.fetch("""
                SELECT m.full_name, COUNT(b.id) as bookings_count,
                       COALESCE(SUM(CASE WHEN b.payment_method='stars' THEN b.total_price ELSE 0 END),0) as stars_sum,
                       COALESCE(SUM(CASE WHEN b.payment_method!='stars' OR b.payment_method IS NULL THEN b.total_price ELSE 0 END),0) as rub_sum
                FROM bookings b JOIN masters m ON b.master_id=m.id
                WHERE b.status IN ('paid','completed') AND b.created_at BETWEEN $1 AND $2
                GROUP BY m.id, m.full_name ORDER BY 3+4 DESC""", date_from, date_to)
            payment_methods = await conn.fetch("""
                SELECT payment_method, COUNT(*) as cnt, SUM(total_price) as total
                FROM bookings WHERE status IN ('paid','completed') AND created_at BETWEEN $1 AND $2
                GROUP BY payment_method ORDER BY total DESC""", date_from, date_to)
        else:
            stars_total = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE payment_method='stars' AND status IN ('paid','completed')")
            rub_total   = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE (payment_method IS NULL OR payment_method!='stars') AND status IN ('paid','completed')")
            bookings_count = await conn.fetchrow("""
                SELECT COUNT(*) FILTER (WHERE status IN ('paid','completed')) as paid_count,
                       COUNT(*) FILTER (WHERE status='completed') as completed_count,
                       COUNT(*) FILTER (WHERE status='cancelled') as cancelled_count
                FROM bookings""")
            masters_stats = await conn.fetch("""
                SELECT m.full_name, COUNT(b.id) as bookings_count,
                       COALESCE(SUM(CASE WHEN b.payment_method='stars' THEN b.total_price ELSE 0 END),0) as stars_sum,
                       COALESCE(SUM(CASE WHEN b.payment_method!='stars' OR b.payment_method IS NULL THEN b.total_price ELSE 0 END),0) as rub_sum
                FROM bookings b JOIN masters m ON b.master_id=m.id
                WHERE b.status IN ('paid','completed')
                GROUP BY m.id, m.full_name ORDER BY 3+4 DESC""")
            payment_methods = await conn.fetch("""
                SELECT payment_method, COUNT(*) as cnt, SUM(total_price) as total
                FROM bookings WHERE status IN ('paid','completed')
                GROUP BY payment_method ORDER BY total DESC""")

    def fmt_pm(pm):
        return {'stars': '⭐ Telegram Stars', None: 'Наличные / перевод'}.get(pm, pm or 'Не указан')

    def fmt_amt(pm, total):
        if pm == 'stars':
            return f"⭐ {int(total)} <small style='color:var(--mu)'>≈ {int(round(float(total)*STAR_TO_RUB))} ₽</small>"
        return f"{int(total)} ₽"

    masters_rows = "".join(
        f"<tr><td>{r['full_name']}</td><td>{r['bookings_count']}</td>"
        f"<td>⭐ {int(r['stars_sum'])}</td>"
        f"<td style='color:var(--mu)'>{int(round(float(r['stars_sum'])*STAR_TO_RUB))} ₽</td>"
        f"<td>{int(r['rub_sum'])} ₽</td></tr>"
        for r in masters_stats
    )
    methods_rows = "".join(
        f"<tr><td>{fmt_pm(pm['payment_method'])}</td><td>{pm['cnt']}</td><td>{fmt_amt(pm['payment_method'], pm['total'])}</td></tr>"
        for pm in payment_methods
    )

    period_label = {'month':'Текущий месяц','prev_month':'Предыдущий месяц',
                    'year':'Текущий год','custom':f'{from_str} — {to_str}','all':'Всё время'}.get(active_period,'Всё время')

    def pb(p, label):
        active = 'btn-primary' if active_period == p else 'btn-outline-secondary'
        return f"<a href='/admin/finance?period={p}' class='btn btn-sm {active}'>{label}</a>"

    stars_rub_eq = int(round(float(stars_total) * STAR_TO_RUB))

    content = f"""
<div class="ph"><h2>Финансовая статистика</h2></div>
<div class="period-bar">
  <strong style="font-size:12.5px;color:var(--mu)">Период:</strong>
  {pb('month','Текущий месяц')} {pb('prev_month','Прошлый месяц')}
  {pb('year','Год')} {pb('all','Всё время')}
  <form method="get" action="/admin/finance" class="d-flex gap-1 align-items-center ms-1">
    <input type="date" name="from" value="{from_str}" class="form-control form-control-sm" style="width:140px">
    <span style="color:var(--mu)">—</span>
    <input type="date" name="to" value="{to_str}" class="form-control form-control-sm" style="width:140px">
    <button type="submit" class="btn btn-sm btn-outline-primary">Ок</button>
  </form>
  <small style="color:var(--mu);margin-left:4px">{period_label}</small>
</div>
<div class="row g-3 mb-4">
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-green">
      <div class="kpi-icon"><i class="bi bi-star-fill"></i></div>
      <div class="kpi-val">⭐ {int(stars_total)}</div>
      <div class="kpi-lbl">Выручка Stars</div>
      <div class="kpi-sub">≈ {stars_rub_eq} ₽</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-purple">
      <div class="kpi-icon"><i class="bi bi-currency-exchange"></i></div>
      <div class="kpi-val">{int(rub_total)} ₽</div>
      <div class="kpi-lbl">Выручка (руб)</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-blue">
      <div class="kpi-icon"><i class="bi bi-check2-all"></i></div>
      <div class="kpi-val">{bookings_count['paid_count']}</div>
      <div class="kpi-lbl">Оплачено броней</div>
    </div>
  </div>
  <div class="col-6 col-xl-3">
    <div class="kpi kpi-red">
      <div class="kpi-icon"><i class="bi bi-x-circle"></i></div>
      <div class="kpi-val">{bookings_count['cancelled_count']}</div>
      <div class="kpi-lbl">Отменено</div>
    </div>
  </div>
</div>
<div class="row g-3">
  <div class="col-md-5">
    <div class="tbl-wrap">
      <div class="dt-toolbar" style="padding:12px 18px;font-weight:600;font-size:13.5px;border-bottom:1px solid var(--bdr)">Способы оплаты</div>
      <div class="table-responsive">
        <table class="dt">
          <thead><tr><th>Способ</th><th>Кол-во</th><th>Сумма</th></tr></thead>
          <tbody>{methods_rows}</tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="col-md-7">
    <div class="tbl-wrap">
      <div class="dt-toolbar" style="padding:12px 18px;font-weight:600;font-size:13.5px;border-bottom:1px solid var(--bdr)">Выручка по мастерам</div>
      <div class="table-responsive">
        <table class="dt">
          <thead><tr><th>Мастер</th><th>Броней</th><th>Stars</th><th>≈ Рублей</th><th>Нал/перевод</th></tr></thead>
          <tbody>{masters_rows}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>"""
    return render("Финансы", content, page="finance", auth_token=auth)


LOGIN_HTML = """<!DOCTYPE html>
<html lang="ru" data-theme="light" data-bs-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Вход — Девичьи дела</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <style>
    :root{{
      --acc:#655bf0;--acc2:#4f46e5;--bg:#f0f2f8;--card:#fff;
      --tx:#1a1d2e;--mu:#6b7280;--bdr:#e4e6f0;--inp:#f7f8fc;
      --sh2:0 4px 24px rgba(0,0,0,.09);
    }}
    [data-theme="dark"]{{
      --bg:#0d0f1a;--card:#181a2b;--tx:#e4e8f8;--mu:#7b82a8;
      --bdr:#242640;--inp:#111320;--sh2:0 4px 20px rgba(0,0,0,.6);
    }}
    *,*::before,*::after{{box-sizing:border-box}}
    body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:var(--bg);color:var(--tx);display:flex;align-items:center;
         justify-content:center;min-height:100vh;font-size:14px}}
    .login-box{{background:var(--card);border-radius:16px;padding:44px 48px;
               max-width:380px;width:90%;box-shadow:var(--sh2)}}
    .form-control{{background:var(--inp)!important;border-color:var(--bdr)!important;
                   color:var(--tx)!important;border-radius:8px!important}}
    .form-control:focus{{border-color:var(--acc)!important;
      box-shadow:0 0 0 3px rgba(101,91,240,.15)!important;background:var(--card)!important}}
    label{{color:var(--mu);font-size:12.5px;font-weight:500}}
    .btn{{border-radius:8px;font-size:13px}}
    .btn-primary{{background:var(--acc)!important;border-color:var(--acc)!important;color:#fff!important}}
    .btn-primary:hover{{background:var(--acc2)!important;border-color:var(--acc2)!important}}
    .th-btn{{display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid var(--bdr);
            background:transparent;color:var(--mu);border-radius:8px;cursor:pointer;
            font-size:13px;width:100%;transition:.15s;margin-top:12px;justify-content:center}}
    .th-btn:hover{{background:var(--bdr);color:var(--tx)}}
  </style>
  <script>(function(){{var t=localStorage.getItem('theme')||'light';document.documentElement.setAttribute('data-theme',t);document.documentElement.setAttribute('data-bs-theme',t);}})();</script>
</head>
<body>
  <div class="login-box">
    <div style="text-align:center;margin-bottom:28px">
      <div style="width:52px;height:52px;background:#655bf0;border-radius:14px;display:inline-flex;align-items:center;justify-content:center;font-size:26px;margin-bottom:14px">&#128133;</div>
      <h1 style="font-size:22px;font-weight:700;margin:0 0 4px">Девичьи дела</h1>
      <p style="color:var(--mu);font-size:13.5px;margin:0">Административная панель</p>
    </div>
    {error_block}
    <form method="post" action="/login">
      <div class="mb-3">
        <label class="form-label">Пароль</label>
        <input type="password" name="password" class="form-control" autofocus required>
      </div>
      <button type="submit" class="btn btn-primary w-100">Войти</button>
    </form>
    <button class="th-btn" onclick="toggleTheme()">
      <i id="themeIcon" class="bi bi-moon-stars-fill"></i>
      <span id="themeLabel">Тёмная тема</span>
    </button>
  </div>
  <script>
  function applyTheme(t){{
    document.documentElement.setAttribute('data-theme',t);
    document.documentElement.setAttribute('data-bs-theme',t);
    localStorage.setItem('theme',t);
    var ic=document.getElementById('themeIcon'),lb=document.getElementById('themeLabel');
    if(t==='dark'){{ic.className='bi bi-sun-fill';lb.textContent='Светлая тема';}}
    else{{ic.className='bi bi-moon-stars-fill';lb.textContent='Тёмная тема';}}
  }}
  function toggleTheme(){{applyTheme(localStorage.getItem('theme')==='dark'?'light':'dark');}}
  document.addEventListener('DOMContentLoaded',function(){{applyTheme(localStorage.getItem('theme')||'light');}});
  </script>
</body>
</html>"""


@app.get("/admin/analytics", response_class=HTMLResponse)
async def admin_analytics(auth=Depends(get_session)):
    async with app.state.pool.acquire() as conn:
        # KPI
        total_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM user_events") or 0
        sessions_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM user_events WHERE event_type='bot_start' AND created_at >= NOW() - INTERVAL '7 days'"
        ) or 0
        top_event_row = await conn.fetchrow(
            "SELECT event_type, COUNT(*) as cnt FROM user_events GROUP BY event_type ORDER BY cnt DESC LIMIT 1"
        )
        top_event = top_event_row['event_type'] if top_event_row else '—'

        # Funnel
        funnel_bot_start   = await conn.fetchval("SELECT COUNT(*) FROM user_events WHERE event_type='bot_start'") or 0
        funnel_bk_started  = await conn.fetchval("SELECT COUNT(*) FROM user_events WHERE event_type='booking_started'") or 0
        funnel_pay_attempt = await conn.fetchval("SELECT COUNT(*) FROM user_events WHERE event_type='payment_attempt'") or 0
        funnel_bk_done     = await conn.fetchval("SELECT COUNT(*) FROM user_events WHERE event_type='booking_completed'") or 0

        # Top workspaces
        top_ws = await conn.fetch("""
            SELECT payload->>'workspace_name' as name, COUNT(*) as views
            FROM user_events WHERE event_type='browse_workspace' AND payload->>'workspace_name' IS NOT NULL
            GROUP BY payload->>'workspace_name' ORDER BY views DESC LIMIT 10
        """)

        # Top categories
        top_cat = await conn.fetch("""
            SELECT payload->>'category_name' as cat, COUNT(*) as views
            FROM user_events WHERE event_type='browse_category' AND payload->>'category_name' IS NOT NULL
            GROUP BY payload->>'category_name' ORDER BY views DESC
        """)

        # Activity last 30 days
        daily_rows = []
        for i in range(29, -1, -1):
            from datetime import date as _date, timedelta as _td
            day = _date.today() - _td(days=i)
            cnt = await conn.fetchval(
                "SELECT COUNT(*) FROM user_events WHERE event_type='bot_start' AND DATE(created_at)=$1", day
            ) or 0
            daily_rows.append({'date': day.strftime('%d.%m'), 'count': int(cnt)})

        # Top active users
        top_users = await conn.fetch("""
            SELECT m.full_name, m.telegram_id, COUNT(*) as sessions
            FROM user_events e LEFT JOIN masters m ON e.user_id = m.telegram_id
            WHERE e.event_type = 'bot_start'
            GROUP BY m.full_name, m.telegram_id ORDER BY sessions DESC LIMIT 10
        """)

    def pct(num, base):
        return f"{round(num/base*100)}%" if base else "—"

    def bar_w(num, base):
        return f"{round(num/base*100)}%" if base else "0%"

    # --- KPI cards ---
    kpi_html = f"""
<div class="row g-3 mb-4">
  <div class="col-sm-4">
    <div class="kpi kpi-purple">
      <div class="kpi-icon"><i class="bi bi-people-fill"></i></div>
      <div class="kpi-val">{total_users}</div>
      <div class="kpi-lbl">Уникальных пользователей</div>
    </div>
  </div>
  <div class="col-sm-4">
    <div class="kpi kpi-green">
      <div class="kpi-icon"><i class="bi bi-activity"></i></div>
      <div class="kpi-val">{sessions_7d}</div>
      <div class="kpi-lbl">Сессий за 7 дней</div>
    </div>
  </div>
  <div class="col-sm-4">
    <div class="kpi kpi-blue">
      <div class="kpi-icon"><i class="bi bi-award-fill"></i></div>
      <div class="kpi-val" style="font-size:18px">{top_event}</div>
      <div class="kpi-lbl">Топ событие</div>
    </div>
  </div>
</div>"""

    # --- Funnel ---
    funnel_rows = [
        ('bot_start',         'Открыли бота',             funnel_bot_start,   funnel_bot_start),
        ('booking_started',   'Начали бронирование',      funnel_bk_started,  funnel_bot_start),
        ('payment_attempt',   'Попытка оплаты',           funnel_pay_attempt, funnel_bot_start),
        ('booking_completed', 'Успешно забронировали',    funnel_bk_done,     funnel_bot_start),
    ]
    funnel_html_rows = ""
    for _, label, num, base in funnel_rows:
        w = bar_w(num, base)
        p = pct(num, base) if base != num else "100%"
        funnel_html_rows += f"""
  <div class="mb-3">
    <div class="d-flex justify-content-between mb-1" style="font-size:13.5px">
      <span>{label}</span>
      <span class="fw-600">{num} &nbsp;<span class="text-muted" style="font-size:12px">({p})</span></span>
    </div>
    <div style="height:10px;background:var(--bdr);border-radius:6px;overflow:hidden">
      <div style="width:{w};height:100%;background:var(--acc);border-radius:6px;transition:.5s"></div>
    </div>
  </div>"""

    funnel_card = f"""
<div class="card mb-4">
  <div class="card-header"><i class="bi bi-filter-left me-1"></i> Воронка конверсии</div>
  <div class="card-body">{funnel_html_rows}</div>
</div>"""

    # --- Top workspaces table ---
    ws_rows_html = "".join(
        f'<tr><td>{i+1}</td><td>{row["name"] or "—"}</td><td>{row["views"]}</td></tr>'
        for i, row in enumerate(top_ws)
    ) or '<tr><td colspan="3" class="text-muted text-center">Нет данных</td></tr>'

    ws_table = f"""
<div class="tbl-wrap mb-4">
  <div class="dt-toolbar"><strong>Топ просматриваемых мест</strong></div>
  <div class="table-responsive">
    <table class="dt">
      <thead><tr><th>#</th><th>Место</th><th>Просмотров</th></tr></thead>
      <tbody>{ws_rows_html}</tbody>
    </table>
  </div>
</div>"""

    # --- Top categories table ---
    cat_rows_html = "".join(
        f'<tr><td>{i+1}</td><td>{row["cat"] or "—"}</td><td>{row["views"]}</td></tr>'
        for i, row in enumerate(top_cat)
    ) or '<tr><td colspan="3" class="text-muted text-center">Нет данных</td></tr>'

    cat_table = f"""
<div class="tbl-wrap mb-4">
  <div class="dt-toolbar"><strong>Топ просматриваемых категорий</strong></div>
  <div class="table-responsive">
    <table class="dt">
      <thead><tr><th>#</th><th>Категория</th><th>Просмотров</th></tr></thead>
      <tbody>{cat_rows_html}</tbody>
    </table>
  </div>
</div>"""

    # --- Activity chart ---
    chart_labels = str([d['date'] for d in daily_rows]).replace("'", '"')
    chart_data   = str([d['count'] for d in daily_rows])
    activity_card = f"""
<div class="card mb-4">
  <div class="card-header"><i class="bi bi-graph-up me-1"></i> Активность за последние 30 дней (bot_start)</div>
  <div class="card-body">
    <canvas id="activityChart" height="80"></canvas>
  </div>
</div>
<script>
(function(){{
  var ctx = document.getElementById('activityChart').getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: {chart_labels},
      datasets: [{{
        label: 'Открытий бота',
        data: {chart_data},
        borderColor: '#655bf0',
        backgroundColor: 'rgba(101,91,240,0.1)',
        borderWidth: 2,
        pointRadius: 3,
        fill: true,
        tension: 0.3
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ y: {{ beginAtZero: true, ticks: {{ precision: 0 }} }} }}
    }}
  }});
}})();
</script>"""

    # --- Top active users ---
    users_rows_html = "".join(
        f'<tr><td>{i+1}</td><td>{row["full_name"] or "—"}</td><td>{row["telegram_id"] or "—"}</td><td>{row["sessions"]}</td></tr>'
        for i, row in enumerate(top_users)
    ) or '<tr><td colspan="4" class="text-muted text-center">Нет данных</td></tr>'

    users_table = f"""
<div class="tbl-wrap mb-4">
  <div class="dt-toolbar"><strong>Топ-10 активных пользователей</strong></div>
  <div class="table-responsive">
    <table class="dt">
      <thead><tr><th>#</th><th>Имя</th><th>Telegram ID</th><th>Сессий</th></tr></thead>
      <tbody>{users_rows_html}</tbody>
    </table>
  </div>
</div>"""

    content = f"""
<div class="ph"><h2><i class="bi bi-person-lines-fill me-2"></i>Поведение пользователей</h2></div>
{kpi_html}
<div class="row g-3 mb-0">
  <div class="col-lg-6">{ws_table}</div>
  <div class="col-lg-6">{cat_table}</div>
</div>
{funnel_card}
{activity_card}
{users_table}"""

    return render("Аналитика поведения", content, page="analytics", auth_token=auth)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    token = request.cookies.get("session")
    if token and verify_session_token(token):
        return RedirectResponse(url="/admin", status_code=303)
    error_block = ""
    if error:
        error_block = '<div class="alert alert-danger py-2 px-3 mb-3" style="font-size:13.5px;border-radius:8px">Неверный пароль</div>'
    return HTMLResponse(LOGIN_HTML.format(error_block=error_block))


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    if verify_password(password, ADMIN_PASSWORD_HASH):
        token = make_session_token()
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie("session", token, httponly=True, samesite="lax", secure=False,
                            max_age=SESSION_MAX_AGE)
        return response
    return RedirectResponse(url="/login?error=1", status_code=303)


@app.post("/logout")
async def logout(_csrf=Depends(check_csrf)):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# ─────────────────────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/admin/logs", response_class=HTMLResponse)
async def logs_dashboard(auth=Depends(get_session)):
    content = """
<div class="ph"><h2>Системные логи</h2></div>
<div class="card mb-3" style="max-width:800px">
  <div class="card-body">
    <div class="row g-3 align-items-end">
      <div class="col-md-4">
        <label class="form-label">Сервис</label>
        <select id="service" class="form-select">
          <option value="bot">Telegram бот</option>
          <option value="admin">Админ-панель</option>
          <option value="nginx">Nginx (ошибки)</option>
          <option value="nginx-access">Nginx (доступ)</option>
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label">Строк</label>
        <input type="number" id="lines" value="100" class="form-control">
      </div>
      <div class="col-md-5 d-flex gap-2">
        <button id="fetchLogsBtn" class="btn btn-primary btn-sm flex-grow-1">Показать</button>
        <button id="autoRefreshBtn" class="btn btn-outline-secondary btn-sm flex-grow-1">Авто (выкл)</button>
      </div>
    </div>
  </div>
</div>
<pre id="logContent"></pre>
<script>
  var autoRefresh=false,intervalId=null;
  var svc=document.getElementById('service'),ln=document.getElementById('lines');
  var fb=document.getElementById('fetchLogsBtn'),arb=document.getElementById('autoRefreshBtn');
  var lc=document.getElementById('logContent');
  async function fetchLogs(){
    var r=await fetch(`/admin/api/logs?service=${svc.value}&lines=${ln.value}`);
    var d=await r.json();
    lc.textContent=d.logs?d.logs.join('\\n'):'Ошибка: '+(d.error||'неизвестная');
  }
  function toggleAR(){
    autoRefresh=!autoRefresh;
    if(autoRefresh){intervalId=setInterval(fetchLogs,5000);arb.textContent='Авто (вкл)';arb.classList.replace('btn-outline-secondary','btn-warning');}
    else{clearInterval(intervalId);arb.textContent='Авто (выкл)';arb.classList.replace('btn-warning','btn-outline-secondary');}
  }
  fb.addEventListener('click',fetchLogs);
  arb.addEventListener('click',toggleAR);
  toggleAR();
</script>"""
    return render("Логи", content, page="logs", auth_token=auth)


@app.get("/admin/api/logs")
async def api_get_logs(service: str, lines: int = 100, auth=Depends(get_session)):
    allowed = ['bot', 'admin', 'nginx', 'nginx-access']
    if service not in allowed:
        return JSONResponse({"error": "Invalid service"}, status_code=400)
    try:
        if service == 'bot':
            cmd = ["journalctl", "-u", "devichyi_bot", "-n", str(lines), "--no-pager"]
        elif service == 'admin':
            cmd = ["journalctl", "-u", "devichyi_admin", "-n", str(lines), "--no-pager"]
        elif service == 'nginx':
            cmd = ["tail", "-n", str(lines), "/var/log/nginx/error.log"]
        elif service == 'nginx-access':
            cmd = ["tail", "-n", str(lines), "/var/log/nginx/access.log"]
        else:
            return JSONResponse({"error": "Unknown service"}, status_code=400)
        result = subprocess.run(cmd, capture_output=True, text=True)
        logs = (result.stderr if result.returncode != 0 else result.stdout).split('\n')[-lines:]
        return JSONResponse({"logs": logs})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/admin/export/{table}")
async def export_csv(table: str, auth=Depends(get_session)):
    allowed = ['workspaces', 'bookings', 'masters']
    if table not in allowed:
        raise HTTPException(400)
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM {table}")
    if not rows:
        return JSONResponse({"error": "No data"}, status_code=404)
    output = StringIO()
    output.write('﻿')  # UTF-8 BOM для Excel
    writer = csv.writer(output, delimiter=';')
    writer.writerow(rows[0].keys())
    for row in rows:
        writer.writerow(row.values())
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={table}.csv"}
    )
