const state = { sites: [], editing: null };
const $ = (id) => document.getElementById(id);
const message = (text, error = false) => { $('message').textContent = text; $('message').className = `message${error ? ' error' : ''}`; };
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

async function request(url, options = {}) {
  const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(data.error || `请求失败（${response.status}）`); error.status = response.status; throw error; }
  return data;
}

function showAuth(mode, error = '') {
  $('auth-screen').classList.remove('hidden');
  $('app').classList.add('hidden');
  const setup = mode === 'setup';
  $('auth-title').textContent = setup ? '首次设置管理员' : '登录 Caddy Manager';
  $('auth-subtitle').textContent = setup ? '设置一个管理员账号和密码，之后用于进入面板。' : '请输入管理员账号和密码。';
  $('confirm-row').classList.toggle('hidden', !setup);
  $('auth-confirm').required = setup;
  $('auth-password').autocomplete = setup ? 'new-password' : 'current-password';
  $('auth-submit').textContent = setup ? '完成设置' : '登录';
  $('auth-error').textContent = error;
}

function showApp() {
  $('auth-screen').classList.add('hidden');
  $('app').classList.remove('hidden');
}

async function authSubmit(event) {
  event.preventDefault();
  const setup = !$('confirm-row').classList.contains('hidden');
  const body = { username: $('auth-username').value.trim(), password: $('auth-password').value };
  if (setup) body.confirmPassword = $('auth-confirm').value;
  try {
    await request(setup ? '/api/auth/setup' : '/api/auth/login', { method: 'POST', body: JSON.stringify(body) });
    $('auth-form').reset();
    showApp();
    await refresh();
  } catch (error) { $('auth-error').textContent = error.message; }
}

async function boot() {
  try {
    const status = await request('/api/auth/status');
    if (status.setupRequired) return showAuth('setup');
    if (!status.authenticated) return showAuth('login');
    showApp();
    await refresh();
  } catch (error) { showAuth('login', error.message); }
}

function render() {
  const container = $('sites');
  container.innerHTML = '';
  $('empty').classList.toggle('hidden', state.sites.length !== 0);
  state.sites.forEach((site) => {
    const certificate = site.certificate || { state: 'unknown', message: '等待检查' };
    const certificateLabels = { active: '证书正常', pending: '等待证书就绪', error: '证书检查异常', disabled: '站点已停用', unknown: '待检查' };
    const certificateText = certificate.state === 'active' && certificate.expiresAt
      ? `${certificateLabels.active} · ${certificate.renewalSoon ? '临近到期，自动续期已启用' : '自动续期已启用'} · 到期 ${new Date(certificate.expiresAt).toLocaleDateString('zh-CN')}`
      : `${certificateLabels[certificate.state] || certificateLabels.unknown}${certificate.message ? ` · ${certificate.message}` : ''}`;
    const certificateClass = certificate.renewalSoon ? 'renewing' : certificate.state;
    const retry = certificate.state === 'error' ? '<button class="button secondary retry"><span class="button-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.8-4L3 10m0-5v5h5M4 13a8 8 0 0 0 14.8 4L21 14m0 5v-5h-5"/></svg></span>重试</button>' : '';
    const domain = escapeHtml(site.domain);
    const note = escapeHtml(site.note || '');
    const upstream = escapeHtml(`${site.upstreamProtocol}://${site.upstream}`);
    const card = document.createElement('article');
    card.className = 'site card';
    card.innerHTML = `<div class="site-info"><div class="site-domain"><a class="site-url" target="_blank" rel="noreferrer" href="https://${domain}">${domain}</a><span class="tag ${site.enabled ? '' : 'off'}">${site.enabled ? '已启用' : '已停用'}</span></div>${note ? `<div class="site-note">${note}</div>` : ''}<div class="site-upstream">${upstream}</div><div class="certificate-status cert-${certificateClass}"><span class="cert-dot"></span>${escapeHtml(certificateText)}</div></div><div class="site-actions">${retry}<button class="button secondary edit"><span class="button-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="m4 16-.7 4.7L8 20l11-11a2.8 2.8 0 0 0-4-4L4 16Z"/><path d="m13.5 6.5 4 4"/></svg></span>编辑</button><button class="icon-button delete" title="删除" aria-label="删除"><svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6m4-6v6M9 7V4h6v3m-9 0 1 13h10l1-13"/></svg></button></div>`;
    card.querySelector('.edit').onclick = () => openEditor(site);
    card.querySelector('.delete').onclick = () => removeSite(site);
    card.querySelector('.retry')?.addEventListener('click', async () => { try { await request(`/api/sites/${site.id}/certificate`, { method: 'POST' }); message('已开始重新检查证书。'); await refresh(); } catch (error) { message(error.message, true); } });
    container.appendChild(card);
  });
}

async function refresh() {
  try {
    state.sites = await request('/api/sites');
    render();
    const status = await request('/api/status');
    $('status').className = `status-pill ${status.reachable ? 'ok' : 'bad'}`;
    $('status').innerHTML = `<span class="dot"></span>${status.message}`;
  } catch (error) {
    if (error.status === 401) return showAuth('login', '登录已过期，请重新登录。');
    message(error.message, true);
  }
}

function openEditor(site = null) {
  state.editing = site;
  $('dialog-title').textContent = site ? '编辑站点' : '添加站点';
  $('domain').value = site?.domain || '';
  $('upstream').value = site?.upstream || '';
  $('upstreamProtocol').value = site?.upstreamProtocol || 'http';
  $('note').value = site?.note || '';
  $('enabled').checked = site?.enabled ?? true;
  $('editor-error').textContent = '';
  $('editor').showModal();
  $('domain').focus();
}

async function save(event) {
  event.preventDefault();
  $('save').disabled = true;
  $('editor-error').textContent = '';
  const payload = { domain: $('domain').value, upstream: $('upstream').value, upstreamProtocol: $('upstreamProtocol').value, note: $('note').value, enabled: $('enabled').checked };
  try {
    const url = state.editing ? `/api/sites/${state.editing.id}` : '/api/sites';
    const method = state.editing ? 'PUT' : 'POST';
    await request(url, { method, body: JSON.stringify(payload) });
    $('editor').close();
    message('站点已保存并应用。');
    await refresh();
  } catch (error) { $('editor-error').textContent = error.message; }
  finally { $('save').disabled = false; }
}

async function removeSite(site) {
  if (!window.confirm(`确定删除 ${site.domain} 吗？`)) return;
  try { await request(`/api/sites/${site.id}`, { method: 'DELETE' }); message('站点已删除并应用。'); await refresh(); }
  catch (error) { message(error.message, true); }
}

$('add').onclick = () => openEditor();
$('empty-add').onclick = () => openEditor();
$('site-form').addEventListener('submit', save);
document.querySelectorAll('.cancel-edit').forEach((button) => button.addEventListener('click', () => $('editor').close()));
$('auth-form').addEventListener('submit', authSubmit);
$('logout').onclick = async () => { await request('/api/auth/logout', { method: 'POST' }); showAuth('login'); };
$('backup').onclick = () => { window.location.href = '/api/backup'; };
$('restore').onchange = async (event) => {
  const file = event.target.files[0]; if (!file) return;
  try { await request('/api/restore', { method: 'POST', body: await file.text() }); message('配置已恢复并应用。'); await refresh(); }
  catch (error) { message(error.message, true); }
  event.target.value = '';
};
boot();
let polling = false;
setInterval(async () => {
  if (document.hidden || $('app').classList.contains('hidden') || $('editor').open || polling) return;
  polling = true;
  try { await refresh(); } finally { polling = false; }
}, 5000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
