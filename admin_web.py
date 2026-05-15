import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, Form, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from database import create_pool
import hashlib
import base64
import os
from dotenv import load_dotenv
import subprocess

load_dotenv()

app = FastAPI()
security = HTTPBasic()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
if not ADMIN_PASSWORD_HASH:
    raise RuntimeError("ADMIN_PASSWORD_HASH not set in .env file")

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        method_part, salt_b64, key_b64 = stored_hash.split('$')
        parts = method_part.split(':')
        iterations = int(parts[2])  # например, 100000
        salt = base64.b64decode(salt_b64)
        key = base64.b64decode(key_b64)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iterations)
        return new_key == key
    except Exception:
        return False

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = verify_password(credentials.password, ADMIN_PASSWORD_HASH)
    if not (correct_username and correct_password):
        raise HTTPException(status_code=401, detail="Неверные учётные данные", headers={"WWW-Authenticate": "Basic"})
    return credentials
    return credentials

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

# ------------------- Базовый HTML-шаблон -------------------
BASE_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Админпанель - {title}</title>
    <link id="theme-css" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ overflow-x: auto; }}
        .custom-container {{
            width: 95%;
            margin-left: auto;
            margin-right: auto;
            padding-left: 15px;
            padding-right: 15px;
        }}
        .clickable {{ cursor: pointer; }}
        .clickable:hover {{ text-decoration: underline; }}
        .theme-switch {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            background: #fff;
            border: 1px solid #ccc;
            border-radius: 30px;
            padding: 8px 15px;
            cursor: pointer;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            font-size: 14px;
        }}
        .dark-theme .theme-switch {{
            background: #2c3034;
            border-color: #555;
            color: #f8f9fa;
        }}
        .btn-sm {{ padding: 0.25rem 0.5rem; font-size: 0.75rem; }}
        table th.sortable {{ cursor: pointer; user-select: none; }}
        table th.sortable:hover {{ background-color: rgba(0,0,0,0.05); }}
        .booking-row {{ cursor: pointer; }}
        .booking-row:hover {{ background-color: rgba(0, 0, 0, 0.05); }}
        .dark-theme .booking-row:hover {{ background-color: rgba(255, 255, 255, 0.1); }}
    </style>
    <script>
        function setTheme(theme) {{
            if (theme === 'dark') {{
                document.getElementById('theme-css').href = 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css';
                document.body.classList.add('dark-theme');
                localStorage.setItem('theme', 'dark');
            }} else {{
                document.getElementById('theme-css').href = 'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css';
                document.body.classList.remove('dark-theme');
                localStorage.setItem('theme', 'light');
            }}
        }}
        function toggleTheme() {{
            const current = localStorage.getItem('theme') || 'light';
            setTheme(current === 'light' ? 'dark' : 'light');
        }}
        window.onload = function() {{
            const saved = localStorage.getItem('theme');
            if (saved === 'dark') setTheme('dark');
        }};

        // Мастера
        async function showMasterInfo(masterId) {{
            const resp = await fetch(`/admin/master_info/${{masterId}}`);
            const data = await resp.json();
            document.getElementById('modalMasterId').value = masterId;
            document.getElementById('modalMasterName').innerText = data.full_name || '—';
            document.getElementById('modalMasterTelegram').innerText = data.telegram_id;
            document.getElementById('modalMasterPhone').innerText = data.phone || '—';
            document.getElementById('modalMasterNotes').innerText = data.notes || '—';
            document.getElementById('modalMasterStatus').innerHTML = data.is_blocked ? '<span class="text-danger">Заблокирован</span>' : '<span class="text-success">Активен</span>';
            const blockBtn = document.getElementById('modalBlockBtn');
            const unblockBtn = document.getElementById('modalUnblockBtn');
            if (data.is_blocked) {{
                blockBtn.style.display = 'none';
                unblockBtn.style.display = 'inline-block';
            }} else {{
                blockBtn.style.display = 'inline-block';
                unblockBtn.style.display = 'none';
            }}
            const modal = new bootstrap.Modal(document.getElementById('masterInfoModal'));
            modal.show();
        }}
        async function blockMaster(masterId) {{
            await fetch(`/admin/masters/block/${{masterId}}`, {{ method: 'GET' }});
            location.reload();
        }}
        async function unblockMaster(masterId) {{
            await fetch(`/admin/masters/unblock/${{masterId}}`, {{ method: 'GET' }});
            location.reload();
        }}
        async function editMaster(masterId) {{
            const resp = await fetch(`/admin/master_info/${{masterId}}`);
            const data = await resp.json();
            document.getElementById('editMasterId').value = masterId;
            document.getElementById('editMasterName').value = data.full_name || '';
            document.getElementById('editMasterPhone').value = data.phone || '';
            document.getElementById('editMasterNotes').value = data.notes || '';
            const modal = new bootstrap.Modal(document.getElementById('editMasterModal'));
            modal.show();
        }}
        async function saveMasterEdit() {{
            const masterId = document.getElementById('editMasterId').value;
            const full_name = document.getElementById('editMasterName').value;
            const phone = document.getElementById('editMasterPhone').value;
            const notes = document.getElementById('editMasterNotes').value;
            const resp = await fetch(`/admin/masters/edit_ajax/${{masterId}}`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                body: new URLSearchParams({{ full_name, phone, notes }})
            }});
            if (resp.ok) location.reload();
            else alert('Ошибка при сохранении');
        }}
        // Редактирование брони
        async function editBooking(bookingId) {{
            const resp = await fetch(`/admin/bookings/get/${{bookingId}}`);
            const data = await resp.json();
            document.getElementById('editBookingId').value = bookingId;
            document.querySelector('#editBookingModal select[name="master_id"]').value = data.master_id;
            document.querySelector('#editBookingModal select[name="workspace_id"]').value = data.workspace_id;
            document.querySelector('#editBookingModal input[name="start_time"]').value = data.start_time.slice(0,16);
            document.querySelector('#editBookingModal input[name="end_time"]').value = data.end_time.slice(0,16);
            document.querySelector('#editBookingModal input[name="total_price"]').value = data.total_price;
            document.querySelector('#editBookingModal select[name="status"]').value = data.status;
            const modal = new bootstrap.Modal(document.getElementById('editBookingModal'));
            modal.show();
        }}
        document.addEventListener('DOMContentLoaded', function() {{
            const form = document.getElementById('editBookingForm');
            if (form) {{
                form.onsubmit = async function(e) {{
                    e.preventDefault();
                    const bookingId = document.getElementById('editBookingId').value;
                    const formData = new FormData(form);
                    const resp = await fetch(`/admin/bookings/edit/${{bookingId}}`, {{
                        method: 'POST',
                        body: formData
                    }});
                    if (resp.ok) {{
                        location.reload();
                    }} else {{
                        alert('Ошибка при редактировании');
                    }}
                }};
            }}
        }});
    </script>
