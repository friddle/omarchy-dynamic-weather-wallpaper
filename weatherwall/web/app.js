const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ---------------- 本机令牌 ---------------- */
/* 启动器以 URL fragment(#t=...) 带入令牌: fragment 不会发往服务器, 取出后立即从地址栏清除,
   只保留在本标签页会话里。手动打开(无 fragment)时由令牌门输入一次。 */
(function(){
  const grab=()=>{
    const m=location.hash.match(/[#&]t=([A-Za-z0-9_-]+)/);
    if(m){
      sessionStorage.setItem('ww_token',m[1]);
      try{history.replaceState(null,'',location.pathname);}catch(_){}
    }
  };
  grab();
  window.addEventListener('hashchange',grab);   /* 已打开的页面再收到 #t= 也能登录 */
})();
const APITOKEN=sessionStorage.getItem('ww_token')||'';
function showTokenGate(){
  const m=$('modal-token');if(!m||!m.classList.contains('hidden'))return;
  m.classList.remove('hidden');
  $('token-input').value=sessionStorage.getItem('ww_token')||'';
}
$('token-go').onclick=()=>{
  const v=$('token-input').value.trim();
  if(!v)return;
  sessionStorage.setItem('ww_token',v);
  location.reload();
};
$('token-input').addEventListener('keydown',e=>{if(e.key==='Enter')$('token-go').click();});
$('modal-token').onclick=e=>{if(e.target.id==='modal-token')$('modal-token').classList.add('hidden');};

let LANG='en';
const t=k=>I18N[LANG][k]??I18N.en[k]??k;
function applyI18n(){
  document.documentElement.lang=LANG==='zh'?'zh-CN':'en';
  document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=t(el.dataset.i18n));
  document.querySelectorAll('[data-i18n-ph]').forEach(el=>el.placeholder=t(el.dataset.i18nPh));
  $('lang-en').classList.toggle('on',LANG==='en');
  $('lang-zh').classList.toggle('on',LANG==='zh');
  updateKeyHowto();
}

/* ---------------- helpers ---------------- */
function toast(msg,err){const tb=$('toast');tb.textContent=msg;tb.className='show'+(err?' err':'');
  clearTimeout(tb._h);tb._h=setTimeout(()=>tb.className='',3200);}
async function api(path,body){
  const hs={'X-Token':(typeof APITOKEN!=='undefined')?APITOKEN:''};
  const opt=body!==undefined?{method:'POST',headers:Object.assign(hs,{'Content-Type':'application/json'}),body:JSON.stringify(body)}:{headers:hs};
  const r=await fetch(path,opt);const j=await r.json().catch(()=>({ok:false,error:'bad response'}));
  if(j&&j.error==='unauthorized')showTokenGate();
  if(!j.ok&&j.error)throw new Error(j.error);return j;}

/* ---------------- tabs ---------------- */
const TABS=['status','base','adv','widget','gallery'];
TABS.forEach(name=>$('tabbtn-'+name).onclick=()=>{
  TABS.forEach(n=>{$('tab-'+n).classList.toggle('hidden',n!==name);
    $('tabbtn-'+n).classList.toggle('on',n===name);});
  if(name==='gallery')loadWalls();
  if(name==='adv'&&!DISPLAYS.length)loadDisplays();
  if(name==='widget'){wgPreviewBg();wgRender();calPlace();calRender();}
});

/* ---------------- language ---------------- */
function setLang(l,persist=true){LANG=l;applyI18n();renderStatus(ST_CACHE);renderBases(BASE_CACHE);renderRefs();renderWalls(WALL_CACHE);
  wgRender();calRender();
  if(persist)api('/api/config',{config:{ui:{language:l}}}).catch(()=>{});}
$('lang-en').onclick=()=>setLang('en');
$('lang-zh').onclick=()=>setLang('zh');
$('cfg-lang').onchange=()=>setLang($('cfg-lang').value);

/* ---------------- status ---------------- */
let ST_CACHE=null;
async function loadStatus(){
  try{
    const st=await api('/api/status');ST_CACHE=st;renderStatus(st);
  }catch(e){toast(e.message,true)}
}
function renderStatus(st){
  if(!st)return;
  $('ver').textContent='v'+st.version+' · '+st.platform;
  const lr=st.state.last_run;
  $('last-run').textContent=lr?(''+lr).replace('T',' '):'—';
  $('last-run').className='badge'+(lr?'':' warn');
  const regionTxt=(st.region_setting==='auto'?t('kw_auto')+(st.region_detected||t('kw_detected')):st.region_setting)
    +(st.proxy?' · proxy '+st.proxy:'');
  $('st-region').innerHTML='<span class="badge">'+esc(regionTxt)+'</span>';
  const w=st.state.last_weather;
  const genErr=st.state.last_gen_error;
  const genBadge=st.state.last_error
    ?' <span class="badge err" title="'+esc(st.state.last_error)+'">'+t('kw_err')+'</span>'
    :(genErr?' <span class="badge warn" title="'+esc(genErr)+'">'+t('kw_degraded')+'</span>':'');
  $('st-weather').innerHTML=w
    ?esc(`${w.city} · ${WX_NAME[LANG][w.tag]||w.desc} · ${w.temp_current}℃ (${w.temp_min}~${w.temp_max}℃) · ${w.provider}`)+genBadge
    :'<span class="badge warn">—</span>';
  const tg=st.state.last_tags;
  $('st-tags').innerHTML=tg
    ?esc(`${WX_NAME[LANG][tg.weather]||tg.weather} / ${PERIOD_NAME[LANG][tg.daypart]||tg.daypart} / ${tg.temp}℃ / ${ST_NAME[LANG][tg.solarterm]||tg.solarterm}`)
    :'—';
  $('st-file').innerHTML=st.state.last_stem
    ?`<span class="preview-name">${esc(st.state.last_stem)}.${esc((st.state.last_target||'.jpg').split('.').pop())}</span>
      ${st.state.last_cached?' <span class="badge ok">'+t('kw_cached')+'</span>':' <span class="badge warn">'+t('kw_new')+'</span>'}`
    :'—';
  $('st-misc').innerHTML=(st.base_image_exists?`<span class="badge ok">${esc(st.base_image)}</span>`:'<span class="badge warn">—</span>')
    +' '+(st.has_api_key?'<span class="badge ok">API Key ✓</span>':'<span class="badge warn">'+t('no_key')+'</span>');
  $('log').textContent=(st.log||[]).join('\n');
  const lb=$('log');lb.scrollTop=lb.scrollHeight;
  /* 未配置生图 API Key: 禁用 立即刷新/强制重新生图(后端接口同步拦截) */
  const genOk=!!st.has_api_key;
  ['btn-refresh','btn-force'].forEach(id=>{
    const b=$(id);b.disabled=!genOk;b.title=genOk?'':t('t_key_required');
    b.style.opacity=genOk?'':'0.5';
  });
  /* ffmpeg 状态: 不可用时给出原因徽标 + 一键安装按钮(mac: brew, 其他平台同理) */
  $('wg-ffwarn').classList.toggle('hidden',!!st.widget_ready);
  if(!st.widget_ready){
    $('wg-ffwarn').textContent=st.ffmpeg_found&&!st.ffmpeg_drawtext
      ?(LANG==='zh'?'ffmpeg 缺少 drawtext 滤镜 — 需重装完整版':'ffmpeg lacks drawtext — reinstall full build')
      :t('wg_need_ffmpeg');
  }
  /* ffmpeg 不可用: 挂件功能整体禁用(仅保留警告与安装按钮) */
  setWidgetEnabled(!!st.widget_ready);
  const installing=!!st.ffmpeg_install_running;
  $('wg-ffinstall').classList.toggle('hidden',!!st.widget_ready||installing);
  $('wg-ffinstall').disabled=installing;
  if(installing&&!$('wg-ffwarn').classList.contains('hidden'))
    $('wg-ffwarn').textContent=t('wg_installing');
  if(st.ffmpeg_install_error&&!installing&&!$('wg-ffwarn').classList.contains('hidden'))
    $('wg-ffwarn').title=st.ffmpeg_install_error;
  /* macOS 专属: 导入系统日历按钮 */
  $('cal-import').classList.toggle('hidden',st.platform!=='macOS');
  if(!$('tab-widget').classList.contains('hidden'))wgRender();
}

/* 挂件 tab 控件开关: ffmpeg 不可用时全部禁用, 仅保留警告徽标与安装按钮 */
function setWidgetEnabled(on){
  $('tab-widget').querySelectorAll('input,select,button,textarea').forEach(el=>{
    if(el.id==='wg-ffinstall')return;   /* 安装按钮保持可用 */
    el.disabled=!on;
  });
  document.getElementById('tab-widget').style.opacity=on?'':'0.75';
}

/* ---------------- base images ---------------- */
let BASE_CACHE=null;
async function loadBases(){BASE_CACHE=await api('/api/base-images');renderBases(BASE_CACHE);wgPreviewBg();}
function renderBases(r){
  if(!r)return;const el=$('base-list');
  el.innerHTML=r.items.length?'':'<div class="hint" style="grid-column:1/-1">'+t('t_no_base')+'</div>';
  for(const it of r.items){
    const active=it.name===r.active;
    const d=document.createElement('div');
    d.className='base-item'+(active?' active':'');
    d.innerHTML=`${active?'<span class="mark">✓</span>':''}
      <span class="ops"><button class="op" data-act="rename" title="${t('rename')}">✏️</button>
      <button class="op" data-act="del" title="${t('del')}">🗑</button></span>
      <img src="/api/base-image-file?name=${encodeURIComponent(it.name)}" title="${LANG==='zh'?'点击设为生效':'click to activate'}">
      <div class="nm">${esc(it.name)}</div>`;
    d.querySelector('img').onclick=()=>selectBase(it.name);
    d.querySelector('[data-act=rename]').onclick=e=>{e.stopPropagation();renameBase(it.name);};
    d.querySelector('[data-act=del]').onclick=e=>{e.stopPropagation();if(confirm(t('del_confirm')+' '+it.name+' ?'))delBase(it.name);};
    el.appendChild(d);
  }
}
async function renameBase(name){
  const cur=name.replace(/\.[^.]+$/,'');
  const input=prompt(t('rename_prompt'),cur);
  if(input===null)return;
  try{const r=await api('/api/base-image-rename',{name:name,new_name:input});
    toast(t('rename')+' -> '+r.name);loadBases();loadStatus();loadWalls();
  }catch(e){toast(e.message,true)}
}
async function selectBase(name){try{await api('/api/base-image-select',{name});toast((LANG==='zh'?'已生效: ':'Active: ')+name);loadBases();loadStatus();}catch(e){toast(e.message,true)}}
async function delBase(name){try{await api('/api/base-image-delete',{name});toast(LANG==='zh'?'已删除':'Deleted');loadBases();loadStatus();}catch(e){toast(e.message,true)}}
async function uploadBase(file){
  if(!file)return;
  if(file.size>30*1024*1024)return toast('>30MB',true);
  const buf=await file.arrayBuffer();
  let bin='';const bytes=new Uint8Array(buf);const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk)bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk));
  try{const r=await api('/api/base-image',{name:file.name,data_b64:btoa(bin)});
    toast((LANG==='zh'?'上传成功: ':'Uploaded: ')+r.name);loadBases();loadStatus();
  }catch(e){toast(e.message,true)}
}
$('drop').onclick=()=>$('file').click();
$('file').onchange=e=>{uploadBase(e.target.files[0]);e.target.value='';};
$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('drag')};
$('drop').ondragleave=()=>$('drop').classList.remove('drag');
$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('drag');uploadBase(e.dataTransfer.files[0])};

