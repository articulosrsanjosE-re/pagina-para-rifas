import os, sqlite3, secrets, io, csv, hmac
from datetime import datetime
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, request, session, redirect, render_template_string, abort, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__, static_folder='public')
app.secret_key = os.environ['SECRET_KEY']
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('HTTPS', '1') == '1',
    MAX_CONTENT_LENGTH=16384,
)

DB = os.getenv('DB_PATH', 'data/rifa.sqlite')
DATABASE_URL = os.getenv('DATABASE_URL')
BASE = os.environ['PUBLIC_URL'].rstrip('/')

if not DATABASE_URL:
    os.makedirs(os.path.dirname(DB) or '.', exist_ok=True)


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _PgConn:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()

    def execute(self, sql, params=()):
        s = sql.strip()
        if s.upper() == 'BEGIN IMMEDIATE':
            return _PgCursor(self._conn.cursor())
        if s.startswith('INSERT OR IGNORE INTO tickets(code) VALUES(?)'):
            s = 'INSERT INTO tickets(code) VALUES(%s) ON CONFLICT (code) DO NOTHING'
        else:
            s = s.replace('?', '%s')
        cur = self._conn.cursor()
        cur.execute(s, params)
        return _PgCursor(cur)

    def executemany(self, sql, seq):
        s = sql.replace('?', '%s')
        cur = self._conn.cursor()
        cur.executemany(s, seq)
        return _PgCursor(cur)


def db():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return _PgConn(conn)
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def now():
    return datetime.now(ZoneInfo('America/Guatemala')).strftime('%Y-%m-%dT%H:%M')


def generate(c, n):
    out = []
    while len(out) < n:
        k = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(10))
        if c.execute('INSERT OR IGNORE INTO tickets(code) VALUES(?)', (k,)).rowcount:
            out.append(k)
    return out


with db() as c:
    if DATABASE_URL:
        c.execute('CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS tickets(code TEXT PRIMARY KEY, name TEXT, address TEXT, phone TEXT, country TEXT, registered TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS winners(id SERIAL PRIMARY KEY, code TEXT UNIQUE, prize TEXT, drawn TEXT)')
    else:
        c.executescript('''CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY,v TEXT); CREATE TABLE IF NOT EXISTS tickets(code TEXT PRIMARY KEY,name TEXT,address TEXT,phone TEXT,country TEXT,registered TEXT); CREATE TABLE IF NOT EXISTS winners(id INTEGER PRIMARY KEY,code TEXT UNIQUE,prize TEXT,drawn TEXT);''')
    c.execute('BEGIN IMMEDIATE')
    if not c.execute("SELECT 1 FROM config WHERE k='password'").fetchone():
        p = os.environ['ADMIN_PASSWORD']
        assert len(p) >= 12, 'Contraseña inicial de 12 caracteres mínimo'
        c.executemany('INSERT INTO config VALUES(?,?)', [
            ('password', generate_password_hash(p)),
            ('title', 'Gran Rifa de Bendiciones'),
            ('deadline', ''),
            ('closed', '0'),
            ('version', '1'),
        ])
        generate(c, 1000)


def cfg(c, k):
    r = c.execute('SELECT v FROM config WHERE k=?', (k,)).fetchone()
    if not r:
        return ''
    return r['v'] if isinstance(r, dict) else r[0]


def closed(c):
    return cfg(c, 'closed') == '1' or bool(cfg(c, 'deadline') and now() >= cfg(c, 'deadline'))


def token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(32)
    return session['csrf']


@app.before_request
def protect():
    if request.method == 'POST' and not hmac.compare_digest(session.get('csrf', '!'), request.form.get('csrf', '')):
        abort(403)


def admin(f):
    @wraps(f)
    def inner(*a, **kw):
        with db() as c:
            valid = session.get('admin') == cfg(c, 'version')
        if not valid:
            return redirect('/admin')
        return f(*a, **kw)
    return inner


STYLE = '''<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><style>*{box-sizing:border-box}body{background:#f7f1e5;color:#51351e;font:16px system-ui;margin:0}main{max-width:1100px;margin:auto;padding:24px}header{text-align:center}header img{width:180px;border-radius:16px}h1,h2{font-family:Georgia,serif}section,article{background:white;border:1px solid #d9c7a2;border-radius:14px;padding:20px;margin:16px 0}input,select,textarea,button{font:inherit;padding:12px;border:1px solid #c9b48c;border-radius:8px;max-width:100%}label{display:block;margin:12px 0 5px}input,select,textarea{width:100%}button,.btn{background:#76532e;color:white;cursor:pointer;padding:12px;border:0;border-radius:8px;display:inline-block;text-decoration:none;margin:8px 0}a{color:#76532e}table{border-collapse:collapse;width:100%}td,th{padding:9px;text-align:left;border-bottom:1px solid #ddd} .scroll{overflow:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.msg{background:#eee4cc;padding:16px;border-radius:8px}footer{text-align:center;padding:20px}canvas{max-width:100%;height:auto}</style>'''