</head>
<body>
    <div class="theme-switch" onclick="toggleTheme()">🌓 Сменить тему</div>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/admin">Девичьи дела (Админ)</a>
            <div class="navbar-nav">
                <a class="nav-link" href="/admin/workspaces">Места</a>
                <a class="nav-link" href="/admin/bookings">Брони</a>
                <a class="nav-link" href="/admin/masters">Мастера</a>
                <a class="nav-link" href="/admin/statistics">Статистика</a>
                <a class="nav-link" href="/admin/finance">Финансы</a>
                <a class="nav-link" href="/admin/logs">Логи</a>
                <a class="nav-link" href="/logout">Выйти</a>
                
            </div>
        </div>
    </nav>
    <div class="custom-container mt-4">
        {content}
    </div>

    <!-- Модалки мастеров -->
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
                <button id="modalBlockBtn" class="btn btn-warning" onclick="blockMaster(document.getElementById('modalMasterId').value)">Заблокировать</button>
                <button id="modalUnblockBtn" class="btn btn-success" onclick="unblockMaster(document.getElementById('modalMasterId').value)">Разблокировать</button>
            </div>
        </div></div>
    </div>
    <div class="modal fade" id="editMasterModal" tabindex="-1">
        <div class="modal-dialog"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">Редактировать мастера</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">
                <input type="hidden" id="editMasterId">
                <div class="mb-3"><label>Имя</label><input type="text" id="editMasterName" class="form-control"></div>
                <div class="mb-3"><label>Телефон</label><input type="text" id="editMasterPhone" class="form-control"></div>
                <div class="mb-3"><label>Заметки</label><textarea id="editMasterNotes" class="form-control" rows="3"></textarea></div>
                <button class="btn btn-success" onclick="saveMasterEdit()">Сохранить</button>
            </div>
        </div></div>
    </div>

    <!-- Модалка добавления мастера -->
    <div class="modal fade" id="addMasterModal" tabindex="-1">
        <div class="modal-dialog"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">Добавить мастера</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">
                <form action="/admin/masters/add" method="post">
                    <div class="mb-3"><label>Имя</label><input type="text" name="full_name" class="form-control" required></div>
                    <div class="mb-3"><label>Телефон</label><input type="text" name="phone" class="form-control"></div>
                    <div class="mb-3"><label>Заметки</label><textarea name="notes" class="form-control" rows="3"></textarea></div>
                    <button type="submit" class="btn btn-success">Сохранить</button>
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                </form>
            </div>
        </div></div>
    </div>

    <!-- Модалка добавления брони вручную -->
    <div class="modal fade" id="addBookingModal" tabindex="-1">
        <div class="modal-dialog"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">Добавить бронь вручную</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">
                <form action="/admin/bookings/add" method="post">
                    <div class="mb-3"><label>Мастер</label><select name="master_id" class="form-control" required>___MASTER_OPTIONS___</select></div>
                    <div class="mb-3"><label>Место</label><select name="workspace_id" class="form-control" required>___WORKSPACE_OPTIONS___</select></div>
                    <div class="mb-3"><label>Начало</label><input type="datetime-local" name="start_time" class="form-control" required></div>
                    <div class="mb-3"><label>Конец</label><input type="datetime-local" name="end_time" class="form-control" required></div>
                    <div class="mb-3"><label>Стоимость (руб)</label><input type="number" step="0.01" name="total_price" class="form-control" required></div>
                    <div class="mb-3"><label>Статус</label>
                        <select name="status" class="form-control">
                            <option value="paid">Оплачено</option>
                            <option value="pending">Ожидает оплаты</option>
                            <option value="cancelled">Отменена</option>
                            <option value="completed">Завершена</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-success">Сохранить</button>
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                </form>
            </div>
        </div></div>
    </div>

    <!-- Модалка редактирования брони -->
    <div class="modal fade" id="editBookingModal" tabindex="-1">
        <div class="modal-dialog"><div class="modal-content">
            <div class="modal-header"><h5 class="modal-title">Редактировать бронь</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
            <div class="modal-body">
                <form id="editBookingForm" method="post">
                    <div class="mb-3"><label>Мастер</label><select name="master_id" class="form-control" required>___MASTER_OPTIONS___</select></div>
                    <div class="mb-3"><label>Место</label><select name="workspace_id" class="form-control" required>___WORKSPACE_OPTIONS___</select></div>
                    <div class="mb-3"><label>Начало</label><input type="datetime-local" name="start_time" class="form-control" required></div>
                    <div class="mb-3"><label>Конец</label><input type="datetime-local" name="end_time" class="form-control" required></div>
                    <div class="mb-3"><label>Стоимость (руб)</label><input type="number" step="0.01" name="total_price" class="form-control" required></div>
                    <div class="mb-3"><label>Статус</label>
                        <select name="status" class="form-control">
                            <option value="paid">Оплачено</option>
                            <option value="pending">Ожидает оплаты</option>
                            <option value="cancelled">Отменена</option>
                            <option value="completed">Завершена</option>
                        </select>
                    </div>
                    <input type="hidden" name="booking_id" id="editBookingId">
                    <button type="submit" class="btn btn-success">Сохранить изменения</button>
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                </form>
            </div>
        </div></div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

