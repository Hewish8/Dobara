"""Dobara — pre-loved saree shop with an admin back office.

Run:  python app.py        (then open http://127.0.0.1:5000, admin at /admin)
"""
import csv
import io
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from PIL import Image, ImageOps
except ImportError:  # Pillow is optional; photos are then stored as uploaded
    Image = None

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DOBARA_DB", BASE / "instance" / "dobara.db"))
UPLOADS = BASE / "static" / "uploads"
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
STATUSES = ["available", "reserved", "sold", "hidden"]
STATUS_LABELS = {"available": "Available", "reserved": "On hold", "sold": "Sold", "hidden": "Hidden"}
LIST_KINDS = {"occasion": "Categories (occasions)", "fabric": "Fabrics", "condition": "Conditions"}

DEFAULT_SETTINGS = {
    "name": "Dobara",
    "tagline": "Pre-loved sarees, worn once and ready to be draped again.",
    "whatsapp": "",
    "currency": "Rs",
    "sell_title": "Have a saree sitting in your cupboard?",
    "sell_text": "Send us a few photos and what you paid. If it's in good condition, "
                 "we'll list it here and pay you when it sells.",
    "footer": "Questions? Message us on WhatsApp.",
    "steps": json.dumps([
        ["Pick a saree", 'Tap "Order on WhatsApp" and your message is written for you.'],
        ["Ask for more photos", "We'll send close-ups of the border and pallu, blouse measurements "
                                "and a video if you'd like."],
        ["Pay by Juice", "Once you're happy, pay and we'll hold it for you."],
        ["Get it delivered", "Dry-cleaned, folded and shipped within 2 days."],
    ]),
}
DEFAULT_LISTS = {
    "occasion": ["Wedding", "Reception", "Festive", "Party", "Haldi", "Mehendi", "Office"],
    "fabric": ["Kanjeevaram", "Banarasi", "Organza", "Georgette", "Chiffon", "Paithani",
               "Cotton", "Linen", "Tussar", "Chanderi"],
    "condition": ["Like new", "Worn once", "Worn twice", "Gently used"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sarees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    occasion TEXT NOT NULL DEFAULT '',
    fabric TEXT NOT NULL DEFAULT '',
    blouse TEXT NOT NULL DEFAULT '',
    condition TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL DEFAULT 0,
    original INTEGER NOT NULL DEFAULT 0,
    color_main TEXT NOT NULL DEFAULT '#C2185B',
    color_trim TEXT NOT NULL DEFAULT '#E8A317',
    photo TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'available',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sold_at TEXT
);
CREATE TABLE IF NOT EXISTS options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE (kind, name)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    saree_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def load_secret_key():
    if os.environ.get("DOBARA_SECRET_KEY"):
        return os.environ["DOBARA_SECRET_KEY"]
    path = DB_PATH.parent / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DOBARA_SECURE_COOKIES") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    fresh = db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
    for key, value in DEFAULT_SETTINGS.items():
        db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    if fresh:
        for kind, names in DEFAULT_LISTS.items():
            db.executemany("INSERT OR IGNORE INTO options (kind, name) VALUES (?, ?)",
                           [(kind, n) for n in names])
        seed = BASE / "seed.json"
        if seed.exists():
            data = json.loads(seed.read_text(encoding="utf-8"))
            for key, value in data.get("shop", {}).items():
                db.execute("UPDATE settings SET value = ? WHERE key = ?", (str(value), key))
            # Oldest first so the first saree in the file ends up newest.
            for s in reversed(data.get("sarees", [])):
                colors = (s.get("colors") or []) + ["#C2185B", "#E8A317"]
                stamp = now()
                db.execute(
                    """INSERT INTO sarees (name, occasion, fabric, blouse, condition, price, original,
                       color_main, color_trim, photo, status, created_at, updated_at, sold_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (s["name"], s.get("occasion", ""), s.get("fabric", ""), s.get("blouse", ""),
                     s.get("condition", ""), int(s.get("price") or 0), int(s.get("original") or 0),
                     colors[0], colors[1], s.get("photo", ""), s.get("status", "available"),
                     stamp, stamp, stamp if s.get("status") == "sold" else None))
    db.commit()
    db.close()


def get_settings():
    rows = get_db().execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    try:
        s["steps_list"] = json.loads(s["steps"])
    except (ValueError, TypeError):
        s["steps_list"] = json.loads(DEFAULT_SETTINGS["steps"])
    return s


def get_options(kind):
    return [r["name"] for r in get_db().execute(
        "SELECT name FROM options WHERE kind = ? ORDER BY name COLLATE NOCASE", (kind,))]


def get_saree(saree_id):
    row = get_db().execute("SELECT * FROM sarees WHERE id = ?", (saree_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def log_event(kind, saree_id=None):
    db = get_db()
    db.execute("INSERT INTO events (kind, saree_id, created_at) VALUES (?, ?, ?)",
               (kind, saree_id, now()))
    db.commit()


# ---------------------------------------------------------------- helpers

def money(n, currency=None):
    """Indian digit grouping, e.g. 148000 -> 1,48,000 (matches the original en-IN format)."""
    if currency is None:
        currency = get_settings()["currency"] or "Rs"
    n = int(n or 0)
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{currency}{sign}{s}"


def pct_off(price, original):
    price, original = int(price or 0), int(original or 0)
    return round((1 - price / original) * 100) if original > price and original > 0 else 0


def wa_link(text):
    num = "".join(c for c in get_settings()["whatsapp"] if c.isdigit())
    return f"https://wa.me/{num}?text={quote(text)}" if num else None


def photo_url(photo):
    return url_for("static", filename=f"uploads/{photo}") if photo else ""


app.jinja_env.globals.update(money=money, pct_off=pct_off, photo_url=photo_url,
                             STATUS_LABELS=STATUS_LABELS, LIST_KINDS=LIST_KINDS)


def save_photo(file_storage):
    """Validate an uploaded image, shrink it and store it. Returns the stored file name."""
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_EXT:
        raise ValueError("Please upload a JPG, PNG, WEBP or GIF photo.")
    if Image is None:
        name = f"{uuid.uuid4().hex}.{ext}"
        file_storage.save(UPLOADS / name)
        return name
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img)
        img.thumbnail((1400, 1400))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
    except Exception as exc:  # Pillow raises many different error types
        raise ValueError("That file couldn't be read as a photo. Try a JPG or PNG.") from exc
    name = f"{uuid.uuid4().hex}.jpg"
    img.save(UPLOADS / name, "JPEG", quality=82, optimize=True)
    return name


def delete_photo(name):
    if name:
        path = (UPLOADS / name).resolve()
        if path.parent == UPLOADS.resolve() and path.exists():
            path.unlink()


# ---------------------------------------------------------------- security

@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or not secrets.compare_digest(token, request.form.get("_csrf", "")):
            abort(400, "Your session expired. Go back, reload the page and try again.")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def current_user():
    uid = session.get("uid")
    if uid is None:
        return None
    if "user" not in g:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return g.user


app.jinja_env.globals["current_user"] = current_user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            session.pop("uid", None)
            return redirect(url_for("admin_login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


_failed_logins = {}  # ip -> (count, first_failure_time)


def too_many_attempts(ip):
    count, first = _failed_logins.get(ip, (0, 0))
    if time.time() - first > 600:
        _failed_logins.pop(ip, None)
        return False
    return count >= 5


def record_failure(ip):
    count, first = _failed_logins.get(ip, (0, time.time()))
    _failed_logins[ip] = (count + 1, first)


# ---------------------------------------------------------------- shop front

def public_sarees():
    rows = get_db().execute(
        "SELECT * FROM sarees WHERE status != 'hidden' ORDER BY created_at DESC, id DESC").fetchall()
    return [{
        "id": r["id"], "name": r["name"], "occasion": r["occasion"], "fabric": r["fabric"],
        "blouse": r["blouse"], "condition": r["condition"], "description": r["description"],
        "price": r["price"], "original": r["original"], "colors": [r["color_main"], r["color_trim"]],
        "photo": photo_url(r["photo"]), "status": r["status"],
    } for r in rows]


@app.route("/")
def shop():
    s = get_settings()
    data = {"shop": {"name": s["name"], "currency": s["currency"],
                     "hasWhatsapp": bool(wa_link(""))},
            "sarees": public_sarees()}
    return render_template("shop.html", s=s, data=data)


@app.route("/go/order/<int:saree_id>")
def go_order(saree_id):
    r = get_saree(saree_id)
    link = wa_link(f"Hi! I'm interested in the {r['name']} ({r['fabric']}, "
                   f"{money(r['price'])}). Is it still available?")
    if r["status"] != "available" or not link:
        return redirect(url_for("shop") + "#shop")
    log_event("order", saree_id)
    return redirect(link)


@app.route("/go/<kind>")
def go_contact(kind):
    messages = {"sell": "Hi! I'd like to sell my saree. Here are some photos:",
                "alert": "Hi! Please message me when new sarees come in."}
    if kind not in messages:
        abort(404)
    link = wa_link(messages[kind])
    if not link:
        return redirect(url_for("shop"))
    log_event(kind)
    return redirect(link)


# ---------------------------------------------------------------- admin: auth

@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return redirect(url_for("admin_login"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = validate_new_user(username, password, request.form.get("confirm", ""))
        if not error:
            cur = db.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                             (username, generate_password_hash(password), now()))
            db.commit()
            session.clear()
            session["uid"] = cur.lastrowid
            flash("Welcome! Your admin account is ready.")
            return redirect(url_for("admin_dashboard"))
    return render_template("admin/setup.html", error=error)


def validate_new_user(username, password, confirm):
    if not username or len(username) > 40:
        return "Choose a username (up to 40 characters)."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "The two passwords don't match."
    exists = get_db().execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    if exists:
        return "That username is already taken."
    return None


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    db = get_db()
    if not db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return redirect(url_for("admin_setup"))
    if current_user():
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if too_many_attempts(ip):
            error = "Too many failed attempts. Wait 10 minutes and try again."
        else:
            user = db.execute("SELECT * FROM users WHERE username = ?",
                              (request.form.get("username", "").strip(),)).fetchone()
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                _failed_logins.pop(ip, None)
                session.clear()
                session.permanent = True
                session["uid"] = user["id"]
                db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now(), user["id"]))
                db.commit()
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/admin") else url_for("admin_dashboard"))
            record_failure(ip)
            error = "Wrong username or password."
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------- admin: dashboard

@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) AS n FROM sarees GROUP BY status"):
        counts[r["status"]] = r["n"]
    stock_value = db.execute(
        "SELECT COALESCE(SUM(price), 0) FROM sarees WHERE status IN ('available', 'reserved')").fetchone()[0]
    month_start = datetime.now().strftime("%Y-%m-01")
    sales_total = db.execute("SELECT COALESCE(SUM(price), 0) FROM sarees WHERE status = 'sold'").fetchone()[0]
    sales_month = db.execute(
        "SELECT COALESCE(SUM(price), 0), COUNT(*) FROM sarees WHERE status = 'sold' AND sold_at >= ?",
        (month_start,)).fetchone()
    since = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    clicks = {k: 0 for k in ("order", "sell", "alert")}
    for r in db.execute("SELECT kind, COUNT(*) AS n FROM events WHERE created_at >= ? GROUP BY kind", (since,)):
        clicks[r["kind"]] = r["n"]
    top = db.execute(
        """SELECT s.id, s.name, s.status, COUNT(e.id) AS n FROM events e JOIN sarees s ON s.id = e.saree_id
           WHERE e.kind = 'order' AND e.created_at >= ? GROUP BY s.id ORDER BY n DESC LIMIT 5""",
        (since,)).fetchall()
    recent_sold = db.execute(
        "SELECT * FROM sarees WHERE status = 'sold' ORDER BY sold_at DESC LIMIT 5").fetchall()
    on_hold = db.execute("SELECT * FROM sarees WHERE status = 'reserved' ORDER BY updated_at").fetchall()
    return render_template("admin/dashboard.html", counts=counts, stock_value=stock_value,
                           sales_total=sales_total, sales_month=sales_month, clicks=clicks, top=top,
                           recent_sold=recent_sold, on_hold=on_hold,
                           no_whatsapp=not wa_link(""))


# ---------------------------------------------------------------- admin: sarees

@app.route("/admin/sarees")
@login_required
def admin_sarees():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    sql, params = "SELECT * FROM sarees WHERE 1=1", []
    if status in STATUSES:
        sql += " AND status = ?"
        params.append(status)
    for word in q.split():
        sql += " AND (name || ' ' || fabric || ' ' || occasion || ' ' || condition) LIKE ?"
        params.append(f"%{word}%")
    sql += " ORDER BY created_at DESC, id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("admin/sarees.html", rows=rows, q=q, status=status, statuses=STATUSES)


def saree_form_values(form):
    def as_int(key):
        try:
            return max(0, int(float(form.get(key, "0") or 0)))
        except ValueError:
            return 0

    def color(key, default):
        v = form.get(key, "")
        return v if len(v) == 7 and v.startswith("#") else default

    status = form.get("status", "available")
    return {
        "name": form.get("name", "").strip()[:200] or "Untitled saree",
        "occasion": form.get("occasion", "").strip()[:60],
        "fabric": form.get("fabric", "").strip()[:60],
        "condition": form.get("condition", "").strip()[:60],
        "blouse": form.get("blouse", "").strip()[:120],
        "description": form.get("description", "").strip()[:2000],
        "price": as_int("price"),
        "original": as_int("original"),
        "color_main": color("color_main", "#C2185B"),
        "color_trim": color("color_trim", "#E8A317"),
        "status": status if status in STATUSES else "available",
    }


def remember_options(values):
    db = get_db()
    for kind in LIST_KINDS:
        if values.get(kind):
            db.execute("INSERT OR IGNORE INTO options (kind, name) VALUES (?, ?)", (kind, values[kind]))


@app.route("/admin/sarees/new", methods=["GET", "POST"])
@app.route("/admin/sarees/<int:saree_id>/edit", methods=["GET", "POST"])
@login_required
def admin_saree_form(saree_id=None):
    db = get_db()
    row = get_saree(saree_id) if saree_id else None
    if request.method == "POST":
        values = saree_form_values(request.form)
        photo = row["photo"] if row else ""
        upload = request.files.get("photo")
        if upload and upload.filename:
            try:
                new_photo = save_photo(upload)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("admin/saree_form.html", row=values | {"id": saree_id, "photo": photo},
                                       options={k: get_options(k) for k in LIST_KINDS}, statuses=STATUSES)
            delete_photo(photo)
            photo = new_photo
        elif request.form.get("remove_photo"):
            delete_photo(photo)
            photo = ""
        values["photo"] = photo
        stamp = now()
        if row:
            sold_at = row["sold_at"]
            if values["status"] == "sold" and row["status"] != "sold":
                sold_at = stamp
            elif values["status"] != "sold":
                sold_at = None
            db.execute(
                """UPDATE sarees SET name=:name, occasion=:occasion, fabric=:fabric, condition=:condition,
                   blouse=:blouse, description=:description, price=:price, original=:original,
                   color_main=:color_main, color_trim=:color_trim, photo=:photo, status=:status,
                   updated_at=:updated_at, sold_at=:sold_at WHERE id=:id""",
                values | {"updated_at": stamp, "sold_at": sold_at, "id": saree_id})
            flash(f'Saved "{values["name"]}".')
        else:
            db.execute(
                """INSERT INTO sarees (name, occasion, fabric, condition, blouse, description, price, original,
                   color_main, color_trim, photo, status, created_at, updated_at, sold_at)
                   VALUES (:name, :occasion, :fabric, :condition, :blouse, :description, :price, :original,
                   :color_main, :color_trim, :photo, :status, :created_at, :created_at, :sold_at)""",
                values | {"created_at": stamp, "sold_at": stamp if values["status"] == "sold" else None})
            flash(f'Added "{values["name"]}".')
        remember_options(values)
        db.commit()
        return redirect(url_for("admin_sarees"))
    blank = {"id": None, "name": "", "occasion": "", "fabric": "", "condition": "Like new", "blouse": "",
             "description": "", "price": "", "original": "", "color_main": "#C2185B",
             "color_trim": "#E8A317", "photo": "", "status": "available"}
    return render_template("admin/saree_form.html", row=row or blank,
                           options={k: get_options(k) for k in LIST_KINDS}, statuses=STATUSES)


@app.route("/admin/sarees/<int:saree_id>/status", methods=["POST"])
@login_required
def admin_saree_status(saree_id):
    row = get_saree(saree_id)
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400)
    sold_at = row["sold_at"] if status == "sold" and row["status"] == "sold" else (now() if status == "sold" else None)
    db = get_db()
    db.execute("UPDATE sarees SET status = ?, sold_at = ?, updated_at = ? WHERE id = ?",
               (status, sold_at, now(), saree_id))
    db.commit()
    flash(f'"{row["name"]}" is now {STATUS_LABELS[status].lower()}.')
    return redirect(request.form.get("back") or url_for("admin_sarees"))


@app.route("/admin/sarees/<int:saree_id>/delete", methods=["POST"])
@login_required
def admin_saree_delete(saree_id):
    row = get_saree(saree_id)
    db = get_db()
    db.execute("DELETE FROM sarees WHERE id = ?", (saree_id,))
    db.execute("UPDATE events SET saree_id = NULL WHERE saree_id = ?", (saree_id,))
    db.commit()
    delete_photo(row["photo"])
    flash(f'Deleted "{row["name"]}".')
    return redirect(url_for("admin_sarees"))


@app.route("/admin/sarees/export.csv")
@login_required
def admin_export_csv():
    rows = get_db().execute("SELECT * FROM sarees ORDER BY id").fetchall()
    out = io.StringIO()
    cols = ["id", "name", "status", "occasion", "fabric", "condition", "blouse", "price", "original",
            "description", "created_at", "sold_at"]
    writer = csv.writer(out)
    writer.writerow(cols)
    for r in rows:
        writer.writerow([r[c] for c in cols])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=dobara-sarees.csv"})


# ---------------------------------------------------------------- admin: lists

@app.route("/admin/lists")
@login_required
def admin_lists():
    db = get_db()
    lists = {}
    for kind in LIST_KINDS:
        lists[kind] = db.execute(
            f"""SELECT o.id, o.name, (SELECT COUNT(*) FROM sarees s WHERE s.{kind} = o.name) AS used
                FROM options o WHERE o.kind = ? ORDER BY o.name COLLATE NOCASE""", (kind,)).fetchall()
    return render_template("admin/lists.html", lists=lists)


@app.route("/admin/lists/add", methods=["POST"])
@login_required
def admin_list_add():
    kind, name = request.form.get("kind"), request.form.get("name", "").strip()[:60]
    if kind not in LIST_KINDS or not name:
        flash("Type a name to add.", "error")
    else:
        db = get_db()
        db.execute("INSERT OR IGNORE INTO options (kind, name) VALUES (?, ?)", (kind, name))
        db.commit()
        flash(f'Added "{name}".')
    return redirect(url_for("admin_lists") + f"#{kind}")


@app.route("/admin/lists/<int:option_id>/rename", methods=["POST"])
@login_required
def admin_list_rename(option_id):
    db = get_db()
    opt = db.execute("SELECT * FROM options WHERE id = ?", (option_id,)).fetchone()
    if opt is None:
        abort(404)
    name = request.form.get("name", "").strip()[:60]
    if not name:
        flash("The name can't be empty.", "error")
    elif name != opt["name"]:
        if db.execute("SELECT 1 FROM options WHERE kind = ? AND name = ?", (opt["kind"], name)).fetchone():
            db.execute("DELETE FROM options WHERE id = ?", (option_id,))  # merge into existing entry
        else:
            db.execute("UPDATE options SET name = ? WHERE id = ?", (name, option_id))
        # kind comes from our own table and is one of LIST_KINDS, so it's safe as a column name
        db.execute(f"UPDATE sarees SET {opt['kind']} = ? WHERE {opt['kind']} = ?", (name, opt["name"]))
        db.commit()
        flash(f'Renamed "{opt["name"]}" to "{name}" (sarees updated too).')
    return redirect(url_for("admin_lists") + f"#{opt['kind']}")


@app.route("/admin/lists/<int:option_id>/delete", methods=["POST"])
@login_required
def admin_list_delete(option_id):
    db = get_db()
    opt = db.execute("SELECT * FROM options WHERE id = ?", (option_id,)).fetchone()
    if opt is None:
        abort(404)
    db.execute("DELETE FROM options WHERE id = ?", (option_id,))
    db.commit()
    flash(f'Removed "{opt["name"]}" from the list. Sarees already using it keep it.')
    return redirect(url_for("admin_lists") + f"#{opt['kind']}")


# ---------------------------------------------------------------- admin: settings

@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        f = request.form
        steps = []
        for title, body in zip(f.getlist("step_title"), f.getlist("step_body")):
            if title.strip() or body.strip():
                steps.append([title.strip()[:80], body.strip()[:400]])
        values = {
            "name": f.get("name", "").strip()[:60] or "Dobara",
            "tagline": f.get("tagline", "").strip()[:200],
            "whatsapp": "".join(c for c in f.get("whatsapp", "") if c.isdigit())[:20],
            "currency": f.get("currency", "").strip()[:8],
            "sell_title": f.get("sell_title", "").strip()[:120],
            "sell_text": f.get("sell_text", "").strip()[:600],
            "footer": f.get("footer", "").strip()[:200],
            "steps": json.dumps(steps),
        }
        db = get_db()
        db.executemany("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", values.items())
        db.commit()
        flash("Shop settings saved. They're live on the shop now.")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", s=get_settings())


# ---------------------------------------------------------------- admin: users

@app.route("/admin/users", methods=["GET", "POST"])
@login_required
def admin_users():
    db = get_db()
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = validate_new_user(username, password, request.form.get("confirm", ""))
        if not error:
            db.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                       (username, generate_password_hash(password), now()))
            db.commit()
            flash(f'Added admin "{username}".')
            return redirect(url_for("admin_users"))
    users = db.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE").fetchall()
    return render_template("admin/users.html", users=users, error=error)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_user_delete(user_id):
    if user_id == current_user()["id"]:
        flash("You can't delete your own account while signed in.", "error")
    else:
        db = get_db()
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
        flash("Admin removed.")
    return redirect(url_for("admin_users"))


@app.route("/admin/account", methods=["GET", "POST"])
@login_required
def admin_account():
    error = None
    if request.method == "POST":
        user = current_user()
        new = request.form.get("new", "")
        if not check_password_hash(user["password_hash"], request.form.get("current", "")):
            error = "Your current password is wrong."
        elif len(new) < 8:
            error = "New password must be at least 8 characters."
        elif new != request.form.get("confirm", ""):
            error = "The two new passwords don't match."
        else:
            db = get_db()
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                       (generate_password_hash(new), user["id"]))
            db.commit()
            flash("Password changed.")
            return redirect(url_for("admin_account"))
    return render_template("admin/account.html", error=error)


# ---------------------------------------------------------------- admin: backup

@app.route("/admin/backup.json")
@login_required
def admin_backup():
    db = get_db()
    s = get_settings()
    data = {
        "exported_at": now(),
        "shop": {k: s[k] for k in DEFAULT_SETTINGS},
        "options": {k: get_options(k) for k in LIST_KINDS},
        "sarees": [dict(r) for r in db.execute("SELECT * FROM sarees ORDER BY id")],
    }
    return Response(json.dumps(data, indent=2, ensure_ascii=False), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=dobara-backup.json"})


@app.route("/healthz")
def healthz():
    return jsonify(ok=True)


@app.errorhandler(413)
def too_large(_e):
    flash("That photo is too big (max 12 MB).", "error")
    return redirect(request.referrer or url_for("admin_sarees"))


init_db()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
