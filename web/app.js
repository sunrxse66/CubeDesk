'use strict';
const $ = selector => document.querySelector(selector);
const key = $('meta[name="cubedesk-key"]').content;
let state = null, library = [], importing = false, switching = false, previewId = null, toastTimer, previousJob = false, serverGone = false;
const titles = {connect:'Подключим ваш кубик',setup:'Настроим новый кубик',library:'Ваша медиатека',widgets:'Виджеты для вашего кубика',background:'Кубик работает сам',guide:'Всё начинается с подключения',updates:'Всегда актуальный CubeDesk'};
const widgetRoutes = new Map([['widgets','daily'], ['widgets/nature','nature'], ['widgets/pets','pets'], ['widgets/village','village'], ['widgets/markets','markets']]);
let backgroundSaving = false;
const bytes = size => size == null ? '—' : size < 1048576 ? `${Math.round(size / 1024)} КБ` : `${(size / 1048576).toFixed(1)} МБ`;
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function toast(message, error = false) { const el = $('#toast'); el.textContent = message; el.classList.toggle('error', error); el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, error ? 11000 : 5000); }
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-CubeDesk-Key':key},body:JSON.stringify(data)});
  let result; try { result = await response.json(); } catch { throw new Error('Локальный сервер не ответил. Запустите CubeDesk снова.'); }
  if (!response.ok) throw new Error(result.error || 'Не удалось выполнить действие');
  return result;
}
function page(route) {
  if (route === 'markets') route = 'widgets/markets';
  const widgetTab = widgetRoutes.get(route);
  if (!widgetTab && !Object.hasOwn(titles, route)) route = 'connect';
  const name = widgetTab ? 'widgets' : route;
  document.querySelectorAll('.page').forEach(el => el.classList.toggle('active',el.id === `page-${name}`));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active',el.dataset.page === name));
  $('#page-title').textContent = titles[name];
  if (location.hash !== `#${route}`) history.replaceState(null,'',`#${route}`);
  window.scrollTo({top:0,behavior:'instant'});
  if (widgetTab && typeof selectWidgetTab === 'function') selectWidgetTab(widgetTab);
}
document.querySelectorAll('[data-page]').forEach(el => el.addEventListener('click', () => page(el.dataset.page)));
window.addEventListener('hashchange', () => page(location.hash.slice(1)));
function renderState() {
  const {device:d,job:j} = state; const connected = ['stock','stream'].includes(d.kind);
  renderBackground();
  if (typeof renderOnboarding === 'function') renderOnboarding();
  $('#exit-app').disabled = j.running && j.kind === 'firmware';
  const badge = $('#connection-badge'); badge.className = `status ${connected ? 'online' : d.kind === 'offline' ? 'offline' : ''} ${j.running ? 'busy' : ''}`;
  badge.replaceChildren(Object.assign(document.createElement('i'),{}),document.createTextNode(j.running ? (j.restoring ? 'Ожидаем кубик' : j.kind === 'stream' ? 'Воспроизводим' : 'Подождите…') : connected ? 'Кубик подключён' : 'Не подключён'));
  $('#device-mode').textContent = d.kind === 'stock' ? 'Штатная прошивка' : d.kind === 'stream' ? 'Потоковый режим' : 'Ожидает подключения';
  $('#connect-button').disabled = j.running || importing; $('#connect-button').textContent = j.running && j.kind === 'connect' ? 'Проверяем…' : connected ? 'Проверить снова' : 'Подключить →';
  const link = $('#device-link'); link.classList.toggle('disabled',!connected); link.href = connected ? `http://${d.host}/` : '#';
  $('#connect-message').textContent = j.message; $('#connect-message').classList.toggle('error',j.error);
  $('#device-details').hidden = !connected; $('#model').textContent = d.model || '—'; $('#firmware').textContent = d.version || '—';
  $('#memory-label').textContent = d.kind === 'stream' ? 'Кадры приходят с ПК' : d.free == null ? 'Проверяется при подключении' : `${bytes(d.free)} свободно из ${bytes(d.total)}`;
  $('#memory-progress').hidden = d.free == null; $('#memory-progress').value = d.total ? 100 * (1-d.free/d.total) : 0;
  $('#token-status').textContent = state.settings.has_token ? 'Токен сохранён на этом ПК' : 'Токен не задан';
  const streamRunning = j.running && j.kind === 'stream';
  const canShow = connected && (!j.running || (d.kind === 'stream' && streamRunning)) && !importing && !switching;
  $('#play').disabled = d.kind !== 'stream' || (j.running && !(streamRunning && ['file','widget','pet'].includes(j.scope))) || !library.some(item => !item.error) || importing || switching;
  $('#stop').disabled = !streamRunning || switching;
  const measured = state.playback?.fps;
  const widgetEdge = state.playback?.resolution || 240;
  $('#player-title').textContent = streamRunning && j.scope === 'pet' ? 'Питомец на кубике' : streamRunning && j.scope === 'widget' ? 'Виджет на кубике' : streamRunning && j.scope === 'file' ? 'Выбранный файл' : 'Воспроизведение всей папки';
  $('#player-description').textContent = j.running && j.kind === 'stream' ?
    j.scope === 'pet' ? `${state.pet?.name || 'Моти'} · ${state.pet?.label || 'Отдыхает'}` : j.scope === 'widget' ? `${j.message} · ${widgetEdge}×${widgetEdge}` : `${measured ? `${measured.toLocaleString('ru-RU')} кадров/с · ${state.playback.resolution}×${state.playback.resolution} · ` : 'Подготовка кадров · '}${j.message}` :
    'Исходная скорость GIF · кадры готовятся заранее';
  $('#library-mode-note').textContent = d.kind === 'stock' ? 'Штатная прошивка: «Показать» загрузит один файл в память кубика. JPG готовится автоматически; GIF нужен размером 240×240. Для длинных анимаций требуется PCStream.' : d.kind === 'stream' ? '«Показать на кубике» запускает только выбранный файл: GIF повторяется, картинка остаётся на экране. Можно переключать файлы во время показа. «Всю папку» включает всю медиатеку по очереди. ПК должен оставаться включённым.' : 'Для показа на устройстве сначала подключите кубик. Просматривать и добавлять файлы можно уже сейчас.';
  $('#event-log').textContent = state.events.length ? state.events.map(e => `${e.time}  ${e.message}`).join('\n') : 'Пока нет событий.';
  document.querySelectorAll('.show-file').forEach(button => {
    const active = streamRunning && j.scope === 'file' && j.file_id === button.dataset.id;
    button.disabled = !canShow || button.dataset.invalid === 'true';
    button.setAttribute('aria-pressed', String(active));
    button.textContent = active ? 'На кубике · с начала ↻' : 'Показать на кубике ↗';
    button.closest('.media-card').classList.toggle('is-playing', active);
  });
  $('#preview-show').disabled = !canShow || !previewId || Boolean(library.find(item => item.id === previewId)?.error);
  ['#add-files','#add-folder','#change-folder','#refresh-library'].forEach(selector => $(selector).disabled = importing || j.running);
  if (previousJob && !j.running) { if (j.error) toast(j.message,true); else if (j.kind !== 'stream') toast(j.message); }
  previousJob = j.running;
  if (typeof renderWidgetControls === 'function') renderWidgetControls();
  if (typeof renderPetControls === 'function') renderPetControls();
  if (typeof renderVillageControls === 'function') renderVillageControls();
}
async function refreshState() { if (serverGone) return; try { state = await api('/api/state'); renderState(); } catch { $('#connection-badge').textContent = 'Приложение недоступно'; $('#connect-message').textContent = 'Запустите CubeDesk заново. Сервер не отвечает.'; } }
function renderBackground() {
  const b = state.background;
  if (!b) return;
  const j = state.job, stream = j.running && j.kind === 'stream';
  if (!backgroundSaving) {
    $('#background-startup').checked = b.startup_enabled;
    $('#background-resume').checked = b.resume_on_start;
  }
  $('#background-startup').disabled = backgroundSaving || !b.startup_supported;
  $('#background-resume').disabled = backgroundSaving;
  $('#background-startup-help').textContent = b.startup_supported ? 'Оставьте CubeDesk.exe в постоянной папке. Автозапуск можно отключить здесь или в настройках Windows.' : 'Автозапуск настраивается в готовом CubeDesk.exe при обычном запуске.';
  $('#background-scene').textContent = b.last_scene || 'Пока ничего не выбрано';
  $('#background-status').textContent = stream ? (j.restoring ? j.message : 'Сейчас на кубике') : b.paused ? 'На паузе. Автоматически не запустится.' : b.has_selection ? (b.resume_on_start ? 'Вернётся при следующем запуске CubeDesk' : 'Автовозобновление выключено') : 'Выберите что-нибудь в медиатеке или виджетах';
  $('#background-continue').disabled = backgroundSaving || j.running || !b.has_selection;
  $('#background-pause').disabled = backgroundSaving || !stream;
}
for (const [id, setting] of [['background-startup','startup_enabled'], ['background-resume','resume_on_start']]) {
  $(`#${id}`).addEventListener('change', async event => {
    const value = event.target.checked;
    backgroundSaving = true; renderBackground();
    try { await api('/api/background/settings',{[setting]:value}); await refreshState(); toast('Настройка сохранена'); }
    catch(error) { toast(error.message,true); }
    finally { backgroundSaving = false; await refreshState(); }
  });
}
$('#background-continue').addEventListener('click', async () => {
  try { await api('/api/background/resume',{}); await refreshState(); } catch(error) { toast(error.message,true); }
});
$('#background-pause').addEventListener('click', async () => {
  try { await api('/api/stop',{}); await refreshState(); } catch(error) { toast(error.message,true); }
});
function renderLibrary() {
  const filtered = library.filter(item => item.name.toLocaleLowerCase().includes($('#search').value.toLocaleLowerCase()));
  const grid = $('#media-grid'); grid.replaceChildren(); $('#empty-library').hidden = filtered.length > 0;
  $('#file-count').textContent = library.length; $('#nav-count').textContent = library.length;
  for (const item of filtered) {
    const card = document.createElement('article'); card.className = 'media-card';
    const type = item.frames > 1 ? 'GIF / АНИМАЦИЯ' : item.name.split('.').pop().toUpperCase();
    card.innerHTML = `<button class="media-image" aria-label="Предпросмотр ${escape(item.name)}"><img loading="lazy" src="/api/thumbnail?id=${item.id}" alt="${escape(item.name)}"><span class="media-type">${escape(type)}</span></button><div class="media-body"><h3 title="${escape(item.name)}">${escape(item.name)}</h3><p>${item.error ? escape(item.error) : `${item.width} × ${item.height} &nbsp; · &nbsp; ${bytes(item.bytes)}`}</p><button class="secondary show-file" data-invalid="${Boolean(item.error)}">Показать на кубике ↗</button></div>`;
    card.querySelector('img').addEventListener('error', event => { event.target.removeAttribute('src'); event.target.alt = 'Предпросмотр недоступен'; }, {once:true});
    card.querySelector('.media-image').addEventListener('click', () => { previewId = item.id; $('#preview-image').src = `/api/preview?id=${item.id}`; $('#preview-name').textContent = item.name; $('#preview-meta').textContent = `${item.width} × ${item.height} · ${bytes(item.bytes)}${item.frames > 1 ? ` · ${item.frames} кадров` : ''}`; renderState(); $('#preview-dialog').showModal(); });
    card.querySelector('.show-file').dataset.id = item.id;
    card.querySelector('.show-file').addEventListener('click', () => showFile(item.id));
    grid.append(card);
  }
  if (!filtered.length && library.length) { $('#empty-library').querySelector('h3').textContent = 'Ничего не найдено'; $('#empty-library').querySelector('p').textContent = 'Попробуйте другое название.'; } else { $('#empty-library').querySelector('h3').textContent = 'Здесь будут ваши картинки'; $('#empty-library').querySelector('p').textContent = 'Добавьте файлы или подключите папку на компьютере.'; }
  if (state) renderState();
}
async function refreshLibrary() { try { const data = await api('/api/library'); library = data.items; $('#folder-label').textContent = data.folder; $('#folder-label').title = data.folder; renderLibrary(); } catch(error) { toast(error.message,true); } }
$('#search').addEventListener('input',renderLibrary);
$('#refresh-library').addEventListener('click',refreshLibrary);
$('#connect-form').addEventListener('submit',async event => { event.preventDefault(); try { state = await api('/api/settings',{host:$('#host').value.trim()}); await api('/api/connect',{}); await refreshState(); } catch(error) { toast(error.message,true); } });
$('#token-form').addEventListener('submit',async event => { event.preventDefault(); if (!$('#token').value.trim()) { toast('Вставьте API-токен PCStream',true); return; } try { state = await api('/api/settings',{token:$('#token').value.trim()}); $('#token').value = ''; renderState(); toast('Токен сохранён. Теперь подключите кубик.'); } catch(error) { toast(error.message,true); } });
$('#change-folder').addEventListener('click', () => { $('#folder-path').value = state.settings.folder; $('#folder-dialog').showModal(); });
$('#folder-cancel').addEventListener('click', () => $('#folder-dialog').close());
$('#folder-form').addEventListener('submit', async event => { event.preventDefault(); try { state = await api('/api/settings',{folder:$('#folder-path').value.trim().replace(/^"|"$/g,'')}); $('#folder-dialog').close(); await refreshLibrary(); toast('Папка подключена'); } catch(error) { toast(error.message,true); } });
$('#preview-close').addEventListener('click', () => $('#preview-dialog').close());
$('#preview-dialog').addEventListener('close', () => { previewId = null; $('#preview-image').removeAttribute('src'); });
const playbackOptions = () => ({fps:Number($('#fps').value),seconds:Number($('#seconds').value),detail:$('#detail').value});
async function showFile(id) {
  if (switching) return;
  switching = true; renderState();
  try { await api('/api/show',{id,...playbackOptions()}); if ($('#preview-dialog').open) $('#preview-dialog').close(); await refreshState(); }
  catch(error) { toast(error.message,true); }
  finally { switching = false; renderState(); }
}
$('#preview-show').addEventListener('click', () => { if (previewId) showFile(previewId); });
$('#add-files').addEventListener('click', () => $('#files-input').click()); $('#empty-add').addEventListener('click', () => $('#files-input').click());
$('#add-folder').addEventListener('click', () => $('#folder-input').click());
async function importFiles(files) {
  if (importing || state?.job.running) { toast('Сначала завершите текущую операцию',true); return; }
  const selected = [...files].filter(file => /\.(jpe?g|png|gif|webp|bmp)$/i.test(file.name));
  if (!selected.length) { toast('Выберите JPG, PNG, GIF, WebP или BMP',true); return; }
  importing = true; renderState(); let folder = '', imported = 0; const failures = [];
  try {
    for (const file of selected) {
      toast(`Добавляем ${imported + failures.length + 1} из ${selected.length}: ${file.name}`);
      try { const response = await fetch(`/api/import?name=${encodeURIComponent(file.name)}`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-CubeDesk-Key':key},body:file}); const data = await response.json(); if (!response.ok) throw new Error(data.error); folder = data.folder; imported++; } catch(error) { failures.push(`${file.name}: ${error.message}`); }
    }
    if (folder) state = await api('/api/settings',{folder});
    await refreshLibrary(); page('library');
    toast(failures.length ? `Добавлено ${imported}. ${failures.join(' · ')}` : `Добавлено файлов: ${imported}`,Boolean(failures.length));
  } catch(error) { toast(error.message,true); } finally { importing = false; renderState(); }
}
['#files-input','#folder-input'].forEach(selector => $(selector).addEventListener('change',event => { importFiles(event.target.files); event.target.value = ''; }));
document.addEventListener('dragover', event => { event.preventDefault(); if (event.dataTransfer.types.includes('Files')) $('#drop-zone').classList.add('dragging'); });
document.addEventListener('dragleave', event => { if (!event.relatedTarget) $('#drop-zone').classList.remove('dragging'); });
document.addEventListener('drop',event => { event.preventDefault(); $('#drop-zone').classList.remove('dragging'); if (event.dataTransfer.files.length) importFiles(event.dataTransfer.files); });
$('#play').addEventListener('click', async () => { if (switching) return; switching = true; renderState(); try { await api('/api/play',playbackOptions()); await refreshState(); } catch(error) { toast(error.message,true); } finally { switching = false; renderState(); } });
$('#stop').addEventListener('click',async () => { try { await api('/api/stop',{}); toast('Останавливаем воспроизведение…'); } catch(error) { toast(error.message,true); } });
$('#exit-app').addEventListener('click',async () => { if (!confirm('Завершить CubeDesk? Воспроизведение с ПК остановится.')) return; try { await api('/api/shutdown',{}); serverGone = true; $('#connection-badge').textContent = 'Приложение завершено'; document.querySelectorAll('button').forEach(button => button.disabled = true); toast('CubeDesk завершён. Эту вкладку можно закрыть.'); } catch(error) { toast(error.message,true); } });
async function start() { try { state = await api('/api/state'); $('#host').value = state.settings.host; $('#fps').value = state.settings.fps; $('#seconds').value = state.settings.seconds; $('#detail').value = state.settings.detail || 'smooth'; renderState(); await refreshLibrary(); const needsSetup = !state.settings.host || ['uncertain','waiting_setup'].includes(state.onboarding?.phase); page(location.hash.slice(1) || (needsSetup ? 'setup' : 'connect')); } catch(error) { toast(error.message,true); } finally { const poll = async () => { await refreshState(); if (!serverGone) setTimeout(poll,1500); }; setTimeout(poll,1500); } }
start();
