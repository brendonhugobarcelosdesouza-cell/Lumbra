"""Página HTML do Developer Console (arquivo único, sem build).

Login integrado (troca e-mail/senha por token via /auth/token), abas de
execução de skills, histórico com cancel/rerun/export, eventos do bus,
logs estruturados, documentos/pipeline, busca e grafo.
"""

CONSOLE_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Lumbra · Developer Console</title><style>
body{font-family:system-ui;margin:0;background:#0e0e11;color:#e8e8ea}
header{padding:10px 16px;background:#16161b;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0 12px 0 0}
input,select,button,textarea{padding:6px;background:#1e1e24;color:#e8e8ea;border:1px solid #34343c;border-radius:4px;font-size:13px}
button{cursor:pointer}
nav{display:flex;gap:2px;background:#16161b;padding:0 12px}
nav button{border:none;border-radius:0;padding:8px 14px;background:transparent}
nav button.active{background:#0e0e11;border-top:2px solid #6c8cff}
main{padding:14px}
table{border-collapse:collapse;width:100%;margin-top:6px}
td,th{border:1px solid #2a2a31;padding:4px 8px;font-size:12.5px;text-align:left;vertical-align:top}
pre{background:#16161b;padding:8px;overflow:auto;max-height:340px;font-size:12px;border-radius:4px}
.ok{color:#7ecb7e}.fail{color:#ef7070}.run{color:#e8c76b}.stop{color:#8ab4f8}
textarea{width:100%;height:90px;font-family:monospace}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
small{color:#9a9aa5}
</style></head><body>
<header><h1>Lumbra · Developer Console</h1>
<input id="email" placeholder="e-mail" size="24"><input id="pass" type="password" placeholder="senha" size="18">
<button onclick="login()">entrar</button><span id="who"><small>desconectado</small></span>
<label><input type="checkbox" id="auto" checked> atualizar (2s)</label></header>
<nav>
<button class="active" onclick="tab('exec',this)">Executar</button>
<button onclick="tab('hist',this)">Histórico</button>
<button onclick="tab('events',this)">Eventos</button>
<button onclick="tab('logs',this)">Logs</button>
<button onclick="tab('docs',this)">Documentos</button>
<button onclick="tab('search',this)">Busca</button>
<button onclick="tab('graph',this)">Grafo</button>
<button onclick="tab('metrics',this)">Métricas</button>
</nav><main>
<div id="t-exec">
 <p>skill: <select id="skillsel"></select> <small id="skilldesc"></small></p>
 <p>parâmetros (JSON):</p><textarea id="payload">{}</textarea>
 <p><button onclick="execSkill()">executar</button></p><div id="execout"></div></div>
<div id="t-hist" hidden></div>
<div id="t-events" hidden></div>
<div id="t-logs" hidden></div>
<div id="t-docs" hidden></div>
<div id="t-search" hidden><p><input id="q" size="40" placeholder="consulta">
 <button onclick="doSearch()">buscar</button></p><div id="searchout"></div></div>
<div id="t-graph" hidden></div>
<div id="t-metrics" hidden></div>
</main><script>
let TOKEN=null,TAB='exec';
const H=()=>({'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json'});
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function cls(s){return s==='completed'?'ok':s==='running'?'run':(s==='cancelled'||s==='timeout')?'stop':'fail'}
async function j(u,opt){const r=await fetch(u,{headers:H(),...opt});if(r.status===401){TOKEN=null;who();throw new Error('401')}return r.json()}
function who(){document.getElementById('who').innerHTML=TOKEN?'<small class="ok">conectado</small>':'<small class="fail">desconectado</small>'}
async function login(){
 const body=new URLSearchParams({username:email.value,password:pass.value});
 let r=await fetch('/api/v1/auth/token',{method:'POST',body});
 if(r.status===401){ // tenta registrar (dev)
   const reg=await fetch('/api/v1/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.value,password:pass.value})});
   if(reg.ok) r=await fetch('/api/v1/auth/token',{method:'POST',body});
 }
 if(!r.ok){alert('login falhou');return}
 TOKEN=(await r.json()).access_token;who();loadSkills();refresh();
}
function tab(name,btn){TAB=name;document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));btn.classList.add('active');
 document.querySelectorAll('main > div').forEach(d=>d.hidden=true);document.getElementById('t-'+name).hidden=false;refresh()}
async function loadSkills(){
 const skills=await j('/api/v1/dev/skills');
 skillsel.innerHTML=skills.map(s=>`<option value="${s.name}">${s.name}</option>`).join('');
 skillsel.onchange=()=>{const s=skills.find(x=>x.name===skillsel.value);skilldesc.textContent=s?s.description:''};
 skillsel.onchange();
}
async function execSkill(){
 let payload;try{payload=JSON.parse(document.getElementById('payload').value)}catch(e){alert('JSON inválido');return}
 const r=await j('/api/v1/dev/executions',{method:'POST',body:JSON.stringify({kind:'skill',name:skillsel.value,payload})});
 pollExec(r.execution_id);
}
async function pollExec(id){
 const d=await j('/api/v1/dev/executions/'+id);const e=d.execution;
 document.getElementById('execout').innerHTML=
  `<p>execução <code>${id}</code> — <b class="${cls(e.status)}">${e.status}</b>`+
  (e.duration_ms?` em ${e.duration_ms}ms`:'')+
  ` <button onclick="cancelExec('${id}')">cancelar</button>`+
  ` <button onclick="rerunExec('${id}')">reexecutar</button>`+
  ` <a href="/api/v1/dev/executions/${id}/export" onclick="return exportExec('${id}')">exportar</a></p>`+
  `<div class="grid"><div><h4>Entrada</h4><pre>${esc(JSON.stringify(e.input,null,2))}</pre></div>`+
  `<div><h4>Saída</h4><pre>${esc(JSON.stringify(e.output,null,2))||''}</pre></div></div>`+
  ((e.status==='cancelled'||e.status==='timeout')
    ?`<h4 class="stop">Interrompida (não é falha)</h4><pre>${esc('motivo: '+(e.cancel_reason||'-')+'\npedido por: '+(e.cancelled_by||'-')+'\netapas concluídas antes: '+((e.completed_steps||[]).join(' > ')||'nenhuma'))}</pre>`
    :(e.error?`<h4 class="fail">Erro</h4><pre>${esc(e.error_detail||e.error)}</pre>`:''))+
  `<h4>Eventos desta execução (${d.events.length})</h4><pre>${esc(d.events.map(ev=>ev.type+'  '+JSON.stringify(ev.payload)).join('\\n'))}</pre>`;
 if(e.status==='running')setTimeout(()=>pollExec(id),700);
}
async function exportExec(id){const d=await j('/api/v1/dev/executions/'+id+'/export');
 const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='execucao-'+id+'.json';a.click();return false}
async function cancelExec(id){await j('/api/v1/dev/executions/'+id+'/cancel',{method:'POST'});pollExec(id)}
async function rerunExec(id){const r=await j('/api/v1/dev/executions/'+id+'/rerun',{method:'POST'});pollExec(r.execution_id)}
async function refresh(){
 if(!TOKEN)return;
 try{
 if(TAB==='hist'){const h=await j('/api/v1/dev/executions');
  document.getElementById('t-hist').innerHTML='<table><tr><th>quando</th><th>skill</th><th>status</th><th>ms</th><th></th></tr>'+
   h.map(e=>`<tr><td>${e.started_at.slice(11,19)}</td><td>${e.name}</td><td class="${cls(e.status)}">${e.status}</td><td>${e.duration_ms??''}</td><td><button onclick="tab('exec',document.querySelector('nav button'));pollExec('${e.id}')">abrir</button></td></tr>`).join('')+'</table>'}
 if(TAB==='events'){const ev=await j('/api/v1/dev/events?limit=100');
  document.getElementById('t-events').innerHTML='<table><tr><th>quando</th><th>tipo</th><th>produtor</th><th>payload</th></tr>'+
   ev.slice().reverse().map(e=>`<tr><td>${e.occurred_at.slice(11,19)}</td><td>${e.type}</td><td>${e.producer}</td><td><pre style="max-height:60px;margin:0">${esc(JSON.stringify(e.payload))}</pre></td></tr>`).join('')+'</table>'}
 if(TAB==='logs'){const lg=await j('/api/v1/dev/logs?limit=200');
  document.getElementById('t-logs').innerHTML='<pre style="max-height:70vh">'+esc(lg.slice().reverse().map(l=>JSON.stringify(l)).join('\\n'))+'</pre>'}
 if(TAB==='docs'){const docs=await j('/api/v1/dev/documents');
  document.getElementById('t-docs').innerHTML='<table><tr><th>uri</th><th>estado</th><th>v</th><th></th></tr>'+
   docs.map(d=>`<tr><td>${esc(d.uri)}</td><td class="${d.processing_state==='indexed'?'ok':'fail'}">${d.processing_state}</td><td>${d.version}</td><td><button onclick="inspectDoc('${d.id}')">inspecionar</button> <button onclick="j('/api/v1/dev/documents/${d.id}/reprocess',{method:'POST'}).then(refresh)">reprocessar</button></td></tr>`).join('')+'</table><div id="docdetail"></div>'}
 if(TAB==='graph'){const g=await j('/api/v1/dev/graph');
  document.getElementById('t-graph').innerHTML='<table><tr><th>tipo</th><th>nome</th><th>conf</th><th>vizinhos</th></tr>'+
   g.map(e=>`<tr><td>${e.kind}</td><td>${esc(e.name)}</td><td>${e.confidence}</td><td>${e.neighbors.map(n=>n.rel+'→'+esc(n.name)).join('<br>')}</td></tr>`).join('')+'</table>'}
 if(TAB==='metrics'){document.getElementById('t-metrics').innerHTML='<pre>'+esc(JSON.stringify(await j('/api/v1/dev/metrics'),null,2))+'</pre>'}
 }catch(e){}
}
async function inspectDoc(id){const d=await j('/api/v1/dev/documents/'+id);
 document.getElementById('docdetail').innerHTML=
  `<h3>${esc(d.document.uri)} — v${d.document.version} (${d.document.processing_state})</h3>`+
  '<h4>Timeline</h4><table><tr><th>estágio</th><th>ok</th><th>ms</th><th>mensagem</th></tr>'+
  d.timeline.map(t=>`<tr><td>${t.stage}</td><td class="${t.success?'ok':'fail'}">${t.success}</td><td>${t.duration_ms}</td><td>${esc(t.message)}</td></tr>`).join('')+'</table>'+
  '<div class="grid"><div><h4>Metadados</h4><pre>'+esc(JSON.stringify(d.metadata,null,2))+'</pre>'+
  '<h4>Entidades</h4><pre>'+esc(JSON.stringify(d.entities,null,2))+'</pre>'+
  '<h4>Versões</h4><pre>'+esc(JSON.stringify(d.versions,null,2))+'</pre></div>'+
  '<div><h4>Chunks ('+d.chunks.length+')</h4><pre>'+esc(d.chunks.map((c,i)=>'['+i+'] '+c).join('\\n---\\n'))+'</pre>'+
  '<h4>Texto</h4><pre>'+esc(d.text_preview)+'</pre></div></div>'}
async function doSearch(){const r=await j('/api/v1/dev/search?q='+encodeURIComponent(q.value));
 document.getElementById('searchout').innerHTML='<p>modo: <b>'+esc(r.mode)+'</b></p>'+
  '<table><tr><th>doc</th><th>score RRF</th><th>trecho</th><th>por quê (léxico + vetorial)</th></tr>'+
  r.hits.map(h=>`<tr><td>${esc(h.title||h.uri)}</td><td>${h.score.toFixed(5)}</td><td>${h.snippet}</td><td><small>${esc(h.explanation)}</small></td></tr>`).join('')+'</table>'}
setInterval(()=>{if(document.getElementById('auto').checked&&TAB!=='exec')refresh()},2000);
</script></body></html>"""


# canário anti-truncamento