/* ---------------- 自动生成基准图弹窗 ---------------- */
let DEFAULT_BASE_PROMPT='';
$('btn-gen-base').onclick=()=>{
  $('genb-prompt').value=$('genb-prompt').value.trim()||DEFAULT_BASE_PROMPT;
  $('genb-status').textContent='';
  $('genb-go').disabled=false;
  $('modal-gen').classList.remove('hidden');
};
$('genb-cancel').onclick=()=>$('modal-gen').classList.add('hidden');
$('modal-gen').onclick=e=>{if(e.target.id==='modal-gen')$('modal-gen').classList.add('hidden');};
$('genb-go').onclick=async()=>{
  const btn=$('genb-go');btn.disabled=true;
  $('genb-status').textContent=t('genb_running');
  try{
    const r=await api('/api/base-image-generate',{prompt:$('genb-prompt').value.trim(),name:$('genb-name').value.trim()});
    toast(t('genb_ok')+r.name);
    $('modal-gen').classList.add('hidden');
    $('genb-name').value='';
    loadBases();loadStatus();
  }catch(e){toast(e.message,true);$('genb-status').textContent='';}
  btn.disabled=false;
};

/* ---------------- gallery (two-level: base → generated) ---------------- */
let WALL_CACHE=null,WALL_GROUP=null;
async function loadWalls(){WALL_CACHE=await api('/api/wallpapers');renderWalls(WALL_CACHE);wgPreviewBg();}
function renderWalls(r){
  if(!r)return;
  const groups=r.groups||[],el=$('wall-list'),chips=$('wall-groups');
  chips.innerHTML='';
  if(!groups.length){el.innerHTML='<div class="hint" style="grid-column:1/-1">'+t('t_no_walls')+'</div>';return;}
  if(!WALL_GROUP||!groups.some(g=>g.base===WALL_GROUP))WALL_GROUP=groups[0].base;
  for(const g of groups){
    const c=document.createElement('button');
    c.className='chip'+(g.base===WALL_GROUP?' on':'');
    c.textContent=`${g.base} (${g.count})`;
    c.onclick=()=>{WALL_GROUP=g.base;renderWalls(WALL_CACHE);};
    chips.appendChild(c);
  }
  const g=groups.find(x=>x.base===WALL_GROUP);
  el.innerHTML='';
  for(const it of g.items.slice(0,60)){
    const d=document.createElement('div');
    d.className='wall-item';
    const fname=it.name.split('/').pop();
    d.innerHTML=`<img src="/api/wallpaper-file?name=${encodeURIComponent(it.name)}" title="${LANG==='zh'?'点击应用':'click to apply'}">
      <div class="nm" title="${esc(fname)}">${esc(fname)}</div>`;
    d.querySelector('img').onclick=async()=>{try{await api('/api/apply',{file:it.name});toast(t('t_apply_ok')+fname)}catch(e){toast(e.message,true)}};
    el.appendChild(d);
  }
}