def page(body, **kw):
    return render_template_string(STYLE + '<main><header><img src="/public/logo.png" alt="San José Artículos Religiosos"><p>✝ &nbsp; Fe, esperanza y bendiciones &nbsp; ✝</p></header>' + body + '<footer>San José · Artículos Religiosos</footer></main>', csrf=token(), **kw)


F = '<input type=hidden name=csrf value="{{csrf}}">'


@app.route('/', methods=['GET', 'POST'])
def public():
    msg = ''
    with db() as c:
        if request.method == 'POST':
            c.execute('BEGIN IMMEDIATE')
            k = request.form.get('code', '').strip().upper()
            row = c.execute('SELECT * FROM tickets WHERE code=?', (k,)).fetchone()
            vals = [request.form.get(x, '').strip() for x in ('name', 'address', 'phone', 'country')]
            if row and row['registered']:
                msg = 'Este código ya fue ingresado anteriormente.'
            elif closed(c):
                msg = 'Las inscripciones han finalizado.'
            elif not row:
                msg = 'Código no válido. Verifica tu tarjeta.'
            elif not all(vals) or any(len(v) > 250 for v in vals) or vals[3] not in ['Guatemala', 'El Salvador', 'Honduras'] or not 7 <= len(''.join(filter(str.isdigit, vals[2]))) <= 15 or request.form.get('consent') != 'yes':
                msg = 'Revisa tus datos y acepta el aviso de privacidad.'
            else:
                c.execute('UPDATE tickets SET name=?,address=?,phone=?,country=?,registered=? WHERE code=?', (*vals, now(), k))
                msg = '¡Felicidades! Ya estás participando en el sorteo. ¡Suerte y muchas bendiciones!'
        return page('''<section style="max-width:520px;margin:auto"><h1>{{title}}</h1>{% if msg %}<p class=msg role=status>{{msg}}</p>{% endif %}{% if not ended %}<form method=post>''' + F + '''<label>Código de tu tarjeta</label><input name=code required maxlength=10 autocomplete=off><label>Nombre completo</label><input name=name required maxlength=150><label>Dirección</label><textarea name=address required maxlength=250></textarea><label>Teléfono</label><input name=phone type=tel required maxlength=25><label>País</label><select name=country><option>Guatemala</option><option>El Salvador</option><option>Honduras</option></select><p><label><input style="width:auto" type=checkbox name=consent value=yes required> Acepto que San José utilice mis datos para administrar la rifa y contactarme si gano. Mi nombre podrá mostrarse en el sorteo.</label></p><button>Participar en el sorteo</button></form>{% else %}<p>Inscripciones cerradas.</p>{% endif %}</section>''', title=cfg(c, 'title'), msg=msg, ended=closed(c))


@app.route('/admin', methods=['GET', 'POST'])
def login():
    with db() as c:
        if session.get('admin') == cfg(c, 'version'):
            return redirect('/panel')
        msg = ''
        if request.method == 'POST':
            if check_password_hash(cfg(c, 'password'), request.form.get('password', '')):
                session.clear()
                session['admin'] = cfg(c, 'version')
                return redirect('/panel')
            msg = 'Contraseña incorrecta.'
    return page('<section style="max-width:420px;margin:auto"><h1>Administración</h1><p>{{msg}}</p><form method=post>' + F + '<label>Contraseña</label><input type=password name=password required><button>Ingresar</button></form></section>', msg=msg)


