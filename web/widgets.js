'use strict';
let weatherState = null, cityBusy = false, widgetsLoading = false, weatherLastCheck = 0;
const widgetNames = {
  clock:'Часы', weather:'Погода', combined:'Часы и погода', markets:'Курсы валют',
  storm:'Гроза', fireflies:'Светлячки', aurora:'Северное сияние', jellyfish:'Медузы',
  village:'Жизнь за стеклом',
};
const widgetTabs = [...document.querySelectorAll('[data-widget-tab]')];

function selectWidgetTab(name) {
  for (const tab of widgetTabs) {
    const selected = tab.dataset.widgetTab === name;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    $('#' + tab.getAttribute('aria-controls')).hidden = !selected;
  }
  if (name === 'daily') loadWidgets();
  if (name === 'markets') loadMarkets();
  if (name === 'village') renderVillageControls();
}

function widgetTabVisible(name) {
  return $('#page-widgets').classList.contains('active') && !$(`#widget-panel-${name}`).hidden;
}

$('.widget-tabs').addEventListener('keydown', event => {
  const index = widgetTabs.indexOf(event.target);
  if (index < 0) return;
  const last = widgetTabs.length - 1;
  const offset = {ArrowLeft: (index + last) % widgetTabs.length,
                  ArrowRight: (index + 1) % widgetTabs.length, Home: 0, End: last, ' ': index};
  if (!Object.hasOwn(offset, event.key)) return;
  event.preventDefault();
  const target = widgetTabs[offset[event.key]];
  target.focus();
  target.click();
});

function renderWidgetControls() {
  if (!state) return;
  const job=state.job;
  const running=job.running && job.kind==='stream';
  const showing=running && job.scope==='widget';
  const allowed=state.device.kind==='stream' && (!job.running || running) && !switching && !importing;
  let activePanel = running && job.scope === 'pet' ? 'widget-panel-pets' :
    showing && ['markets','village'].includes(job.widget) ? `widget-panel-${job.widget}` : null;
  document.querySelectorAll('.show-widget').forEach(button => {
    const kind=button.dataset.kind;
    const active=showing && job.widget===kind;
    button.disabled=!allowed || ((kind==='weather' || kind==='combined') && !state.settings.widget_city);
    button.setAttribute('aria-pressed',String(active));
    button.textContent=active ? 'На кубике ✓' : 'Показать на кубике ↗';
    button.closest('.widget-card').classList.toggle('is-playing',active);
    if (active) activePanel = button.closest('.widget-panel').id;
  });
  for (const tab of widgetTabs) tab.classList.toggle('has-playback', tab.getAttribute('aria-controls') === activePanel);
  const output = $('#widget-now');
  const description = {
    widget: widgetNames[job.widget], pet: state.pet?.name,
    file: library.find(item => item.id === job.file_id)?.name || 'Файл из медиатеки', folder: 'Медиатека',
  };
  const label = job.restoring && running ? 'Ожидаем кубик…' : running ? (description[job.scope] || 'Идёт показ') :
    state.device.kind === 'stream' ? 'Показ с ПК остановлен' : state.device.kind === 'stock' ? 'Подключена штатная прошивка' : 'Кубик не подключён';
  if (output.textContent !== label) output.textContent = label;
  output.closest('.widget-output').classList.toggle('is-playing', running && !job.restoring);
  $('#widgets-stop').disabled=!running || switching;
  $('#weather-refresh').disabled=!state.settings.widget_city || cityBusy || Boolean(weatherState?.refreshing);
  $('#city-search').disabled=cityBusy;
  $('#city-query').disabled=cityBusy;
  if (typeof renderMarketControls === 'function') renderMarketControls();
}

