/* Risk "Credited" column for every report page (2026-11-28).
   Include on a report page:
     <script src="https://wins-ledger-production.up.railway.app/credit.js" data-brand="pots" defer></script>
   player mode (default): game reports, one row per player; the first text of the first cell is the account.
     The toggle covers that player's wins in the page's From/To range.
   win mode (data-mode="win"): ledger report-brand.html, one row per win, <tr data-id="<win id>">.
   Anyone with the link sees the status; changing it asks for the Risk PIN once per browser. */
(function(){
  const me=document.currentScript;
  const BRAND=me.dataset.brand||location.pathname.split("/").filter(Boolean)[1]||"", MODE=me.dataset.mode||"player";
  const BASE=new URL(me.src).origin;
  const TOKEN=location.pathname.split("/").filter(Boolean).pop();
  const API=BASE+"/api/credit/"+encodeURIComponent(BRAND)+"/"+encodeURIComponent(TOKEN);
  const PIN_KEY="risk-pin";
  let data={players:{},ids:{}}, busy=false;

  const css=document.createElement("style");
  css.textContent=".crb{font:700 12px/1 system-ui,sans-serif;border-radius:999px;padding:6px 11px;cursor:pointer;white-space:nowrap;border:1px solid transparent}"+
    ".crb.yes{background:rgba(73,209,122,.16);color:#49d17a;border-color:rgba(73,209,122,.45)}"+
    ".crb.no{background:rgba(255,255,255,.04);color:#c9c2d6;border-color:rgba(255,255,255,.22)}"+
    ".crb.part{background:rgba(245,184,74,.15);color:#f5b84a;border-color:rgba(245,184,74,.45)}"+
    ".crb:disabled{opacity:.5;cursor:wait}.crnone{color:rgba(255,255,255,.35)}"+
    ".crsum{margin-left:auto;font-size:12.5px;opacity:.85}";
  document.head.appendChild(css);

  const tbody=()=>document.getElementById("tbody");
  const today=()=>new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Manila"});
  const range=()=>{const f=document.getElementById("from"),t=document.getElementById("to");return {from:(f&&f.value)||today(),to:(t&&t.value)||today()}};
  const pin=()=>{try{return localStorage.getItem(PIN_KEY)||""}catch(e){return ""}};
  const setPin=v=>{try{v?localStorage.setItem(PIN_KEY,v):localStorage.removeItem(PIN_KEY)}catch(e){}};

  function header(){
    const tr=document.querySelector("#tbody")?.closest("table")?.querySelector("thead tr");
    if(tr&&!tr.querySelector(".crh")){const th=document.createElement("th");th.className="crh";th.textContent="Credited (Risk)";tr.appendChild(th)}
  }
  function keyOf(tr){
    if(MODE==="win")return tr.dataset.id||"";
    const td=tr.cells[0];if(!td)return "";
    const n=td.firstChild;return ((n&&n.nodeType===3?n.nodeValue:td.textContent)||"").trim().toLowerCase();
  }
  function cellFor(tr){
    let td=tr.querySelector("td.crc");
    if(!td){td=document.createElement("td");td.className="crc";tr.appendChild(td)}
    return td;
  }
  function decorate(){
    header();
    const tb=tbody();if(!tb)return;
    let done=0,tot=0;
    for(const tr of tb.rows){
      const k=keyOf(tr),td=cellFor(tr);
      let st=null;
      if(MODE==="win"){const d=data.ids[k];if(d!==undefined)st={wins:1,done:d?1:0}}
      else st=data.players[k]||null;
      let html;
      if(!st||!st.wins){html="<span class='crnone'>—</span>"}
      else{
        tot++;
        if(st.done>=st.wins){done++;html="<button class='crb yes' data-k='"+encodeURIComponent(k)+"' data-v='0' title='Click to mark NOT credited'>✓ Credited</button>"}
        else if(st.done>0)html="<button class='crb part' data-k='"+encodeURIComponent(k)+"' data-v='1' title='Some wins credited — click to credit all'>Partial "+st.done+"/"+st.wins+"</button>";
        else html="<button class='crb no' data-k='"+encodeURIComponent(k)+"' data-v='1' title='Click to mark credited'>Not yet</button>";
      }
      if(td.innerHTML!==html)td.innerHTML=html;
    }
    const totals=document.getElementById("totals");
    if(totals&&!totals.hidden){
      let s=totals.querySelector(".crsum");
      if(!s){s=document.createElement("span");s.className="crsum";totals.appendChild(s)}
      const txt=tot?("Credited: "+done+"/"+tot+(MODE==="win"?" wins":" players")):"";
      if(s.textContent!==txt)s.textContent=txt;
    }
  }
  async function refresh(){
    const r=range();
    try{
      const res=await fetch(API+"?from="+encodeURIComponent(r.from)+"&to="+encodeURIComponent(r.to));
      if(!res.ok)return;
      data=await res.json();decorate();
    }catch(e){}
  }
  async function toggle(btn){
    if(busy)return;
    let p=pin();
    if(!p){p=(prompt("Risk PIN (para ma-mark ang credited):")||"").trim();if(!p)return}
    const k=decodeURIComponent(btn.dataset.k),credited=btn.dataset.v==="1",r=range();
    const body=MODE==="win"?{pin:p,credited,ids:[Number(k)]}:{pin:p,credited,player:k,from:r.from,to:r.to};
    busy=true;btn.disabled=true;
    try{
      const res=await fetch(API,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(res.status===403){setPin("");alert("Mali ang Risk PIN.");return}
      if(!res.ok){alert("Hindi na-save. Subukan ulit.");return}
      setPin(p);
    }catch(e){alert("Connection error. Subukan ulit.")}
    finally{busy=false;btn.disabled=false}
    await refresh();
  }

  function start(){
    const tb=tbody();if(!tb)return setTimeout(start,300);
    new MutationObserver(decorate).observe(tb,{childList:true});
    tb.addEventListener("click",e=>{const b=e.target.closest("button.crb");if(b)toggle(b)});
    ["loadBtn","todayBtn"].forEach(id=>{const b=document.getElementById(id);if(b)b.addEventListener("click",()=>setTimeout(refresh,50))});
    ["from","to"].forEach(id=>{const i=document.getElementById(id);if(i)i.addEventListener("change",()=>setTimeout(refresh,50))});
    refresh();setInterval(refresh,30000);
  }
  document.readyState==="loading"?document.addEventListener("DOMContentLoaded",start):start();
})();