@app.get('/panel')
@admin
def panel():
    with db() as c:
        rows = c.execute('SELECT * FROM tickets WHERE registered IS NOT NULL ORDER BY registered DESC').fetchall()
        cnt_row = c.execute('SELECT count(*) AS cnt FROM tickets').fetchone()
        total = cnt_row['cnt'] if isinstance(cnt_row, dict) else cnt_row[0]
        wins = c.execute('SELECT w.*,t.name FROM winners w JOIN tickets t USING(code)').fetchall()
        return page('''<h1>{{title}} · Administración</h1><div class=grid><article><h2>{{total}}</h2>Códigos generados</article><article><h2>{{rows|length}}</h2>Inscritos</article><article><h2>{{total-rows|length}}</h2>Disponibles</article></div><section><h2>Tarjetas y QR</h2><img width=150 src=/qr><p>{{base}}</p><form method=post action=/generate>''' + F + '''<label>Cantidad adicional (1–5000)</label><input type=number name=n min=1 max=5000 value=100 required><button>Generar e imprimir nuevos códigos</button></form><a class=btn href=/cards>Imprimir todos los códigos disponibles</a></section><section><h2>Configuración</h2><form method=post action=/settings>''' + F + '''<label>Nombre de la rifa</label><input name=title value="{{title}}" required maxlength=120><label>Cierre de inscripción (hora Guatemala)</label><input type=datetime-local name=deadline value="{{deadline}}"><label>Estado</label><select name=closed><option value=0 {% if not manual %}selected{% endif %}>Abierta</option><option value=1 {% if manual %}selected{% endif %}>Cerrada</option></select><button>Guardar</button></form><form method=post action=/password>''' + F + '''<label>Contraseña actual</label><input type=password name=old required><label>Nueva contraseña (mínimo 12 caracteres)</label><input type=password name=new minlength=12 required><button>Cambiar contraseña</button></form></section><section><h2>Participantes</h2><a class=btn href=/export>Exportar CSV para Excel</a><input id=search placeholder="Buscar nombre, código, país o teléfono" oninput="for(const r of document.querySelectorAll('#participants tbody tr'))r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase())"><div class=scroll><table id=participants><thead><tr><th>Código</th><th>Nombre</th><th>Dirección</th><th>Teléfono</th><th>País</th><th>Fecha</th></tr></thead><tbody>{% for r in rows %}<tr>{% for k in ['code','name','address','phone','country','registered'] %}<td>{{r[k]}}</td>{% endfor %}</tr>{% endfor %}</tbody></table></div></section><section><h2>Sorteo general</h2><p>Cierra las inscripciones antes de sortear. Cada código tiene una oportunidad; un código ganador no vuelve a ganar.</p><a class=btn href=/wheel>Abrir ruleta</a><h3>Ganadores registrados</h3>{% for w in wins %}<p>{{w.prize}} — {{w.name}} ({{w.code}}) · {{w.drawn}}</p>{% endfor %}</section><form method=post action=/logout>''' + F + '<button>Cerrar sesión</button></form>', rows=rows, total=total, wins=wins, title=cfg(c, 'title'), deadline=cfg(c, 'deadline'), manual=cfg(c, 'closed') == '1', base=BASE)


@app.get('/qr')
def qr():
    b = io.BytesIO()
    qrcode.make(BASE + '/').save(b, format='PNG')
    b.seek(0)
    return send_file(b, mimetype='image/png')


def cards(codes, title):
    return page('''<style>.tickets{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.ticket{text-align:center;border:1px dashed #987b4e;padding:8px;break-inside:avoid}.ticket img.logo{width:100px}.ticket img.qr{width:100px}.ticket strong{display:block;font-size:20px;letter-spacing:2px}@media print{@page{size:letter;margin:10mm}header,footer,.no-print{display:none}main{padding:0}.ticket{height:61mm}.ticket img.logo{width:65px}.ticket img.qr{width:75px}.tickets{gap:3mm}body{background:white}}</style><div class=no-print><a href=/panel>Volver</a> <button onclick=print()>Imprimir / Guardar PDF</button><p>{{codes|length}} tarjetas</p></div><div class=tickets>{% for code in codes %}<div class=ticket><img class=logo src=/public/logo.png><div>{{title}}</div><img class=qr src=/qr><div>Escanea y participa</div><strong>{{code}}</strong><small>¡Dios bendiga tu hogar!</small></div>{% endfor %}</div>''', codes=codes, title=title)


@app.post('/generate')
@admin
def gen():
    try:
        n = int(request.form['n'])
        assert 1 <= n <= 5000
    except Exception:
        abort(400)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        codes = generate(c, n)
        title = cfg(c, 'title')
    return cards(codes, title)


@app.get('/cards')
@admin
def allcards():
    with db() as c:
        rows = c.execute('SELECT code FROM tickets WHERE registered IS NULL').fetchall()
        codes = [r['code'] if isinstance(r, dict) else r[0] for r in rows]
        return cards(codes, cfg(c, 'title'))


@app.route('/settings', methods=['POST'])
@admin
def settings():
    title = request.form['title'].strip()
    deadline = request.form['deadline']
    state = request.form['closed']
    if not title or len(title) > 120 or state not in ('0', '1'):
        abort(400)
    if deadline:
        try:
            datetime.strptime(deadline, '%Y-%m-%dT%H:%M')
        except ValueError:
            abort(400)
    with db() as c:
        c.executemany('UPDATE config SET v=? WHERE k=?', [
            (title, 'title'),
            (deadline, 'deadline'),
            (state, 'closed'),
        ])
    return redirect('/panel')


