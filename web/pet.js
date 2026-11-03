'use strict';
let petVisible=false, petBusy=false, petPreviewBusy=false;
const petImage=$('#pet-preview');
new IntersectionObserver(entries => {petVisible=entries.some(entry=>entry.isIntersecting);}, {rootMargin:'100px'}).observe(petImage);

function renderPetControls() {
  if (!state) return;
  const job=state.job;
  const allowed=state.device.kind==='stream' && (!job.running || job.kind==='stream') && !importing && !switching && !petBusy;
  $('#pet-call').disabled=!allowed;
  $('#pet-show').disabled=!allowed || Boolean(state.pet?.active);
  const pet=state.pet || {};
  const name=pet.name || 'Моти';
  $('#pet-heading').textContent=name;
  $('#pet-description').textContent=pet.id==='momo' ? 'Сначала присмотрится, подкрадётся и тронет стекло лапкой.' : 'Подойдёт к стеклу и покажет обе лапки.';
  petImage.alt=name+' — котик внутри кубика';
  document.querySelectorAll('[data-pet]').forEach(button=>{
    button.setAttribute('aria-pressed',String(button.dataset.pet===(pet.id || 'moti')));
    button.disabled=petBusy || importing || switching || Boolean(job.running && job.kind!=='stream');
  });
  $('#pet-status').textContent=pet.active ? pet.label : 'Ждёт вашего зова';
  $('.pet-card').classList.toggle('is-playing',Boolean(pet.active));
  $('.pet-status').classList.toggle('pet-near',pet.phase==='greeting' && pet.active);
  $('#pet-call').textContent=pet.active && ['approaching','curious'].includes(pet.phase) ? name+' уже идёт ♡' : 'Позвать ♡';
  renderFindings(allowed);
}

document.querySelectorAll('[data-pet]').forEach(button=>button.addEventListener('click',async()=>{
  if(petBusy || button.dataset.pet===state?.pet?.id)return;
  petBusy=true;renderPetControls();
  try {await api('/api/pet/select',{character:button.dataset.pet});await refreshState();}
  catch(error){toast(error.message,true);}
  finally{petBusy=false;renderPetControls();}
}));

async function petAction(action) {
  if (petBusy || switching) return;
  petBusy=true;switching=true;renderState();
  try {await api('/api/pet/'+action,{});await refreshState();}
  catch(error) {toast(error.message,true);}
  finally {petBusy=false;switching=false;renderState();}
}
$('#pet-call').addEventListener('click',()=>petAction('call'));
$('#pet-show').addEventListener('click',()=>petAction('show'));

function petPreviewLoop() {
  if (serverGone) return;
  if (petVisible && !document.hidden && $('#page-widgets').classList.contains('active') && !petPreviewBusy) {
    petPreviewBusy=true;
    petImage.onload=petImage.onerror=()=>{petPreviewBusy=false;setTimeout(petPreviewLoop,120);};
    petImage.src='/api/pet/preview?t='+Date.now();
  } else setTimeout(petPreviewLoop,350);
}
petPreviewLoop();

let findingPreviewKey='', findingFolderBusy=false;
const findingDialog=$('#findings-dialog');

