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