@app.post('/password')
@admin
def password():
    with db() as c:
        if not check_password_hash(cfg(c, 'password'), request.form['old']) or len(request.form['new']) < 12:
            return page('<p>Contraseña incorrecta o demasiado corta.</p><a href=/panel>Volver</a>'), 400
        c.execute('UPDATE config SET v=? WHERE k=?', (generate_password_hash(request.form['new']), 'password'))
        c.execute('UPDATE config SET v=? WHERE k=?', (secrets.token_hex(16), 'version'))
    session.clear()
    return redirect('/admin')


@app.post('/logout')
def logout():
    session.clear()
    return redirect('/admin')


@app.get('/export')
@admin
def export():
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(['Código', 'Nombre', 'Dirección', 'Teléfono', 'País', 'Fecha'])
    with db() as c:
        for r in c.execute('SELECT * FROM tickets WHERE registered IS NOT NULL'):
            vals = list(r.values()) if isinstance(r, dict) else list(r)
            w.writerow(["'" + v if isinstance(v, str) and v and v[0] in '=+-@\t\r' else v for v in vals])
    return send_file(io.BytesIO(('\ufeff' + s.getvalue()).encode()), download_name='participantes.csv', as_attachment=True, mimetype='text/csv')


@app.get('/wheel')
@admin
def wheel():
    with db() as c:
        c.execute('SELECT code,name FROM tickets WHERE registered IS NOT NULL AND code NOT IN (SELECT code FROM winners)')
        entries = [dict(r) for r in c.fetchall()]
        ended = closed(c)
    return page('''<section style="text-align:center"><a href=/panel>Volver</a><h1>Ruleta de bendiciones</h1><p id=count>{{entries|length}} participaciones elegibles</p><canvas id=wheel width=600 height=600></canvas><form id=draw>''' + F + '''<label>Nombre del premio</label><input name=prize required maxlength=150 placeholder="Primer premio"><button {% if not ended or not entries %}disabled{% endif %}>Girar ruleta</button></form><h2 id=result aria-live=polite></h2>{% if not ended %}<p>Cierra las inscripciones primero.</p>{% endif %}<button onclick=location.reload()>Preparar siguiente premio</button></section><script>const entries={{entries|tojson}},cv=document.getElementById('wheel'),ctx=cv.getContext('2d'),n=entries.length;function paint(rot=0){ctx.clearRect(0,0,600,600);if(!n)return;for(let i=0;i<n;i++){let a=i*2*Math.PI/n-Math.PI/2+rot,b=a+2*Math.PI/n;ctx.beginPath();ctx.moveTo(300,300);ctx.arc(300,300,285,a,b);ctx.fillStyle=i%2?'#e6d4ac':'#967344';ctx.fill();if(n<=80){ctx.save();ctx.translate(300,300);ctx.rotate((a+b)/2);ctx.fillStyle=i%2?'#51351e':'white';ctx.font='14px sans-serif';ctx.textAlign='right';ctx.fillText(entries[i].name.slice(0,25),270,4);ctx.restore()}}ctx.fillStyle='#51351e';ctx.beginPath();ctx.moveTo(285,0);ctx.lineTo(315,0);ctx.lineTo(300,35);ctx.fill()}paint();document.getElementById('draw').onsubmit=async e=>{e.preventDefault();let b=e.target.querySelector('button');b.disabled=true;try{let r=await fetch('/draw',{method:'POST',body:new URLSearchParams(new FormData(e.target))});let d=await r.json();if(!r.ok)throw Error(d.error);let i=entries.findIndex(x=>x.code===d.code);let target=12*Math.PI-((i+.5)*2*Math.PI/n),start=performance.now();function frame(t){let p=Math.min(1,(t-start)/5000);paint(target*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(frame);else document.getElementById('result').textContent='¡Felicidades, '+d.name+'! · '+d.prize}requestAnimationFrame(frame)}catch(err){document.getElementById('result').textContent=err.message+' — revisa el historial antes de repetir.'}};</script>''', entries=entries, ended=ended)


@app.post('/draw')
@admin
def draw():
    prize = request.form.get('prize', '').strip()
   if not closed(c) or not prize or len(prize) > 150:
            return jsonify(error='Cierra inscripciones e indica el premio.'), 400
        c.execute('SELECT code,name FROM tickets WHERE registered IS NOT NULL AND code NOT IN (SELECT code FROM winners)')
        rows = [dict(r) for r in c.fetchall()]
        if not rows:
            return jsonify(error='No quedan participantes.'), 400
        r = secrets.choice(rows)
        c.execute('INSERT INTO winners(code,prize,drawn) VALUES(?,?,?)', (r['code'], prize, drawn))
        return jsonify(code=r['code'], name=r['name'], prize=prize)
        return jsonify(code=r['code'], name=r['name'], prize=prize)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000)
