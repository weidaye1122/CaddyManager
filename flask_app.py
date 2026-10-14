"""Caddy Manager Lite powered by Flask for the personal server deployment."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, make_response, request, send_from_directory
from werkzeug.exceptions import HTTPException


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = Path(os.environ.get("CADDY_MANAGER_DATA", str(ROOT / "data")))
SITES_FILE = DATA_DIR / "sites.json"
AUTH_FILE = DATA_DIR / "auth.json"
BACKUP_DIR = DATA_DIR / "backups"
CADDYFILE = Path(os.environ.get("CADDYFILE", "/etc/caddy/Caddyfile"))
CADDY_BIN = os.environ.get("CADDY_BIN", "caddy")
HOST = os.environ.get("CADDY_MANAGER_HOST", "127.0.0.1")
PORT = int(os.environ.get("CADDY_MANAGER_PORT", "7080"))
SKIP_CADDY = os.environ.get("CADDY_MANAGER_SKIP_CADDY") == "1"
SESSION_TTL = 12 * 60 * 60

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
mutation_lock = threading.RLock()
sites: list[dict] = []
auth: dict | None = None
sessions: dict[str, dict] = {}
site_statuses: dict[str, dict] = {}
probe_versions: dict[str, str] = {}


@app.before_request
def serialize_api_requests():
    if request.path.startswith('/api/'):
        mutation_lock.acquire()
        request.environ['manager_lock_held'] = True


@app.teardown_request
def release_api_lock(exc):
    if request.environ.pop('manager_lock_held', False):
        mutation_lock.release()


@app.after_request
def response_headers(response):
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'no-cache'
    return response


@app.errorhandler(Exception)
def handle_error(exc):
    if request.path.startswith('/api/'):
        code = exc.code if isinstance(exc, HTTPException) else 500
        app.logger.error('API error: %s', exc)
        return error(str(exc), code)
    if isinstance(exc, HTTPException):
        return exc
    app.logger.exception('Request failed')
    return error('服务器错误', 500)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temp.write_text(content, encoding="utf-8")
    os.chmod(temp, mode)
    temp.replace(path)


def load_data() -> None:
    global sites, auth
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        sites = json.loads(SITES_FILE.read_text(encoding="utf-8"))
        if not isinstance(sites, list):
            raise ValueError("sites.json must contain an array")
    except FileNotFoundError:
        sites = []
        save_sites()
    except Exception as exc:
        app.logger.warning("无法读取 %s: %s", SITES_FILE, exc)
        sites = []
    try:
        auth = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if not isinstance(auth, dict) or not all(key in auth for key in ("username", "salt", "hash")):
            auth = None
    except FileNotFoundError:
        auth = None
    except Exception as exc:
        app.logger.warning("无法读取 %s: %s", AUTH_FILE, exc)
        auth = None


def save_sites() -> None:
    atomic_write(SITES_FILE, json.dumps(sites, ensure_ascii=False, indent=2) + "\n")


def save_auth() -> None:
    atomic_write(AUTH_FILE, json.dumps(auth, ensure_ascii=False, indent=2) + "\n", 0o600)
    AUTH_FILE.chmod(0o600)


def hash_password(password: str, salt: str, algorithm: str = 'scrypt') -> str:
    # Unlabelled hashes created by the Node version use these scrypt parameters.
    if algorithm == 'scrypt':
        if not hasattr(hashlib, 'scrypt'):
            raise RuntimeError('当前 Python 不支持原账号的 scrypt，请使用支持 scrypt 的 Python')
        return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()
    if algorithm == 'pbkdf2-sha256':
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000, dklen=64).hex()
    raise ValueError('密码哈希格式不受支持')


def password_valid(password: str) -> bool:
    return isinstance(password, str) and 8 <= len(password) <= 128


def username_valid(username: str) -> bool:
    return 3 <= len(username) <= 32 and username.isascii() and all(char.isalnum() or char in "_.-" for char in username)


def session_user() -> str | None:
    token = request.cookies.get("caddy_manager_session")
    item = sessions.get(token or "")
    if not item:
        return None
    if item["expires_at"] <= time.time():
        sessions.pop(token, None)
        return None
    item["expires_at"] = time.time() + SESSION_TTL
    return item["username"]


def login_response(body: dict, username: str, status: int = 200):
    token = secrets.token_hex(32)
    sessions[token] = {"username": username, "expires_at": time.time() + SESSION_TTL}
    response = make_response(jsonify(body), status)
    response.set_cookie("caddy_manager_session", token, max_age=SESSION_TTL, httponly=True, samesite="Strict")
    return response


def error(message: str, status: int = 400):
    return jsonify(error=message), status


def validate_site(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("请求内容无效")
    domain = str(payload.get("domain", "")).strip().lower()
    upstream = str(payload.get("upstream", "")).strip()
    protocol = "https" if payload.get("upstreamProtocol") == "https" else "http"
    note = str(payload.get("note", "")).strip()
    import re
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain, re.I):
        raise ValueError("请输入有效域名，例如 ha.example.com")
    if not re.fullmatch(r"[a-z0-9.:[\]\-]+:\d{1,5}", upstream, re.I):
        raise ValueError("上游地址应为 host:port，例如 127.0.0.1:8123")
    port = int(upstream.rsplit(":", 1)[1])
    if not 1 <= port <= 65535:
        raise ValueError("上游端口范围应为 1-65535")
    if len(note) > 120:
        raise ValueError("备注不能超过 120 个字符")
    return {"domain": domain, "upstream": upstream, "upstreamProtocol": protocol, "enabled": payload.get("enabled") is not False, "note": note}


def caddyfile_for(current_sites: list[dict]) -> str:
    active = [site for site in current_sites if site.get("enabled")]
    if not active:
        return "# 暂无启用的反代站点\n"
    blocks = []
    for site in active:
        target = f"https://{site['upstream']}" if site.get("upstreamProtocol") == "https" else site["upstream"]
        blocks.append(f"{site['domain']} {{\n    reverse_proxy {target}\n}}")
    return "\n\n".join(blocks) + "\n"


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


def validate_and_reload(next_sites: list[dict]) -> dict:
    config = caddyfile_for(next_sites)
    if SKIP_CADDY:
        return {"config": config, "skipped": True, "message": "已跳过 Caddy 命令（开发模式）"}
    CADDYFILE.parent.mkdir(parents=True, exist_ok=True)
    candidate = CADDYFILE.with_name(f"{CADDYFILE.name}.candidate-{os.getpid()}")
    candidate.write_text(config, encoding="utf-8")
    validation = run([CADDY_BIN, "validate", "--config", str(candidate), "--adapter", "caddyfile"])
    if validation.returncode != 0:
        candidate.unlink(missing_ok=True)
        raise RuntimeError(f"Caddy 配置校验失败：{(validation.stderr or validation.stdout).strip()}")
    backup = BACKUP_DIR / f"Caddyfile-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.bak"
    if CADDYFILE.exists():
        shutil.copy2(CADDYFILE, backup)
    candidate.replace(CADDYFILE)
    reload = run([CADDY_BIN, "reload", "--config", str(CADDYFILE), "--adapter", "caddyfile"])
    if reload.returncode != 0:
        if backup.exists():
            shutil.copy2(backup, CADDYFILE)
            run([CADDY_BIN, "reload", "--config", str(CADDYFILE), "--adapter", "caddyfile"])
        raise RuntimeError(f"Caddy reload 失败，已恢复旧配置：{(reload.stderr or reload.stdout).strip()}")
    return {"config": config, "skipped": False, "message": "配置已校验并应用"}


def status_for(site: dict) -> dict:
    return site_statuses.get(site["id"], {"state": "unknown" if site.get("enabled") else "disabled", "message": "等待检查"})


def set_status(site: dict, state: str, **extra) -> None:
    site_statuses[site["id"]] = {"state": state, "checkedAt": now_iso(), **extra}


def probe_certificate(site: dict, attempt: int = 0, version: str | None = None) -> None:
    if version is None:
        version = secrets.token_hex(8)
        probe_versions[site['id']] = version
    def current():
        return probe_versions.get(site['id']) == version and any(item['id'] == site['id'] and item['domain'] == site['domain'] and item.get('enabled') == site.get('enabled') for item in sites)
    if not current():
        return
    if not site.get("enabled"):
        set_status(site, "disabled", message="站点已停用")
        return
    if site["domain"].startswith("*."):
        set_status(site, "unknown", message="泛域名证书需要 DNS 验证配置")
        return
    set_status(site, "pending", message=f"正在申请或检查证书（第 {attempt + 1} 次）", attempt=attempt)
    try:
        context = ssl.create_default_context()
        with socket.create_connection(('127.0.0.1', 443), timeout=8) as raw:
            with context.wrap_socket(raw, server_hostname=site["domain"]) as secure:
                certificate = secure.getpeercert()
        expires = certificate.get("notAfter") if certificate else None
        if expires:
            expiry = datetime.strptime(expires, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (expiry - datetime.now(timezone.utc)).days
            if not current():
                return
            soon = days <= 30
            set_status(site, "active", message='自动续期已启用', expiresAt=expiry.isoformat().replace("+00:00", "Z"), daysRemaining=days, renewalSoon=soon, attempt=attempt)
        else:
            set_status(site, "active", message="证书连接正常", attempt=attempt)
    except Exception as exc:
        if not current():
            return
        if attempt < 4:
            delay = [1.5, 4, 10, 30][attempt]
            timer = threading.Timer(delay, probe_certificate, args=(site, attempt + 1, version))
            timer.daemon = True
            timer.start()
        else:
            set_status(site, "error", message=f"证书检查失败：{exc}", attempt=attempt)


def refresh_statuses(current_sites: list[dict], previous_sites: list[dict] | None = None) -> None:
    previous_sites = previous_sites or []
    previous = {site["id"]: site for site in previous_sites}
    current_ids = {site["id"] for site in current_sites}
    for site_id in list(site_statuses):
        if site_id not in current_ids:
            site_statuses.pop(site_id, None)
            probe_versions.pop(site_id, None)
    for site in current_sites:
        if not site.get("enabled"):
            probe_versions.pop(site['id'], None)
            set_status(site, "disabled", message="站点已停用")
        elif previous.get(site["id"], {}).get("enabled") and previous[site["id"]].get("domain") == site["domain"] and site_statuses.get(site["id"], {}).get("state") == "active":
            continue
        else:
            probe_versions[site['id']] = secrets.token_hex(8)
            set_status(site, "pending", message="等待证书检查", attempt=0)
            timer = threading.Timer(0.1, probe_certificate, args=(site, 0, probe_versions[site['id']]))
            timer.daemon = True
            timer.start()


def require_login():
    if session_user() is None:
        return error("请先登录", 401)
    return None


@app.get("/api/auth/status")
def auth_status():
    username = session_user()
    return jsonify(setupRequired=auth is None, authenticated=username is not None, username=username)


@app.post("/api/auth/setup")
def auth_setup():
    global auth
    if auth is not None:
        return error("初始设置已经完成", 409)
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username_valid(username):
        return error("账号需为 3-32 位字母、数字、下划线、点或短横线")
    if not password_valid(password):
        return error("密码长度需为 8-128 位")
    if password != str(payload.get("confirmPassword", "")):
        return error("两次输入的密码不一致")
    salt = secrets.token_hex(16)
    algorithm = 'scrypt' if hasattr(hashlib, 'scrypt') else 'pbkdf2-sha256'
    auth = {"username": username, "salt": salt, "hash": hash_password(password, salt, algorithm), 'algorithm': algorithm}
    save_auth()
    return login_response({"username": username}, username, 201)


@app.post("/api/auth/login")
def auth_login():
    if auth is None:
        return error("请先完成初始设置", 409)
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    valid = username == auth["username"] and secrets.compare_digest(hash_password(password, auth["salt"], auth.get('algorithm', 'scrypt')), auth["hash"])
    if not valid:
        return error("账号或密码错误", 401)
    return login_response({"username": auth["username"]}, auth["username"])


@app.post("/api/auth/logout")
def auth_logout():
    token = request.cookies.get("caddy_manager_session")
    sessions.pop(token or "", None)
    response = make_response(jsonify(message="已退出登录"))
    response.delete_cookie("caddy_manager_session")
    return response


@app.get("/api/sites")
def list_sites():
    denied = require_login()
    if denied:
        return denied
    return jsonify([{**site, "certificate": status_for(site)} for site in sites])


@app.get("/api/status")
def caddy_status():
    denied = require_login()
    if denied:
        return denied
    if SKIP_CADDY:
        return jsonify(reachable=False, message="开发模式：未检测 Caddy")
    try:
        import urllib.request
        with urllib.request.urlopen(os.environ.get("CADDY_ADMIN_URL", "http://127.0.0.1:2019/config/"), timeout=3) as response:
            return jsonify(reachable=response.status == 200, status=response.status, message="Caddy 正常运行" if response.status == 200 else f"Admin API 返回 {response.status}")
    except Exception as exc:
        return jsonify(reachable=False, message=f"无法连接 Caddy Admin API：{exc}")


@app.get("/api/backup")
def backup():
    denied = require_login()
    if denied:
        return denied
    response = make_response(json.dumps(sites, ensure_ascii=False, indent=2) + "\n")
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="caddy-manager-sites.json"'
    return response


@app.post("/api/apply")
def apply_config():
    denied = require_login()
    if denied:
        return denied
    previous = sites[:]
    try:
        result = validate_and_reload(sites)
        refresh_statuses(sites, previous)
        return jsonify(result)
    except Exception as exc:
        return error(str(exc))


@app.post("/api/restore")
def restore():
    global sites
    denied = require_login()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, list):
        return error("备份文件格式无效")
    try:
        next_sites = [{"id": str(uuid.uuid4()), **validate_site(item)} for item in payload]
        if len({item['domain'] for item in next_sites}) != len(next_sites):
            return error('备份中存在重复域名', 409)
        previous = sites[:]
        validate_and_reload(next_sites)
        sites = next_sites
        save_sites()
        refresh_statuses(sites, previous)
        return jsonify(message="备份已恢复", sites=sites)
    except Exception as exc:
        return error(str(exc))


@app.post("/api/sites/<site_id>/certificate")
def retry_certificate(site_id: str):
    denied = require_login()
    if denied:
        return denied
    site = next((item for item in sites if item["id"] == site_id), None)
    if site is None:
        return error("站点不存在", 404)
    set_status(site, "pending", message="正在重新检查证书", attempt=0)
    threading.Thread(target=probe_certificate, args=(site,), daemon=True).start()
    return jsonify(message="已开始检查证书"), 202


@app.route("/api/sites", methods=["POST"])
def create_site():
    denied = require_login()
    if denied:
        return denied
    global sites
    try:
        site = {"id": str(uuid.uuid4()), **validate_site(request.get_json(silent=True) or {})}
        if any(item["domain"] == site["domain"] for item in sites):
            return error("该域名已存在", 409)
        previous = sites[:]
        validate_and_reload(sites + [site])
        sites.append(site)
        save_sites()
        refresh_statuses(sites, previous)
        return jsonify(site), 201
    except Exception as exc:
        return error(str(exc))


@app.route("/api/sites/<site_id>", methods=["PUT", "DELETE"])
def update_or_delete_site(site_id: str):
    denied = require_login()
    if denied:
        return denied
    global sites
    index = next((idx for idx, item in enumerate(sites) if item["id"] == site_id), None)
    if index is None:
        return error("站点不存在", 404)
    previous = sites[:]
    try:
        if request.method == "DELETE":
            next_sites = [item for item in sites if item["id"] != site_id]
            validate_and_reload(next_sites)
            sites = next_sites
            save_sites()
            refresh_statuses(sites, previous)
            return jsonify(message="站点已删除", sites=sites)
        updated = {"id": site_id, **validate_site(request.get_json(silent=True) or {})}
        if any(item['id'] != site_id and item['domain'] == updated['domain'] for item in sites):
            return error('该域名已存在', 409)
        next_sites = sites[:]
        next_sites[index] = updated
        validate_and_reload(next_sites)
        sites = next_sites
        save_sites()
        refresh_statuses(sites, previous)
        return jsonify(updated)
    except Exception as exc:
        return error(str(exc))


@app.route("/", defaults={"filename": "index.html"})
@app.route("/<path:filename>")
def public_file(filename: str):
    return send_from_directory(PUBLIC_DIR, filename)


load_data()
refresh_statuses(sites)

if __name__ == "__main__":
    from waitress import serve
    serve(app, host=HOST, port=PORT, threads=2)
