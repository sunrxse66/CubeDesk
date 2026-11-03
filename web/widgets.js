'use strict';
let weatherState = null, cityBusy = false, widgetsLoading = false, weatherLastCheck = 0, cityEditorInitialized=false;
const widgetNames = {clock:'Часы',weather:'Погода',combined:'Часы и погода'};
const widgetButtons = {clock:'Показать часы ↗',weather:'Показать погоду ↗',combined:'Показать общий экран ↗'};

function renderWidgetControls() {
  if (!state) return;
  const job=state.job;
  const running=job.running && job.kind==='stream';
  const showing=running && job.scope==='widget';
  const allowed=state.device.kind==='stream' && (!job.running || running) && !switching && !importing;
  document.querySelectorAll('.show-widget').forEach(button => {
    const kind=button.dataset.kind;
    const active=showing && job.widget===kind;
    button.disabled=!allowed || (kind!=='clock' && !state.settings.widget_city);
    button.setAttribute('aria-pressed',String(active));
    button.textContent=active ? 'На кубике сейчас ✓' : widgetButtons[kind];
    button.closest('.widget-card').classList.toggle('is-playing',active);
  });
  $('#widget-now').textContent=showing ? 'На кубике · '+widgetNames[job.widget] : 'Выберите виджет';
  $('#widgets-stop').disabled=!running || switching;
  $('#weather-refresh').disabled=!state.settings.widget_city || cityBusy || Boolean(weatherState?.refreshing);
  $('#city-search').disabled=cityBusy;
  $('#city-query').disabled=cityBusy;
}

function renderWeather() {
  if (!weatherState) return;
  const w=weatherState;
  $('#chosen-city').textContent=w.city ? [w.city.name,w.city.region,w.city.country].filter(Boolean).join(' · ') : 'Выберите город для погодных виджетов.';
  $('#chosen-city').title=$('#chosen-city').textContent;
  if(!cityEditorInitialized){$('#city-editor').open=!w.city;cityEditorInitialized=true;}
  let text='Часы уже готовы. Для погоды нужен город и интернет.';
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
  try { await api('/api/stop',{});await refreshState(); }
  catch(error) { toast(error.message,true); }
});
setInterval(() => { if (!serverGone && $('#page-widgets').classList.contains('active')) loadWidgets(); },2000);
