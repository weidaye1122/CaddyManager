const http = require('node:http');
const fs = require('node:fs');
const fsp = fs.promises;
const path = require('node:path');
const crypto = require('node:crypto');
const tls = require('node:tls');
const { spawn } = require('node:child_process');

const ROOT = __dirname;
const PUBLIC_DIR = path.join(ROOT, 'public');
const DATA_DIR = process.env.CADDY_MANAGER_DATA || path.join(ROOT, 'data');
const SITES_FILE = path.join(DATA_DIR, 'sites.json');
const AUTH_FILE = path.join(DATA_DIR, 'auth.json');
const BACKUP_DIR = path.join(DATA_DIR, 'backups');
const CADDYFILE = process.env.CADDYFILE || '/etc/caddy/Caddyfile';
const CADDY_BIN = process.env.CADDY_BIN || 'caddy';
const HOST = process.env.CADDY_MANAGER_HOST || '127.0.0.1';
const PORT = Number(process.env.CADDY_MANAGER_PORT || 7080);
const SKIP_CADDY_COMMANDS = process.env.CADDY_MANAGER_SKIP_CADDY === '1';
const SESSION_TTL = 12 * 60 * 60 * 1000;

let sites = [];
let auth = null;
const sessions = new Map();
const siteStatuses = new Map();

function json(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(data),
    'Cache-Control': 'no-store',
  });
  res.end(data);
}

