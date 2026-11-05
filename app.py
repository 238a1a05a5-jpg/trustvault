import os, re, secrets, sqlite3, smtplib, ssl, threading, logging, mimetypes
from io import BytesIO
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, g, request, jsonify, session, send_file, render_template, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman


load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "storage"); os.makedirs(STORE, exist_ok=True)
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "trustvault.db"))
PROD = os.environ.get("PRODUCTION") == "1"
IST = timezone(timedelta(hours=5, minutes=30))
ALLOWED = {"pdf", "docx", "xlsx", "pptx", "png", "jpg", "jpeg", "txt", "csv", "mp4"}
ROLES = ("admin", "owner", "viewer")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

def secret(name, make):
    """Read a secret from the environment, else from a local hidden file (created once)."""
    if os.environ.get(name): return os.environ[name]
    p = os.path.join(BASE, "." + name.lower())
    if not os.path.exists(p):
        with open(p, "w") as f: f.write(make())
    return open(p).read().strip()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = secret("SECRET_KEY", lambda: secrets.token_hex(32))
app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=PROD)
Talisman(app, force_https=PROD, content_security_policy=None)
limiter = Limiter(get_remote_address, app=app, default_limits=["200/minute"], storage_uri="memory://")
fernet = Fernet(secret("FILE_KEY", lambda: Fernet.generate_key().decode()).encode())

# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH); g.db.row_factory = sqlite3.Row
    return g.db

def q(sql, args=()):
    cur = db().execute(sql, args); db().commit(); return cur

def log(u, action, detail="", owner_id=None, actor=None):
    """Write one line to the audit trail."""
    q("INSERT INTO audit(ts,actor_id,actor,action,detail,owner_id) VALUES(?,?,?,?,?,?)",
      (datetime.now(timezone.utc).isoformat(), u["id"] if u else None, actor or (u["name"] if u else "-"), action, detail, owner_id))

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

with sqlite3.connect(DB_PATH) as _c:
    _c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT,
        role TEXT DEFAULT 'viewer', must_change INTEGER DEFAULT 0, otp_expires TEXT);
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, orig TEXT, stored TEXT, owner_id INTEGER);
    CREATE TABLE IF NOT EXISTS perms(file_id INTEGER, user_id INTEGER, can_dl INTEGER DEFAULT 0,
        PRIMARY KEY(file_id, user_id));
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, actor_id INTEGER, actor TEXT,
        action TEXT, detail TEXT, owner_id INTEGER);""")
    for _t, _col, _ddl in (("files", "created", "TEXT"), ("files", "size", "INTEGER")):   # upgrade older databases
        if _col not in [r[1] for r in _c.execute(f"PRAGMA table_info({_t})")]:
            _c.execute(f"ALTER TABLE {_t} ADD COLUMN {_col} {_ddl}")

# ---------- mail ----------
def send_mail(to, subject, body):
    def go():
        try:
            u, p = os.environ.get("MAIL_USER"), os.environ.get("MAIL_APP_PASS")
            if not (u and p):                      # no Gmail set up: print instead (local testing)
                print(f"\n[DEV MAIL] To: {to}\nSubject: {subject}\n{body}\n"); return
            m = EmailMessage(); m["From"], m["To"], m["Subject"] = u, to, subject; m.set_content(body)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as s:
                s.login(u, p); s.send_message(m)
        except Exception:
            logging.exception("Mail failed")
    threading.Thread(target=go, daemon=True).start()

# ---------- auth helpers ----------
def current():
    uid = session.get("uid")
    return q("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None

def need(*roles, allow_change=False):
    """Route guard: must be logged in, must have finished the one-time-password step, must have a role."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            u = current()
            if not u: return jsonify(error="Login required"), 401
            if u["must_change"] and not allow_change: return jsonify(error="Set a new password first"), 403
            if roles and u["role"] not in roles: return jsonify(error="Forbidden"), 403
            return f(u, *a, **k)
        return wrapper
    return deco

def body(): return request.get_json(silent=True) or {}

# ---------- pages ----------
@app.get("/")
def home():
    u = current()
    return redirect("/dashboard") if u and not u["must_change"] else render_template("login.html")

@app.get("/dashboard")
def dashboard():
    u = current()
    return render_template("dashboard.html") if u and not u["must_change"] else redirect("/")

# ---------- accounts ----------
def issue_otp(name, email):
    otp = secrets.token_urlsafe(6)
    exp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    send_mail(email, "Your TrustVault account is created",
        f"Hi {name},\n\nYour account is created.\nEmail: {email}\nOne-time password: {otp}\n"
        f"(valid for 24 hours)\n\nSign in with it and set your own password.\n"
        f"Your Drive folder: {os.environ.get('DRIVE_LINK', 'not configured')}")
    return generate_password_hash(otp), exp