def render(title: str, content: str, masters_options_html: str = "", workspaces_options_html: str = "") -> HTMLResponse:
    full_html = BASE_HTML.format(title=title, content=content)
    full_html = full_html.replace("___MASTER_OPTIONS___", masters_options_html)
    full_html = full_html.replace("___WORKSPACE_OPTIONS___", workspaces_options_html)
    return HTMLResponse(full_html)

# ------------------- Главная страница с графиками -------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_index(auth=Depends(authenticate)):
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
    content = f"""
    <div class="row"><div class="col-md-12"><h2>Статистика</h2></div></div>
    <div class="row">
        <div class="col-md-5"><canvas id="statusChart" width="400" height="400"></canvas></div>
        <div class="col-md-7"><canvas id="topWorkspacesChart" width="500" height="400"></canvas></div>
    </div>
    <div class="row mt-5"><div class="col-md-12"><h4>Брони по дням (последние 14 дней)</h4><canvas id="dailyChart" width="800" height="300"></canvas></div></div>
    <script>
        new Chart(document.getElementById('statusChart'), {{type:'pie', data:{{labels:{[s for s in status_counts.keys()]}, datasets:[{{data:{[status_counts[s] for s in status_counts.keys()]}, backgroundColor:['#ffc107','#28a745','#17a2b8','#dc3545']}}]}}, options:{{responsive:true, plugins:{{legend:{{position:'bottom'}}}}}}}});
        new Chart(document.getElementById('topWorkspacesChart'), {{type:'bar', data:{{labels:{[row['name'] for row in top]}, datasets:[{{label:'Количество броней', data:{[row['count'] for row in top]}, backgroundColor:'#007bff'}}]}}, options:{{responsive:true, scales:{{y:{{beginAtZero:true}}}}}}}});
        new Chart(document.getElementById('dailyChart'), {{type:'line', data:{{labels:{[d['date'] for d in last_14_days]}, datasets:[{{label:'Брони', data:{[d['count'] for d in last_14_days]}, borderColor:'#28a745', tension:0.2, fill:false}}]}}, options:{{responsive:true, plugins:{{tooltip:{{callbacks:{{label:(ctx)=>ctx.raw+' броней'}}}}}}}}}});
    </script>
    """
    return render("Главная", content)

# ------------------- Рабочие места (CRUD) -------------------
@app.get("/admin/workspaces", response_class=HTMLResponse)
async def list_workspaces(request: Request, auth=Depends(authenticate)):
    sort = request.query_params.get('sort', 'id')
    order = request.query_params.get('order', 'asc')
    if order not in ('asc','desc'): order='asc'
    allowed=['id','name','category','price_per_hour']
    if sort not in allowed: sort='id'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM workspaces ORDER BY {sort} {order}")
    table_rows = ""
    for row in rows:
        table_rows += f"<tr><td>{row['id']}</td><td>{row['name']}</td><td>{row['category']}</td><td>{row['price_per_hour']}</td><td>{row['price_per_day']}</td><td>{row['price_per_multi_day']}</td><td><a href='/admin/workspaces/edit/{row['id']}' class='btn btn-sm btn-warning'>Редакт</a> <a href='/admin/workspaces/delete/{row['id']}' class='btn btn-sm btn-danger' onclick=\"return confirm('Удалить?')\">Удалить</a></td></tr>"
    asc_desc = "asc" if order=="desc" else "desc"
    content = f"<h2>Рабочие места</h2><a href='/admin/workspaces/add' class='btn btn-primary mb-3'>Добавить место</a><table class='table table-bordered'><thead><tr><th><a href='/admin/workspaces?sort=id&order={asc_desc}'>ID</a></th><th><a href='/admin/workspaces?sort=name&order={asc_desc}'>Название</a></th><th><a href='/admin/workspaces?sort=category&order={asc_desc}'>Категория</a></th><th><a href='/admin/workspaces?sort=price_per_hour&order={asc_desc}'>Почасово</a></th><th>На день</th><th>Многодневная</th><th>Действия</th></tr></thead><tbody>{table_rows}</tbody></table>"
    return render("Места", content)