/* ---------------- displays ---------------- */
let DISPLAYS=[];
async function loadDisplays(){
  try{
    const r=await api('/api/displays');
    DISPLAYS=r.displays||[];
    const selected=Array.isArray(r.selected)?r.selected.map(String):(r.selected==='all'?null:r.selected);
    const box=$('disp-list');
    if(!DISPLAYS.length){box.innerHTML='<div class="hint">'+t('disp_empty')+'</div>';$('disp-status').textContent='';return;}
    let html=`<label style="display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer">
      <input type="checkbox" id="disp-all" ${selected===null?'checked':''} style="width:auto">
      <span style="color:var(--text);font-size:13px">${t('disp_all')} (${DISPLAYS.length}${t('disp_count')})</span></label>`;
    for(const d of DISPLAYS){
      const cur=d.picture?d.picture.split('/').pop():'';
      const checked=selected&&selected.includes(String(d.index));
      html+=`<label style="display:flex;align-items:center;gap:8px;margin:4px 0;cursor:pointer">
        <input type="checkbox" class="disp-item" data-index="${d.index}" ${checked?'checked':''} ${selected===null?'disabled':''} style="width:auto">
        <span style="color:var(--text);font-size:13px">#${d.index} · ${esc(d.name)}</span>
        <span style="color:var(--muted);font-size:11px">${esc(cur)}</span></label>`;
    }
    box.innerHTML=html;
    $('disp-all').onchange=e=>{document.querySelectorAll('.disp-item').forEach(c=>{c.checked=false;c.disabled=e.target.checked;});};
    document.querySelectorAll('.disp-item').forEach(c=>c.onchange=()=>{
      const any=[...document.querySelectorAll('.disp-item')].some(x=>x.checked);
      $('disp-all').checked=!any;
      document.querySelectorAll('.disp-item').forEach(x=>x.disabled=!any&&false);
    });
    $('disp-status').innerHTML=`<span class="badge ok">${DISPLAYS.length}${t('disp_count')}</span>`;
  }catch(e){$('disp-status').innerHTML='<span class="badge err">'+esc(e.message)+'</span>';}
}
$('btn-displays').onclick=loadDisplays;
$('btn-save-displays').onclick=async()=>{
  const all=$('disp-all')&&$('disp-all').checked;
  const picked=[...(document.querySelectorAll('.disp-item:checked'))].map(c=>+c.dataset.index);
  try{await api('/api/config',{config:{wallpaper:{displays:all?'all':picked}}});
    toast(t('disp_saved'));}catch(e){toast(e.message,true)}
};

