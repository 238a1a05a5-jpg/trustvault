const $ = id => document.getElementById(id);
let mode = 'in';
const say = (t, ok) => { $('msg').textContent = t || ''; $('msg').className = ok ? 'ok' : 'err'; };
const post = async (url, body) => {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return {ok: r.ok, ...(await r.json().catch(() => ({})))};
};
function setMode(m) {
  mode = m;
  $('tabIn').classList.toggle('on', m === 'in'); $('tabUp').classList.toggle('on', m === 'up');
  $('nameBox').hidden = m === 'in'; $('pwBox').hidden = m === 'up'; $('upHint').hidden = m === 'in';
  $('go').textContent = m === 'in' ? 'Sign in' : 'Create account'; say('');
}
function showChange() {
  $('authForm').hidden = true; $('tabs').hidden = true; $('changeForm').hidden = false;
  say('First sign-in: please set your own password.', true);
}
$('tabIn').onclick = () => setMode('in'); $('tabUp').onclick = () => setMode('up');

$('authForm').onsubmit = async e => {
  e.preventDefault();
  const email = $('email').value.trim();
  if (mode === 'up') {
    const r = await post('/register', {name: $('name').value.trim(), email});
    if (r.ok) { say('Check your email for the one-time password, then sign in.', true); setMode('in'); $('password').focus(); }
    else say(r.error);
  } else {
    const r = await post('/login', {email, password: $('password').value});
    if (!r.ok) return say(r.error || 'Something went wrong (too many attempts? wait a few minutes).');
    r.must_change ? showChange() : location.href = '/dashboard';
  }
};
$('changeForm').onsubmit = async e => {
  e.preventDefault();
  const r = await post('/change-password', {password: $('newpw').value});
  r.ok ? location.href = '/dashboard' : say(r.error);
};
fetch('/me').then(r => r.ok ? r.json() : null).then(me => { if (me && me.must_change) showChange(); });
