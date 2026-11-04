'use strict';
let setupSubmitting = false, setupCheckId = '', previousSetupPhase = '';
function renderOnboarding() {
  if (!state?.onboarding) return;
  const s = state.onboarding, phase = s.phase, busy = state.job.running || setupSubmitting;
  const pairing = ['needs_pairing','waiting_setup','uncertain','complete'].includes(phase) || (phase === 'error' && (s.device?.kind === 'stream' || s.firmware));
  const installing = ['compatible','preparing','ready','installing'].includes(phase);
  if (setupCheckId !== s.check_id || phase !== 'ready') $('#setup-consent').checked = false;
  setupCheckId = s.check_id;
  $('#setup-status').textContent = s.message;
  $('#setup-status').classList.toggle('error',['error','unsupported','uncertain'].includes(phase));
  $('#setup-detect-card').hidden = phase === 'complete';
  $('#setup-install-card').hidden = !installing;
  $('#setup-pair-card').hidden = !pairing || phase === 'complete';
  $('#setup-complete').hidden = phase !== 'complete';
  $('#setup-device').hidden = !s.device;
  $('#setup-device').textContent = s.device ? `${s.device.model} · ${s.device.version}` : '';
  $('#setup-stream-note').hidden = !(state.job.running && state.job.kind === 'stream');
  const blocked = busy && state.job.kind !== 'stream';
  $('#setup-host').disabled = blocked;
  $('#setup-probe').disabled = blocked || setupSubmitting;
  $('#setup-probe').textContent = phase === 'checking' ? 'Проверяем…' : 'Проверить кубик';
  $('#setup-prepare').disabled = busy || !['compatible','ready'].includes(phase);
  $('#setup-prepare').hidden = phase === 'ready' || phase === 'installing';
  $('#setup-consent-block').hidden = phase !== 'ready';
  $('#setup-consent').disabled = busy;
  $('#setup-install').disabled = busy || phase !== 'ready' || !$('#setup-consent').checked;
  $('#setup-firmware').textContent = s.firmware ? `PCStream ${s.firmware.version} · ${bytes(s.firmware.size)} · SHA-256 проверен` : '';
  $('#setup-progress').hidden = !['preparing','installing'].includes(phase);
  if (phase === 'preparing') $('#setup-progress').removeAttribute('value');
  else $('#setup-progress').value = s.progress;
  for (const id of ['setup-pair','setup-pair-host','setup-token']) $(`#${id}`).disabled = blocked || setupSubmitting;
  $('#setup-key-help').textContent = state.settings.has_token ? 'Для этого кубика можно оставить поле пустым и проверить сохранённый ключ. Для нового кубика вставьте его новый API-токен.' : 'Скопируйте ключ из настройки PCStream. Это не пароль Wi-Fi.';
  const step = phase === 'complete' ? 4 : pairing ? 3 : installing ? 2 : 1;
  document.querySelectorAll('[data-setup-step]').forEach(el => { const n=Number(el.dataset.setupStep); el.classList.toggle('active',n===step); el.classList.toggle('done',n<step); });
  if (phase === 'complete' && previousSetupPhase !== phase && $('#page-setup').classList.contains('active')) window.scrollTo({top:0,behavior:'instant'});
  previousSetupPhase = phase;
}
async function setupRequest(path, data) {
  if (setupSubmitting) return;
  setupSubmitting = true; renderOnboarding();
  try { await api(path,data); await refreshState(); }
  catch(error) { toast(error.message,true); }
  finally { setupSubmitting = false; renderOnboarding(); }
}
$('#setup-probe-form').addEventListener('submit',async event => {
  event.preventDefault();
  const host=$('#setup-host').value.trim();
  if (!$('#setup-pair-host').value) $('#setup-pair-host').value=host;
  await setupRequest('/api/setup/probe',{host});
});
$('#setup-prepare').addEventListener('click',() => setupRequest('/api/setup/prepare',{}));
$('#setup-another').addEventListener('click',async () => {
  await setupRequest('/api/setup/reset',{});
  if (state.onboarding?.phase === 'idle') { $('#setup-host').value=''; $('#setup-pair-host').value=''; $('#setup-host').focus(); }
});
$('#setup-consent').addEventListener('change',renderOnboarding);
$('#setup-install').addEventListener('click',() => setupRequest('/api/setup/install',{confirmed:$('#setup-consent').checked,check_id:setupCheckId}));
$('#setup-pair-form').addEventListener('submit',async event => {
  event.preventDefault();
  const token=$('#setup-token').value.trim();
  $('#setup-token').value='';
  await setupRequest('/api/setup/pair',{host:$('#setup-pair-host').value.trim(),token});
  if (state.onboarding?.phase === 'complete') { $('#host').value=state.settings.host; toast('Кубик готов. Выберите GIF или виджет.'); }
});
// Restore a pending first-install guide even if the browser or PC was restarted.
api('/api/state').then(s => {
  if (!$('#setup-host').value) $('#setup-host').value=s.onboarding?.host || s.settings.host || '';
  if (!$('#setup-pair-host').value) $('#setup-pair-host').value=s.onboarding?.host || s.settings.host || '';
  if (!location.hash && (!s.settings.host || ['uncertain','waiting_setup'].includes(s.onboarding?.phase))) page('setup');
}).catch(() => {});