function renderFindings(allowed) {
  const pet=state.pet || {}, found=state.findings || {};
  const momo=pet.id==='momo';
  const hunting=pet.active && (pet.finding_pending || ['departing','searching','bringing'].includes(pet.phase));
  const busy=pet.active && pet.finding_busy;
  $('#findings-card').hidden=!momo;
  $('#pet-find').hidden=!momo;
  $('#pet-find').disabled=!allowed || busy;
  $('#pet-find').textContent=hunting ? 'Момо ищет…' : found.folder ? 'Принести находку ✧' : 'Находки с вашего ПК ✧';
  $('#findings-folder').disabled=petBusy || findingFolderBusy || Boolean(state.job.running && state.job.kind!=='stream');
  $('#findings-folder').textContent=found.folder ? 'Изменить папку' : 'Выбрать папку';
  const source=$('#findings-source');
  source.textContent=found.folder ? `${found.count} фото${found.limited ? ' · достигнут предел поиска' : ''} · ${found.folder}` : 'Момо будет приносить фотографии из выбранной папки.';
  source.title=found.folder || '';
  const visible=Boolean(found.current) && !hunting;
  $('#findings-result').hidden=!visible;
  $('#findings-empty').hidden=visible;
  $('#findings-empty p').textContent=hunting ? 'Тихо… Момо выбирает для вас фотографию. Скоро вернётся!' : found.folder ? 'Нажмите «Принести находку» — Момо отправится за фотографией.' : 'Доверьте Момо папку с фото — он найдёт в ней что-нибудь особенное.';
  if (visible) {
    $('#findings-name').textContent=found.current.name;
    $('#findings-name').title=found.current.name;
    const pinned=found.frame?.id===found.current.id;
    $('#findings-caption').textContent=pinned ? 'Эта находка украшает комнату Момо' : 'Можно сохранить в рамке или попросить другую';
    $('#findings-pin').textContent=pinned ? 'Уже в рамке ♡' : 'В рамку ♡';
    $('#findings-pin').disabled=petBusy || pinned;
    const previewKey=found.current.id+':'+found.revision;
    if (findingPreviewKey!==previewKey) {
      findingPreviewKey=previewKey;
      $('#findings-preview').src='/api/pet/findings/preview?kind=current&v='+encodeURIComponent(previewKey);
    }
  }
  $('#findings-next').disabled=!allowed || busy;
  $('#findings-open').disabled=petBusy;
  $('#findings-frame').hidden=!found.frame;
  $('#findings-frame-name').textContent=found.frame ? 'В комнате: '+found.frame.name : '';
  $('#findings-unpin').disabled=petBusy;
}

function openFindingsFolder() {
  $('#findings-path').value=state?.findings?.folder || '';
  $('#findings-folder-message').textContent='Фотографии обрабатываются локально и передаются только вашему кубику.';
  findingDialog.showModal();
}

$('#findings-folder').addEventListener('click',openFindingsFolder);
$('#findings-cancel').addEventListener('click',()=>findingDialog.close());
$('#findings-browse').addEventListener('click',async()=>{
  if(findingFolderBusy)return;
  findingFolderBusy=true;
  $('#findings-browse').disabled=true;$('#findings-save').disabled=true;
  $('#findings-folder-message').textContent='Выберите папку в открывшемся окне Windows…';
  try {
    const result=await api('/api/pet/findings/browse',{});
    if(result.folder)$('#findings-path').value=result.folder;
    $('#findings-folder-message').textContent=result.folder ? 'Нажмите «Доверить папку Момо», чтобы начать.' : 'Выбор отменён. Можно вставить путь вручную.';
  } catch(error){$('#findings-folder-message').textContent=error.message;}
  finally{findingFolderBusy=false;$('#findings-browse').disabled=false;$('#findings-save').disabled=false;}
});
$('#findings-form').addEventListener('submit',async event=>{
  event.preventDefault();if(findingFolderBusy)return;
  findingFolderBusy=true;$('#findings-save').disabled=true;$('#findings-browse').disabled=true;
  $('#findings-folder-message').textContent='Знакомим Момо с папкой…';
  try {
    await api('/api/pet/findings/folder',{folder:$('#findings-path').value.trim()});
    await refreshState();findingDialog.close();toast('Папка готова. Попросите Момо принести находку ✧');
  } catch(error){$('#findings-folder-message').textContent=error.message;}
  finally{findingFolderBusy=false;$('#findings-save').disabled=false;$('#findings-browse').disabled=false;renderPetControls();}
});

async function findingAction(action) {
  if(petBusy || switching)return;
  if(action==='next' && !state?.findings?.folder){openFindingsFolder();return;}
  petBusy=true;renderState();
  try {
    await api('/api/pet/findings/'+action,{id:state.findings?.current?.id});
    await refreshState();
    if(action==='pin')toast('Находка теперь в рамке в комнате Момо ♡');
    if(action==='open')toast('Оригинал открыт в приложении для фотографий');
  } catch(error){toast(error.message,true);}
  finally{petBusy=false;renderState();}
}
$('#pet-find').addEventListener('click',()=>findingAction('next'));
$('#findings-next').addEventListener('click',()=>findingAction('next'));
$('#findings-pin').addEventListener('click',()=>findingAction('pin'));
$('#findings-open').addEventListener('click',()=>findingAction('open'));
$('#findings-unpin').addEventListener('click',()=>findingAction('unpin'));
