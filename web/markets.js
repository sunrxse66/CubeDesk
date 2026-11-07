'use strict';

let marketData = null;
let marketCatalogRevision = null;
let marketLoading = false;
let marketSaving = false;
let marketCardsKey = '';
let marketOrderKey = '';
let marketGeneration = 0;
let marketLastCheck = 0;

const marketName = pair => pair.split(':', 2)[1];

function renderMarketControls() {
  const settings = marketData?.settings;
  const job = state?.job;
  const playing = job?.running && job.kind === 'stream' && job.widget === 'markets';
  const current = playing ? state.playback.market_pair : null;
  const canShow = state?.device.kind === 'stream' && (!job.running || job.kind === 'stream');
  $('#market-show').disabled = !canShow || !settings?.pairs.length || switching || marketSaving;
  $('#market-show').textContent = playing ? 'На кубике ✓' : 'Показать на кубике ↗';
  $('#market-refresh').disabled = marketLoading || marketSaving || Boolean(marketData?.refreshing);
  $('#market-add-button').disabled = marketSaving || !settings || settings.pairs.length >= 12;
  $('#market-days').disabled = marketSaving || !settings;
  $('#market-selected').disabled = marketSaving || !settings?.pairs.length;
  $('#market-seconds').disabled = marketSaving || !settings || Boolean(settings.selected);
  document.querySelectorAll('.market-card').forEach(card => {
    card.classList.toggle('on-cube', card.dataset.pair === current);
    card.querySelectorAll('button').forEach(button => {
      button.disabled = marketSaving || button.dataset.blocked === 'true';
    });
  });
  if (!marketData) return;
  const count = marketData.items.filter(item => item.observed_at).length;
  const message = marketData.refreshing ? 'Обновляем котировки…' : `${count} из ${settings.pairs.length} пар с данными`;
  $('#market-status').textContent = current ? `На кубике ${marketName(current)} · ${message}` : message;
}

function marketButton(label, symbol, blocked, action) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = symbol;
  button.title = label;
  button.setAttribute('aria-label', label);
  button.dataset.blocked = String(blocked);
  button.addEventListener('click', action);
  return button;
}

function renderMarkets() {
  if (!marketData) return;
  const {settings, items} = marketData;
  const order = JSON.stringify(settings.pairs);
  if (order !== marketOrderKey) {
    const options = settings.pairs.map(pair => new Option(marketName(pair), pair));
    $('#market-selected').replaceChildren(new Option('Все пары по очереди', ''), ...options);
    marketOrderKey = order;
  }
  $('#market-days').value = settings.days;
  $('#market-seconds').value = settings.seconds;
  $('#market-selected').value = settings.selected || '';
  $('#market-count').textContent = `${settings.pairs.length} / 12`;
  $('#market-empty').hidden = Boolean(items.length);

  const key = JSON.stringify(items);
  if (key !== marketCardsKey) {
    const cards = items.map((item, index) => {
      const pair = item.pair;
      const name = marketName(pair);
      const card = document.createElement('article');
      card.className = 'market-card card';
      card.dataset.pair = pair;
      const image = document.createElement('img');
      image.width = 240;
      image.height = 240;
      image.loading = 'lazy';
      image.alt = `Курс и график ${name} за ${settings.days} дней`;
      const query = new URLSearchParams({kind:'markets', pair, days:settings.days, t:item.updated_at || 0});
      if (item.observed_at && !matchMedia('(prefers-reduced-motion: reduce)').matches) query.set('animate', '1');
      image.src = '/api/widgets/preview?' + query;
      const controls = document.createElement('div');
      controls.className = 'market-card-controls';
      const status = document.createElement('span');
      status.className = 'market-card-status';
      status.textContent = item.stale ? 'Сохранённые данные' : item.error ? 'Нет данных' :
        item.loading ? 'Загрузка…' : pair.startsWith('crypto:') ? 'Криптовалюта' : 'Валюта';
      const buttons = document.createElement('div');
      buttons.className = 'market-card-buttons';
      buttons.append(
        marketButton(`Поднять ${name}`, '↑', index === 0, () => moveMarket(pair, -1)),
        marketButton(`Опустить ${name}`, '↓', index === items.length - 1, () => moveMarket(pair, 1)),
        marketButton(`Убрать ${name}`, '×', false, () => removeMarket(pair)),
      );
      controls.append(status, buttons);
      card.append(image, controls);
      return card;
    });
    $('#market-grid').replaceChildren(...cards);
    marketCardsKey = key;
  }
  renderMarketControls();
}