@app.get("/admin/workspaces/add", response_class=HTMLResponse)
async def add_workspace_form(auth=Depends(authenticate)):
    content = '<h2>Добавить место</h2><form method="post"><div class="mb-3"><label>Название</label><input type="text" name="name" class="form-control" required></div><div class="mb-3"><label>Описание</label><textarea name="description" class="form-control"></textarea></div><div class="mb-3"><label>Категория</label><select name="category" class="form-control"><option value="couch_202">🛏 Кушетки 202</option><option value="dressing_202">🎭 Гримерки 202</option><option value="dressing_201">🎭 Гримерки 201</option><option value="hairdresser_201">💺 Кресла 201</option></select></div><div class="mb-3"><label>Цена почасовая (руб)</label><input type="number" name="price_per_hour" class="form-control" required></div><div class="mb-3"><label>Цена на день (руб)</label><input type="number" name="price_per_day" class="form-control" required></div><div class="mb-3"><label>Цена многодневная (руб/сутки)</label><input type="number" name="price_per_multi_day" class="form-control" required></div><div class="mb-3"><label>Фото 1 (file_id)</label><input type="text" name="image_url_1" class="form-control"></div><div class="mb-3"><label>Фото 2</label><input type="text" name="image_url_2" class="form-control"></div><div class="mb-3"><label>Фото 3</label><input type="text" name="image_url_3" class="form-control"></div><button type="submit" class="btn btn-success">Сохранить</button><a href="/admin/workspaces" class="btn btn-secondary">Отмена</a></form>'
    return render("Добавить место", content)

