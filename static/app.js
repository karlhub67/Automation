const $=id=>document.getElementById(id);let P=null,SYS={},SEL=new Set(),CUR=null,JOB=null,LIB=[];
let CAPDRAFT=null,CAPT=null,TOPDRAFT=[],TOPSEL=0,CAPDRAG=null;
const STAGES=['ingesting','analyzing audio','analyzing video','transcription','candidate selection','thumbnails','rendering'];
const api=async(p,d,m)=>{const r=await fetch(p,d===undefined?{}:{method:m||'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.statusText);return j};
const fmt=s=>{s=Math.max(0,s||0);return Math.floor(s/60)+':'+(s%60).toFixed(1).padStart(4,'0')};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function drawPlat(){}   // platform buttons were removed from the header; project.platform stays in the backend (safe-area data) but is no longer user-facing

let origPhoneWrap = null;
function showTab(t) {
    const ed = t === 'editing';
    $('autoclips').hidden = ed;
    $('editing').hidden = !ed;
    $('projtools').style.visibility = ed ? 'hidden' : 'visible';
    for (const k of ['clips', 'editing']) {
        const b = $('tab-' + k);
        b.classList.toggle('on', (k === 'editing') === ed);
        b.setAttribute('aria-selected', String((k === 'editing') === ed));
    }
    
    const phone = $('phone');
    if (ed) {
        if (!origPhoneWrap) origPhoneWrap = phone.parentNode;
        $('ed-player-wrap').appendChild(phone);
        try { vid().pause(); } catch(e) {}
        if (typeof updateTL === 'function') updateTL();
    } else {
        if (origPhoneWrap) origPhoneWrap.insertBefore(phone, origPhoneWrap.firstChild);
        if (P) drawClips();
    }
}

// Platform-neutral safe-area guide: the most conservative margin across every platform's UI.
function safeArea(){const v=Object.values(SYS.safe||{});return v.length?{top:Math.max(...v.map(x=>x.top)),bottom:Math.max(...v.map(x=>x.bottom)),right:Math.max(...v.map(x=>x.right))}:{top:.1,bottom:.2,right:.14}}
async function boot(){try{SYS=await api('/api/system');$('sys').textContent=(SYS.ffmpeg?'FFmpeg ✓':'FFmpeg MISSING')+' · ASR: '+(SYS.asr.join(', ')||'none (import .srt)')+' · enc: '+Object.values(SYS.encoders).filter(Boolean).join('/')+(SYS.face_tracking&&SYS.face_tracking.available?' · Face tracking ✓':' · Face tracking fallback');
 {const ps=(SYS.export_presets||Object.entries(SYS.presets).filter(([k])=>k!=='preview').map(([k,v])=>({key:k,label:v})));$('xpre').innerHTML=ps.map(x=>`<option value="${x.key}" ${x.key==='1080p60'?'selected':''}>${esc(x.label)}${x.width?' ('+x.width+'×'+x.height+')':''}</option>`).join('')}
 LIB=await api('/api/sfx');$('sfxsel').innerHTML=LIB.map(s=>`<option value="${esc(s.id)}">${esc(s.category)} · ${esc(s.name)}</option>`).join('');
 drawPlat();initVideo();await loadFonts();await refreshProjects()}catch(e){$('sys').textContent='Startup error: '+e.message}}
async function refreshProjects(){if(!$('recent'))return;try{const q=encodeURIComponent(($('projectsearch')?.value||'').trim());const rec=await api('/api/projects?q='+q,undefined);$('recent').innerHTML=rec.map(r=>{const status=r.source_exists?'source ready':(r.stored_in_project?'stored source ready':'source missing');const stamp=r.last_opened_at||r.saved_at||r.created;return `<div class="row fit" style="margin:5px 0"><div style="flex:1;min-width:0"><a href="#" onclick="openProj('${esc(r.id)}');return false"><b>${esc(r.name)}</b></a><br><span class="small">${esc(r.source_name||'no source')} · ${r.clips} clips · ${status} · ${stamp?new Date(stamp*1000).toLocaleString():''}</span></div><button onclick="openProj('${esc(r.id)}')">Load</button></div>`}).join('')||'<span class="small">No saved projects found.</span>'}catch(e){$('recent').innerHTML='<span class="warn">Could not load projects: '+esc(e.message)+'</span>'}}
async function openPath(){try{P=await api('/api/project',{path:$('path').value,platform:P?P.platform:'instagram'});load(P)}catch(e){alert(e.message)}}
async function openProj(id){P=await api('/api/project/'+id,undefined);load(P)}
const up=async f=>{const fd=new FormData();fd.append('file',f);const r=await fetch('/api/upload',{method:'POST',body:fd});const j=await r.json();if(!r.ok)throw new Error(j.error||'Upload failed');return j.path};
$('file').onchange=async e=>{if(e.target.files[0]){try{$('meta').textContent='Uploading…';$('path').value=await up(e.target.files[0]);openPath()}catch(x){alert(x.message)}}};
const drop=$('drop');drop.ondragover=e=>e.preventDefault();drop.ondrop=async e=>{e.preventDefault();const f=e.dataTransfer.files[0];if(f){try{$('meta').textContent='Uploading…';$('path').value=await up(f);openPath()}catch(x){alert(x.message)}}};
function load(p){P=p;P.template=P.template||{};drawPlat();const s=P.source;$('meta').innerHTML=`<b>${esc(s.path.split(/[\\/]/).pop())}</b><br>${s.width}×${s.height} · ${s.fps} fps · ${esc(s.vcodec)} · ${fmt(s.duration)}${s.vfr?' · <span class="warn">variable frame rate</span>':''}${s.has_audio?'':' · <span class="warn">no audio</span>'}`;
 $('undo').disabled=!P.can_undo;$('redo').disabled=!P.can_redo;$('saved').textContent='saved';if(P.instruction)$('instr').value=P.instruction;
 const t=P.template||{};$('tname').value=(t.profile||{}).name||'';$('thandle').value=(t.profile||{}).handle||'';$('tver').checked=!!(t.profile||{}).verified;$('tpon').checked=(t.profile||{}).on!==false;$('tring').value=(t.profile||{}).ring||'#7a2a5a';$('tlon').checked=!!(t.logo||{}).on;$('tltxt').value=(t.logo||{}).text||'';
 $('layouton').checked=t.layout_template_enabled!==false;$('blur').value=(t.background||{}).blur??20;$('darken').value=(t.background||{}).darken??0.05;fillCap();initTopDraft();drawTopEditor();drawCanvas();
 if(!CUR||!P.clips.find(c=>c.id===CUR))CUR=P.clips[0]?P.clips[0].id:null;drawClips();drawCues();drawSfx();fmtSync();preview();drawExportState()}
function fillCap(){const cs=P.caption_style||{},set=(id,k,d,chk)=>{const e=$(id);const v=cs[k]!==undefined?cs[k]:d;if(chk)e.checked=!!v;else e.value=v};CAPDRAFT={pos_x:cs.pos_x??0.5,pos_y:cs.pos_y??0.8,size:cs.size??0.045,font:cs.font??'Poppins',color:cs.color??'#ffffff',bold:cs.bold??true,box:cs.box??false,emphasis:cs.emphasis??true,fade_in:cs.fade_in??120,fade_out:cs.fade_out??120,fade_in_on:cs.fade_in_on!==false,outline:cs.outline??0.004,outline_color:cs.outline_color??'#000000',shadow:cs.shadow??0.002,align:cs.align??'center',emph_color:cs.emph_color??'#ffd43b',max_chars:cs.max_chars??24,max_lines:cs.max_lines??2};
 set('cposx','pos_x',CAPDRAFT.pos_x);set('cpos','pos_y',CAPDRAFT.pos_y);set('csize','size',CAPDRAFT.size);setFontSel('cfont',FONTNAMES,CAPDRAFT.font);set('ccol','color',CAPDRAFT.color);set('cbold','bold',CAPDRAFT.bold,1);set('cbox','box',CAPDRAFT.box,1);set('cemph','emphasis',CAPDRAFT.emphasis,1);set('cfade','fade_in',CAPDRAFT.fade_in);set('col_w','outline',CAPDRAFT.outline);set('col_c','outline_color',CAPDRAFT.outline_color);set('cshad','shadow',CAPDRAFT.shadow);set('calign','align',CAPDRAFT.align);set('cemc','emph_color',CAPDRAFT.emph_color);set('cmc','max_chars',CAPDRAFT.max_chars);set('cml','max_lines',CAPDRAFT.max_lines);setFadeUI(CAPDRAFT.fade_in_on);$('capnote').textContent='';}
function readCap(){return {...CAPDRAFT,pos_y:+$('cpos').value,pos_x:+$('cposx').value,size:+$('csize').value,font:$('cfont').value,color:$('ccol').value,bold:$('cbold').checked,box:$('cbox').checked,emphasis:$('cemph').checked,fade_in:+$('cfade').value,fade_out:+$('cfade').value,fade_in_on:$('cfadeon').getAttribute('aria-pressed')==='true',outline:+$('col_w').value,outline_color:$('col_c').value,shadow:+$('cshad').value,align:$('calign').value,emph_color:$('cemc').value,max_chars:Math.max(1,+$('cmc').value),max_lines:Math.max(1,+$('cml').value)}; }
function setFadeUI(on){const b=$('cfadeon');b.setAttribute('aria-pressed',String(!!on));b.classList.toggle('on',!!on);b.textContent=on?'ON':'OFF';$('cfadewrap').style.display=on?'':'none'}
function toggleFade(){setFadeUI($('cfadeon').getAttribute('aria-pressed')!=='true');capChanged()}
function capChanged(){CAPDRAFT=readCap();$('capnote').textContent='Unsaved caption changes';drawCanvas()}
async function applyCap(){CAPDRAFT=readCap();if(!Number.isFinite(CAPDRAFT.pos_x)||!Number.isFinite(CAPDRAFT.pos_y)||CAPDRAFT.size<=0)return alert('Please enter valid caption position/size values.');try{await edit({op:'caption_style',style:CAPDRAFT})}catch(e){alert(e.message)}}
function cancelCap(){fillCap();drawCanvas();$('capnote').textContent='Caption changes cancelled';}
function resetCap(){CAPDRAFT={pos_x:.5,pos_y:.8,size:.045,font:'Poppins',color:'#ffffff',bold:true,box:false,emphasis:true,fade_in:120,fade_out:120,fade_in_on:true,outline:.004,outline_color:'#000000',shadow:.002,align:'center',emph_color:'#ffd43b',max_chars:24,max_lines:2};for(const [id,key] of [['cposx','pos_x'],['cpos','pos_y'],['csize','size'],['cfont','font'],['ccol','color'],['cbold','bold'],['cbox','box'],['cemph','emphasis'],['cfade','fade_in'],['col_w','outline'],['col_c','outline_color'],['cshad','shadow'],['calign','align'],['cemc','emph_color'],['cmc','max_chars'],['cml','max_lines']]){const e=$(id);if(['bold','box','emphasis'].includes(key))e.checked=CAPDRAFT[key];else if(key==='font')setFontSel('cfont',FONTNAMES,CAPDRAFT.font);else e.value=CAPDRAFT[key]}setFadeUI(true);$('capnote').textContent='Reset to defaults (not applied)';drawCanvas()}
let PROJECT_NAME_DIRTY=false;
function markProjectName(){PROJECT_NAME_DIRTY=true;$('saved').textContent='Unsaved project name'}
async function saveProject(){if(!P)return alert('Open or create a project first.');try{const name=($('pname').value||'').trim();const r=await api(`/api/project/${P.id}/save`,{name,store_source:true});P=r;PROJECT_NAME_DIRTY=false;$('pname').value=P.name||name;$('saved').textContent='saved '+new Date((P.saved_at||Date.now()/1000)*1000).toLocaleTimeString();await refreshProjects()}catch(e){alert('Save failed: '+e.message)}}
function clip(){return P&&P.clips.find(c=>c.id===CUR)}
function drawClips(){const box=$('clips');if(!P||!P.clips.length){box.textContent='No clips yet. Open a video and run the analysis.';return}box.innerHTML=P.clips.map(c=>`<div class="clip ${c.id===CUR?'sel':''} ${c.status==='rejected'?'rej':''}" onclick="selClip('${esc(c.id)}')"><img src="/api/project/${P.id}/thumb/${esc(c.id)}?${c.start}"><div><div class="row fit"><b>${esc(c.id.toUpperCase())}</b><span class="tag">score ${(c.score*100).toFixed(0)}</span><span class="tag ${c.status==='accepted'?'acc':c.status==='rejected'?'rej':''}">${esc(c.status)}</span><span class="small">${fmt(c.start)} → ${fmt(c.end)} · ${(c.end-c.start).toFixed(1)}s → <b>${c.out_duration}s</b> after dead-air</span><input type="checkbox" ${SEL.has(c.id)?'checked':''} onclick="event.stopPropagation();tog('${esc(c.id)}')" title="select for merge"></div><div class="small" style="margin:3px 0">${esc((c.hook_text||'').slice(0,110))}</div><div class="row fit" onclick="event.stopPropagation()"><button class="ok" onclick="setStatus('${esc(c.id)}','accepted')">Accept</button><button class="bad" onclick="setStatus('${esc(c.id)}','rejected')">Reject</button><label class="small">start</label><input type="number" step="0.1" value="${c.start}" style="width:70px" onchange="trim('${esc(c.id)}','start',this.value)"><label class="small">end</label><input type="number" step="0.1" value="${c.end}" style="width:70px" onchange="trim('${esc(c.id)}','end',this.value)"><label class="small"><input type="checkbox" ${c.locked?'checked':''} onchange="patch('${esc(c.id)}',{locked:this.checked})"> lock</label></div><details onclick="event.stopPropagation()"><summary>Why this clip?</summary><div class="why"><ul style="margin:0;padding-left:16px">${(c.why||[]).map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div></details></div></div>`).join('')}
const tog=id=>{SEL.has(id)?SEL.delete(id):SEL.add(id)};function selClip(id){CUR=id;PV.mode='edited';setModeBtns();drawClips();drawCues();drawSfx();resetVideo();preview(true)}
async function edit(d){P=await api(`/api/project/${P.id}/edit`,d);load(P)}
const patch=(id,pt)=>edit({op:'clip',id,patch:pt});const setStatus=(id,s)=>patch(id,{status:s});const trim=(id,k,v)=>patch(id,{[k]:parseFloat(v)});const bulk=s=>edit({op:'bulk',status:s});function mergeSel(){const a=[...SEL];if(a.length!==2)return alert('Tick exactly two clips to merge.');SEL.clear();edit({op:'merge',ids:a})};async function undo(w){P=await api(`/api/project/${P.id}/${w}`,{});load(P)}
async function analyze(){if(!P||!P.id)return alert('Open a video first.');const params={n_clips:+$('n').value,min_dur:+$('dmin').value,target_dur:+$('dtar').value,max_dur:+$('dmax').value,deadair:$('dead').value,asr_model:$('asr').value,auto_sfx:$('asfx').checked};const j=await api(`/api/project/${P.id}/analyze`,{instruction:$('instr').value,params});watch(j.id,async()=>{await openProj(P.id)})}
function watch(id,done){JOB=id;$('xcancel').style.display='inline-block';$('go').disabled=true;const iv=setInterval(async()=>{const s=await api('/api/jobs/'+id,undefined);$('pb').style.width=(s.progress*100)+'%';$('pst').textContent=s.stage+' ('+Math.round(s.progress*100)+'%)';$('log').textContent=s.logs.join('\n');$('log').scrollTop=1e9;$('stages').innerHTML=STAGES.map(x=>{const i=STAGES.findIndex(y=>s.stage.startsWith(y)),k=STAGES.indexOf(x);return `<span class="st ${s.status==='done'||k<i?'done':k===i?'on':''}">${x}</span>`}).join('');if(s.status!=='running'){clearInterval(iv);$('go').disabled=false;if(s.status==='error')$('pst').innerHTML='<span class="warn">'+esc(s.human||'Failed')+'</span> <span class="small">(details in the log)</span>';if(s.status==='cancelled')$('pst').innerHTML='<span class="warn">Cancelled</span>';$('xcancel').style.display='none';if(done)await done(s)}},700)}
const PV={gen:0,fp:null,job:null,timer:null,poll:null,mode:'edited',cid:null,off:0,len:0,ctxEnd:0};const vid=()=>$('vid');const pvStatus=(t,cls)=>{$('pvstat').textContent=t;$('pvstat').className='tag '+(cls||'')};
function pvMsg(m,log){$('pvmsg').innerHTML=m||'';$('pvdet').style.display=log?'block':'none';if(log)$('pvlog').textContent=log}function drawSafe(){if(!P)return;const S=safeArea();$('safes').innerHTML=$('safeon').checked&&S?`<div class="safe" style="left:0;right:0;top:0;height:${S.top*100}%">top UI</div><div class="safe" style="left:0;right:0;bottom:0;height:${S.bottom*100}%">bottom UI</div><div class="safe" style="right:0;top:${S.top*100}%;bottom:${S.bottom*100}%;width:${S.right*100}%"></div>${fmtZoneHtml()}`:''}
function drawPreviewTimeline(){const c=clip(),el=$('pvmarkers');if(!el)return;const D=Math.max(0.01,PV.len||c?.out_duration||0);if(!c||!D){el.innerHTML='';return}const marks=[];(c.cues||[]).forEach(q=>{if(q.deleted)return;const a=clamp(+q.start||0,0,D),b=clamp(+q.end||a,0,D);marks.push(`<span class=\"pvmark cue\" style=\"left:${a/D*100}%;width:${Math.max(.4,(b-a)/D*100)}%\" title=\"${esc(q.text||'caption')}\"></span>`)});let pos=0;(c.keep||[]).forEach(([a,b])=>{const w=Math.max(0,+b-+a);const ra=pos,rb=Math.min(D,pos+w);if(rb>ra)marks.push(`<span class=\"pvmark keep\" style=\"left:${ra/D*100}%;width:${Math.max(.2,(rb-ra)/D*100)}%\"></span>`);pos+=w});el.innerHTML=marks.join('')}
function outT(c,t){let a=0;for(const [s,e] of c.keep){if(t>=s&&t<=e)return a+(t-s);a+=e-s}return null}
function preview(now){if(!P||!P.id)return;clearTimeout(PV.timer);const c=clip();if(!c){resetVideo();pvStatus('no clip');return}$('pvname').textContent='· '+c.id.toUpperCase();drawSafe();if(PV.mode!=='edited')return;if(PV.cid!==c.id)resetVideo();pvStatus('Preview outdated','warn');PV.timer=setTimeout(requestPreview,now?0:700)}
function resetVideo(){const v=vid();v.pause();v.removeAttribute('src');v.load();PV.fp=null;PV.cid=null;$('pvplay').disabled=true;$('pvseek').disabled=true;$('pvplay').textContent='▶ Play';$('pvtime').textContent='0:00.0 / 0:00.0';$('pvseek').value=0;drawPreviewTimeline()}
async function requestPreview(){const c=clip();if(!c)return;const gen=++PV.gen;clearTimeout(PV.poll);const old=PV.job;let r;try{r=await api(`/api/project/${P.id}/preview`,{clip:c.id})}catch(e){if(gen===PV.gen){pvStatus('Preview failed','bad');pvMsg('Could not start the preview: '+esc(e.message))}return}if(gen!==PV.gen)return;if(old&&old!==r.job)api('/api/jobs/'+old+'/cancel',{}).catch(()=>{});if(r.state==='ready'){PV.job=null;showPreview(r.url,r.fp,c.id);return}PV.job=r.job;$('pvbusy').style.display='block';$('pvcancel').style.display='inline-block';pvStatus('Preview updating…','warn');pvMsg(PV.fp?'Showing the last valid preview while the new one is built.':'Building the edited preview…');const tick=async()=>{let j;try{j=await api('/api/jobs/'+r.job,undefined)}catch(e){return}if(gen!==PV.gen)return;if(j.status==='running'){$('pvbusy').textContent='Updating preview… '+Math.round(j.progress*100)+'%';PV.poll=setTimeout(tick,400);return}$('pvbusy').style.display='none';$('pvcancel').style.display='none';PV.job=null;if(j.status==='done'){const r2=await api(`/api/project/${P.id}/preview`,{clip:c.id});if(gen===PV.gen&&r2.state==='ready')showPreview(r2.url,r2.fp,c.id)}else if(j.status==='cancelled'){pvStatus('Preview cancelled','warn');pvMsg('Cancelled. '+(PV.fp?'The previous preview is still usable.':''))}else{pvStatus('Preview failed','bad');pvMsg(`<span class="warn">${esc(j.human||'Preview failed')}</span> ${PV.fp?'The previous preview is still usable.':'No preview available yet.'}`,j.logs.join('\n'))}};tick()}
function showPreview(url,fp,cid){const v=vid();$('pvbusy').style.display='none';$('pvcancel').style.display='none';pvStatus('Preview current','ok');pvMsg('');if(PV.fp===fp&&PV.cid===cid&&v.getAttribute('src')===url)return;PV.fp=fp;PV.cid=cid;PV.mode='edited';setModeBtns();v.src=url;v.load()}
function setModeBtns(){$('pvm1').classList.toggle('on',PV.mode==='edited');$('pvm2').classList.toggle('on',PV.mode==='ctx')}function setMode(m){const c=clip();if(!c)return;PV.mode=m;setModeBtns();const v=vid();v.pause();if(m==='edited'){PV.fp=null;PV.cid=null;v.removeAttribute('src');preview(true)}else{clearTimeout(PV.timer);PV.gen++;$('pvbusy').style.display='none';pvStatus('Original context (unedited)','warn');pvMsg('Playing the untouched source: no dead-air cuts, crop, captions or SFX.');PV.off=Math.max(0,c.start-5);PV.ctxEnd=c.end+5;v.src=`/api/project/${P.id}/source`;v.load()}}
function togglePlay(){const v=vid();if(!v.src)return;if(v.ended||(PV.len&&v.currentTime>=PV.off+PV.len-0.05))v.currentTime=PV.off;if(v.paused){const p=v.play();if(p&&p.catch)p.catch(e=>pvMsg(`<span class="warn">Playback was blocked: ${esc(e.name==='NotAllowedError'?'press Play again':e.message)}</span>`))}else v.pause()}
function pvSync(){const v=vid();if(!PV.len)return;drawPreviewTimeline();const t=clamp(v.currentTime-PV.off,0,PV.len);$('pvseek').value=Math.round(t/PV.len*1000);$('pvtime').textContent=fmt(t)+' / '+fmt(PV.len)}
function initVideo(){const v=vid();v.addEventListener('loadedmetadata',()=>{if(PV.mode==='ctx'){PV.off=Math.max(0,PV.off);PV.ctxEnd=Math.min(PV.ctxEnd,v.duration);v.currentTime=PV.off;PV.len=Math.max(0,PV.ctxEnd-PV.off)}else{PV.off=0;PV.len=v.duration}$('pvplay').disabled=false;$('pvseek').disabled=false;$('pvplay').textContent='▶ Play';pvSync()});v.addEventListener('play',()=>{$('pvplay').textContent='⏸ Pause'});v.addEventListener('pause',()=>{$('pvplay').textContent='▶ Play'});v.addEventListener('ended',()=>{$('pvplay').textContent='▶ Play';pvSync()});v.addEventListener('timeupdate',()=>{if(PV.mode==='ctx'&&v.currentTime>=PV.off+PV.len){v.pause();v.currentTime=PV.off+PV.len}pvSync()});v.addEventListener('error',()=>{if(!v.getAttribute('src'))return;$('pvplay').disabled=true;pvStatus('Playback error','bad');pvMsg('<span class="warn">The preview video could not be played.</span>',v.error?v.error.message:'unknown media error')});$('pvseek').addEventListener('input',e=>{if(v.readyState>=1&&PV.len)v.currentTime=PV.off+e.target.value/1000*PV.len})}
function cancelPreview(){if(PV.job)api('/api/jobs/'+PV.job+'/cancel',{})}
// ---------- Layout/template + top on-screen captions
function tplObj(){const p=P.template||{};return{...p,layout_template_enabled:$('layouton').checked,background:{...(p.background||{}),blur:+$('blur').value,darken:+$('darken').value},profile:{...(p.profile||{}),on:$('tpon').checked,name:$('tname').value,handle:$('thandle').value,verified:$('tver').checked,ring:$('tring').value},logo:{...(p.logo||{}),on:$('tlon').checked,text:$('tltxt').value},top_captions:TOPDRAFT.length?TOPDRAFT:(p.top_captions||[])}}
async function saveTpl(){try{await edit({op:'template',template:tplObj()})}catch(e){alert(e.message)}}async function setLayoutEnabled(){await saveTpl()}async function upAsset(inp,kind){const fd=new FormData();fd.append('file',inp.files[0]);fd.append('kind',kind);const r=await fetch(`/api/project/${P.id}/asset`,{method:'POST',body:fd});const j=await r.json();if(!r.ok)return alert(j.error);const t=tplObj();if(kind==='avatar')t.profile.avatar=j.path;else{t.logo.path=j.path;t.logo.on=true}await edit({op:'template',template:t})}
function initTopDraft(){TOPDRAFT=JSON.parse(JSON.stringify((P.template||{}).top_captions||[]));if(!TOPDRAFT.length&&(P.template||{}).hook?.text){TOPDRAFT=[{id:'top1',enabled:true,text:P.template.hook.text,x:.08,y:.11,font:'Poppins',size:.034,color:P.template.hook.color||'#fff',bold:true,align:P.template.hook.align||'left',outline:.002,outline_color:'#000',shadow:.002}]};TOPSEL=clamp(TOPSEL,0,Math.max(0,TOPDRAFT.length-1))}
function topLayer(){if(!TOPDRAFT.length)return null;return TOPDRAFT[TOPSEL]}
function drawTopEditor(){const l=topLayer();$('toplayers').innerHTML=TOPDRAFT.map((x,i)=>`<button class="${i===TOPSEL?'on':''}" onclick="topSelect(${i})">${esc(x.text||'Text '+(i+1))}</button>`).join('')||'<span class="small">No text layers. Add one.</span>';$('topempty').style.display=l?'none':'block';if(!l)return;const set=(id,v)=>$(id).value=v;set('ttxt',l.text||'');$('ten').checked=l.enabled!==false;set('tx',l.x??.5);set('ty',l.y??.11);setFontSel('tfont',FONTNAMES,l.font||'Poppins');set('tsize',l.size??.04);set('tcol',l.color||'#fff');$('tbold').checked=l.bold!==false;set('talign',l.align||'center');set('tol',l.outline??.002);set('tolc',l.outline_color||'#000000');set('tsh',l.shadow??.002);}
function topSelect(i){TOPSEL=i;drawTopEditor()}function topRead(){const l=topLayer();if(!l)return;l.text=$('ttxt').value;l.enabled=$('ten').checked;l.x=clamp(+$('tx').value,0,1);l.y=clamp(+$('ty').value,0,1);l.font=$('tfont').value;l.size=Math.max(.005,+$('tsize').value);l.color=$('tcol').value;l.bold=$('tbold').checked;l.align=$('talign').value;l.outline=Math.max(0,+$('tol').value);l.outline_color=$('tolc').value;l.shadow=Math.max(0,+$('tsh').value);$('topnote').textContent='Unsaved top-caption changes';drawTopEditor()}
function addTop(){TOPDRAFT.push({id:'top'+Date.now().toString(36),enabled:true,text:'New text',x:.5,y:(fmtSpec()||{}).caption_y??.11,font:$('cfont').value||'Poppins',size:.04,color:'#ffffff',bold:true,align:'center',outline:.002,outline_color:'#000000',shadow:.002});TOPSEL=TOPDRAFT.length-1;drawTopEditor()}
function removeTop(){if(!TOPDRAFT.length)return;TOPDRAFT.splice(TOPSEL,1);TOPSEL=clamp(TOPSEL,0,Math.max(0,TOPDRAFT.length-1));drawTopEditor()}
function moveTop(dir){const j=TOPSEL+dir;if(j<0||j>=TOPDRAFT.length)return;[TOPDRAFT[TOPSEL],TOPDRAFT[j]]=[TOPDRAFT[j],TOPDRAFT[TOPSEL]];TOPSEL=j;drawTopEditor();$('topnote').textContent='Unsaved top-caption changes'}
async function applyTop(){topRead();await saveTpl();$('topnote').textContent=''}function cancelTop(){initTopDraft();drawTopEditor();$('topnote').textContent='Top-caption changes cancelled'}
// ---------- caption cue editor + positioning canvas
function drawCues(){const c=clip();$('capcard').style.display=c?'block':'none';if(!c)return;$('capid').textContent=c.id.toUpperCase()+' · '+c.cues.length+' cues';$('cues').innerHTML=c.cues.map((q,i)=>`<div class="cue"><input type="number" step="0.05" value="${q.start}" onchange="cue(${i},'start',this.value)"><input type="number" step="0.05" value="${q.end}" onchange="cue(${i},'end',this.value)"><input type="text" value="${esc(q.text)}" onchange="cue(${i},'text',this.value)"><span class="small">${q.words_status==='stale'?'word timing stale':''}</span><button onclick="cue(${i},'deleted',true)">×</button></div>`).join('')||'<span class="small">No transcript for this clip. Import an .srt/.vtt or install faster-whisper, then re-run.</span>';drawCanvas()}
function cue(i,k,v){const c=clip();const cues=c.cues.map(x=>({...x}));cues[i][k]=(k==='start'||k==='end')?parseFloat(v):v;if(k==='text'||k==='start'||k==='end')cues[i].words_status='stale';if(k==='deleted')cues.splice(i,1);patch(c.id,{cues,locked_cues:true})}
function addCue(){const c=clip();if(!c)return;const v=vid();const t=PV.mode==='edited'?clamp(v.currentTime,0,c.out_duration||1):0;const e=clamp(t+1.5,0,c.out_duration||1);const start=Math.min(t,Math.max(0,(c.out_duration||1)-0.05));const end=Math.max(start+0.05,Math.min(c.out_duration||1,e));patch(c.id,{cues:[...(c.cues||[]),{start:+start.toFixed(2),end:+end.toFixed(2),text:'New caption',words_status:'stale'}],locked_cues:true})}
const regenCues=()=>edit({op:'reprepare',id:CUR,params:{}});async function importSrt(inp){const fd=new FormData();fd.append('file',inp.files[0]);const r=await fetch(`/api/project/${P.id}/subtitles`,{method:'POST',body:fd});const j=await r.json();alert('Imported '+j.count+' transcript segments. Re-run analysis to use them for selection.');await edit({op:'reprepare',id:CUR,params:{}})}
function drawCanvas(){const c=clip(),wrap=$('capcanvas'),txt=$('captext');if(!wrap||!txt)return;const d=CAPDRAFT||{};const q=c&&c.cues&&c.cues.find(x=>!x.deleted);txt.textContent=q?(q.text||'Caption'):'Caption';txt.style.left=(clamp(+d.pos_x||.5,0,1)*100)+'%';txt.style.top=(clamp(+d.pos_y||.8,0,1)*100)+'%';txt.style.fontSize=Math.max(8,(+(d.size||.045))*480)+'px';txt.style.color=d.color||'#fff';txt.style.fontWeight=d.bold?'700':'400';txt.style.fontFamily=d.font?JSON.stringify(d.font)+',sans-serif':'';txt.style.textAlign=d.align||'center';txt.style.transform=d.align==='left'?'translate(0,-50%)':d.align==='right'?'translate(-100%,-50%)':'translate(-50%,-50%)';$('capcanvas').style.setProperty('--safe-top',safeArea().top*100+'%');$('capcanvas').style.setProperty('--safe-bottom',safeArea().bottom*100+'\%');fmtHint()}$('capcanvas')?.addEventListener('pointerdown',e=>{if(e.target.id!=='captext'||!CAPDRAFT)return;const r=$('capcanvas').getBoundingClientRect();CAPDRAG={r};e.target.setPointerCapture?.(e.pointerId)});$('capcanvas')?.addEventListener('pointermove',e=>{if(!CAPDRAG||!CAPDRAFT)return;const r=CAPDRAG.r;CAPDRAFT.pos_x=clamp((e.clientX-r.left)/r.width,0,1);CAPDRAFT.pos_y=clamp((e.clientY-r.top)/r.height,0,1);$('cposx').value=CAPDRAFT.pos_x.toFixed(2);$('cpos').value=CAPDRAFT.pos_y.toFixed(2);$('capnote').textContent='Unsaved caption changes';drawCanvas()});$('capcanvas')?.addEventListener('pointerup',()=>CAPDRAG=null);
function fontOpts(names,cur){const l=names.slice();if(cur&&!l.includes(cur))l.push(cur);return l.map(n=>`<option value="${esc(n)}" style="font-family:${esc(JSON.stringify(n))}">${esc(n)}${names.includes(n)?'':' (not installed)'}</option>`).join('')}
function setFontSel(id,names,cur){const e=$(id);if(!e)return;e.innerHTML=fontOpts(names,cur);e.value=cur||names[0]||'Poppins'}
let FONTNAMES=[];
async function loadFonts(){try{const [f,files]=await Promise.all([api('/api/fonts',undefined),api('/api/fonts/files',undefined)]);FONTNAMES=f;
 setFontSel('cfont',f,(CAPDRAFT&&CAPDRAFT.font)||$('cfont').value);setFontSel('tfont',f,(topLayer()&&topLayer().font)\vert{}\vert{}$('tfont').value);
 let st=document.getElementById('local-fonts');if(!st){st=document.createElement('style');st.id='local-fonts';document.head.appendChild(st)}st.textContent=(files||[]).map(x=>`@font-face{font-family:${JSON.stringify(x.family)};src:url(${JSON.stringify(x.url)}) format('truetype');font-display:swap}`).join('\n')}catch(e){}}
async function upFont(inp){if(!inp.files[0])return;const fd=new FormData();fd.append('file',inp.files[0]);const r=await fetch('/api/fonts/upload',{method:'POST',body:fd});const j=await r.json();if(!r.ok)return alert(j.error);await loadFonts()}
// ---------- SFX / export
function drawSfx(){const c=clip(),tl=$('tl');if(!c){tl.innerHTML='';$('sfxl').innerHTML='';return}const D=c.out_duration||1;tl.innerHTML=(c.sfx||[]).map((e,i)=>`<div class="mk ${e.enabled?'':'off'}" style="left:${Math.min(96,e.t/D*100)}%" onmousedown="drag(event,${i},${D})" title="${esc(e.sound)} @ ${e.t}s">${esc(e.sound.replace('.wav',''))}</div>`).join('');$('sfxl').innerHTML=(c.sfx||[]).map((e,i)=>`<div class="row fit small"><input type="checkbox" ${e.enabled?'checked':''} onchange="sfxp(${i},{enabled:this.checked})"><b style="min-width:80px">${esc(e.sound.replace('.wav',''))}</b>t<input type="number" step="0.05" value="${e.t}" style="width:62px" onchange="sfxp(${i},{t:+this.value})">gain<input type="number" value="${e.gain_db}" style="width:54px" onchange="sfxp(${i},{gain_db:+this.value})">dB fade out<input type="number" step="0.05" value="${e.fade_out}" style="width:54px" onchange="sfxp(${i},{fade_out:+this.value})"><label><input type="checkbox" ${e.duck?'checked':''} onchange="sfxp(${i},{duck:this.checked})">duck</label><button onclick="sfxdup(${i})">⧉</button><button class="bad" onclick="sfxdel(${i})">×</button></div>`).join('')}
function sfxp(i,pt){const c=clip();const s=(c.sfx||[]).map(x=>({...x}));Object.assign(s[i],pt);patch(c.id,{sfx:s})}const sfxdel=i=>{const c=clip();patch(c.id,{sfx:c.sfx.filter((_,j)=>j!==i)})};const sfxdup=i=>{const c=clip();patch(c.id,{sfx:[...c.sfx,{...c.sfx[i],id:'d'+Math.random().toString(36).slice(2,8),t:c.sfx[i].t+0.4}]})};async function addSfx(){const c=clip();if(!c)return;const v=$('vid');let t=PV.mode==='edited'?v.currentTime:(outT(c,v.currentTime)||0);const e=await api('/api/sfx/new',{sound:$('sfxsel').value,t});patch(c.id,{sfx:[...(c.sfx\vert{}\vert{}[]),e]})}function drag(ev,i,D){const tl=$('tl'),r=tl.getBoundingClientRect();const mv=e=>{const t=Math.max(0,Math.min(D,(e.clientX-r.left)/r.width*D));ev.target.style.left=(t/D*100)+'%';ev.target._t=t};const up=()=>{document.removeEventListener('mousemove',mv);document.removeEventListener('mouseup',up);if(ev.target._t!==undefined)sfxp(i,{t:+ev.target._t.toFixed(2)})};document.addEventListener('mousemove',mv);document.addEventListener('mouseup',up)}const pre=()=>{const a=new Audio('/api/sfx/file/'+$('sfxsel').value);a.play()};async function importSfx(inp){const fd=new FormData();fd.append('file',inp.files[0]);await fetch('/api/sfx/import',{method:'POST',body:fd});LIB=await api('/api/sfx');$('sfxsel').innerHTML=LIB.map(s=>`<option value="${esc(s.id)}">${esc(s.category)} · ${esc(s.name)}</option>`).join('');$('sfxsel').value=inp.files[0].name}
const cancelJob=()=>JOB&&api('/api/jobs/'+JOB+'/cancel',{});async function drawExportState(){if(!P)return;const st=await api(`/api/project/${P.id}/export_state`,undefined);const c=clip();$('xstate').innerHTML=c&&st[c.id]?(st[c.id].last_export_fp===null?'No export yet for this clip':st[c.id].last_export_fp===st[c.id].fp?'<span style="color:var(--ok)">Export current</span>':'<span class="warn">Export outdated (edits since last export)</span>'):'';$('hist').innerHTML=(P.export_history||[]).slice().reverse().map(r=>`<div>${new Date(r.ts*1000).toLocaleString()} · ${esc(r.clip.toUpperCase())} · ${esc(r.rendered)} · <a href="${esc(r.url)}" target="_blank" style="color:var(--a)">open</a></div>`).join('')||'none yet'}
async function renderSel(previewFlag){if(!P)return;let ids=previewFlag?[CUR]:P.clips.filter(c=>c.status==='accepted').map(c=>c.id);if(!ids.length||!ids[0])return alert(previewFlag?'Select a clip.':'Accept at least one clip first.');const options={preset:previewFlag?'preview':$('xpre').value,codec:$('xcod').value,quality:$('xq').value,hardware:$('xhw').checked,denoise:$('xden').checked,loudnorm:$('xln').checked,interpolate:$('xint').checked};$('results').innerHTML='';const j=await api(`/api/project/${P.id}/render`,{clips:ids,options});watch(j.id,async s=>{const pr=await api('/api/project/'+P.id,undefined);P=pr;if(s.status==='cancelled'){$('results').innerHTML='<div class="res err">Export cancelled.</div>';return}const fk=P.template&&P.template.format?P.template.format:(SYS.default_format||'format3');
 const card=r=>{if(r.error)return `<div class="res err"><b>${esc(r.clip.toUpperCase())}</b> export FAILED<pre>${esc(r.error)}</pre></div>`;
  const v=r.verification||{checks:[]};const chk=(v.checks||[]).map(c=>`<span class="chk"><b class="${c.ok?'ok':'no'}">${c.ok?'✓':'✗'}</b> ${esc(c.name)} — ${esc(c.detail)}</span>`).join('<br>');
  return `<div class="res"><b>${esc(r.clip.toUpperCase())}</b> · <a href="${esc(r.url)}" target="_blank" rel="noopener" style="color:var(--a)">open</a> · <a href="${esc(r.download_url||r.url)}" style="color:var(--a)">download</a><br>Source: ${esc(r.source)}<br>Requested: ${esc(r.requested)} (${esc(r.requested_size||'')} @ ${esc(r.requested_fps||'')} fps)<br>Rendered: ${esc(r.rendered)} (${r.duration}s)<br>Format: ${esc(r.format_name||r.format)}${r.format&&r.format!==fk?' <span class="warn">(project now uses a different format - export is outdated)</span>':''}<br>Encoder: ${esc(r.encoder)}<br>${r.upscaled?'<span class="warn">UPSCALED</span> · ':''}${r.interpolated?'<span class="warn">INTERPOLATED</span> · ':''}${esc((r.notes||[]).join(' · '))}<details><summary>Output verification ${v.ok?'(all checks passed)':'(PROBLEM)'}</summary>${chk}</details><video src="${esc(r.url)}" controls style="width:100%;max-height:340px;margin-top:6px;background:#000"></video></div>`};
 let html=(pr.last_exports||[]).map(card).join('');
 if(s.status==='error'&&!(pr.last_exports||[]).some(r=>r.error))html=`<div class="res err">Export failed: ${esc(s.human||s.error||'unknown error')}<pre>${esc((s.logs||[]).join('\n'))}</pre></div>`;
 $('results').innerHTML=html;drawExportState()})}
// ---------- Video format selector: template.format = 'format1' | 'format2' | 'format3'
// Specs (geometry, card text, image) come from the server (SYS.formats = core/templates.FORMAT_SPECS) so the UI can never drift from
// the renderer. A project with no template.format (saved before this feature) uses SYS.default_format, which is the original composition.
let FMTUI={sel:null,busy:false,job:null,aborted:false,opener:null};
const fmtCat=()=>SYS.formats||{};
const fmtKey=()=>{const k=P&&P.template&&P.template.format;return fmtCat()[k]?k:(SYS.default_format||'format3')};
const fmtSpec=k=>fmtCat()[k||fmtKey()]||null;
const fmtTag=sp=>sp?sp.name.split(' — ')[0]:'';
function fmtVideoRect(){ // normalised rect the clip really occupies on the 9:16 canvas (cover is cropped to the box, contain is fitted inside it)
 const sp=fmtSpec();if(!sp||!P||!P.source)return null;const b=sp.box,sw=P.source.width||16,sh=P.source.height||9,bw=b.w*9,bh=b.h*16; // canvas measured as 9 x 16 units
 const sc=sp.fit==='cover'?Math.max(bw/sw,bh/sh):Math.min(bw/sw,bh/sh),w=Math.min(bw,sw*sc),h=Math.min(bh,sh*sc),cx=b.x*9+bw/2,cy=b.y*16+bh/2;
 return {x:(cx-w/2)/9,y:(cy-h/2)/16,w:w/9,h:h/16}}
function fmtZoneHtml(){const sp=fmtSpec(),z=sp&&sp.caption_zone;return z&&$('safeon').checked?`<div class="safe zone" style="left:${z.x*100}%;top:${z.y*100}%;width:${z.w*100}%;height:${z.h*100}%">top caption zone</div>`:''}
function fmtHint(){const cv=$('capcanvas'),h=cv&&cv.querySelector('.videohint'),r=fmtVideoRect(),sp=fmtSpec();if(!h||!r)return;
 Object.assign(h.style,{left:r.x*100+'%',width:r.w*100+'%',right:'auto',top:r.y*100+'%',height:r.h*100+'%'});
 let z=$('capzone');if(!z){z=document.createElement('div');z.id='capzone';z.className='zone';z.title='Top caption zone';cv.appendChild(z)}
 const c=sp.caption_zone;Object.assign(z.style,{left:c.x*100+'%',top:c.y*100+'%',width:c.w*100+'%',height:c.h*100+'%'})}
function fmtSync(){const b=$('fmtbtn');if(!b)return;const sp=fmtSpec();b.disabled=!P||!P.id||FMTUI.busy;$('fmtcur').textContent=P&&P.id&&sp?sp.name:'';
 const blur=!sp||sp.background==='blur';$('blurnote').textContent=blur?'':'Blur/Darken only apply to Format 3 (blurred background). Your values are kept for when you switch back.';$('blur').parentElement.style.opacity=blur?'':'.55';$('darken').style.opacity=blur?'':'.55';fmtHint();drawSafe()}
function fmtNote(){const sp=fmtSpec(FMTUI.sel);$('fmtnote').textContent=!sp?'':FMTUI.sel===fmtKey()?'Currently applied.':'Selected: '+sp.name}
function fmtPick(k){FMTUI.sel=k;fmtNote()}
function openFormat(){ // opening only READS state; nothing is modified until Okay
 if(!P||!P.id)return alert('Open a video first.');if(FMTUI.busy)return;
 const cat=fmtCat(),keys=Object.keys(cat);if(!keys.length)return alert('Format information is unavailable. Reload the page.');
 const cur=fmtKey();FMTUI.sel=cur;FMTUI.opener=document.activeElement;
 $('fmtgrid').innerHTML=keys.map(k=>{const f=cat[k];return `<label class="fwrap"><input type="radio" name="vfmt" value="${esc(k)}" ${k===cur?'checked':''} onchange="fmtPick('${esc(k)}')"><div class="fcard"><img class="fimg" src="${esc(f.image)}" alt="${esc(f.name)} layout preview" draggable="false"><div class="ftx"><div class="fname">${esc(f.name)}${k===cur?' <span class="tag acc">Current</span>':''}</div><div class="fplat">${esc(f.platforms)}</div><div class="fdesc">${esc(f.description)}</div><div class="flay">${esc(f.layout)}</div></div></div></label>`}).join('');
 fmtNote();$('fmtmodal').hidden=false;document.body.style.overflow='hidden';const f=document.querySelector('#fmtgrid input:checked');(f||$('fmtok')).focus()}
function closeFormat(){const m=$('fmtmodal');if(m.hidden)return;m.hidden=true;document.body.style.overflow='';FMTUI.sel=null;const o=FMTUI.opener;FMTUI.opener=null;if(o&&o.focus&&document.contains(o)&&!o.disabled)o.focus()}
document.addEventListener('keydown',e=>{const m=$('fmtmodal');if(!m||m.hidden)return;
 if(e.key==='Escape'){e.preventDefault();closeFormat();return}
 if(e.key==='Enter'&&e.target.matches&&e.target.matches('input[name=vfmt]')){e.preventDefault();applyFormat();return}
 if(e.key==='Tab'){const f=[...m.querySelectorAll('input[name=vfmt]:checked,button:not(:disabled)')];if(!f.length)return;const a=f[0],z=f[f.length-1];
  if(!m.contains(document.activeElement)){e.preventDefault();a.focus()}else if(e.shiftKey&&document.activeElement===a){e.preventDefault();z.focus()}else if(!e.shiftKey&&document.activeElement===z){e.preventDefault();a.focus()}}});
function fmtBusy(on,t1,t2,pct){const o=$('fmtbusy');o.hidden=!on;if(!on)return;if(t1!==undefined)$('fmtb1').textContent=t1;if(t2!==undefined)$('fmtb2').textContent=t2;$('fmtbar').style.width=(pct\vert{}\vert{}0)+'\%';$('fmtbx').disabled=false}
function cancelFormatApply(){FMTUI.aborted=true;$('fmtbx').disabled=true;$('fmtb2').textContent='Cancelling…';if(FMTUI.job)api('/api/jobs/'+FMTUI.job+'/cancel',{}).catch(()=>{})}
async function fmtPrerender(cid,next){ // render the edited preview AS IF `next` were applied, without saving anything: proves it works before we commit
 const r=await api(`/api/project/${P.id}/preview`,{clip:cid,format:next});if(r.state==='ready')return;FMTUI.job=r.job;
 for(;;){await new Promise(res=>setTimeout(res,350));const j=await api('/api/jobs/'+r.job,undefined),pc=Math.round((j.progress||0)*100);
  if(FMTUI.aborted||j.status==='cancelled'){const e=new Error('cancelled');e.fmtCancelled=true;throw e}
  if(j.status==='running'){fmtBusy(true,undefined,'Updating preview… '+pc+'%',pc);continue}
  if(j.status==='done')return;const e=new Error(j.human||'Preview render failed');e.log=(j.logs||[]).join('\n');throw e}}
async function applyFormat(){
 const next=FMTUI.sel,prev=fmtKey();closeFormat();if(!next||next===prev||!P)return;
 const sp=fmtSpec(next),old=fmtSpec(prev),c=clip();FMTUI.busy=true;FMTUI.aborted=false;FMTUI.job=null;fmtSync();pvMsg('');
 try{
  if(c){fmtBusy(true,'Applying '+fmtTag(sp)+'…','Updating preview…',0);await fmtPrerender(c.id,next);fmtBusy(true,undefined,'Saving format…',100)}
  P=await api(`/api/project/${P.id}/edit`,{op:'format',format:next});load(P);                // commit: template.format is saved, snapshotted for undo/redo, and part of the preview/export fingerprint
  if(c){if(PV.mode!=='edited')setMode('edited');else{clearTimeout(PV.timer);await requestPreview()}}  // the pre-rendered file is cached, so this shows it immediately
  else pvMsg(esc(sp.name)+' applied. It will be used for the preview and for exports once clips exist.');
 }catch(e){
  if(e&&e.fmtCancelled){pvStatus('Format change cancelled','warn');pvMsg('Format change cancelled. '+esc(old.name)+' is still applied.')}
  else{pvStatus('Format not applied','bad');pvMsg('<span class="warn">Could not apply '+esc(sp.name)+': '+esc(e&&e.message||'unknown error')+'</span> '+esc(old.name)+' is still applied'+(PV.fp?' and your previous preview is unchanged.':'.'),e&&e.log)}
 }finally{FMTUI.busy=false;FMTUI.job=null;fmtBusy(false);fmtSync()}}

boot();

// --- STAGE 1: CAPCUT-STYLE TIMELINE ---
let TL = { zoom: 100, sel: null, drag: null, dur: 0 };

function updateTLToolbar() {
    $('tl-split').disabled = !TL.sel;
    $('tl-del').disabled = !TL.sel;
}

function updateTL() {
    const c = clip(); if (!c) return;
    TL.dur = c.out_duration || 0;
    $('tl-container').style.width = Math.max(800, TL.dur * TL.zoom + 200) + 'px';
    
    const mk = (id, type, start, dur, label, noHandle) => {
        const isSel = TL.sel && TL.sel.type === type && TL.sel.id === id;
        return `<div class="tl-block ${isSel ? 'sel' : ''}" data-type="${type}" data-id="${id}" style="left: ${start * TL.zoom}px; width: ${Math.max(2, dur * TL.zoom)}px;">
            ${noHandle ? '' : '<div class="tl-handle left" data-action="edge-l"></div>'}
            <div class="tl-content" data-action="move">${esc(label)}</div>
            ${noHandle ? '' : '<div class="tl-handle right" data-action="edge-r"></div>'}
        </div>`;
    };

    let htmlKeep = '', tKeep = 0;
    (c.keep || []).forEach((k, i) => {
        const w = k[1] - k[0];
        htmlKeep += mk(i, 'keep', tKeep, w, `Video ${i+1}`);
        tKeep += w;
    });
    $('tl-tracks').querySelector('[data-type="keep"]').innerHTML = htmlKeep;

    $('tl-tracks').querySelector('[data-type="cues"]').innerHTML = (c.cues || []).map((q, i) => 
        q.deleted ? '' : mk(i, 'cues', q.start, q.end - q.start, q.text)
    ).join('');

    $('tl-tracks').querySelector('[data-type="top"]').innerHTML = TOPDRAFT.map((q, i) => 
        mk(i, 'top', q.start || 0, (q.end !== undefined ? q.end : TL.dur) - (q.start || 0), q.text || 'Text')
    ).join('');

    $('tl-tracks').querySelector('[data-type="sfx"]').innerHTML = (c.sfx || []).map((s, i) => 
        mk(i, 'sfx', s.t, 2, s.sound.replace('.wav',''), true)
    ).join('');
}

$('tl-tracks')?.addEventListener('pointerdown', e => {
    if (e.target.closest('.tl-block')) {
        const block = e.target.closest('.tl-block');
        TL.sel = { type: block.dataset.type, id: parseInt(block.dataset.id) };
        updateTLToolbar(); updateTL();
        const action = e.target.dataset.action;
        if (!action) return;
        TL.drag = { action, block, type: TL.sel.type, id: TL.sel.id, startX: e.clientX, startLeft: parseFloat(block.style.left), startWidth: parseFloat(block.style.width) };
        e.target.setPointerCapture(e.pointerId);
    } else {
        TL.sel = null; updateTLToolbar(); updateTL();
    }
});

$('tl-tracks')?.addEventListener('pointermove', e => {
    if (!TL.drag) return;
    const dx = e.clientX - TL.drag.startX;
    const { action, block, startLeft, startWidth } = TL.drag;
    if (action === 'move') {
        block.style.left = Math.max(0, startLeft + dx) + 'px';
    } else if (action === 'edge-l') {
        const newLeft = Math.max(0, Math.min(startLeft + startWidth - 5, startLeft + dx));
        block.style.left = newLeft + 'px';
        block.style.width = Math.max(2, startWidth - (newLeft - startLeft)) + 'px';
    } else if (action === 'edge-r') {
        block.style.width = Math.max(5, startWidth + dx) + 'px';
    }
});

$('tl-tracks')?.addEventListener('pointerup', async e => {
    if (!TL.drag) return;
    const { type, id, action, startLeft, startWidth } = TL.drag;
    const newStart = parseFloat(TL.drag.block.style.left) / TL.zoom;
    const newDur = parseFloat(TL.drag.block.style.width) / TL.zoom;
    const c = clip(); TL.drag = null; if (!c) return;

    if (type === 'keep') {
        let k = [...c.keep];
        if (action === 'move') { // Reorder kept regions
            const center = newStart + newDur / 2;
            let tK = 0, tgt = 0;
            for (let i = 0; i < k.length; i++) { if (i !== id) { tK += k[i][1] - k[i][0]; if (center > tK) tgt = i + 1; } }
            const moved = k.splice(id, 1)[0]; if (tgt > id) tgt--; k.splice(tgt, 0, moved); TL.sel.id = tgt;
        } else if (action === 'edge-l') {
            k[id][0] = Math.max(0, k[id][0] + (newStart - (startLeft / TL.zoom)));
        } else if (action === 'edge-r') {
            k[id][1] = Math.max(k[id][0] + 0.1, k[id][1] + (newDur - (startWidth / TL.zoom)));
        }
        await patch(c.id, { keep: k, locked: true });
    } else if (type === 'cues') {
        let cues = [...c.cues]; cues[id].start = Math.max(0, newStart); cues[id].end = cues[id].start + newDur; cues[id].words_status = 'stale';
        await patch(c.id, { cues, locked_cues: true });
    } else if (type === 'top') {
        TOPDRAFT[id].start = Math.max(0, newStart); TOPDRAFT[id].end = TOPDRAFT[id].start + newDur;
        await applyTop();
    } else if (type === 'sfx') {
        let sfx = [...c.sfx]; sfx[id].t = Math.max(0, newStart);
        await patch(c.id, { sfx });
    }
});

async function tlSplit() {
    if (!TL.sel) return;
    const c = clip(); if (!c) return;
    const t = $('vid').currentTime; const { type, id } = TL.sel;
    if (type === 'keep') {
        let tK = 0, k = [...c.keep];
        for (let i = 0; i < k.length; i++) {
            const w = k[i][1] - k[i][0];
            if (i === id && t > tK && t < tK + w) {
                const splitSource = k[i][0] + (t - tK); const oldE = k[i][1]; k[i][1] = splitSource; k.splice(i + 1, 0, [splitSource, oldE]);
                await patch(c.id, { keep: k, locked: true }); TL.sel.id = i + 1; return;
            }
            tK += w;
        }
    } else if (type === 'cues') {
        let cues = [...c.cues]; const q = cues[id];
        if (t > q.start && t < q.end) { const q2 = JSON.parse(JSON.stringify(q)); q.end = t; q2.start = t; cues.splice(id + 1, 0, q2); await patch(c.id, { cues, locked_cues: true }); TL.sel.id = id + 1; }
    } else if (type === 'top') {
        const q = TOPDRAFT[id], start = q.start || 0, end = q.end !== undefined ? q.end : TL.dur;
        if (t > start && t < end) { const q2 = JSON.parse(JSON.stringify(q)); q.end = t; q2.id = 'top' + Date.now().toString(36); q2.start = t; TOPDRAFT.splice(id + 1, 0, q2); await applyTop(); TL.sel.id = id + 1; }
    }
}

async function tlDelete() {
    if (!TL.sel) return;
    const c = clip(); if (!c) return; const { type, id } = TL.sel; TL.sel = null; updateTLToolbar();
    if (type === 'keep') {
        let k = [...c.keep]; if (k.length > 1) { k.splice(id, 1); await patch(c.id, { keep: k, locked: true }); } else alert("Cannot delete the last video segment.");
    } else if (type === 'cues') {
        let cues = [...c.cues]; cues[id].deleted = true; await patch(c.id, { cues, locked_cues: true });
    } else if (type === 'top') {
        TOPDRAFT.splice(id, 1); await applyTop();
    } else if (type === 'sfx') {
        let sfx = [...c.sfx]; sfx.splice(id, 1); await patch(c.id, { sfx });
    }
}

$('tl-zoom')?.addEventListener('input', function() { TL.zoom = parseInt(this.value); updateTL(); tlSync(); });$('tl-ruler')?.addEventListener('pointerdown', e => { const rect = $('tl-tracks').getBoundingClientRect();$('vid').currentTime = Math.max(0, (e.clientX - rect.left + $('tl-scroll').scrollLeft) / TL.zoom); });$('tl-play')?.addEventListener('click', togglePlay);
$('tl-split')?.addEventListener('click', tlSplit);$('tl-del')?.addEventListener('click', tlDelete);

function tlSync() {
    const v = $('vid');
    if (TL.dur > 0 && v) {
        const px = v.currentTime * TL.zoom; $('tl-playhead').style.left = px + 'px';
        if (!v.paused) {
            const scr = $('tl-scroll'); if (px < scr.scrollLeft \vert{}\vert{} px > scr.scrollLeft + scr.clientWidth - 50) scr.scrollLeft = Math.max(0, px - scr.clientWidth / 2); } } }$('vid')?.addEventListener('timeupdate', tlSync);
$('vid')?.addEventListener('play', () =>$('tl-play').textContent = '⏸ Pause');
$('vid')?.addEventListener('pause', () =>$('tl-play').textContent = '▶ Play');

// Intercept loads to re-render the timeline
const origLoad = load; load = function(p) { origLoad(p); if (!$('editing').hidden) updateTL(); };
const origSelClip = selClip; selClip = function(id) { origSelClip(id); if (!$('editing').hidden) updateTL(); };

document.addEventListener('keydown', e => {
    if (!$('editing').hidden) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.code === 'Space') { e.preventDefault(); togglePlay(); } 
        else if (e.code === 'KeyS' || e.key === 's') { e.preventDefault(); tlSplit(); } 
        else if (e.code === 'Delete' || e.code === 'Backspace') { e.preventDefault(); tlDelete(); } 
        else if (e.code === 'KeyZ' && (e.ctrlKey || e.metaKey) && !e.shiftKey) { e.preventDefault(); undo('undo'); setTimeout(updateTL, 250); } 
        else if (e.code === 'KeyY' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo('redo'); setTimeout(updateTL, 250); } 
        else if (e.code === 'KeyZ' && (e.ctrlKey || e.metaKey) && e.shiftKey) { e.preventDefault(); undo('redo'); setTimeout(updateTL, 250); }
    }
});