function text(res, status, body, contentType = 'text/plain; charset=utf-8') {
  res.writeHead(status, { 'Content-Type': contentType, 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

function fail(res, status, message) {
  json(res, status, { error: message });
}

async function ensureData() {
  await fsp.mkdir(DATA_DIR, { recursive: true });
  await fsp.mkdir(BACKUP_DIR, { recursive: true });
  try {
    sites = JSON.parse(await fsp.readFile(SITES_FILE, 'utf8'));
    if (!Array.isArray(sites)) throw new Error('sites.json must contain an array');
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn(`无法读取 ${SITES_FILE}: ${error.message}`);
    sites = [];
    await saveSites();
  }
  try {
    auth = JSON.parse(await fsp.readFile(AUTH_FILE, 'utf8'));
    if (!auth || typeof auth.username !== 'string' || typeof auth.salt !== 'string' || typeof auth.hash !== 'string') auth = null;
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn(`无法读取 ${AUTH_FILE}: ${error.message}`);
    auth = null;
  }
}

async function saveSites() {
  const temp = `${SITES_FILE}.tmp-${process.pid}`;
  await fsp.writeFile(temp, `${JSON.stringify(sites, null, 2)}\n`, 'utf8');
  await fsp.rename(temp, SITES_FILE);
}

async function saveAuth() {
  const temp = `${AUTH_FILE}.tmp-${process.pid}`;
  await fsp.writeFile(temp, `${JSON.stringify(auth, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
  await fsp.rename(temp, AUTH_FILE);
  await fsp.chmod(AUTH_FILE, 0o600);
}

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 64).toString('hex');
}

function parseCookies(req) {
  const cookies = {};
  for (const item of String(req.headers.cookie || '').split(';')) {
    const index = item.indexOf('=');
    if (index === -1) continue;
    cookies[item.slice(0, index).trim()] = decodeURIComponent(item.slice(index + 1).trim());
  }
  return cookies;
}

function sessionFor(req) {
  const token = parseCookies(req).caddy_manager_session;
  if (!token) return null;
  const session = sessions.get(token);
  if (!session || session.expiresAt <= Date.now()) {
    sessions.delete(token);
    return null;
  }
  session.expiresAt = Date.now() + SESSION_TTL;
  return { token, ...session };
}

function setSession(res, username) {
  const token = crypto.randomBytes(32).toString('hex');
  sessions.set(token, { username, expiresAt: Date.now() + SESSION_TTL });
  res.setHeader('Set-Cookie', `caddy_manager_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${SESSION_TTL / 1000}`);
}

function clearSession(req, res) {
  const token = parseCookies(req).caddy_manager_session;
  if (token) sessions.delete(token);
  res.setHeader('Set-Cookie', 'caddy_manager_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');
}

function validUsername(username) {
  return /^[a-zA-Z0-9_.-]{3,32}$/.test(username);
}

function validPassword(password) {
  return typeof password === 'string' && password.length >= 8 && password.length <= 128;
}

function statusFor(site) {
  return siteStatuses.get(site.id) || { state: site.enabled ? 'unknown' : 'disabled', message: site.enabled ? '等待检查' : '站点已停用' };
}

function setSiteStatus(site, state, extra = {}) {
  siteStatuses.set(site.id, { state, checkedAt: new Date().toISOString(), ...extra });
}

function probeCertificate(site, attempt = 0) {
  if (!site.enabled) {
    setSiteStatus(site, 'disabled', { message: '站点已停用' });
    return;
  }
  if (site.domain.startsWith('*.')) {
    setSiteStatus(site, 'unknown', { message: '泛域名证书需要 DNS 验证配置' });
    return;
  }
  setSiteStatus(site, 'pending', { message: attempt ? `正在检查证书（第 ${attempt + 1} 次）` : '正在申请或检查证书', attempt });
  const socket = tls.connect({
    host: site.domain,
    port: 443,
    servername: site.domain,
    rejectUnauthorized: false,
    timeout: 8000,
  });
  let finished = false;
  const failProbe = (error) => {
    if (finished) return;
    finished = true;
    socket.destroy();
    if (attempt < 4) {
      const delays = [1500, 4000, 10000, 30000];
      setTimeout(() => probeCertificate(site, attempt + 1), delays[attempt]);
      return;
    }
    setSiteStatus(site, 'error', { message: `证书检查失败：${error.code || error.message || '连接失败'}`, attempt });
  };
  socket.setTimeout(8000, () => failProbe(new Error('连接超时')));
  socket.once('error', failProbe);
  socket.once('secureConnect', () => {
    if (finished) return;
    finished = true;
    const certificate = socket.getPeerCertificate();
    socket.end();
    if (!certificate || !certificate.valid_to) {
      setSiteStatus(site, 'error', { message: '未取得有效证书', attempt });
      return;
    }
    const expiresAt = new Date(certificate.valid_to);
    const daysRemaining = Math.ceil((expiresAt.getTime() - Date.now()) / 86400000);
    const renewalSoon = daysRemaining <= 30;
    setSiteStatus(site, 'active', {
      message: renewalSoon ? `证书将在 ${Math.max(0, daysRemaining)} 天内自动续期` : '证书正常',
      expiresAt: certificate.valid_to,
      daysRemaining,
      renewalSoon,
      subject: certificate.subject?.CN || site.domain,
      issuer: certificate.issuer?.O || certificate.issuer?.CN || '',
      attempt,
    });
  });
}

function refreshSiteStatuses(currentSites, previousSites = []) {
  const currentIds = new Set(currentSites.map((site) => site.id));
  const previousById = new Map(previousSites.map((site) => [site.id, site]));
  for (const id of siteStatuses.keys()) if (!currentIds.has(id)) siteStatuses.delete(id);
  for (const site of currentSites) {
    if (!site.enabled) setSiteStatus(site, 'disabled', { message: '站点已停用' });
    else {
      const previous = previousById.get(site.id);
      const previousStatus = siteStatuses.get(site.id);
      if (previous && previous.enabled && previous.domain === site.domain && previousStatus && previousStatus.state === 'active') {
        continue;
      }
      setSiteStatus(site, 'pending', { message: '等待证书检查', attempt: 0 });
      setTimeout(() => probeCertificate(site), 100);
    }
  }
}

function validateSite(input) {
  if (!input || typeof input !== 'object') throw new Error('请求内容无效');
  const domain = String(input.domain || '').trim().toLowerCase();
  const upstream = String(input.upstream || '').trim();
  const note = String(input.note || '').trim();
  const protocol = input.upstreamProtocol === 'https' ? 'https' : 'http';
  if (!domain || !/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/i.test(domain)) {
    throw new Error('请输入有效域名，例如 ha.example.com');
  }
  if (!upstream || !/^[a-z0-9.:[\]-]+(?::\d{1,5})$/i.test(upstream)) {
    throw new Error('上游地址应为 host:port，例如 127.0.0.1:8123');
  }
  const port = Number(upstream.match(/:(\d{1,5})$/)?.[1]);
  if (port < 1 || port > 65535) throw new Error('上游端口范围应为 1-65535');
  if (note.length > 120) throw new Error('备注不能超过 120 个字符');
  return {
    domain,
    upstream,
    upstreamProtocol: protocol,
    enabled: input.enabled !== false,
    note,
  };
}

function caddyfileFor(currentSites) {
  const active = currentSites.filter((site) => site.enabled);
  if (!active.length) {
    return '# 暂无启用的反代站点\n';
  }
  return `${active.map((site) => [
    `${site.domain} {`,
    `    reverse_proxy ${site.upstreamProtocol === 'https' ? 'https://' : ''}${site.upstream}`,
    '}',
  ].join('\n')).join('\n\n')}\n`;
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', reject);
    child.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

async function validateAndReload(nextSites) {
  const config = caddyfileFor(nextSites);
  if (SKIP_CADDY_COMMANDS) {
    return { config, skipped: true, message: '已跳过 Caddy 命令（开发模式）' };
  }

  await fsp.mkdir(path.dirname(CADDYFILE), { recursive: true });
  const candidate = `${CADDYFILE}.candidate-${process.pid}`;
  await fsp.writeFile(candidate, config, 'utf8');

  const validation = await run(CADDY_BIN, ['validate', '--config', candidate, '--adapter', 'caddyfile']);
  if (validation.code !== 0) {
    await fsp.rm(candidate, { force: true });
    throw new Error(`Caddy 配置校验失败：${(validation.stderr || validation.stdout).trim()}`);
  }

  const backup = path.join(BACKUP_DIR, `Caddyfile-${new Date().toISOString().replace(/[:.]/g, '-')}.bak`);
  try {
    await fsp.copyFile(CADDYFILE, backup);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await fsp.rename(candidate, CADDYFILE);

  const reload = await run(CADDY_BIN, ['reload', '--config', CADDYFILE, '--adapter', 'caddyfile']);
  if (reload.code !== 0) {
    try {
      await fsp.copyFile(backup, CADDYFILE);
      await run(CADDY_BIN, ['reload', '--config', CADDYFILE, '--adapter', 'caddyfile']);
    } finally {
      throw new Error(`Caddy reload 失败，已恢复旧配置：${(reload.stderr || reload.stdout).trim()}`);
    }
  }
  return { config, skipped: false, message: '配置已校验并应用' };
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = Buffer.concat(chunks).toString('utf8');
  if (body.length > 1024 * 1024) throw new Error('请求内容过大');
  return body ? JSON.parse(body) : {};
}

async function caddyStatus() {
  if (SKIP_CADDY_COMMANDS) return { reachable: false, message: '开发模式：未检测 Caddy' };
  try {
    const response = await fetch(process.env.CADDY_ADMIN_URL || 'http://127.0.0.1:2019/config/');
    return { reachable: response.ok, status: response.status, message: response.ok ? 'Caddy 正常运行' : `Admin API 返回 ${response.status}` };
  } catch (error) {
    return { reachable: false, message: `无法连接 Caddy Admin API：${error.message}` };
  }
}

async function api(req, res, pathname) {
  if (pathname === '/api/auth/status' && req.method === 'GET') {
    const session = sessionFor(req);
    return json(res, 200, { setupRequired: !auth, authenticated: Boolean(session), username: session?.username || null });
  }
  if (pathname === '/api/auth/setup' && req.method === 'POST') {
    if (auth) return fail(res, 409, '初始设置已经完成');
    const body = await readBody(req);
    const username = String(body.username || '').trim();
    const password = String(body.password || '');
    const confirmPassword = String(body.confirmPassword || '');
    if (!validUsername(username)) return fail(res, 400, '账号需为 3-32 位字母、数字、下划线、点或短横线');
    if (!validPassword(password)) return fail(res, 400, '密码长度需为 8-128 位');
    if (password !== confirmPassword) return fail(res, 400, '两次输入的密码不一致');
    const salt = crypto.randomBytes(16).toString('hex');
    auth = { username, salt, hash: hashPassword(password, salt) };
    await saveAuth();
    setSession(res, username);
    return json(res, 201, { username });
  }
  if (pathname === '/api/auth/login' && req.method === 'POST') {
    if (!auth) return fail(res, 409, '请先完成初始设置');
    const body = await readBody(req);
    const username = String(body.username || '').trim();
    const password = String(body.password || '');
    const suppliedHash = hashPassword(password, auth.salt);
    const valid = username === auth.username && suppliedHash.length === auth.hash.length && crypto.timingSafeEqual(Buffer.from(suppliedHash), Buffer.from(auth.hash));
    if (!valid) return fail(res, 401, '账号或密码错误');
    setSession(res, auth.username);
    return json(res, 200, { username: auth.username });
  }
  if (pathname === '/api/auth/logout' && req.method === 'POST') {
    clearSession(req, res);
    return json(res, 200, { message: '已退出登录' });
  }
  if (pathname === '/api/sites' && req.method === 'GET') return json(res, 200, sites.map((site) => ({ ...site, certificate: statusFor(site) })));
  if (pathname === '/api/status' && req.method === 'GET') return json(res, 200, await caddyStatus());
  if (pathname === '/api/backup' && req.method === 'GET') {
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Disposition': 'attachment; filename="caddy-manager-sites.json"',
    });
    return res.end(`${JSON.stringify(sites, null, 2)}\n`);
  }
  if (pathname === '/api/apply' && req.method === 'POST') {
    const previousSites = sites;
    const result = await validateAndReload(sites);
    refreshSiteStatuses(sites, previousSites);
    return json(res, 200, result);
  }
  const probeMatch = pathname.match(/^\/api\/sites\/([^/]+)\/certificate$/);
  if (probeMatch && req.method === 'POST') {
    const site = sites.find((item) => item.id === probeMatch[1]);
    if (!site) return fail(res, 404, '站点不存在');
    setSiteStatus(site, 'pending', { message: '正在重新检查证书', attempt: 0 });
    probeCertificate(site);
    return json(res, 202, { message: '已开始检查证书' });
  }
  if (pathname === '/api/restore' && req.method === 'POST') {
    const imported = await readBody(req);
    if (!Array.isArray(imported)) throw new Error('备份文件格式无效');
    const nextSites = imported.map(validateSite).map((site) => ({ id: crypto.randomUUID(), ...site }));
    const previousSites = sites;
    await validateAndReload(nextSites);
    sites = nextSites;
    await saveSites();
    refreshSiteStatuses(sites, previousSites);
    return json(res, 200, { message: '备份已恢复', sites });
  }
  const match = pathname.match(/^\/api\/sites\/([^/]+)$/);
  if (match && ['PUT', 'DELETE'].includes(req.method)) {
    const index = sites.findIndex((site) => site.id === match[1]);
    if (index === -1) return fail(res, 404, '站点不存在');
    if (req.method === 'DELETE') {
      const nextSites = sites.filter((site) => site.id !== match[1]);
      const previousSites = sites;
      await validateAndReload(nextSites);
      sites = nextSites;
      await saveSites();
      refreshSiteStatuses(sites, previousSites);
      return json(res, 200, { message: '站点已删除', sites });
    }
    const next = { ...sites[index], ...validateSite(await readBody(req)) };
    const nextSites = sites.slice();
    nextSites[index] = next;
    const previousSites = sites;
    await validateAndReload(nextSites);
    sites = nextSites;
    await saveSites();
    refreshSiteStatuses(sites, previousSites);
    return json(res, 200, next);
  }
  if (pathname === '/api/sites' && req.method === 'POST') {
    const site = { id: crypto.randomUUID(), ...validateSite(await readBody(req)) };
    if (sites.some((item) => item.domain === site.domain)) return fail(res, 409, '该域名已存在');
    const nextSites = [...sites, site];
    const previousSites = sites;
    await validateAndReload(nextSites);
    sites = nextSites;
    await saveSites();
    refreshSiteStatuses(sites, previousSites);
    return json(res, 201, site);
  }
  return fail(res, 404, '接口不存在');
}

async function serve(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/') && !url.pathname.startsWith('/api/auth/') && !sessionFor(req)) {
      return fail(res, 401, '请先登录');
    }
    if (url.pathname.startsWith('/api/')) return await api(req, res, url.pathname);
    if (req.method !== 'GET' && req.method !== 'HEAD') return fail(res, 405, '方法不允许');
    const requested = url.pathname === '/' ? '/index.html' : url.pathname;
    const file = path.resolve(PUBLIC_DIR, `.${requested}`);
    if (!file.startsWith(`${PUBLIC_DIR}${path.sep}`)) return fail(res, 400, '路径无效');
    const content = await fsp.readFile(file);
    const types = {
      '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
      '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json; charset=utf-8',
    };
    const type = types[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': content.length, 'Cache-Control': 'no-cache' });
    if (req.method === 'HEAD') return res.end();
    return res.end(content);
  } catch (error) {
    console.error(error);
    return fail(res, error.message.includes('不存在') ? 404 : 400, error.message || '请求失败');
  }
}

ensureData().then(() => {
  http.createServer((req, res) => serve(req, res).catch((error) => {
    console.error(error);
    fail(res, 500, error.message || '服务器错误');
  })).listen(PORT, HOST, () => {
    console.log(`Caddy Manager running at http://${HOST}:${PORT}`);
    if (!auth) console.warn('首次启动：请在 Web 页面设置管理员账号和密码');
    refreshSiteStatuses(sites);
  });
}).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