function fillMarketCatalog(catalog) {
  $('#market-crypto-list').replaceChildren(...catalog.crypto.map(pair => new Option(pair)));
  for (const [selector, fallback] of [['#market-base', 'USD'], ['#market-quote', 'RUB']]) {
    const select = $(selector);
    const previous = select.value || fallback;
    select.replaceChildren(...Object.entries(catalog.fx).map(([code, name]) =>
      new Option(name === code ? code : `${code} · ${name}`, code)));
    select.value = previous;
  }
  marketCatalogRevision = catalog.revision;
}

async function loadMarkets(force = false) {
  if (marketLoading || marketSaving) return;
  marketLoading = true;
  const generation = marketGeneration;
  try {
    const missing = marketData && !marketData.refreshing && marketData.items.some(item => !item.updated_at && !item.error);
    const check = force || missing || Date.now() - marketLastCheck > 30000;
    const result = check ? await api('/api/markets/refresh', {force}) : await api('/api/markets/state');
    if (check) marketLastCheck = Date.now();
    if (generation === marketGeneration) {
      marketData = result;
      renderMarkets();
    }
    if (marketCatalogRevision !== result.catalog_revision) fillMarketCatalog(await api('/api/markets/catalog'));
  } catch (error) {
    $('#market-status').textContent = error.message;
    if (force) toast(error.message, true);
  } finally {
    marketLoading = false;
    renderMarketControls();
  }
}

async function saveMarkets(changes) {
  if (!marketData || marketSaving) return false;
  marketSaving = true;
  marketGeneration++;
  renderMarketControls();
  try {
    marketData = await api('/api/markets/settings', {...marketData.settings, ...changes});
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  } finally {
    marketSaving = false;
    renderMarkets();
  }
}

function moveMarket(pair, step) {
  const pairs = [...marketData.settings.pairs];
  const index = pairs.indexOf(pair);
  const other = index + step;
  if (index < 0 || other < 0 || other >= pairs.length) return;
  [pairs[index], pairs[other]] = [pairs[other], pairs[index]];
  saveMarkets({pairs});
}

function removeMarket(pair) {
  const {pairs, selected} = marketData.settings;
  saveMarkets({pairs:pairs.filter(item => item !== pair), selected:selected === pair ? null : selected});
}

$('#market-kind').addEventListener('change', () => {
  const fx = $('#market-kind').value === 'fx';
  $('#market-crypto-field').hidden = fx;
  $('#market-fx-fields').hidden = !fx;
});
$('#market-add').addEventListener('submit', async event => {
  event.preventDefault();
  if (!marketData || marketSaving) return;
  const kind = $('#market-kind').value;
  const name = kind === 'crypto' ? $('#market-crypto').value.trim().toUpperCase().replace('-', '/') :
    `${$('#market-base').value}/${$('#market-quote').value}`;
  if (!/^[A-Z0-9.]{2,12}\/[A-Z0-9.]{2,12}$/.test(name)) {
    toast('Введите пару в формате BTC/USD или выберите её из списка', true);
    return;
  }
  if (await saveMarkets({pairs:[...marketData.settings.pairs, `${kind}:${name}`]})) $('#market-crypto').value = '';
});
$('#market-days').addEventListener('change', event => saveMarkets({days:Number(event.target.value)}));
$('#market-seconds').addEventListener('change', event => saveMarkets({seconds:Number(event.target.value)}));
$('#market-selected').addEventListener('change', event => saveMarkets({selected:event.target.value || null}));
$('#market-refresh').addEventListener('click', () => loadMarkets(true));
$('#market-show').addEventListener('click', async () => {
  if (switching) return;
  switching = true;
  renderState();
  try {
    await api('/api/widgets/show', {kind:'markets'});
    await refreshState();
  } catch (error) { toast(error.message, true); }
  finally { switching = false; renderState(); }
});
setInterval(() => {
  if (!serverGone && widgetTabVisible('markets')) loadMarkets();
}, 2500);
