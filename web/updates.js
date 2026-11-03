'use strict';
let updateState = null, installingApp = false;
const compareVersion = value => String(value || '').replace(/^PCStream v|^v/,'').split('.').map(Number);
function newerVersion(candidate, current) {
  const a = compareVersion(candidate), b = compareVersion(current);
  if (!a.length || !b.length || [...a,...b].some(Number.isNaN)) return false;
  for (let i=0;i<3;i++) { if ((a[i]||0)!==(b[i]||0)) return (a[i]||0)>(b[i]||0); }
  return false;
}
function renderUpdates() {
  if (!updateState) return;
  const u = updateState, device = state?.device;
  $('#updates-status').textContent = installingApp ? 'CubeDesk перезапускается. Подождите, панель подключится автоматически…' : u.message;
  $('#updates-check').disabled = u.busy || installingApp;
  $('#updates-progress').hidden = u.status !== 'downloading';
  $('#updates-progress').value = u.progress;
  $('#update-app-versions').textContent = `Установлена ${u.current_version}${u.latest_version ? ' · В релизе '+u.latest_version : ''}`;
  $('#update-app-download').disabled = !u.available || u.busy || installingApp || u.ready.includes('app');
  $('#update-app-install').hidden = !u.ready.includes('app');
  $('#update-app-install').disabled = u.busy || installingApp || !u.install_supported || Boolean(state?.job.running && state.job.kind !== 'stream');
  $('#update-app-help').textContent = u.install_supported ? 'Перед установкой файл проверяется по SHA-256. Предыдущий .exe сохраняется для отката.' : 'Установка из панели доступна в готовом CubeDesk.exe для Windows.';
  const compatible = device?.kind === 'stream' && device.model === 'HelloCubic-Lite';
  const fwAvailable = compatible && u.firmware && newerVersion(u.firmware.version, device.version);
  $('#update-fw-versions').textContent = compatible ? `Установлена ${device.version}${u.firmware ? ' · В релизе '+u.firmware.version : ''}` : 'Подключите HelloCubic-Lite с PCStream.';
  $('#update-fw-download').disabled = !fwAvailable || u.busy || installingApp || u.ready.includes('firmware');
  $('#update-fw-install').hidden = !u.ready.includes('firmware');
  $('#update-fw-install').disabled = !fwAvailable || u.busy || installingApp || Boolean(state?.job.running && state.job.kind !== 'stream');
  $('#update-fw-help').textContent = state?.job.kind === 'firmware' ? state.job.message : compatible && u.firmware && !fwAvailable ? 'На кубике актуальная или более новая прошивка.' : 'При обновлении воспроизведение остановится. Не отключайте питание кубика.';
  $('#update-notes').textContent = u.notes || 'После публикации релиза здесь появится описание изменений.';
  $('#updates-dot').hidden = !u.available && !fwAvailable;
}
async function refreshUpdates() {
  if (installingApp) return;
  try { updateState = await api('/api/updates'); renderUpdates(); } catch { /* Retry after a temporary local restart. */ }
}
async function updateAction(path, body) {
  try { await api(path,body); await refreshUpdates(); } catch(error) { toast(error.message,true); }
}
$('#updates-check').addEventListener('click',()=>updateAction('/api/updates/check',{}));
$('#update-app-download').addEventListener('click',()=>updateAction('/api/updates/download',{kind:'app'}));
$('#update-fw-download').addEventListener('click',()=>updateAction('/api/updates/download',{kind:'firmware'}));
$('#update-fw-install').addEventListener('click',async()=>{
  if (!confirm('Обновить прошивку HelloCubic-Lite? Воспроизведение остановится. Оставьте питание включённым до завершения обновления.')) return;
  await updateAction('/api/updates/install-firmware',{});
  await refreshState(); renderUpdates();
});
$('#update-app-install').addEventListener('click',async()=>{
  if (!confirm('Установить новую версию CubeDesk и перезапустить приложение? Медиатека и настройки сохранятся.')) return;
  try {
    const oldVersion = state?.version;
    await api('/api/updates/install-app',{});
    installingApp = true; renderUpdates();
    const deadline = Date.now()+150000;
    const reconnect = async()=>{
      try {
        const response = await fetch('/api/health',{cache:'no-store'});
        const health = await response.json();
        if (health.app === 'CubeDesk' && (health.version !== oldVersion || Date.now()>deadline-60000)) { location.reload(); return; }
      } catch { }
      if (Date.now()<deadline) setTimeout(reconnect,1000);
      else { installingApp=false; $('#updates-status').textContent='Не удалось подключиться после обновления. Запустите CubeDesk.exe. Предыдущая версия сохранена рядом в .previous.'; }
    };
    setTimeout(reconnect,2000);
  } catch(error) { toast(error.message,true); }
});
refreshUpdates();
setInterval(()=>{ if (!document.hidden) refreshUpdates(); },2000);