@app.post("/register")
@limiter.limit("10 per 15 minutes")
def register():
    d = body(); name = (d.get("name") or "").strip()[:60]; email = (d.get("email") or "").strip().lower()
    if not name or not EMAIL.fullmatch(email): return jsonify(error="Enter a valid name and email"), 400
    msg = jsonify(ok=True, message="If this email can be registered, the password is on its way.")
    old = q("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if old:
        if old["must_change"]:                       # never signed in yet: send a fresh one-time password
            pw, exp = issue_otp(old["name"], email)
            q("UPDATE users SET pw=?, otp_expires=? WHERE id=?", (pw, exp, old["id"]))
        return msg                                    # same answer either way: no email enumeration
    role = "admin" if email == os.environ.get("ADMIN_EMAIL", "").strip().lower() else "viewer"  # role is NEVER taken from the request
    pw, exp = issue_otp(name, email)
    q("INSERT INTO users(name,email,pw,role,must_change,otp_expires) VALUES(?,?,?,?,1,?)", (name, email, pw, role, exp))
    log(None, "account_created", email, actor=name)
    return msg

@app.post("/login")
@limiter.limit("10 per 15 minutes", deduct_when=lambda r: r.status_code != 200)  # only failures count
def login():
    d = body(); u = q("SELECT * FROM users WHERE email=?", ((d.get("email") or "").strip().lower(),)).fetchone()
    if not u or not check_password_hash(u["pw"], d.get("password") or ""):
        log(None, "login_failed", (d.get("email") or "")[:80], actor="unknown")
        return jsonify(error="Wrong email or password"), 401
    if u["must_change"] and u["otp_expires"] and datetime.now(timezone.utc) > datetime.fromisoformat(u["otp_expires"]):
        return jsonify(error="One-time password expired. Create account again with the same email to get a new one."), 401
    session.clear(); session["uid"] = u["id"]; log(u, "login", f"from IP {request.remote_addr}")
    send_mail(u["email"], "New sign-in to TrustVault",
        f"You signed in on {datetime.now(IST):%d %b %Y, %I:%M %p} IST from IP {request.remote_addr}.\n"
        "If this wasn't you, contact the admin.")
    return jsonify(ok=True, role=u["role"], must_change=bool(u["must_change"]))

@app.post("/change-password")
@need(allow_change=True)
def change_password(u):
    pw = body().get("password") or ""
    if len(pw) < 8: return jsonify(error="Password must be at least 8 characters"), 400
    q("UPDATE users SET pw=?, must_change=0, otp_expires=NULL WHERE id=?", (generate_password_hash(pw), u["id"]))
    log(u, "password_set", "first sign-in")
    return jsonify(ok=True)

@app.get("/me")
@need(allow_change=True)
def me(u): return jsonify(name=u["name"], email=u["email"], role=u["role"], must_change=bool(u["must_change"]))

@app.post("/logout")
def logout(): session.clear(); return jsonify(ok=True)

# ---------- admin ----------
@app.get("/users")
@need("admin")
def users(u): return jsonify(users=[dict(r) for r in q("SELECT id,name,email,role FROM users")])

@app.put("/users/<int:uid>/role")
@need("admin")
def set_role(u, uid):
    role = body().get("role")
    if role not in ROLES: return jsonify(error="Invalid role"), 400
    if uid == u["id"] and role != "admin" and q("SELECT COUNT(*) c FROM users WHERE role='admin'").fetchone()["c"] == 1:
        return jsonify(error="Cannot remove the last admin"), 400
    t = q("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    if not t: return jsonify(error="User not found"), 404
    q("UPDATE users SET role=? WHERE id=?", (role, uid)); log(u, "role_changed", f"{t['email']} -> {role}")
    return jsonify(ok=True)

# ---------- files ----------
def can_manage(u, f): return u["role"] == "admin" or f["owner_id"] == u["id"]

@app.post("/upload")
@need("owner", "admin")
def upload(u):
    f = request.files.get("file")
    if not f or not f.filename: return jsonify(error="No file chosen"), 400
    orig = secure_filename(f.filename) or "file"
    if orig.rsplit(".", 1)[-1].lower() not in ALLOWED: return jsonify(error="File type not allowed"), 400
    stored = secrets.token_hex(16) + ".vault"            # random name; real name lives only in the database
    raw = f.read()
    with open(os.path.join(STORE, stored), "wb") as out: out.write(fernet.encrypt(raw))
    cur = q("INSERT INTO files(orig,stored,owner_id,created,size) VALUES(?,?,?,?,?)",
            (orig, stored, u["id"], datetime.now(timezone.utc).isoformat(), len(raw)))
    log(u, "upload", orig, 
        ["id"])
    return jsonify(ok=True, id=cur.lastrowid)

@app.get("/files-list")
@need()
def files_list(u):
    sql = """SELECT f.id, f.orig, f.size, f.created, us.name AS owner,
        (:adm OR f.owner_id=:i OR COALESCE(p.can_dl,0)) AS can_dl, (:adm OR f.owner_id=:i) AS can_manage,
        (f.owner_id=:i) AS mine, (p.user_id IS NOT NULL) AS shared
        FROM files f JOIN users us ON us.id=f.owner_id LEFT JOIN perms p ON p.file_id=f.id AND p.user_id=:i
        WHERE :adm OR f.owner_id=:i OR p.user_id IS NOT NULL ORDER BY f.id DESC"""
    return jsonify(files=[dict(r) for r in q(sql, {"i": u["id"], "adm": int(u["role"] == "admin")})])

@app.get("/access")
@need("owner", "admin")
def access_list(u):
    sql = """SELECT p.file_id, f.orig, p.user_id, us.name, us.email, p.can_dl FROM perms p
        JOIN files f ON f.id=p.file_id JOIN users us ON us.id=p.user_id
        WHERE :adm OR f.owner_id=:i ORDER BY f.id DESC, us.name"""
    return jsonify(grants=[dict(r) for r in q(sql, {"i": u["id"], "adm": int(u["role"] == "admin")})])

@app.get("/audit")
@need()
def audit(u):
    sql = """SELECT ts, actor, action, detail FROM audit WHERE :adm OR actor_id=:i OR owner_id=:i ORDER BY id DESC LIMIT 100"""
    return jsonify(events=[dict(r) for r in q(sql, {"i": u["id"], "adm": int(u["role"] == "admin")})])

@app.put("/profile")
@need()
def profile(u):
    name = (body().get("name") or "").strip()[:60]
    if not name: return jsonify(error="Name cannot be empty"), 400
    q("UPDATE users SET name=? WHERE id=?", (name, u["id"])); log(u, "profile_updated", "name changed")
    return jsonify(ok=True)

@app.post("/upload")
@need()
def profile_password(u):
    d = body()
    if not check_password_hash(u["pw"], d.get("current") or ""): return jsonify(error="Current password is wrong"), 400
    if len(d.get("password") or "") < 8: return jsonify(error="New password must be at least 8 characters"), 400
    q("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(d["password"]), u["id"])); log(u, "password_changed")
    return jsonify(ok=True)

@app.get("/files/<int:fid>")
@need()
def view_file(u, fid):
    f = q("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    p = q("SELECT can_dl FROM perms WHERE file_id=? AND user_id=?", (fid, u["id"])).fetchone()
    if not f or not (can_manage(u, f) or p): return jsonify(error="Forbidden"), 403
    allowed_dl = can_manage(u, f) or bool(p and p["can_dl"])
    want_dl = request.args.get("download") == "1"
    if want_dl and not allowed_dl: return jsonify(error="Download not allowed"), 403
    data = fernet.decrypt(open(os.path.join(STORE, f["stored"]), "rb").read())
    log(u, "download" if want_dl else "view", f["orig"], f["owner_id"])
    r = send_file(BytesIO(data), mimetype=mimetypes.guess_type(f["orig"])[0] or "application/octet-stream",
                  download_name=f["orig"], as_attachment=want_dl)
    r.headers["Cache-Control"] = "no-store"; return r

@app.post("/files/<int:fid>/share")
@need("owner", "admin")
def share(u, fid):
    f = q("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not f or not can_manage(u, f): return jsonify(error="Not your file"), 403
    t = q("SELECT id FROM users WHERE email=?", ((body().get("email") or "").strip().lower(),)).fetchone()
    if not t: return jsonify(error="No user with that email"), 404
    if t["id"] == f["owner_id"]: return jsonify(error="Owner already has access"), 400
    dl = 1 if body().get("canDownload") else 0
    q("INSERT OR REPLACE INTO perms VALUES(?,?,?)", (fid, t["id"], dl))
    log(u, "access_granted", f"{f['orig']} -> {(body().get('email') or '').strip().lower()} ({'DOWNLOAD' if dl else 'READ'})", f["owner_id"])
    return jsonify(ok=True)

@app.delete("/files/<int:fid>/share/<int:uid>")
@need("owner", "admin")
def revoke(u, fid, uid):
    f = q("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not f or not can_manage(u, f): return jsonify(error="Not your file"), 403
    q("DELETE FROM perms WHERE file_id=? AND user_id=?", (fid, uid))
    t = q("SELECT email FROM users WHERE id=?", (uid,)).fetchone()
    log(u, "access_revoked", f"{f['orig']} from {t['email'] if t else uid}", f["owner_id"])
    return jsonify(ok=True)

@app.delete("/files/<int:fid>")
@need("owner", "admin")
def delete_file(u, fid):
    f = q("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not f or not can_manage(u, f): return jsonify(error="Not your file"), 403
    try: os.remove(os.path.join(STORE, f["stored"]))
    except FileNotFoundError: pass
    q("DELETE FROM perms WHERE file_id=?", (fid,)); q("DELETE FROM files WHERE id=?", (fid,))
    log(u, "file_deleted", f["orig"], f["owner_id"])
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