/* ---------------- city picker ---------------- */
let CHINA=[],US=[];
function fillCitySelect(country,selected){
  const sel=$('cfg-city');
  sel.innerHTML='';
  if(country==='china'){
    for(const c of CHINA){
      const o=document.createElement('option');
      o.value=c.en;o.textContent=LANG==='zh'?`${c.cn} (${c.en})`:`${c.en} (${c.cn})`;
      o.dataset.code=c.code;sel.appendChild(o);
    }
    if(selected)sel.value=selected;
  }else if(country==='us'){
    for(const name of US){const o=document.createElement('option');o.value=name;o.textContent=name;sel.appendChild(o);}
    if(selected)sel.value=selected;
  }
  $('wrap-city-select').classList.toggle('hidden',country==='other');
  $('wrap-city-text').classList.toggle('hidden',country!=='other');
}
function guessCountry(city){
  if(CHINA.some(c=>c.en.toLowerCase()===String(city).toLowerCase()||c.cn===city))return 'china';
  if(US.some(c=>c.toLowerCase()===String(city).toLowerCase()))return 'us';
  return 'other';
}
$('cfg-country').onchange=()=>fillCitySelect($('cfg-country').value,null);
$('btn-locate').onclick=async()=>{
  try{
    const r=await api('/api/locate',{});
    let where=r.city+(r.country?', '+r.country:'');
    if(r.china_city){$('cfg-country').value='china';fillCitySelect('china',r.china_city.en);}
    else if(r.country_code==='US'&&US.includes(r.city)){$('cfg-country').value='us';fillCitySelect('us',r.city);}
    else{$('cfg-country').value='other';fillCitySelect('other');$('cfg-city-free').value=r.city;}
    if(r.latitude){$('cfg-lat').value=r.latitude;$('cfg-lon').value=r.longitude;}
    toast(t('t_located')+where);
  }catch(e){toast(t('t_locate_fail')+e.message,true)}
};

/* ---------------- weather key visibility ---------------- */
function updateKeyHowto(){
  const p=$('cfg-provider').value;
  const needKey=(p==='qweather'||p==='openweathermap');
  $('wkey-block').style.display=needKey?'':'none';
  $('whost-wrap').style.display=p==='qweather'?'':'none';
  $('key-howto').innerHTML=p==='qweather'?t('key_howto_q'):(p==='openweathermap'?t('key_howto_o'):t('key_howto_free'));
}
$('cfg-provider').addEventListener('change',updateKeyHowto);

/* ---------------- collect / fill / save ---------------- */
function collectWeather(){
  const country=$('cfg-country').value;
  let city='',code='';
  if(country==='other'){city=$('cfg-city-free').value.trim();}
  else{city=$('cfg-city').value;
    const opt=$('cfg-city').selectedOptions[0];code=country==='china'?(opt&&opt.dataset.code||''):'';}
  const lat=parseFloat($('cfg-lat').value),lon=parseFloat($('cfg-lon').value);
  return{provider:$('cfg-provider').value,city:city||'Hangzhou',city_code:code,
    api_key:$('cfg-weather-key').value.trim(),api_host:$('cfg-weather-host').value.trim(),
    latitude:isNaN(lat)?null:lat,longitude:isNaN(lon)?null:lon};
}
function fillForm(cfg){
  $('cfg-region').value=cfg.region||'auto';
  $('cfg-proxy').value=cfg.network?.proxy||'';
  $('cfg-provider').value=cfg.weather?.provider||'auto';
  $('cfg-city-free').value=(cfg.weather?.provider==='auto'||!cfg.weather?.city)?'':
    (guessCountry(cfg.weather?.city)==='other'?cfg.weather.city:'');
  $('cfg-country').value=guessCountry(cfg.weather?.city||'Hangzhou');
  fillCitySelect($('cfg-country').value,
    $('cfg-country').value==='other'?null:(cfg.weather?.city||'Hangzhou'));
  $('cfg-weather-key').value=cfg.weather?.api_key||'';
  $('cfg-weather-key').placeholder=cfg.weather?.api_key?(LANG==='zh'?'已配置':'configured'):'';
  $('cfg-weather-host').value=cfg.weather?.api_host||'';
  $('cfg-lat').value=cfg.weather?.latitude??'';$('cfg-lon').value=cfg.weather?.longitude??'';
  $('cfg-refresh').value=cfg.refresh_minutes||30;
  $('cfg-temp-mode').value=cfg.naming?.temp_mode||'band';
  const ck=cfg.naming?.cache_key||{};
  $('ck-weather').checked=ck.weather!==false;
  $('ck-period').checked=ck.period!==false;
  $('ck-solarterm').checked=ck.solarterm!==false;
  $('ck-temp').checked=ck.temp===true;
  $('ck-date').checked=ck.date===true;
  $('gen-base-url').value=cfg.generator?.base_url||'';
  $('gen-key').value=cfg.generator?.api_key||'';
  $('gen-key').placeholder=cfg.generator?.api_key?(LANG==='zh'?'已配置(点击可修改)':'configured'):'sk-...';
  $('gen-model').value=cfg.generator?.model||'gpt-image-1';
  $('gen-size').value=cfg.generator?.size||'auto';
  PROMPTS=(cfg.generator?.prompts&&cfg.generator.prompts.length)
    ?cfg.generator.prompts:[{name:'default',template:cfg.generator?.prompt||''}];
  PT_ACTIVE=cfg.generator?.active_prompt||PROMPTS[0].name;
  if(!PROMPTS.some(p=>p.name===PT_ACTIVE))PT_ACTIVE=PROMPTS[0].name;
  PT_EDIT=PT_ACTIVE;
  renderPrompts();
  LANG=cfg.ui?.language||'en';$('cfg-lang').value=LANG;
  const wg=cfg.widget||{};
  $('wg-enable').checked=!!wg.enabled;
  $('wg-style').value=wg.style||'glass';
  $('wg-opacity').value=Math.round(((wg.bg_opacity??0.55))*100);
  $('wg-op-v').textContent=$('wg-opacity').value+'%';
  $('wg-scale').value=Math.round((wg.scale??1)*100);
  $('wg-scale-v').textContent=(+$('wg-scale').value/100).toFixed(1);
  WGPOS.x=+((wg.position||{}).x??0.94);WGPOS.y=+((wg.position||{}).y??0.08);
  wgPlace();
  $('wg-fields').innerHTML='';
  (wg.fields&&wg.fields.length?wg.fields:['{city}']).forEach(f=>wgAddField(String(f)));
  wgRender();
  const cc=cfg.widget_calendar||{};
  $('cal-enable').checked=!!cc.enabled;
  $('cal-style').value=cc.style||'glass';
  $('cal-opacity').value=Math.round(((cc.bg_opacity??0.55))*100);
  $('cal-op-v').textContent=$('cal-opacity').value+'%';
  $('cal-scale').value=Math.round((cc.scale??0.5)*100);
  $('cal-scale-v').textContent=(+$('cal-scale').value/100).toFixed(1);
  CALPOS.x=+((cc.position||{}).x??0.09);CALPOS.y=+((cc.position||{}).y??0.5);
  calPlace();calRender();
  applyI18n();
}
$('btn-save-gen').onclick=async()=>{
  if(!$('gen-key').value.trim()){
    $('gen-key').style.borderColor='var(--err)';
    $('gen-key').focus();
    toast(t('t_key_required'),true);
    setTimeout(()=>$('gen-key').style.borderColor='',2400);
    return;
  }
  try{await api('/api/config',{config:{generator:{
    base_url:$('gen-base-url').value.trim()||'https://api.openai.com/v1',
    api_key:$('gen-key').value.trim(),model:$('gen-model').value.trim()||'gpt-image-1',
    size:$('gen-size').value}}});
    toast(t('t_saved'));loadStatus();}catch(e){toast(e.message,true)}};
