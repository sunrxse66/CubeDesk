'use strict';

const villageForm = $('#village-form');
const villageImage = $('#village-preview');
let villageEditing = false, villageSaving = false, villagePreviewBusy = false;
let villageJournalKey = '', villageJournalBusy = false, villageNoticeKey = '';
let villagePeopleKey = '';

function villageCanShow() {
  const job = state?.job;
  return state?.device.kind === 'stream' && (!job.running || job.kind === 'stream') && !switching && !importing;
}

function villageProfileInput() {
  return {
    name: $('#village-name').value.trim(),
    look: $('#village-look').value,
    color: $('#village-color').value,
    home: villageForm.querySelector('input[name="village-home"]:checked').value,
  };
}

function showVillagePoster() {
  const {home, look, color} = villageProfileInput();
  villageImage.src = '/api/village/preview?' + new URLSearchParams({home, look, color});
}

function villagePreviewLoop() {
  if (serverGone || villagePreviewBusy || villageEditing || !state?.village || document.hidden || !widgetTabVisible('village')) return;
  villagePreviewBusy = true;
  villageImage.onload = villageImage.onerror = () => { villagePreviewBusy = false; };
  villageImage.src = '/api/village/preview?t=' + Date.now();
}
setInterval(villagePreviewLoop, 300);

async function loadVillageJournal(key) {
  if (villageJournalBusy || key === villageJournalKey) return;
  villageJournalBusy = true;
  try {
    const {entries} = await api('/api/village/journal');
    $('#village-journal-empty').hidden = Boolean(entries.length);
    $('#village-entries').replaceChildren(...entries.map(entry => {
      const item = document.createElement('li');
      item.className = 'card';
      const photo = new Image(72, 72);
      photo.loading = 'lazy';
      photo.alt = `Кадр из посёлка. ${entry.title}`;
      photo.src = '/api/village/preview?' + new URLSearchParams({event: entry.id});
      const copy = document.createElement('div');
      const day = document.createElement('small');
      day.textContent = `День ${entry.day}`;
      const title = document.createElement('strong');
      title.textContent = entry.title;
      const description = document.createElement('p');
      description.textContent = entry.text;
      copy.append(day, title, description);
      item.append(photo, copy);
      return item;
    }));
    villageJournalKey = key;
  } catch {
    // The next poll retries after a transient local connection failure.
  } finally {
    villageJournalBusy = false;
  }
}

function renderVillageControls() {
  if (!state) return;
  const village = state.village;
  const playing = state.job.running && state.job.kind === 'stream' && state.job.widget === 'village';
  const active = village?.active && village.active === village.latest?.id;
  if (active && !document.hidden) {
    const key = `${village.key}/${village.latest.id}`;
    if (key !== villageNoticeKey) {
      villageNoticeKey = key;
      toast(`Посёлок · ${village.latest.title}`);
    }
  }
  if (!widgetTabVisible('village')) return;
  villageForm.hidden = Boolean(village && !villageEditing);
  $('#village-resident').hidden = !village || villageEditing;
  $('#village-journal').hidden = !village;
  $('#village-neighbors').hidden = !village;
  $('#village-alert').hidden = !active;
  $('#village-save').disabled = villageSaving;
  $('#village-cancel').hidden = !villageEditing;
  $('#village-cancel').disabled = villageSaving;
  $('#village-save').textContent = villageEditing ? 'Сохранить героя' : 'Поселиться';
  if (!village) return;
  $('#village-home-name').textContent = village.home_name;
  $('#village-hero').textContent = village.profile.name;
  $('#village-calendar').textContent = `${village.season_name} · День ${village.day} · ${village.time}`;
  const activity = [village.stage, village.task];
  if (village.harvests) activity.push(`Урожаи: ${village.harvests}`);
  if (village.coins) activity.push(`Монеты: ${village.coins}`);
  $('#village-task').textContent = activity.join(' · ');
  const chat = $('#village-last-talk');
  chat.hidden = !village.conversation;
  if (village.conversation) {
    const {name, lines} = village.conversation;
    chat.textContent = `${name}: «${lines[0]}» · ${village.profile.name}: «${lines[1]}»`;
  }
  const people = village.people || [];
  $('#village-town-stock').textContent = `Продукты в лавке: ${village.shop_food || 0} · Блюда в трактире: ${village.meals || 0}`;
  const peopleKey = JSON.stringify(people);
  if (villagePeopleKey !== peopleKey) {
    $('#village-people').replaceChildren(...people.map(person => {
      const row = document.createElement('li');
      const name = document.createElement('strong');
      name.textContent = `${person.name} · ${person.role}`;
      const activity = document.createElement('span');
      activity.textContent = `${person.place} · ${person.activity}${person.affinity ? ` · Знакомство ${person.affinity}` : ''}`;
      row.append(name, activity);
      return row;
    }));
    villagePeopleKey = peopleKey;
  }
  $('#village-show').disabled = !villageCanShow() || playing || villageSaving;
  $('#village-show').textContent = playing ? 'На кубике ✓' : 'Показать на кубике ↗';
  $('#village-display-hint').hidden = state.device.kind === 'stream';
  if (active) {
    $('#village-alert-title').textContent = village.latest.title;
    $('#village-alert-text').textContent = village.latest.text;
  }
  loadVillageJournal(`${village.key}/${village.latest?.id || 0}`);
}

function showVillageOnCube() {
  return api('/api/widgets/show', {kind: 'village'});
}

villageForm.addEventListener('change', event => {
  if (event.target.id !== 'village-name') showVillagePoster();
});
villageForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (villageSaving || !state) return;
  const first = !state.village;
  const display = first && villageCanShow();
  villageSaving = true;
  if (display) switching = true;
  renderState();
  let saved = false;
  try {
    await api('/api/village/profile', villageProfileInput());
    saved = true;
    villageEditing = false;
    if (display) await showVillageOnCube();
  } catch (error) {
    toast(saved ? `Герой сохранён. Показ не запустился. ${error.message}` : error.message, true);
  } finally {
    if (display) switching = false;
    villageSaving = false;
    await refreshState();
    villagePreviewLoop();
  }
});

$('#village-show').addEventListener('click', async () => {
  if (!villageCanShow()) return;
  switching = true;
  renderState();
  try { await showVillageOnCube(); }
  catch (error) { toast(error.message, true); }
  finally { switching = false; await refreshState(); }
});

$('#village-edit').addEventListener('click', () => {
  const profile = state.village.profile;
  $('#village-name').value = profile.name;
  $('#village-look').value = profile.look;
  $('#village-color').value = profile.color;
  for (const input of villageForm.querySelectorAll('input[name="village-home"]')) input.checked = input.value === profile.home;
  villageEditing = true;
  renderVillageControls();
  showVillagePoster();
  $('#village-name').focus();
});
$('#village-cancel').addEventListener('click', () => {
  villageEditing = false;
  renderVillageControls();
  villagePreviewLoop();
});