function renderWeather() {
  if (!weatherState) return;
  const w=weatherState;
  $('#chosen-city').textContent=w.city ? [w.city.name,w.city.region,w.city.country].filter(Boolean).join(' · ') : 'Выберите город для погодных виджетов.';
  $('#chosen-city').title=$('#chosen-city').textContent;
  $('.city-edit-label').textContent = w.city ? 'Изменить' : 'Выбрать';
  let text='Выберите город, чтобы включить виджеты с погодой.';
  if (w.city) {
    if (w.forecast) {
      const updated=w.updated_at ? new Date(w.updated_at*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}) : '—';
      text=(w.phase==='stale' ? 'Сохранённый прогноз · ' : 'Погода обновлена в ')+updated;
      if (w.error) text+=' · '+w.error;
      else if (w.refreshing) text+=' · обновляем…';
    } else text=w.error || 'Загружаем погоду для выбранного города…';
  }
  $('#weather-status').textContent=text;
  $('#weather-status').classList.toggle('weather-warning',w.phase==='stale' || w.phase==='error');
  renderWidgetControls();
}

function refreshWidgetPreviews() {
  const tick=Math.floor(Date.now()/1000);
  document.querySelectorAll('[data-widget-preview]').forEach(img => {
    img.src='/api/widgets/preview?kind='+img.dataset.widgetPreview+'&t='+tick;
  });
}

async function loadWidgets(refresh=false, force=false) {
  if (widgetsLoading) return;
  widgetsLoading=true;
  try {
    const check=refresh || Date.now()-weatherLastCheck>60000;
    weatherState=await api(check ? '/api/widgets/refresh' : '/api/widgets/state',check ? {force} : undefined);
    if (check) weatherLastCheck=Date.now();
    renderWeather();refreshWidgetPreviews();
  } catch(error) { toast(error.message,true); }
  finally { widgetsLoading=false; }
}

$('#city-search-form').addEventListener('submit',async event => {
  event.preventDefault();
  if (cityBusy) return;
  cityBusy=true;renderWidgetControls();$('#city-results').replaceChildren();
  $('#weather-status').textContent='Ищем город…';
  try {
    const data=await api('/api/widgets/search',{query:$('#city-query').value.trim()});
    if (!data.cities.length) $('#weather-status').textContent='Город не найден. Попробуйте другое название или добавьте страну.';
    else {
      $('#weather-status').textContent='Выберите ваш город в списке.';
      for (const city of data.cities) {
        const button=document.createElement('button');button.type='button';button.className='city-option';
        const name=document.createElement('strong');name.textContent=city.name;
        const region=document.createElement('span');region.textContent=[city.region,city.country].filter(Boolean).join(' · ');
        button.append(name,region);
        button.addEventListener('click',async () => {
          if (cityBusy) return;
          cityBusy=true;renderWidgetControls();
          try {
            weatherState=await api('/api/widgets/city',{id:city.id});
            $('#city-results').replaceChildren();$('#city-query').value='';
            $('#city-editor').open=false;
            await refreshState();renderWeather();refreshWidgetPreviews();toast('Город сохранён · '+city.name);
          } catch(error) { toast(error.message,true); }
          finally { cityBusy=false;renderWidgetControls(); }
        });
        $('#city-results').append(button);
      }
    }
  } catch(error) { $('#weather-status').textContent=error.message;toast(error.message,true); }
  finally { cityBusy=false;renderWidgetControls(); }
});

document.querySelectorAll('.show-widget').forEach(button => button.addEventListener('click',async () => {
  if (switching) return;
  switching=true;renderState();
  try { await api('/api/widgets/show',{kind:button.dataset.kind});await refreshState(); }
  catch(error) { toast(error.message,true); }
  finally { switching=false;renderState(); }
}));
$('#weather-refresh').addEventListener('click',() => loadWidgets(true,true));
$('#widgets-stop').addEventListener('click',async () => {
  if (switching) return;
  switching=true;renderState();
  try { await api('/api/stop',{});await refreshState(); }
  catch(error) { toast(error.message,true); }
  finally { switching=false;renderState(); }
});
setInterval(() => { if (!serverGone && widgetTabVisible('daily')) loadWidgets(); },2000);