$('gen-key').oninput=()=>{$('gen-key').style.borderColor='';};
async function loadGenModels(){
  try{
    const r=await api('/api/gen-models');
    const dl=$('model-options');dl.innerHTML='';
    (r.models||[]).forEach(m=>{const o=document.createElement('option');o.value=m;dl.appendChild(o);});
  }catch(e){/* base_url/key 未配置或网络不通: 静默保留手输 */}
}
$('gen-base-url').addEventListener('change',loadGenModels);
$('gen-key').addEventListener('change',loadGenModels);

/* ---------------- prompt 模板管理(命名多条, 本地存储于 config.json) ---------------- */
let PROMPTS=[],PT_ACTIVE='',PT_EDIT='';
function renderPrompts(){
  const box=$('prompt-list');box.innerHTML='';
  for(const p of PROMPTS){
    const c=document.createElement('button');
    c.className='chip'+(p.name===PT_EDIT?' on':'');
    c.textContent=(p.name===PT_ACTIVE?'✓ ':'')+p.name;
    c.title=p.name===PT_ACTIVE?t('pt_active'):'';
    c.onclick=()=>{PT_EDIT=p.name;renderPrompts();};
    box.appendChild(c);
  }
  const cur=PROMPTS.find(p=>p.name===PT_EDIT);
  $('gen-prompt').value=cur?cur.template:'';
  $('pt-cur').textContent=`${t('pt_active')}: ${PT_ACTIVE} · ${t('pt_editing')}: ${PT_EDIT}`;
}
async function promptCfg(action,name){
  try{
    const r=await api('/api/prompt-cfg',{action,name,template:$('gen-prompt').value});
    PROMPTS=r.prompts;PT_ACTIVE=r.active;
    if(!PROMPTS.some(p=>p.name===PT_EDIT))PT_EDIT=PT_ACTIVE;
    renderPrompts();toast(t('t_saved'));
  }catch(e){toast(e.message,true)}
}
$('pt-add').onclick=()=>{
  const name=prompt(t('pt_name_prompt'));
  if(name===null)return;
  if(!name.trim())return toast(t('pt_name_prompt'),true);
  PT_EDIT='';   // 新建后由服务端归一化命名, 响应里同步
  promptCfg('add',name.trim());
};
$('pt-save').onclick=()=>promptCfg('save',PT_EDIT);
$('pt-select').onclick=()=>promptCfg('select',PT_EDIT);
$('pt-del').onclick=()=>promptCfg('delete',PT_EDIT);

/* ---------------- 参考图(角色/风格样例, 随生图上传) ---------------- */
let REF_CACHE=null;
async function loadRefs(){try{REF_CACHE=await api('/api/ref-images');renderRefs();}catch(e){/* 静默 */}}
function renderRefs(){
  const r=REF_CACHE;if(!r)return;
  const el=$('ref-list');
  el.innerHTML=r.items.length?'':'<div class="hint" style="grid-column:1/-1">'+t('t_no_ref')+'</div>';
  for(const it of r.items){
    const d=document.createElement('div');
    d.className='base-item';
    d.innerHTML=`<span class="ops"><button class="op" data-act="del" title="${t('del')}">🗑</button></span>
      <img src="/api/ref-image-file?name=${encodeURIComponent(it.name)}">
      <div class="nm">${esc(it.name)}</div>`;
    d.querySelector('[data-act=del]').onclick=e=>{e.stopPropagation();
      if(confirm(t('del_confirm')+' '+it.name+' ?'))delRef(it.name);};
    el.appendChild(d);
  }
}
async function delRef(name){
  try{await api('/api/ref-image-delete',{name});toast(LANG==='zh'?'已删除':'Deleted');loadRefs();}
  catch(e){toast(e.message,true)}
}
async function uploadRef(file){
  if(!file)return;
  if(file.size>30*1024*1024)return toast('>30MB',true);
  const buf=await file.arrayBuffer();
  let bin='';const bytes=new Uint8Array(buf);const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk)bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+chunk));
  try{const r=await api('/api/ref-image',{name:file.name,data_b64:btoa(bin)});
    toast((LANG==='zh'?'上传成功: ':'Uploaded: ')+r.name);loadRefs();
  }catch(e){toast(e.message,true)}
}
$('ref-drop').onclick=()=>$('ref-file').click();
$('ref-file').onchange=e=>{[...e.target.files].forEach(uploadRef);e.target.value='';};
$('ref-drop').ondragover=e=>{e.preventDefault();$('ref-drop').classList.add('drag')};
$('ref-drop').ondragleave=()=>$('ref-drop').classList.remove('drag');
$('ref-drop').ondrop=e=>{e.preventDefault();$('ref-drop').classList.remove('drag');
  [...e.dataTransfer.files].forEach(uploadRef)};

/* ---------------- ffmpeg 一键安装 ---------------- */
$('wg-ffinstall').onclick=async()=>{
  try{
    await api('/api/install-ffmpeg',{});
    toast(t('wg_installing'));
    $('wg-ffinstall').disabled=true;
  }catch(e){toast(e.message,true)}
};
$('btn-save-weather').onclick=async()=>{try{await api('/api/config',{config:{weather:collectWeather(),
  region:$('cfg-region').value,network:{proxy:$('cfg-proxy').value.trim()}}});
  toast(t('t_saved'));loadStatus();}catch(e){toast(e.message,true)}};
