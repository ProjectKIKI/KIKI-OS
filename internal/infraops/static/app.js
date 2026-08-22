'use strict';
const byId=(id)=>document.getElementById(id);
const escapeHTML=(value)=>String(value??'').replace(/[&<>'"]/g,(char)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const buildId=(prefix)=>prefix+'-'+new Date().toISOString().replace(/[-:TZ.]/g,'').slice(0,14);

function headers(){
  const value={'Authorization':'Bearer '+byId('token').value.trim()};
  const actor=byId('actor').value.trim();
  if(actor)value['X-Kiki-Actor']=actor;
  return value;
}
async function api(path,options={}){
  options.headers={...headers(),...(options.headers||{})};
  const response=await fetch(path,options);
  const value=await response.json();
  if(!response.ok)throw new Error(value.error||response.statusText);
  return value;
}
async function submitBuild(payload){return api('/api/v1/builds',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})}
function security(prefix){return {generate_sbom:byId(prefix+'-sbom').checked,generate_provenance:byId(prefix+'-provenance').checked,sign:byId(prefix+'-sign').checked}}
function requireCommit(value){if(!/^[0-9a-f]{40}$/i.test(value))throw new Error('Commit SHA는 정확한 40자리 hexadecimal 값이어야 합니다.');return value}
function requireSHA256(value){if(!/^[0-9a-f]{64}$/i.test(value))throw new Error('소스 SHA-256은 정확한 64자리 hexadecimal 값이어야 합니다.');return value.toLowerCase()}
function lines(id){return byId(id).value.split('\n').map((value)=>value.trim()).filter(Boolean)}
function commas(id){return byId(id).value.split(',').map((value)=>value.trim()).filter(Boolean)}

function phaseClass(phase){return ['Succeeded','Failed'].includes(phase)?phase.toLowerCase():'running'}
function renderBuilds(builds){
  if(!builds.length){byId('builds').innerHTML='<div class="empty">등록된 빌드가 없습니다.</div>';return}
  byId('builds').innerHTML=builds.slice().reverse().map((build)=>{
    const label=build.type==='bos'?'BOS 패키지':({'iso':'ISO 이미지','pxe':'PXE 번들','disk':'QCOW2 이미지'}[build.type]||build.type);
    return `<article class="build-item"><div class="build-kind">${build.type==='bos'?'BOS':'OS'}</div><div class="build-main"><strong>${escapeHTML(build.output_name||build.id)}</strong><span>${escapeHTML(label)} · ${escapeHTML(build.id)}</span></div><div class="build-source">${escapeHTML(build.source?.revision?.slice(0,12)||'-')}</div><span class="phase ${phaseClass(build.phase)}">${escapeHTML(build.phase)}</span></article>`;
  }).join('');
}
function renderArtifacts(items){
  if(!items.length){byId('artifacts').innerHTML='<div class="empty">게시된 아티팩트가 없습니다.</div>';return}
  byId('artifacts').innerHTML=items.slice().reverse().map((item)=>`<article class="artifact-item"><div><strong>${escapeHTML(item.name||item.build_id)}</strong><span>${escapeHTML(item.media_type||'artifact')}</span></div><code>${escapeHTML(item.digest)}</code><span>${Number(item.size_bytes||0).toLocaleString()} bytes</span></article>`).join('');
}
async function refreshAll(){
  try{
    const [builds,artifacts]=await Promise.all([api('/api/v1/builds'),api('/api/v1/artifacts')]);
    renderBuilds(builds);renderArtifacts(artifacts);
    byId('connection-dot').className='online';byId('connection-label').textContent='InfraOps 연결됨';
    byId('status').textContent=`빌드 ${builds.length}건 · 아티팩트 ${artifacts.length}건`;
  }catch(error){
    byId('connection-dot').className='error';byId('connection-label').textContent='연결 필요';
    byId('status').textContent='오류: '+error.message;
  }
}
async function run(work){
  try{byId('status').textContent='빌드 요청을 등록하는 중…';const build=await work();byId('status').textContent=`${build.id} 빌드가 ${build.phase} 상태로 등록되었습니다.`;await refreshAll()}
  catch(error){byId('status').textContent='빌드 요청 실패: '+error.message}
}

document.querySelectorAll('.tab').forEach((tab)=>tab.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach((item)=>item.classList.toggle('active',item===tab));
  document.querySelectorAll('.build-panel').forEach((panel)=>panel.classList.toggle('active',panel.id===tab.dataset.panel));
}));
byId('settings-toggle').addEventListener('click',()=>byId('settings').classList.toggle('open'));
byId('connect').addEventListener('click',()=>{byId('settings').classList.remove('open');refreshAll()});
byId('refresh').addEventListener('click',refreshAll);
byId('image-type').addEventListener('change',(event)=>{
  const type=event.target.value;byId('image-output').value=type==='iso'?'kiki-os.iso':type==='pxe'?'kiki-os-pxe.tar.gz':'kiki-os.qcow2';
  if(type==='disk')byId('boot-uefi').checked=false;
});
byId('bos-mode').addEventListener('change',(event)=>{
  const recipe=event.target.value==='recipe';
  byId('bos-recipe-fields').classList.toggle('hidden',!recipe);
  byId('bos-source-fields').classList.toggle('hidden',recipe);
  for(const input of byId('bos-recipe-fields').querySelectorAll('[required]'))input.disabled=!recipe;
  for(const input of byId('bos-source-fields').querySelectorAll('input'))input.disabled=recipe;
});
for(const id of ['bos-name','bos-version','bos-release'])byId(id).addEventListener('input',()=>{
  const values=['bos-name','bos-version','bos-release'].map((field)=>byId(field).value.trim()).filter(Boolean);
  if(values.length===3)byId('bos-output').value=values.join('-')+'.bos';
});
byId('image-form').addEventListener('submit',(event)=>{
  event.preventDefault();run(()=>{
    const type=byId('image-type').value;
    const modes=[byId('boot-bios').checked?'bios':'',byId('boot-uefi').checked?'uefi':''].filter(Boolean);
    if(!modes.length)throw new Error('부팅 모드를 하나 이상 선택하세요.');
    if(type==='disk'&&modes.length!==1)throw new Error('QCOW2 디스크 이미지는 부팅 모드를 하나만 선택해야 합니다.');
    return submitBuild({id:buildId(type),type,source:{url:byId('image-source').value.trim(),revision:requireCommit(byId('image-revision').value.trim())},output_name:byId('image-output').value.trim(),platforms:[],factory:{release:byId('image-release').value,arch:byId('image-arch').value,boot_modes:modes},security:security('image')});
  });
});
byId('bos-form').addEventListener('submit',(event)=>{
  event.preventDefault();run(()=>{
    const common={id:buildId('bos'),type:'bos',output_name:byId('bos-output').value.trim(),artifact_pvc:byId('bos-pvc').value.trim(),platforms:[byId('bos-platform').value],security:security('bos')};
    if(byId('bos-mode').value==='source')return submitBuild({...common,source:{url:byId('bos-source').value.trim(),revision:requireCommit(byId('bos-revision').value.trim())},context_path:byId('bos-context').value.trim()});
    const sha=requireSHA256(byId('bos-archive-sha').value.trim());
    return submitBuild({...common,source:{url:byId('bos-archive-url').value.trim(),revision:sha},bos_recipe:{name:byId('bos-name').value.trim(),version:byId('bos-version').value.trim(),release:byId('bos-release').value.trim(),summary:byId('bos-summary').value.trim(),description:byId('bos-description').value.trim(),license:byId('bos-license').value.trim(),build_requires:commas('bos-build-requires'),requires:commas('bos-requires'),prepare:lines('bos-prepare'),build:lines('bos-build'),install:lines('bos-install'),check:lines('bos-check'),files:lines('bos-files')}});
  });
});
