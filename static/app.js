const $ = id => document.getElementById(id);
const h = (tag, props = {}, ...kids) => {
  const e = Object.assign(document.createElement(tag), props);
  kids.flat().forEach(k => k != null && e.append(k)); return e;
};
const api = async (url, opt = {}) => {
  if (opt.body && !(opt.body instanceof FormData)) { opt.headers = {'Content-Type': 'application/json'}; opt.body = JSON.stringify(opt.body); }
  const r = await fetch(url, opt);
  if (r.status === 401) { location.href = '/'; return {}; }
  return {ok: r.ok, ...(await r.json().catch(() => ({})))};
};
const fmtSize = n => !n ? '' : n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
const fmtTime = t => t ? new Date(t).toLocaleString('en-IN', {timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short'}) : '';
const ACTIONS = {login: 'Signed in', login_failed: 'Failed sign-in', account_created: 'Account created', password_set: 'Set first password',
  password_changed: 'Changed password', profile_updated: 'Updated profile', upload: 'Uploaded', view: 'Viewed', download: 'Downloaded',
  access_granted: 'Granted access', access_revoked: 'Revoked access', file_deleted: 'Deleted', role_changed: 'Changed role'};
const TITLES = {overview: 'Overview', documents: 'My documents', shared: 'Shared with me', access: 'Access management',
  audit: 'Audit trail', users: 'Users & roles', profile: 'Profile settings'};
let ME, toastTimer;
const page = $('page');
const isMgr = () => ['owner', 'admin'].includes(ME.role);
const myDocs = files => ME.role === 'admin' ? files : files.filter(f => f.mine);
const sharedDocs = files => files.filter(f => f.shared && !f.mine);
const head = (title, sub) => [h('h1', {textContent: title}), h('p', {className: 'sub', textContent: sub})];
const card = (title, sub, ...kids) => h('section', {className: 'card2'}, h('h3', {textContent: title}), sub ? h('p', {className: 'sub', textContent: sub}) : null, ...kids);
const msg = () => h('p', {className: 'msg'});
const say = (el, t, ok) => { el.textContent = t; el.className = 'msg ' + (ok ? 'ok' : 'err'); };
const field = (label, input) => [h('label', {textContent: label}), input];
const empty = t => h('p', {className: 'empty', textContent: t});
function toast(t) {
  const el = $('toast'); el.textContent = t; el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, 2500);
}
function docRow(f, o = {}) {
  const acts = h('span', {className: 'acts'}, h('button', {className: 'link', textContent: 'View', onclick: () => window.open(`/files/${f.id}`, '_blank')}));
  if (f.can_dl) acts.append(h('button', {className: 'link', textContent: 'Download', onclick: () => location.href = `/files/${f.id}?download=1`}));
  if (o.del && f.can_manage) acts.append(h('button', {className: 'link danger', textContent: 'Delete', onclick: async () => {
    if (!confirm('Delete this file permanently?')) return;
    const r = await api(`/files/${f.id}`, {method: 'DELETE'}); toast(r.ok ? 'File deleted' : r.error); route();
  }}));
  const meta = [fmtSize(f.size), o.owner ? 'Owner: ' + f.owner : '', fmtTime(f.created)].filter(Boolean).join(' · ');
  return h('div', {className: 'row'}, h('div', {}, h('b', {textContent: f.orig}), h('div', {className: 'meta', textContent: meta})),
    o.tag ? h('span', {className: 'tag', textContent: f.can_dl ? 'DOWNLOAD' : 'READ'}) : null, acts);
}
const eventRow = e => h('div', {className: 'row'}, h('div', {}, h('b', {textContent: ACTIONS[e.action] || e.action}),
  h('div', {className: 'meta', textContent: [e.detail, 'by ' + e.actor].filter(Boolean).join(' · ')})), h('span', {className: 'meta', textContent: fmtTime(e.ts)}));

const PAGES = {
  async overview() {
    const [fl, ac, au] = await Promise.all([api('/files-list'), isMgr() ? api('/access') : {}, api('/audit')]);
    const files = fl.files || [], events = (au.events || []).slice(0, 5);
    const stat = (n, l) => h('div', {className: 'stat'}, h('b', {textContent: n}), h('span', {textContent: l}));
    const stats = [stat(myDocs(files).length, 'My documents'), stat(sharedDocs(files).length, 'Shared with me')];
    if (isMgr()) stats.push(stat((ac.grants || []).length, 'Active grants'));
    page.replaceChildren(...head('Overview', 'Your protected workspace at a glance'), h('div', {className: 'stats'}, ...stats),
      card('Recent activity', 'Latest events on your documents', ...(events.length ? events.map(eventRow) : [empty('No activity yet.')])));
  },
  async documents() {
    const {files = []} = await api('/files-list'), docs = myDocs(files);
    const kids = [];
    if (isMgr()) {
      const input = h('input', {type: 'file'}), m = msg();
      kids.push(card('Upload a document', 'Files are encrypted before they are stored. Allowed: PDF, Word, Excel, PowerPoint, images, text, CSV, MP4 (max 20 MB).',
        input,
        h('button', {className: 'primary', textContent: 'Upload', onclick: async () => {
          if (!input.files[0]) return say(m, 'Choose a file first');
          const fd = new FormData(); fd.append('file', input.files[0]);
          const r = await api('/upload', {method: 'POST', body: fd});
          // Silent on success: just refresh the list. Show a message only on failure.
          if (r.ok) route(); else say(m, r.error || 'Upload failed');
        }}),
        m));
    } else {
      kids.push(empty('Viewers cannot upload. Documents shared with you are under "Shared with me".'));
    }
    kids.push(card('Documents', 'Your files', ...(docs.length ? docs.map(f => docRow(f, {del: true, owner: ME.role === 'admin'})) : [empty('No documents yet.')])));
    page.replaceChildren(...head('My documents', 'Files you own'), ...kids);
  },
  async shared() {
    const {files = []} = await api('/files-list'), docs = sharedDocs(files);
    page.replaceChildren(...head('Shared with me', 'Documents other people granted you access to'),
      card('Documents', 'READ = view only, DOWNLOAD = view and download', ...(docs.length ? docs.map(f => docRow(f, {owner: true, tag: true})) : [empty('Nothing has been shared with you yet.')])));
  },
  async access() {
    const [fl, ac] = await Promise.all([api('/files-list'), api('/access')]);
    const docs = (fl.files || []).filter(f => f.can_manage), grants = ac.grants || [];
    const list = grants.length ? grants.map(g => h('div', {className: 'row'},
      h('div', {}, h('b', {textContent: g.orig}), h('div', {className: 'meta', textContent: `${g.name} · ${g.email}`})),
      h('span', {className: 'tag', textContent: g.can_dl ? 'DOWNLOAD' : 'READ'}),
      h('button', {className: 'link danger', textContent: 'Revoke', onclick: async () => {
        const r = await api(`/files/${g.file_id}/share/${g.user_id}`, {method: 'DELETE'}); toast(r.ok ? 'Access revoked' : r.error); route();
      }}))) : [empty('No active grants. Use the form below to share a document.')];
    const sel = h('select', {}, ...docs.map(d => h('option', {value: d.id, textContent: d.orig})));
    const email = h('input', {type: 'email', placeholder: 'name@example.com', required: true});
    const perm = h('select', {}, h('option', {value: 'READ', textContent: 'READ'}), h('option', {value: 'DOWNLOAD', textContent: 'DOWNLOAD'}));
    const m = msg();
    const form = h('form', {onsubmit: async e => {
      e.preventDefault();
      if (!docs.length) return say(m, 'Upload a document first (My documents).');
      const r = await api(`/files/${sel.value}/share`, {method: 'POST', body: {email: email.value, canDownload: perm.value === 'DOWNLOAD'}});
      r.ok ? (toast('Access granted'), route()) : say(m, r.error);
    }}, ...field('Document', sel), ...field('User email', email), ...field('Permission', perm), h('button', {className: 'primary full', textContent: 'Grant access'}), m);
    page.replaceChildren(...head('Access management', 'Grant named users specific permissions and revoke them when needed'),
      card('Current permissions', 'Who can open what', ...list), card('Grant new access', 'Select a document, registered user and permission.', form));
  },
  async audit() {
    const {events = []} = await api('/audit');
    page.replaceChildren(...head('Audit trail', ME.role === 'admin' ? 'Everything that happened in the workspace' : 'Your activity and activity on your documents'),
      card('Events', 'Newest first, last 100', ...(events.length ? events.map(eventRow) : [empty('No events yet.')])));
  },
  async users() {
    const {users = []} = await api('/users');
    const rows = users.map(u => {
      const sel = h('select', {onchange: async () => {
        const r = await api(`/users/${u.id}/role`, {method: 'PUT', body: {role: sel.value}});
        r.ok ? toast('Role updated') : (toast(r.error), route());
      }}, ...['viewer', 'owner', 'admin'].map(r => h('option', {textContent: r, selected: r === u.role})));
      return h('div', {className: 'row'}, h('div', {}, h('b', {textContent: u.name}), h('div', {className: 'meta', textContent: u.email})), sel);
    });
    page.replaceChildren(...head('Users & roles', 'Admins decide who can upload (owner) and who can only view (viewer)'), card('Users', 'New accounts start as viewer', ...rows));
  },
  async profile() {
    const name = h('input', {value: ME.name}), m1 = msg(), cur = h('input', {type: 'password', autocomplete: 'current-password'}),
      nw = h('input', {type: 'password', minLength: 8, autocomplete: 'new-password'}), m2 = msg();
    const f1 = h('form', {onsubmit: async e => {
      e.preventDefault();
      const r = await api('/profile', {method: 'PUT', body: {name: name.value}});
      if (r.ok) { ME.name = name.value.trim(); $('avatar').textContent = ME.name[0].toUpperCase(); say(m1, 'Saved', true); } else say(m1, r.error);
    }}, ...field('Name', name), ...field('Email', h('input', {value: ME.email, disabled: true})), ...field('Role', h('input', {value: ME.role, disabled: true})),
      h('button', {className: 'primary', textContent: 'Save'}), m1);
    const f2 = h('form', {onsubmit: async e => {
      e.preventDefault();
      const r = await api('/profile/password', {method: 'POST', body: {current: cur.value, password: nw.value}});
      r.ok ? (cur.value = nw.value = '', say(m2, 'Password changed', true)) : say(m2, r.error);
    }}, ...field('Current password', cur), ...field('New password (8+ characters)', nw), h('button', {className: 'primary', textContent: 'Change password'}), m2);
    page.replaceChildren(...head('Profile settings', 'Your account details'), card('Profile', null, f1), card('Change password', null, f2));
  },
};

async function route() {
  let p = location.hash.replace('#/', '') || 'overview';
  const link = document.querySelector(`[data-p="${p}"]`);
  if (!PAGES[p] || (link && link.hidden)) p = 'overview';
  document.querySelectorAll('[data-p]').forEach(a => a.classList.toggle('on', a.dataset.p === p));
  $('crumb').textContent = `Workspace / ${TITLES[p]}`;
  page.replaceChildren(h('p', {className: 'sub', textContent: 'Loading…'}));
  try { await PAGES[p](); } catch (e) { page.replaceChildren(empty('Something went wrong. Refresh the page.')); console.error(e); }
}
async function init() {
  ME = await api('/me');
  if (ME.must_change) return location.href = '/';
  $('avatar').textContent = (ME.name || '?')[0].toUpperCase();
  document.querySelectorAll('[data-roles]').forEach(a => a.hidden = !a.dataset.roles.split(',').includes(ME.role));
  $('logout').onclick = e => { e.preventDefault(); fetch('/logout', {method: 'POST'}).then(() => location.href = '/'); };
  window.onhashchange = route; route();
}
init();