$('btn-save-sch').onclick=async()=>{try{await api('/api/config',{config:{refresh_minutes:+$('cfg-refresh').value||30,
  naming:{temp_mode:$('cfg-temp-mode').value,temp_band:5,
    cache_key:{weather:$('ck-weather').checked,period:$('ck-period').checked,
      solarterm:$('ck-solarterm').checked,temp:$('ck-temp').checked,date:$('ck-date').checked}}}});
  toast(t('t_saved'));loadStatus();}catch(e){toast(e.message,true)}};
$('btn-save-lang').onclick=()=>setLang($('cfg-lang').value);

/* ---------------- actions ---------------- */
async function doDetect(){
  try{const r=await api('/api/detect-region',{});
    const label=r.region||(LANG==='zh'?'网络不可用':'unreachable');
    $('detect-result').innerHTML='<span class="badge ok">'+esc(label)+'</span>';
    toast((LANG==='zh'?'探测结果: ':'Detect: ')+label);loadStatus();
  }catch(e){toast(e.message,true)}
}
$('btn-detect').onclick=doDetect;$('btn-detect2').onclick=doDetect;
$('btn-refresh').onclick=async()=>{try{const r=await api('/api/refresh',{apply:true});
  toast(r.queued?t('t_gen_q'):(r.ok?t('t_gen_ok'):(r.error||'error')));loadStatus();loadWalls();}catch(e){toast(e.message,true)}};
$('btn-force').onclick=async()=>{if(!confirm(t('t_confirm_force')))return;
  try{const r=await api('/api/force-generate',{apply:true});
  toast(r.queued?t('t_gen_q'):t('t_gen_ok'));loadStatus();loadWalls();}catch(e){toast(e.message,true)}};
$('btn-test').onclick=async()=>{try{const r=await api('/api/test-weather',{force:false});
  $('test-result').innerHTML=`
  <div class="kv"><span class="k">${t('st_weather')}</span><span class="v">${esc(r.weather.city)} · ${esc(WX_NAME[LANG][r.weather.tag]||r.weather.desc)} · ${r.weather.temp_current}℃ · ${esc(r.weather.provider)}</span></div>
  <div class="kv"><span class="k">${t('st_file')}</span><span class="v"><span class="preview-name">${esc(r.stem)}.jpg</span>
    ${r.cached?'<span class="badge ok">'+t('kw_cached')+'</span>':'<span class="badge warn">'+t('t_new')+'</span>'}</span></div>
  <div class="kv"><span class="k">Prompt</span><span class="v" style="font-size:12px;color:var(--muted)">${esc(r.prompt)}</span></div>`;
  }catch(e){toast(e.message,true)}};

/* ---------------- widget (info overlay) ---------------- */
let WGPOS={x:0.94,y:0.08};
const getFieldInputs=()=>[...document.querySelectorAll('#wg-fields input')].map(i=>i.value);

function wgSample(){
  const w=ST_CACHE?.state?.last_weather||{city:LANG==='zh'?'杭州市':'Hangzhou',temp_current:22,temp_min:18,temp_max:28};
  const tg=ST_CACHE?.state?.last_tags||{weather:'cloudy',hours:'1216',temp:'20-25',temp_min:18,temp_max:28,solarterm:'colddew'};
  const n=new Date();
  const wi=WX_ICON[tg.weather]||'';
  const si=ST_ICON[tg.solarterm]||'';
  /* 时段优先取后端标签(渲染时段), 预览时回落当前小时 */
  const period=tg.daypart||periodOfHour(n.getHours());
  const r={city:w.city||'—',temp:Math.round(w.temp_current??0),temp_min:Math.round(w.temp_min??0),
    temp_max:Math.round(w.temp_max??0),weather:tg.weather,weather_name:WX_NAME[LANG][tg.weather]||tg.weather,
    weather_en:WX_NAME.en[tg.weather]||tg.weather,weather_cn:WX_NAME.zh[tg.weather]||tg.weather,
    hours:tg.hours,solarterm:tg.solarterm,solarterm_name:ST_NAME[LANG][tg.solarterm]||tg.solarterm,
    solarterm_en:ST_NAME.en[tg.solarterm]||tg.solarterm,solarterm_cn:ST_NAME.zh[tg.solarterm]||tg.solarterm,
    weather_icon:wi,icon:wi,solarterm_icon:si,
    period:PERIOD_NAME[LANG][period]||period,period_name:PERIOD_NAME[LANG][period]||period,
    period_en:PERIOD_NAME.en[period]||period,period_cn:PERIOD_NAME.zh[period]||period,
    daypart:period,daypart_name:PERIOD_NAME[LANG][period]||period,
    time:n.toTimeString().slice(0,5),date:n.toISOString().slice(0,10)};
  /* 单一时段 key: 仅当前时段非空 */
  PERIOD_ORDER.forEach(k=>r[k]=k===period?(PERIOD_NAME[LANG][k]||k):'');
  return r;
}
/* {morning} 等单一时段 key 的本地映射 */
function periodOfHour(h){
  if(h>=5&&h<8)return 'morning';
  if(h>=8&&h<11)return 'forenoon';
  if(h>=11&&h<14)return 'noon';
  if(h>=14&&h<18)return 'afternoon';
  if(h>=18&&h<20)return 'dusk';
  if(h>=20&&h<23)return 'evening';
  return 'latenight';
}
/* {time_HH:mm} {date_YYYY-MM-DD} 带格式占位符(与后端 format_clock 同规则) */
function expandDt(s){
  const n=new Date(),pad=v=>String(v).padStart(2,'0');
  const tk={YYYY:String(n.getFullYear()),YY:pad(n.getFullYear()%100),
    MM:pad(n.getMonth()+1),DD:pad(n.getDate()),HH:pad(n.getHours()),mm:pad(n.getMinutes()),
    M:String(n.getMonth()+1),D:String(n.getDate()),H:String(n.getHours()),m:String(n.getMinutes())};
  return String(s).replace(/\{(?:time|date)_([^{}]*)\}/g,(all,spec)=>{
    let out='',i=0;
    outer:while(i<spec.length){
      for(const k of ['YYYY','YY','MM','DD','HH','mm','M','D','H','m']){
        if(spec.startsWith(k,i)){out+=tk[k];i+=k.length;continue outer;}
      }
      out+=spec[i];i++;
    }
    return out;
  });
}
function wgFillLine(s){const r=wgSample();let out=String(s);for(const k in r)out=out.replaceAll('{'+k+'}',r[k]);return expandDt(out);}