@app.post("/admin/workspaces/add")
async def add_workspace(name: str=Form(...), description: str=Form(""), category: str=Form(...), price_per_hour: int=Form(...), price_per_day: int=Form(...), price_per_multi_day: int=Form(...), image_url_1: str=Form(""), image_url_2: str=Form(""), image_url_3: str=Form(""), auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("INSERT INTO workspaces (name,description,category,price_per_hour,price_per_day,price_per_multi_day,image_url_1,image_url_2,image_url_3) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)", name,description,category,price_per_hour,price_per_day,price_per_multi_day,image_url_1,image_url_2,image_url_3)
    return RedirectResponse(url="/admin/workspaces", status_code=303)

@app.get("/admin/workspaces/edit/{wid}", response_class=HTMLResponse)
async def edit_workspace_form(request: Request, wid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM workspaces WHERE id = $1", wid)
        if not row: raise HTTPException(404)
    content = f"<h2>Редактировать место</h2><form method='post'><div class='mb-3'><label>Название</label><input type='text' name='name' class='form-control' value='{row['name']}' required></div><div class='mb-3'><label>Описание</label><textarea name='description' class='form-control'>{row['description'] or ''}</textarea></div><div class='mb-3'><label>Категория</label><select name='category' class='form-control'><option value='couch' {'selected' if row['category']=='couch' else ''}>Кушетки</option><option value='hairdresser' {'selected' if row['category']=='hairdresser' else ''}>Парикмахерские</option><option value='dressing' {'selected' if row['category']=='dressing' else ''}>Гримерки</option></select></div><div class='mb-3'><label>Цена почасовая (руб)</label><input type='number' name='price_per_hour' class='form-control' value='{row['price_per_hour']}' required></div><div class='mb-3'><label>Цена на день (руб)</label><input type='number' name='price_per_day' class='form-control' value='{row['price_per_day']}' required></div><div class='mb-3'><label>Цена многодневная (руб/сутки)</label><input type='number' name='price_per_multi_day' class='form-control' value='{row['price_per_multi_day']}' required></div><div class='mb-3'><label>Фото 1 (file_id)</label><input type='text' name='image_url_1' class='form-control' value='{row['image_url_1'] or ''}'></div><div class='mb-3'><label>Фото 2</label><input type='text' name='image_url_2' class='form-control' value='{row['image_url_2'] or ''}'></div><div class='mb-3'><label>Фото 3</label><input type='text' name='image_url_3' class='form-control' value='{row['image_url_3'] or ''}'></div><button type='submit' class='btn btn-success'>Сохранить</button><a href='/admin/workspaces' class='btn btn-secondary'>Отмена</a></form>"
    return render("Редактировать место", content)

@app.post("/admin/workspaces/edit/{wid}")
async def edit_workspace(wid: int, name: str=Form(...), description: str=Form(""), category: str=Form(...), price_per_hour: int=Form(...), price_per_day: int=Form(...), price_per_multi_day: int=Form(...), image_url_1: str=Form(""), image_url_2: str=Form(""), image_url_3: str=Form(""), auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE workspaces SET name=$1, description=$2, category=$3, price_per_hour=$4, price_per_day=$5, price_per_multi_day=$6, image_url_1=$7, image_url_2=$8, image_url_3=$9 WHERE id=$10", name,description,category,price_per_hour,price_per_day,price_per_multi_day,image_url_1,image_url_2,image_url_3,wid)
    return RedirectResponse(url="/admin/workspaces", status_code=303)

@app.get("/admin/workspaces/delete/{wid}")
async def delete_workspace(wid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("DELETE FROM workspaces WHERE id = $1", wid)
    return RedirectResponse(url="/admin/workspaces", status_code=303)

# ------------------- Бронирования -------------------
@app.get("/admin/bookings", response_class=HTMLResponse)
async def list_bookings(request: Request, auth=Depends(authenticate)):
    sort = request.query_params.get('sort', 'created_at')
    order = request.query_params.get('order', 'desc')
    if order not in ('asc','desc'): order='desc'
    allowed_sort = ['created_at', 'start_time', 'end_time', 'workspace_name', 'type', 'hours', 'days', 'master_name', 'price', 'total_price', 'id', 'status']
    if sort not in allowed_sort: sort='created_at'
    sql_sort_map = {
        'created_at': 'b.created_at',
        'start_time': 'b.start_time',
        'end_time': 'b.end_time',
        'workspace_name': 'w.name',
        'type': "CASE WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) < interval '11 hours' THEN 'Почасовая' WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) >= interval '11 hours' THEN 'На день' ELSE 'На несколько дней' END",
        'hours': 'EXTRACT(EPOCH FROM (b.end_time - b.start_time))/3600',
        'days': 'EXTRACT(DAY FROM (b.end_time - b.start_time))',
        'master_name': 'm.full_name',
        'price': 'CASE WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) < interval \'11 hours\' THEN w.price_per_hour WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) >= interval \'11 hours\' THEN w.price_per_day ELSE w.price_per_multi_day END',
        'total_price': 'b.total_price',
        'id': 'b.id',
        'status': 'b.status'
    }
    order_by = f"{sql_sort_map[sort]} {order}"
    query = f"""
        SELECT b.*, m.full_name as master_name, m.id as master_id, w.name as workspace_name,
               w.price_per_hour, w.price_per_day, w.price_per_multi_day,
               CASE
                   WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) < interval '11 hours' THEN 'Почасовая'
                   WHEN b.start_time::date = b.end_time::date AND (b.end_time - b.start_time) >= interval '11 hours' THEN 'На день'
                   ELSE 'На несколько дней'
               END as type,
               EXTRACT(EPOCH FROM (b.end_time - b.start_time))/3600 as hours,
               EXTRACT(DAY FROM (b.end_time - b.start_time)) as days
        FROM bookings b
        JOIN masters m ON b.master_id = m.id
        JOIN workspaces w ON b.workspace_id = w.id
        WHERE 1=1
        ORDER BY {order_by}
    """
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(query)
    table_rows = ""
    for row in rows:
        created_fmt = row['created_at'].strftime('%d.%m.%Y %H:%M') if row['created_at'] else ''
        start_fmt = row['start_time'].strftime('%d.%m.%y %H:%M') if row['start_time'] else ''
        end_fmt = row['end_time'].strftime('%d.%m.%y %H:%M') if row['end_time'] else ''
        status_ru = {'pending':'Ожидает оплаты','paid':'Оплачено','completed':'Завершена','cancelled':'Отменена'}.get(row['status'], row['status'])
        # Вычисляем цену за единицу в зависимости от типа
        if row['type'] == 'Почасовая':
            price_unit = row['price_per_hour'] or 0
        elif row['type'] == 'На день':
            price_unit = row['price_per_day'] or 0
        else:
            price_unit = row['price_per_multi_day'] or 0
        hours_val = int(row['hours']) if row['hours'] else 0
        days_val = int(row['days']) if row['days'] else 1
        # Если total_price не задана или равна 0, вычисляем её
        total_price = row['total_price'] if row['total_price'] else (price_unit * hours_val if row['type'] == 'Почасовая' else price_unit * days_val)
        master_link = f"<a href='#' onclick='showMasterInfo({row['master_id']}); return false;'>{row['master_name']}</a>"
        actions = ""
        if row['status'] == 'pending':
            actions += f"<a href='/admin/bookings/confirm/{row['id']}' class='btn btn-sm btn-success'>Подтвердить оплату</a> "
        if row['status'] != 'cancelled':
            actions += f"<a href='/admin/bookings/cancel/{row['id']}' class='btn btn-sm btn-danger'>Отменить</a> "
        if row['status'] != 'completed':
            actions += f"<a href='/admin/bookings/complete/{row['id']}' class='btn btn-sm btn-secondary'>Завершить</a> "
        table_rows += f"""
            <tr class='booking-row' data-id='{row['id']}' ondblclick='editBooking({row['id']})'>
                <td>{created_fmt}</td>
                <td>{start_fmt}</td>
                <td>{end_fmt}</td>
                <td>{row['workspace_name']}</td>
                <td>{row['type']}</td>
                <td>{hours_val}</td>
                <td>{days_val}</td>
                <td>{master_link}</td>
                <td>{price_unit}</td>
                <td>{total_price}</td>
                <td>{row['id']}</td>
                <td>{status_ru}</td>
                <td>{actions}</td>
            </tr>
        """
    async with app.state.pool.acquire() as conn:
        masters = await conn.fetch("SELECT id, full_name FROM masters ORDER BY full_name")
        workspaces = await conn.fetch("SELECT id, name FROM workspaces ORDER BY name")
    master_options = "".join(f"<option value='{m['id']}'>{m['full_name']}</option>" for m in masters)
    workspace_options = "".join(f"<option value='{w['id']}'>{w['name']}</option>" for w in workspaces)
    # Формируем ссылки для сортировки
    def sort_link(field):
        new_order = 'desc' if sort == field and order == 'asc' else 'asc'
        return f"/admin/bookings?sort={field}&order={new_order}"
    table_header = f"""
    <table class="table table-bordered">
        <thead>
            <tr>
                <th><a href="{sort_link('created_at')}">Время создания брони</a></th>
                <th><a href="{sort_link('start_time')}">Начало</a></th>
                <th><a href="{sort_link('end_time')}">Конец</a></th>
                <th><a href="{sort_link('workspace_name')}">Место</a></th>
                <th><a href="{sort_link('type')}">Тип брони</a></th>
                <th><a href="{sort_link('hours')}">Количество часов</a></th>
                <th><a href="{sort_link('days')}">Количество дней</a></th>
                <th><a href="{sort_link('master_name')}">Мастер</a></th>
                <th><a href="{sort_link('price')}">Цена</a></th>
                <th><a href="{sort_link('total_price')}">Стоимость</a></th>
                <th><a href="{sort_link('id')}">ID</a></th>
                <th><a href="{sort_link('status')}">Статус</a></th>
                <th>Действия</th>
            </tr>
        </thead>
        <tbody>
    """
    content = f"<h2>Бронирования</h2><div style='margin-bottom:20px;'><button class='btn btn-success' data-bs-toggle='modal' data-bs-target='#addBookingModal'>➕ Добавить бронь вручную</button></div>{table_header}{table_rows}</tbody></table>"
    return render("Брони", content, master_options, workspace_options)

@app.post("/admin/bookings/add")
async def add_booking_manual(master_id: int = Form(...), workspace_id: int = Form(...),
                             start_time: str = Form(...), end_time: str = Form(...),
                             total_price: float = Form(...), status: str = Form(...),
                             auth=Depends(authenticate)):
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bookings (master_id, workspace_id, start_time, end_time, status, payment_method, payment_status, total_price, created_at)
            VALUES ($1, $2, $3, $4, $5, 'manual', 'paid', $6, now())
        """, master_id, workspace_id, start, end, status, total_price)
    return RedirectResponse(url="/admin/bookings", status_code=303)

@app.get("/admin/bookings/confirm/{bid}")
async def confirm_booking(bid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='paid', payment_status='paid' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)

@app.get("/admin/bookings/cancel/{bid}")
async def cancel_booking(bid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='cancelled' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)

@app.get("/admin/bookings/complete/{bid}")
async def complete_booking(bid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET status='completed' WHERE id=$1", bid)
    return RedirectResponse(url="/admin/bookings", status_code=303)

@app.get("/admin/bookings/get/{bid}")
async def get_booking_json(bid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, master_id, workspace_id, start_time, end_time, total_price, status FROM bookings WHERE id = $1", bid)
        if not row: raise HTTPException(404)
        return JSONResponse({
            "id": row['id'],
            "master_id": row['master_id'],
            "workspace_id": row['workspace_id'],
            "start_time": row['start_time'].isoformat(),
            "end_time": row['end_time'].isoformat(),
            "total_price": float(row['total_price']),
            "status": row['status']
        })

@app.post("/admin/bookings/edit/{bid}")
async def edit_booking(bid: int, master_id: int = Form(...), workspace_id: int = Form(...),
                       start_time: str = Form(...), end_time: str = Form(...),
                       total_price: float = Form(...), status: str = Form(...),
                       auth=Depends(authenticate)):
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            UPDATE bookings
            SET master_id=$1, workspace_id=$2, start_time=$3, end_time=$4, total_price=$5, status=$6
            WHERE id=$7
        """, master_id, workspace_id, start, end, total_price, status, bid)
    return JSONResponse({"success": True})

# ------------------- Мастера -------------------
@app.get("/admin/masters", response_class=HTMLResponse)
async def list_masters(request: Request, auth=Depends(authenticate)):
    sort = request.query_params.get('sort', 'id')
    order = request.query_params.get('order', 'asc')
    if order not in ('asc','desc'): order='asc'
    allowed=['id','full_name','telegram_id','created_at']
    if sort not in allowed: sort='id'
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM masters ORDER BY {sort} {order}")
    table_rows = ""
    for row in rows:
        created_fmt = row['created_at'].strftime('%d.%m.%Y %H:%M:%S') if row['created_at'] else ''
        table_rows += f"<tr><td>{row['id']}</td><td>{row['full_name'] or ''}</td><td>{row['telegram_id']}</td><td>{row['phone'] or ''}</td><td>{created_fmt}</td><td>{'Активен' if not row['is_blocked'] else 'Заблокирован'}</td><td><button class='btn btn-sm btn-primary' onclick='editMaster({row['id']})'>✏️ Ред.</button> {'<a href=\"/admin/masters/block/'+str(row['id'])+'\" class=\"btn btn-sm btn-warning\">Заблокировать</a>' if not row['is_blocked'] else '<a href=\"/admin/masters/unblock/'+str(row['id'])+'\" class=\"btn btn-sm btn-success\">Разблокировать</a>'}</td></tr>"
    asc_desc = "asc" if order=="desc" else "desc"
    content = f"<h2>Мастера</h2><button class='btn btn-primary mb-3' data-bs-toggle='modal' data-bs-target='#addMasterModal'>➕ Добавить мастера</button><table class='table table-bordered'><thead><tr><th><a href='/admin/masters?sort=id&order={asc_desc}'>ID</a></th><th><a href='/admin/masters?sort=full_name&order={asc_desc}'>Имя</a></th><th><a href='/admin/masters?sort=telegram_id&order={asc_desc}'>Telegram ID</a></th><th>Телефон</th><th><a href='/admin/masters?sort=created_at&order={asc_desc}'>Дата регистрации</a></th><th>Статус</th><th>Действия</th></tr></thead><tbody>{table_rows}</tbody></table>"
    return render("Мастера", content)

@app.post("/admin/masters/add")
async def add_master(full_name: str = Form(...), phone: str = Form(None), notes: str = Form(None), auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        last_id = await conn.fetchval("SELECT COALESCE(MIN(telegram_id), 0) FROM masters WHERE telegram_id < 0")
        new_telegram_id = (last_id - 1) if last_id < 0 else -1
        await conn.execute("INSERT INTO masters (telegram_id, full_name, phone, notes, created_at) VALUES ($1,$2,$3,$4,now())", new_telegram_id, full_name, phone, notes)
    return RedirectResponse(url="/admin/masters", status_code=303)

@app.get("/admin/masters/block/{mid}")
async def block_master(mid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET is_blocked=true WHERE id=$1", mid)
    return RedirectResponse(url="/admin/masters", status_code=303)

@app.get("/admin/masters/unblock/{mid}")
async def unblock_master(mid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET is_blocked=false WHERE id=$1", mid)
    return RedirectResponse(url="/admin/masters", status_code=303)

@app.get("/admin/master_info/{mid}")
async def master_info(mid: int, auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, full_name, telegram_id, phone, notes, is_blocked FROM masters WHERE id = $1", mid)
        if not row: raise HTTPException(404)
        return JSONResponse(dict(row))

@app.post("/admin/masters/edit_ajax/{mid}")
async def edit_master_ajax(mid: int, full_name: str = Form(None), phone: str = Form(None), notes: str = Form(None), auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        await conn.execute("UPDATE masters SET full_name=$1, phone=$2, notes=$3 WHERE id=$4", full_name, phone, notes, mid)
    return JSONResponse({"success": True})

# ------------------- Статистика и финансы -------------------
@app.get("/admin/statistics", response_class=HTMLResponse)
async def statistics(auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        pending = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='pending'")
        paid = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='paid'")
        completed = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='completed'")
        cancelled = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE status='cancelled'")
        top = await conn.fetch("SELECT w.name, COUNT(b.id) as count FROM bookings b JOIN workspaces w ON b.workspace_id=w.id GROUP BY w.id ORDER BY count DESC LIMIT 5")
    top_html = "<ul>" + "".join(f"<li>{row['name']} – {row['count']} брони</li>" for row in top) + "</ul>"
    content = f"<h2>Статистика (текстовая)</h2><div class='row'><div class='col-md-6'><h4>Брони по статусам</h4><ul><li>Ожидают оплаты: {pending}</li><li>Оплачены: {paid}</li><li>Завершены: {completed}</li><li>Отменены: {cancelled}</li></ul></div><div class='col-md-6'><h4>Загрузка мест (топ-5)</h4>{top_html}</div></div>"
    return render("Статистика", content)

@app.get("/admin/finance", response_class=HTMLResponse)
async def finance(auth=Depends(authenticate)):
    async with app.state.pool.acquire() as conn:
        stars_total = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE payment_method='stars' AND status='paid'")
        rub_total = await conn.fetchval("SELECT COALESCE(SUM(total_price),0) FROM bookings WHERE (payment_method IS NULL OR payment_method!='stars') AND status='paid'")
        masters_stats = await conn.fetch("""
            SELECT m.full_name,
                   COALESCE(SUM(CASE WHEN b.payment_method='stars' THEN b.total_price ELSE 0 END),0) as stars_sum,
                   COALESCE(SUM(CASE WHEN b.payment_method!='stars' OR b.payment_method IS NULL THEN b.total_price ELSE 0 END),0) as rub_sum
            FROM bookings b
            JOIN masters m ON b.master_id = m.id
            WHERE b.status='paid'
            GROUP BY m.id
        """)
        masters_table = "<table class='table table-bordered'><thead><tr><th>Мастер</th><th>Звёзд (оплачено)</th><th>Рублей (оплачено)</th></tr></thead><tbody>" + "".join(f"<tr><td>{row['full_name']}</td><td>{row['stars_sum']}</td><td>{row['rub_sum']}</td></tr>" for row in masters_stats) + "</tbody></table>"
        payment_methods = await conn.fetch("SELECT payment_method, COUNT(*) as cnt, SUM(total_price) as total FROM bookings WHERE status='paid' GROUP BY payment_method")
        methods_table = "<table class='table table-bordered'><thead><tr><th>Способ оплаты</th><th>Количество</th><th>Сумма (в единицах валюты)</th></tr></thead><tbody>" + "".join(f"<tr><td>{pm['payment_method'] or 'Не указан'}</td><td>{pm['cnt']}</td><td>{pm['total']}</td></tr>" for pm in payment_methods) + "</tbody></table>"
        content = f"<h2>Финансовая статистика</h2><div class='row'><div class='col-md-6'><div class='card mb-3'><div class='card-header'>Общая выручка (оплаченные брони)</div><div class='card-body'><h5>Рубли: {rub_total} руб</h5><h5>Звёзды (Telegram Stars): {stars_total}</h5></div></div></div><div class='col-md-6'><div class='card'><div class='card-header'>Выручка по способам оплаты</div><div class='card-body'>{methods_table}</div></div></div></div><div class='row mt-4'><div class='col-md-12'><h4>Выручка по мастерам</h4>{masters_table}</div></div>"
    return render("Финансы", content)

@app.get("/logout")
async def logout():
    return RedirectResponse(url="/admin")

@app.get("/admin/logs", response_class=HTMLResponse)
async def logs_dashboard(auth=Depends(authenticate)):
    # Страница для просмотра логов
    content = """
    <h2>Системные логи</h2>
    <div class="row">
        <div class="col-md-3">
            <div class="mb-3">
                <label>Сервис</label>
                <select id="service" class="form-control">
                    <option value="bot">Telegram бот</option>
                    <option value="admin">Админ-панель</option>
                    <option value="nginx">Nginx (ошибки)</option>
                    <option value="nginx-access">Nginx (доступ)</option>
                </select>
            </div>
        </div>
        <div class="col-md-3">
            <div class="mb-3">
                <label>Количество строк</label>
                <input type="number" id="lines" value="100" class="form-control">
            </div>
        </div>
        <div class="col-md-3">
            <div class="mb-3">
                <label>&nbsp;</label>
                <button id="fetchLogsBtn" class="btn btn-primary d-block">Показать логи</button>
            </div>
        </div>
        <div class="col-md-3">
            <div class="mb-3">
                <label>&nbsp;</label>
                <button id="autoRefreshBtn" class="btn btn-secondary d-block">Автообновление (выкл)</button>
            </div>
        </div>
    </div>
    <div class="row">
        <div class="col-md-12">
            <pre id="logContent" style="background: #f4f4f4; padding: 10px; height: 500px; overflow-y: scroll;"></pre>
        </div>
    </div>
    <script>
        let autoRefresh = false;
        let intervalId = null;
        const serviceSelect = document.getElementById('service');
        const linesInput = document.getElementById('lines');
        const fetchBtn = document.getElementById('fetchLogsBtn');
        const autoRefreshBtn = document.getElementById('autoRefreshBtn');
        const logContent = document.getElementById('logContent');

        async function fetchLogs() {
            const service = serviceSelect.value;
            const lines = linesInput.value;
            const response = await fetch(`/admin/api/logs?service=${service}&lines=${lines}`);
            const data = await response.json();
            if (data.logs) {
                logContent.textContent = data.logs.join('\\n');
            } else {
                logContent.textContent = 'Ошибка: ' + (data.error || 'неизвестная ошибка');
            }
        }

        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            if (autoRefresh) {
                intervalId = setInterval(fetchLogs, 5000); // каждые 5 секунд
                autoRefreshBtn.textContent = 'Автообновление (вкл)';
                autoRefreshBtn.classList.remove('btn-secondary');
                autoRefreshBtn.classList.add('btn-warning');
            } else {
                if (intervalId) clearInterval(intervalId);
                autoRefreshBtn.textContent = 'Автообновление (выкл)';
                autoRefreshBtn.classList.remove('btn-warning');
                autoRefreshBtn.classList.add('btn-secondary');
            }
        }

        fetchBtn.addEventListener('click', fetchLogs);
        autoRefreshBtn.addEventListener('click', toggleAutoRefresh);
        fetchLogs(); // первая загрузка
    </script>
    """
    return render("Логи", content)

@app.get("/admin/api/logs")
async def api_get_logs(service: str, lines: int = 100, auth=Depends(authenticate)):
    allowed_services = ['bot', 'admin', 'nginx', 'nginx-access']
    if service not in allowed_services:
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
        if result.returncode != 0:
            logs = result.stderr.split('\n')
        else:
            logs = result.stdout.split('\n')
        logs = logs[-lines:]
        return JSONResponse({"logs": logs})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)