function wgRender(){
  const dg=$('wg-drag'),style=$('wg-style').value;
  dg.className='wg-drag wgstyle-'+style;
  dg.style.setProperty('--wgo',(+$('wg-opacity').value)/100);
  const sc=+$('wg-scale').value/100;
  dg.style.fontSize=Math.max(7,Math.min(30,13*sc))+'px';
  const lines=getFieldInputs().map(v=>v.trim()).filter(Boolean).map(wgFillLine);
  dg.innerHTML=expBtn()+(lines.map((s,i)=>i===0?`<div class="t">${esc(s)}</div>`:`<div>${esc(s)}</div>`).join('')||'—');
  syncBigIfOpen();
}
function wgPlace(){
  $('wg-drag').style.left=(WGPOS.x*100)+'%';
  $('wg-drag').style.top=(WGPOS.y*100)+'%';
  $('wg-drag-big').style.left=(WGPOS.x*100)+'%';
  $('wg-drag-big').style.top=(WGPOS.y*100)+'%';
}
function wgAddField(v=''){
  const row=document.createElement('div');row.className='wg-row';
  row.innerHTML=`<input type="text" value="${esc(v)}">
    <button class="op" data-a="up" title="up">↑</button>
    <button class="op" data-a="dn" title="down">↓</button>
    <button class="op" data-a="del" title="✕">✕</button>`;
  row.querySelector('[data-a=up]').onclick=()=>row.previousElementSibling&&row.parentNode.insertBefore(row,row.previousElementSibling);
  row.querySelector('[data-a=dn]').onclick=()=>row.nextElementSibling&&row.parentNode.insertBefore(row.nextElementSibling,row);
  row.querySelector('[data-a=del]').onclick=()=>{row.remove();wgRender();};
  row.querySelector('input').oninput=wgRender;
  $('wg-fields').appendChild(row);
}
function wgPreviewBg(){
  /* 预览背景优先跟随当前生效的基准图, 没有再回落最新壁纸 */
  let url=null;
  if(BASE_CACHE&&BASE_CACHE.active)url='/api/base-image-file?name='+encodeURIComponent(BASE_CACHE.active);
  const g=WALL_CACHE&&WALL_CACHE.groups&&WALL_CACHE.groups[0];
  if(!url&&g&&g.items&&g.items.length)url='/api/wallpaper-file?name='+encodeURIComponent(g.items[0].name);
  if(url){const bg=`url(${url})`;$('wg-preview').style.backgroundImage=bg;$('wg-preview-big').style.backgroundImage=bg;}
}
/* 挂件盒角上的放大按钮(委托处理, 小/大预览共用) */
const expBtn=()=>`<span class="wg-exp" title="${esc(t('wg_expand'))}">⤢</span>`;
function makeDrag(pv,dg,pos,place,styleSel){
  /* position 语义 = 挂件盒中心点(0~1), 拖动时指针位置即新的中心 */
  const setFromEvent=e=>{
    const r=pv.getBoundingClientRect();
    pos.x=Math.min(1,Math.max(0,(e.clientX-r.left)/r.width));
    pos.y=Math.min(1,Math.max(0,(e.clientY-r.top)/r.height));
    place();
  };
  let dragging=false;
  dg.addEventListener('pointerdown',e=>{
    if(e.target.closest('.wg-exp'))return;   /* 放大按钮不触发拖拽 */
    if($(styleSel).value==='banner')return;
    dragging=true;
    try{dg.setPointerCapture(e.pointerId);}catch(_){}
    setFromEvent(e);e.preventDefault();
  });
  dg.addEventListener('pointermove',e=>{if(dragging)setFromEvent(e);});
  dg.addEventListener('pointerup',()=>dragging=false);
  dg.addEventListener('pointercancel',()=>dragging=false);
}
function syncBigIfOpen(){if(!$('modal-wgview').classList.contains('hidden'))syncBig();}
function syncBig(){
  /* 大视图按容器宽度比例放大, 低缩放档位再补一个放大系数保证可读(上限 52px) */
  const k=$('wg-preview-big').clientWidth/Math.max(1,$('wg-preview').clientWidth);
  const ref=parseFloat($('wg-drag').style.fontSize)||13;
  const z=Math.max(1,15/(ref*k));
  [['wg-drag','wg-drag-big'],['cal-drag','cal-drag-big']].forEach(([s,b])=>{
    const so=$(s),bo=$(b);
    bo.className=so.className;
    bo.style.setProperty('--wgo',so.style.getPropertyValue('--wgo'));
    const fs=parseFloat(so.style.fontSize)||13;
    bo.style.fontSize=Math.min(52,fs*k*z)+'px';
    bo.innerHTML=so.innerHTML;
    bo.style.left=so.style.left;bo.style.top=so.style.top;
  });
}
function openBig(){
  $('wg-preview-big').style.backgroundImage=$('wg-preview').style.backgroundImage;
  $('modal-wgview').classList.remove('hidden');
  syncBig();
}
$('wg-style').onchange=wgRender;
$('wg-opacity').oninput=()=>{$('wg-op-v').textContent=$('wg-opacity').value+'%';wgRender();};
$('wg-scale').oninput=()=>{$('wg-scale-v').textContent=(+$('wg-scale').value/100).toFixed(1);};
$('wg-add').onclick=()=>{wgAddField('');$('wg-fields').lastElementChild.querySelector('input').focus();};
$('btn-save-widget').onclick=async()=>{
  const fields=getFieldInputs().map(v=>v.trim()).filter(Boolean);
  try{await api('/api/config',{config:{widget:{
    enabled:$('wg-enable').checked,style:$('wg-style').value,
    bg_opacity:(+$('wg-opacity').value)/100,scale:(+$('wg-scale').value)/100,
    position:{x:+WGPOS.x.toFixed(3),y:+WGPOS.y.toFixed(3)},fields}}});
    toast(t('t_saved'));loadStatus();}catch(e){toast(e.message,true)}};

/* ---------------- calendar widget ---------------- */
let CALPOS={x:0.09,y:0.5};
const CALWD={en:['Mo','Tu','We','Th','Fr','Sa','Su'],zh:['一','二','三','四','五','六','日']};
function calRender(){
  const dg=$('cal-drag'),style=$('cal-style').value;
  dg.className='wg-drag calgrid wgstyle-'+style;
  dg.style.setProperty('--wgo',(+$('cal-opacity').value)/100);
  const sc=+$('cal-scale').value/100;
  dg.style.fontSize=Math.max(6,Math.min(26,11*sc))+'px';
  const n=new Date(),wd=CALWD[LANG]||CALWD.en;
  const first=new Date(n.getFullYear(),n.getMonth(),1);
  const start=(first.getDay()+6)%7;               /* Monday=0 */
  const days=new Date(n.getFullYear(),n.getMonth()+1,0).getDate();
  const title=LANG==='zh'?n.getFullYear()+'年'+(n.getMonth()+1)+'月'
    :first.toLocaleString('en',{month:'long'})+' '+n.getFullYear();
  let html=`<div class="t">${title}</div><div class="cg">`;
  wd.forEach((w,i)=>{html+=`<span class="hd${i>=5?' we':''}">${w}</span>`;});
  for(let i=0;i<start;i++)html+='<span></span>';
  const evp=n.getFullYear()+'-'+String(n.getMonth()+1).padStart(2,'0')+'-';
  for(let d=1;d<=days;d++){
    const col=(start+d-1)%7;
    const cls=d===n.getDate()?'today':(CALEVT[evp+String(d).padStart(2,'0')]?'evt':(col>=5?'we':''));
    html+=cls?`<span class="${cls}">${d}</span>`:`<span>${d}</span>`;
  }
  dg.innerHTML=expBtn()+html+'</div>';
  syncBigIfOpen();
}
/* 已导入的日历日程 {YYYY-MM-DD: [标题...]}: 月历中对应日子标橙 */
let CALEVT={};
async function loadCalendarEvents(){
  try{const r=await api('/api/calendar-events');CALEVT=r.events||{};calRender();}
  catch(e){/* 静默 */}
}
$('cal-import').onclick=async()=>{
  const st=$('cal-import-status');
  st.textContent=t('cal_importing');
  try{
    const r=await api('/api/calendar-import',{});
    st.textContent=r.count?t('cal_import_done')+r.days+'d / '+r.count:t('cal_import_empty');
    await loadCalendarEvents();
  }catch(e){st.textContent='';toast(e.message,true)}
};
function calPlace(){
  $('cal-drag').style.left=(CALPOS.x*100)+'%';
  $('cal-drag').style.top=(CALPOS.y*100)+'%';
  $('cal-drag-big').style.left=(CALPOS.x*100)+'%';
  $('cal-drag-big').style.top=(CALPOS.y*100)+'%';
}
$('cal-style').onchange=calRender;
$('cal-opacity').oninput=()=>{$('cal-op-v').textContent=$('cal-opacity').value+'%';calRender();};
$('cal-scale').oninput=()=>{$('cal-scale-v').textContent=(+$('cal-scale').value/100).toFixed(1);calRender();};
$('btn-save-calendar').onclick=async()=>{
  try{await api('/api/config',{config:{widget_calendar:{
    enabled:$('cal-enable').checked,style:$('cal-style').value,
    bg_opacity:(+$('cal-opacity').value)/100,scale:(+$('cal-scale').value)/100,
    position:{x:+CALPOS.x.toFixed(3),y:+CALPOS.y.toFixed(3)}}}});
    toast(t('t_saved'));loadStatus();}catch(e){toast(e.message,true)}};

/* ---------------- 挂件拖拽/放大绑定(共用预览 + 大视图) ---------------- */
document.addEventListener('click',e=>{
  const exp=e.target.closest('.wg-exp');if(!exp)return;
  if(exp.closest('#wg-preview-big'))$('modal-wgview').classList.add('hidden');
  else openBig();
});
$('wgview-close').onclick=()=>$('modal-wgview').classList.add('hidden');
$('modal-wgview').onclick=e=>{if(e.target.id==='modal-wgview')$('modal-wgview').classList.add('hidden');};
window.addEventListener('resize',syncBigIfOpen);
(function(){
  const pv=$('wg-preview');
  makeDrag(pv,$('wg-drag'),WGPOS,wgPlace,'wg-style');
  makeDrag(pv,$('cal-drag'),CALPOS,calPlace,'cal-style');
  const pb=$('wg-preview-big');
  makeDrag(pb,$('wg-drag-big'),WGPOS,wgPlace,'wg-style');
  makeDrag(pb,$('cal-drag-big'),CALPOS,calPlace,'cal-style');
})();

/* ---------------- init ---------------- */
(async function init(){
  try{
    const [cfg,cities]=await Promise.all([api('/api/config'),api('/api/cities')]);
    CHINA=cities.china;US=cities.us;
    DEFAULT_BASE_PROMPT=cfg.default_base_prompt||'';
    fillForm(cfg.config);
    renderStatus(ST_CACHE);
  }catch(e){toast(e.message,true)}
  if(!APITOKEN)showTokenGate();
  loadStatus();loadBases();loadWalls();loadRefs();loadCalendarEvents();
  loadGenModels();
  wgRender();wgPlace();calRender();calPlace();
  setTimeout(()=>{wgPreviewBg();wgRender();},800);
  setInterval(loadStatus,15000);
})();
