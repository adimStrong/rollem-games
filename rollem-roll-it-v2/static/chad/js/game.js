const $=id=>document.getElementById(id),cv=$('c'),x=cv.getContext('2d'),W=480,H=620,reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
const lerp=(a,b,k)=>a+(b-a)*k,ease=k=>k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function shade(hex,amt){const n=parseInt(hex.slice(1),16),c=v=>Math.max(0,Math.min(255,v));return`rgb(${c((n>>16)+amt)},${c((n>>8&255)+amt)},${c((n&255)+amt)})`}
// face cut-outs: crop box (head + neck) in each photo's pixels; heads[i] for each of the 5 holes
// face cut-outs, one per Chad photo (face-02, 03, 04 and 06 are the bald ones used in play)
const PF=[1,2,3,4,5,6,7].map(n=>'assets/faces/face-0'+n+'.webp');
const SKIN=["#b88b75", "#b77e74", "#81503e", "#bc8474", "#d4716a", "#a3614f", "#976052"];
const PHOTOS=SKIN.map((sk,i)=>({src:PF[i],skin:sk}));
PHOTOS.forEach(p=>{p.img=new Image();p.img.src=p.src});
const BALD=[1,2,3,5],HEADS=[1,2,3,5,1,2,3,5,1];
const HAND=new Image();HAND.src='assets/hand.webp';

// ---------------- sound ----------------
let AC=null,soundOn=true;
function ac(){if(!AC){try{AC=new(window.AudioContext||window.webkitAudioContext)()}catch(e){}}if(AC&&AC.state==='suspended')AC.resume();return AC}
function nbuf(a,d){const b=a.createBuffer(1,a.sampleRate*d|0,a.sampleRate),c=b.getChannelData(0);for(let i=0;i<c.length;i++)c[i]=Math.random()*2-1;return b}
function sfx(kind,k=1){if(!soundOn)return;const a=ac();if(!a)return;const n=a.currentTime,out=a.createGain();out.gain.value=.7;out.connect(a.destination);
  const env=(node,peak,att,dec)=>{const g=a.createGain();g.gain.setValueAtTime(.0001,n);g.gain.linearRampToValueAtTime(peak,n+att);g.gain.exponentialRampToValueAtTime(.0001,n+att+dec);node.connect(g);g.connect(out);return g};
  const noise=(d,type,f,q)=>{const s=a.createBufferSource();s.buffer=nbuf(a,d);const fl=a.createBiquadFilter();fl.type=type;fl.frequency.value=f;fl.Q.value=q;s.connect(fl);s.start(n);return fl};
  const osc=(type,f0,f1,dur,peak)=>{const o=a.createOscillator();o.type=type;o.frequency.setValueAtTime(f0,n);o.frequency.exponentialRampToValueAtTime(f1,n+dur);env(o,peak,.003,dur);o.start(n);o.stop(n+dur+.05)};
  if(kind==='slap'){env(noise(.3,'bandpass',1700+k*500,.8),1.3*k,.002,.1+k*.06);env(noise(.1,'highpass',3500,.5),.6*k,.001,.04);osc('sine',190,45,.18,.9*k)}
  if(kind==='pop'){osc('sine',260,720,.12,.18)}
  if(kind==='bonk'){osc('triangle',520,140,.25,.5);env(noise(.2,'lowpass',600,1),.6,.002,.15)}
  if(kind==='boom'){osc('sine',120,30,.6,1.2);env(noise(1,'lowpass',900,.7),1.2,.002,.8)}
  if(kind==='miss'){osc('triangle',300,180,.12,.15)}
  if(kind==='coin'){osc('square',988,988,.07,.12);setTimeout(()=>sfx('coin2'),70)}
  if(kind==='coin2'){osc('square',1319,1319,.18,.12)}
  if(kind==='ding'){[1318,1976,2637].forEach((f,i)=>osc('sine',f,f*.99,1.2,.22/(i+1)))}
  if(kind==='buzz'){osc('sawtooth',140,120,.5,.25)}
  if(kind==='crowd'){env(noise(1.6,'lowpass',650,1),.5,.25,1.2);env(noise(1.6,'bandpass',1100,4),.18,.3,1)}}

// ---------------- night carnival backdrop, painted once ----------------
let BG;
function fit(){const d=Math.min(2,devicePixelRatio||1);cv.width=W*d;cv.height=H*d;x.setTransform(d,0,0,d,0,0)}
function paintBG(d){const c=document.createElement('canvas');c.width=W*d;c.height=H*d;const g=c.getContext('2d');g.setTransform(d,0,0,d,0,0);
  let r=0x9e3779b9;const rnd=()=>((r=Math.imul(r^r>>>15,2246822507)^Math.imul(r^r>>>13,3266489909))>>>0)/4294967296;
  let gr=g.createLinearGradient(0,0,0,360);gr.addColorStop(0,'#120a33');gr.addColorStop(.6,'#3a1a5e');gr.addColorStop(1,'#6a2a62');g.fillStyle=gr;g.fillRect(0,0,W,H);
  for(let i=0;i<70;i++){g.fillStyle=`rgba(255,255,255,${.3+rnd()*.6})`;g.fillRect(rnd()*W,rnd()*200,1.4,1.4)}
  // ferris wheel
  const fx=120,fy=150,fr=96;g.strokeStyle='#2a1640';g.lineWidth=6;g.beginPath();g.moveTo(fx-50,330);g.lineTo(fx,fy);g.lineTo(fx+50,330);g.stroke();
  g.strokeStyle='rgba(255,210,120,.45)';g.lineWidth=2;g.beginPath();g.arc(fx,fy,fr,0,7);g.stroke();g.beginPath();g.arc(fx,fy,fr*.55,0,7);g.stroke();
  for(let i=0;i<16;i++){const a=i/16*6.283;g.beginPath();g.moveTo(fx,fy);g.lineTo(fx+Math.cos(a)*fr,fy+Math.sin(a)*fr);g.stroke()}
  for(let i=0;i<8;i++){const a=i/8*6.283;g.fillStyle=['#ff4f6d','#2fd3c4','#ffcc33','#9b6bff'][i%4];g.fillRect(fx+Math.cos(a)*fr-7,fy+Math.sin(a)*fr+2,14,11)}
  // striped tents
  [[330,250,90,'#e2343f'],[430,270,70,'#2f6de2'],[250,285,60,'#e2a52f']].forEach(([tx,ty,tw,col])=>{for(let i=0;i<8;i++){g.fillStyle=i%2?'#fff3e0':col;g.beginPath();g.moveTo(tx,ty-tw*.8);g.lineTo(tx-tw+i*tw/4,ty);g.lineTo(tx-tw+(i+1)*tw/4,ty);g.fill()}
    g.fillStyle=col;g.fillRect(tx-tw*.9,ty,tw*1.8,40);g.fillStyle='#ffcc33';g.beginPath();g.arc(tx,ty-tw*.8-6,5,0,7);g.fill()});
  gr=g.createLinearGradient(0,280,0,360);gr.addColorStop(0,'rgba(20,8,40,0)');gr.addColorStop(1,'rgba(20,8,40,.9)');g.fillStyle=gr;g.fillRect(0,280,W,80);
  // booth: back wall with stripes and prize shelf
  for(let i=0;i<12;i++){g.fillStyle=i%2?'#c9283a':'#f4e3c3';g.fillRect(40+i*33.4,150,33.4,215)}
  gr=g.createLinearGradient(0,150,0,365);gr.addColorStop(0,'rgba(0,0,0,.35)');gr.addColorStop(1,'rgba(0,0,0,.1)');g.fillStyle=gr;g.fillRect(40,150,400,215);
  g.fillStyle='#6b3d1d';g.fillRect(40,262,400,10);g.fillStyle='#8a5228';g.fillRect(40,258,400,5);
  const toy=(px,py,col,sc)=>{g.fillStyle=col;g.beginPath();g.arc(px,py-22*sc,16*sc,0,7);g.fill();g.beginPath();g.arc(px-12*sc,py-36*sc,6*sc,0,7);g.arc(px+12*sc,py-36*sc,6*sc,0,7);g.fill();
    g.beginPath();g.ellipse(px,py-2*sc,17*sc,13*sc,0,0,7);g.fill();g.fillStyle='#111';g.beginPath();g.arc(px-5*sc,py-24*sc,2*sc,0,7);g.arc(px+5*sc,py-24*sc,2*sc,0,7);g.fill();
    g.fillStyle=shade(col,40);g.beginPath();g.ellipse(px,py-17*sc,6*sc,4*sc,0,0,7);g.fill()};
  ['#ff8fb1','#7fd3ff','#ffd56b','#a98bff','#8fe08a','#ff9b5a','#ffffff'].forEach((col,i)=>toy(70+i*56,258,col,.9+(i%3)*.12));
  // marquee header with bulbs
  gr=g.createLinearGradient(0,60,0,150);gr.addColorStop(0,'#e2343f');gr.addColorStop(1,'#8f1424');g.fillStyle=gr;g.beginPath();g.roundRect(26,64,428,88,16);g.fill();
  g.strokeStyle='#ffcc33';g.lineWidth=5;g.beginPath();g.roundRect(32,70,416,76,12);g.stroke();
  // wooden posts
  [[14,'#7a4a22'],[438,'#7a4a22']].forEach(([px,col])=>{gr=g.createLinearGradient(px,0,px+28,0);gr.addColorStop(0,'#5a3416');gr.addColorStop(.5,'#9a6232');gr.addColorStop(1,'#4a2a12');g.fillStyle=gr;g.fillRect(px,60,28,560)});
  // counter: wooden top in perspective with felt inlay
  g.fillStyle='#4a2410';g.beginPath();g.moveTo(28,352);g.lineTo(452,352);g.lineTo(480,620);g.lineTo(0,620);g.fill();
  gr=g.createLinearGradient(0,352,0,620);gr.addColorStop(0,'#b5763a');gr.addColorStop(1,'#7a4620');g.fillStyle=gr;g.beginPath();g.moveTo(36,360);g.lineTo(444,360);g.lineTo(472,620);g.lineTo(8,620);g.fill();
  g.strokeStyle='rgba(60,25,8,.35)';g.lineWidth=1.2;for(let i=0;i<9;i++){const t=i/8;g.beginPath();g.moveTo(36+t*408,360);g.lineTo(8+t*464,620);g.stroke()}
  for(let i=0;i<60;i++){g.strokeStyle='rgba(255,220,170,.08)';const yy=365+rnd()*250;g.beginPath();g.moveTo(20,yy);g.lineTo(460,yy+rnd()*6-3);g.stroke()}
  gr=g.createLinearGradient(0,372,0,600);gr.addColorStop(0,'#1d7a4a');gr.addColorStop(1,'#0f4a2c');g.fillStyle=gr;g.beginPath();g.moveTo(62,376);g.lineTo(418,376);g.lineTo(446,604);g.lineTo(34,604);g.fill();
  g.strokeStyle='#ffcc33';g.lineWidth=3;g.stroke();
  g.fillStyle='#ffcc33';g.fillRect(28,350,424,6);
  gr=g.createRadialGradient(W/2,H*.6,H*.3,W/2,H*.6,H*.8);gr.addColorStop(0,'rgba(0,0,0,0)');gr.addColorStop(1,'rgba(10,0,20,.5)');g.fillStyle=gr;g.fillRect(0,0,W,H);
  return c}

// ---------------- holes and the heads that pop out ----------------
// ---------------- 3D carnival booth (three.js), drawn behind the 2D heads ----------------
const BGSRC='assets/bets-bg.webp';
document.body.style.background=`linear-gradient(rgba(25,10,45,.25),rgba(25,10,45,.55)),url(${BGSRC}) center/cover fixed`;
const G3={};
(()=>{const V=THREE.Vector3,cvs=document.getElementById('g3');
  const MOBILE=matchMedia('(pointer: coarse)').matches||Math.min(screen.width,screen.height)<700;
  const R=new THREE.WebGLRenderer({canvas:cvs,antialias:!MOBILE,alpha:false,powerPreference:'high-performance'});R.setPixelRatio(MOBILE?Math.min(devicePixelRatio||1,1.25):Math.min(devicePixelRatio||1,2));R.shadowMap.enabled=true;R.shadowMap.type=THREE.PCFSoftShadowMap;
  R.outputEncoding=THREE.sRGBEncoding;R.toneMapping=THREE.ACESFilmicToneMapping;R.toneMappingExposure=1.1;
  const sc=new THREE.Scene();sc.background=new THREE.Color('#120a2e');sc.fog=new THREE.Fog('#1a0d3a',9,30);
  const cam=new THREE.PerspectiveCamera(40,W/H,.1,80);const CAM=new V(0,3.6,6.4),LOOK=new V(0,2.05,-1.6);cam.position.copy(CAM);cam.lookAt(LOOK);
  const M=(c,o={})=>new THREE.MeshStandardMaterial(Object.assign({color:new THREE.Color(c).convertSRGBToLinear(),roughness:.7,metalness:0},o));
  const E=(c,i=1)=>new THREE.MeshStandardMaterial({color:new THREE.Color(c).convertSRGBToLinear(),emissive:new THREE.Color(c).convertSRGBToLinear(),emissiveIntensity:i,roughness:.4});
  const add=(geo,mat,x,y,z,par)=>{const m=new THREE.Mesh(geo,mat);m.position.set(x,y,z);m.castShadow=m.receiveShadow=true;(par||sc).add(m);return m};
  const tex=(w,h,fn)=>{const c=document.createElement('canvas');c.width=w;c.height=h;fn(c.getContext('2d'),w,h);const t=new THREE.CanvasTexture(c);t.encoding=THREE.sRGBEncoding;t.anisotropy=4;return t};
  // lights
  sc.add(new THREE.HemisphereLight(new THREE.Color('#8a7ad0'),new THREE.Color('#2a1206'),.55));
  const key=new THREE.SpotLight('#ffe7c0',2.2,14,.75,.5,1.2);key.position.set(0,4.6,2.6);key.target.position.set(0,.9,-.4);key.castShadow=true;key.shadow.mapSize.set(MOBILE?512:1024,MOBILE?512:1024);key.shadow.bias=-.0005;sc.add(key,key.target);
  const warm1=new THREE.PointLight('#ff9a4a',1.2,6,2);warm1.position.set(-2,2.4,.6);const warm2=new THREE.PointLight('#ff4f8a',1,6,2);warm2.position.set(2,2.4,.6);sc.add(warm1,warm2);
  // ground and night sky
  add(new THREE.PlaneGeometry(80,80),M('#1d1430',{roughness:.95}),0,0,0).rotation.x=-Math.PI/2;
  const sg=new THREE.BufferGeometry(),sp=[];for(let i=0;i<600;i++){const a=Math.random()*Math.PI,b=Math.random()*Math.PI*.42;sp.push(Math.cos(a)*30*Math.cos(b),4+Math.sin(b)*22,-Math.sin(a)*30*Math.cos(b)-4)}
  sg.setAttribute('position',new THREE.Float32BufferAttribute(sp,3));sc.add(new THREE.Points(sg,new THREE.PointsMaterial({color:'#ffffff',size:.07,sizeAttenuation:true})));
  // ferris wheel far behind the booth
  const fw=new THREE.Group();fw.position.set(-3.2,5.2,-11);sc.add(fw);const rimM=E('#ffcf6a',.9);
  [3.6,2.1].forEach(r=>{const t=new THREE.Mesh(new THREE.TorusGeometry(r,.05,8,64),rimM);fw.add(t)});
  for(let i=0;i<16;i++){const s=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,3.6,5),rimM);s.position.set(Math.cos(i/16*6.283)*1.8,Math.sin(i/16*6.283)*1.8,0);s.rotation.z=i/16*6.283+Math.PI/2;fw.add(s)}
  const gond=[];['#ff4f6d','#2fd3c4','#ffcc33','#9b6bff','#ff8a1f','#5fd35f','#ff4f6d','#2fd3c4'].forEach((c,i)=>{const g=add(new THREE.BoxGeometry(.5,.42,.4),E(c,.55),0,0,0);gond.push({g,a:i/8*6.283})});
  const leg=M('#2b1d40');[[-1.7,1],[1.7,-1]].forEach(([dx,s])=>{const l=add(new THREE.CylinderGeometry(.09,.12,5.6,8),leg,-3.2+dx*.9,2.6,-11);l.rotation.z=s*.32});
  // striped tents
  [[3.6,-7,1.7,'#e2343f'],[6.2,-9,1.3,'#2f6de2'],[-6.5,-8,1.4,'#e2a52f']].forEach(([tx,tz,r,c])=>{const t2=tex(256,64,(g,w,h)=>{for(let i=0;i<8;i++){g.fillStyle=i%2?'#fff1dc':c;g.fillRect(i*w/8,0,w/8,h)}});
    const roof=add(new THREE.ConeGeometry(r,r*1.1,16,1,true),new THREE.MeshStandardMaterial({map:t2,side:THREE.DoubleSide,roughness:.8}),tx,1.6+r*.55,tz);
    add(new THREE.CylinderGeometry(r*.94,r*.94,1.6,16),new THREE.MeshStandardMaterial({map:t2,roughness:.8}),tx,.8,tz);
    add(new THREE.SphereGeometry(.1,10,8),E('#ffcf33',1),tx,1.6+r*1.12,tz)});
  // booth back wall: red/white stripes
  const wallT=tex(512,256,(g,w,h)=>{for(let i=0;i<12;i++){g.fillStyle=i%2?'#c9283a':'#f4e3c3';g.fillRect(i*w/12,0,w/12,h)}const gr=g.createLinearGradient(0,0,0,h);gr.addColorStop(0,'rgba(0,0,0,.35)');gr.addColorStop(1,'rgba(0,0,0,.05)');g.fillStyle=gr;g.fillRect(0,0,w,h)});
  add(new THREE.BoxGeometry(3.3,1.6,.08),new THREE.MeshStandardMaterial({map:wallT,roughness:.85}),0,1.85,-1.35);
  // prize shelf with plush toys
  const wood=M('#8a5228',{roughness:.6});add(new THREE.BoxGeometry(3.2,.06,.32),wood,0,1.72,-1.18);
  ['#ff8fb1','#7fd3ff','#ffd56b','#a98bff','#8fe08a','#ff9b5a','#ffffff'].forEach((c,i)=>{const g=new THREE.Group();g.position.set(-1.32+i*.44,1.75,-1.16);sc.add(g);const m=M(c,{roughness:.95});
    add(new THREE.SphereGeometry(.12,16,12),m,0,.12,0,g).scale.set(1,.9,.85);add(new THREE.SphereGeometry(.1,16,12),m,0,.3,0,g);
    add(new THREE.SphereGeometry(.04,8,6),m,-.07,.38,0,g);add(new THREE.SphereGeometry(.04,8,6),m,.07,.38,0,g);
    add(new THREE.SphereGeometry(.014,6,6),M('#111'),-.035,.32,.09,g);add(new THREE.SphereGeometry(.014,6,6),M('#111'),.035,.32,.09,g);G3['toy'+i]=g});
  // posts
  const postM=M('#7a4a22',{roughness:.55});[-1.68,1.68].forEach(px=>{add(new THREE.BoxGeometry(.16,3.2,.16),postM,px,1.6,-1.25);add(new THREE.BoxGeometry(.2,.12,.2),M('#ffcc33',{metalness:.6,roughness:.3}),px,3.2,-1.25)});
  // marquee sign with lit title and chasing bulbs
  const signT=tex(1024,256,(g,w,h)=>{const gr=g.createLinearGradient(0,0,0,h);gr.addColorStop(0,'#e2343f');gr.addColorStop(1,'#8f1424');g.fillStyle=gr;g.fillRect(0,0,w,h);
    g.strokeStyle='#ffcc33';g.lineWidth=12;g.strokeRect(14,14,w-28,h-28);g.font='140px "Lilita One", Impact, sans-serif';g.textAlign='center';g.textBaseline='middle';
    g.lineWidth=16;g.strokeStyle='#5a0a14';g.strokeText('CHAD SMASH',w/2,h/2+8);const tg=g.createLinearGradient(0,60,0,200);tg.addColorStop(0,'#fff3a0');tg.addColorStop(1,'#ffb21f');g.fillStyle=tg;g.fillText('CHAD SMASH',w/2,h/2+8)});
  G3.signT=signT;add(new THREE.BoxGeometry(3.45,.78,.14),[M('#8f1424'),M('#8f1424'),M('#8f1424'),M('#8f1424'),new THREE.MeshStandardMaterial({map:signT,emissive:new THREE.Color('#ffffff'),emissiveMap:signT,emissiveIntensity:.55,roughness:.5}),M('#8f1424')],0,3.0,-1.22);
  const bulbs=[];for(let i=0;i<22;i++)for(const by of [2.64,3.36]){const b=add(new THREE.SphereGeometry(.035,8,6),E('#fff2b0',1.4),-1.62+i*3.24/21,by,-1.13);bulbs.push({b,i})}
  for(const bx of [-1.66,1.66])for(let k=1;k<4;k++){const b=add(new THREE.SphereGeometry(.035,8,6),E('#fff2b0',1.4),bx,2.64+k*.18,-1.13);bulbs.push({b,i:k*3})}
  // string lights across the top
  const strP=[];const lights=[];for(let i=0;i<=40;i++){const u=i/40,px=-2.4+u*4.8,py=3.95-Math.sin(u*Math.PI)*.35;strP.push(new V(px,py,-.6));if(i%3===1){const l=add(new THREE.SphereGeometry(.05,8,6),E(['#ff4f6d','#ffcc33','#2fd3c4','#9b6bff'][(i/3|0)%4],1.6),px,py-.07,-.6);lights.push({l,i})}}
  sc.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(strP),new THREE.LineBasicMaterial({color:'#2a1640'})));
  // counter: wooden body, green felt top, gold trim
  const woodT=tex(512,256,(g,w,h)=>{g.fillStyle='#9a5e2c';g.fillRect(0,0,w,h);for(let i=0;i<70;i++){g.strokeStyle=`rgba(${60+Math.random()*40|0},30,10,${.15+Math.random()*.2})`;g.lineWidth=1+Math.random()*2;const y=Math.random()*h;g.beginPath();g.moveTo(0,y);g.bezierCurveTo(w*.3,y+6,w*.6,y-6,w,y+3);g.stroke()}
    for(let i=0;i<8;i++){g.fillStyle='rgba(40,20,5,.5)';g.fillRect(i*w/8,0,3,h)}});
  add(new THREE.BoxGeometry(3.4,.9,2.2),new THREE.MeshStandardMaterial({map:woodT,roughness:.6}),0,.45,.15);
  const feltT=tex(512,512,(g,w,h)=>{const gr=g.createRadialGradient(w/2,h/2,40,w/2,h/2,w*.7);gr.addColorStop(0,'#24945a');gr.addColorStop(1,'#0f4a2c');g.fillStyle=gr;g.fillRect(0,0,w,h);
    for(let i=0;i<9000;i++){g.fillStyle=Math.random()<.5?'rgba(0,0,0,.08)':'rgba(255,255,255,.05)';g.fillRect(Math.random()*w,Math.random()*h,1.5,1.5)}});
  add(new THREE.BoxGeometry(3.1,.03,1.95),new THREE.MeshStandardMaterial({map:feltT,roughness:.95}),0,.915,.17);
  const gold=M('#ffc83a',{metalness:.7,roughness:.3});add(new THREE.BoxGeometry(3.46,.05,.06),gold,0,.92,1.26);add(new THREE.BoxGeometry(3.46,.05,.06),gold,0,.92,-.94);
  add(new THREE.BoxGeometry(.06,.05,2.2),gold,-1.71,.92,.16);add(new THREE.BoxGeometry(.06,.05,2.2),gold,1.71,.92,.16);
  // soft bokeh lights drifting in the far background
  const bok=tex(64,64,(g,w,h)=>{const gr=g.createRadialGradient(32,32,2,32,32,32);gr.addColorStop(0,'rgba(255,255,255,1)');gr.addColorStop(.4,'rgba(255,255,255,.55)');gr.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=gr;g.fillRect(0,0,64,64)});
  const bg2=new THREE.BufferGeometry(),bp=[],bc=[],pal=['#ff4f6d','#ffcc33','#2fd3c4','#9b6bff','#ff8a1f','#ffffff'].map(c=>new THREE.Color(c));
  for(let i=0;i<70;i++){bp.push((Math.random()-.5)*26,1+Math.random()*7,-6-Math.random()*10);const c=pal[i%pal.length];bc.push(c.r,c.g,c.b)}
  bg2.setAttribute('position',new THREE.Float32BufferAttribute(bp,3));bg2.setAttribute('color',new THREE.Float32BufferAttribute(bc,3));
  const bokeh=new THREE.Points(bg2,new THREE.PointsMaterial({size:.9,map:bok,vertexColors:true,transparent:true,opacity:.55,depthWrite:false,blending:THREE.AdditiveBlending}));sc.add(bokeh);G3.bokeh=bokeh;
  // side walls of the booth with stripes and gold trim
  [-1,1].forEach(s=>{const w2=add(new THREE.BoxGeometry(.06,1.6,1.1),new THREE.MeshStandardMaterial({map:wallT,roughness:.85}),s*1.62,1.85,-.82);
    add(new THREE.BoxGeometry(.08,.06,1.12),M('#ffc83a',{metalness:.7,roughness:.3}),s*1.62,2.66,-.82)});
  // scalloped awning under the sign
  const awn=new THREE.Group();awn.position.set(0,2.52,-1.05);sc.add(awn);
  for(let i=0;i<14;i++){const sx=-1.55+i*3.1/13,m=new THREE.Mesh(new THREE.CircleGeometry(.12,16,Math.PI,Math.PI),new THREE.MeshStandardMaterial({color:new THREE.Color(i%2?'#f4e3c3':'#d42a3c').convertSRGBToLinear(),side:THREE.DoubleSide,roughness:.8}));
    m.position.set(sx,0,0);awn.add(m)}
  add(new THREE.BoxGeometry(3.3,.1,.18),M('#d42a3c',{roughness:.8}),0,2.57,-1.06);
  // banderitas between the posts and the corners
  const bandC=['#ff4f6d','#ffcc33','#2fd3c4','#9b6bff','#ff8a1f','#5fd35f'],tri=new THREE.BufferGeometry();tri.setAttribute('position',new THREE.Float32BufferAttribute([-.07,0,0,.07,0,0,0,-.16,0],3));tri.computeVertexNormals();
  const flags=[];[[[-2.6,2.62,-.2],[2.6,2.62,-.2],.18],[[-2.8,2.95,.2],[-1.7,3.3,-1.2],.12],[[2.8,2.95,.2],[1.7,3.3,-1.2],.12]].forEach(([A,B,sag],li)=>{const pts=[];const n=li?8:26;
    for(let i=0;i<=n;i++){const u=i/n,px=A[0]+(B[0]-A[0])*u,py=A[1]+(B[1]-A[1])*u-Math.sin(u*Math.PI)*sag,pz=A[2]+(B[2]-A[2])*u;pts.push(new V(px,py,pz));
      if(i&&i<n){const f=new THREE.Mesh(tri,new THREE.MeshStandardMaterial({color:new THREE.Color(bandC[i%6]).convertSRGBToLinear(),side:THREE.DoubleSide,roughness:.7,emissive:new THREE.Color(bandC[i%6]).convertSRGBToLinear(),emissiveIntensity:.15}));f.position.set(px,py,pz);sc.add(f);flags.push({f,i})}}
    sc.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:'#3a2a20'})))});G3.flags=flags;
  // glowing parol star lanterns hanging beside the booth
  const star=new THREE.Shape();for(let i=0;i<10;i++){const a=i/10*Math.PI*2-Math.PI/2,rr=i%2?.09:.22;i?star.lineTo(Math.cos(a)*rr,-Math.sin(a)*rr):star.moveTo(Math.cos(a)*rr,-Math.sin(a)*rr)}
  const sgeo=new THREE.ExtrudeGeometry(star,{depth:.05,bevelEnabled:true,bevelSize:.015,bevelThickness:.015,bevelSegments:1});
  const parols=[];[[-2.25,2.75,-.5,'#ff4f6d'],[2.25,2.75,-.5,'#2fd3c4'],[-2.9,3.6,-2.5,'#ffcc33'],[2.9,3.6,-2.5,'#9b6bff']].forEach(([px,py,pz,c])=>{const m=new THREE.Mesh(sgeo,E(c,1.3));m.position.set(px,py,pz);sc.add(m);
    const tail=new THREE.Mesh(new THREE.CylinderGeometry(.005,.005,.5,4),M('#ddd'));tail.position.set(px,py+.42,pz);sc.add(tail);
    for(let k=0;k<2;k++){const tt=new THREE.Mesh(new THREE.BoxGeometry(.03,.32,.005),E(c,.8));tt.position.set(px+(k?.05:-.05),py-.32,pz);sc.add(tt)}
    const pl=new THREE.PointLight(c,.8,2.6,2);pl.position.set(px,py,pz+.15);sc.add(pl);parols.push({m,ph:px})});G3.parols=parols;
  // lamp posts on the fairground
  [[-3.6,-2.2],[3.6,-2.2]].forEach(([px,pz])=>{add(new THREE.CylinderGeometry(.05,.07,3.4,8),M('#2a2a32',{metalness:.6,roughness:.4}),px,1.7,pz);
    add(new THREE.SphereGeometry(.18,16,12),E('#fff1c8',1.6),px,3.5,pz);const l=new THREE.PointLight('#ffd9a0',.9,5,2);l.position.set(px,3.4,pz);sc.add(l)});
  // tiny confetti scattered on the felt
  const cg=new THREE.BufferGeometry(),cp=[],cc=[];for(let i=0;i<220;i++){cp.push((Math.random()-.5)*3,.935,.17+(Math.random()-.5)*1.9);const c=pal[i%pal.length];cc.push(c.r,c.g,c.b)}
  cg.setAttribute('position',new THREE.Float32BufferAttribute(cp,3));cg.setAttribute('color',new THREE.Float32BufferAttribute(cc,3));sc.add(new THREE.Points(cg,new THREE.PointsMaterial({size:.03,vertexColors:true})));
  // deeper fairground: carousel, more tents, crowd, moon and fireworks, all in a group that drifts with the pointer for depth
  const far=new THREE.Group();sc.add(far);G3.far=far;
  const moon=new THREE.Mesh(new THREE.SphereGeometry(1.1,24,16),E('#fff4d6',1.1));moon.position.set(7,11,-22);far.add(moon);
  const mh=new THREE.Sprite(new THREE.SpriteMaterial({map:bok,color:'#fff0c0',transparent:true,opacity:.45,blending:THREE.AdditiveBlending,depthWrite:false}));mh.position.copy(moon.position);mh.scale.setScalar(6);far.add(mh);
  // carousel
  const car=new THREE.Group();car.position.set(4.6,0,-8.5);far.add(car);G3.car=car;
  const roofT=tex(256,64,(g,w,h)=>{for(let i=0;i<12;i++){g.fillStyle=i%2?'#fff1dc':'#2fa6ff';g.fillRect(i*w/12,0,w/12,h)}});
  const croof=new THREE.Mesh(new THREE.ConeGeometry(2,1,24,1,true),new THREE.MeshStandardMaterial({map:roofT,side:THREE.DoubleSide,roughness:.7}));croof.position.y=3.1;car.add(croof);
  const cbase=new THREE.Mesh(new THREE.CylinderGeometry(2,2,.25,32),M('#c9283a'));cbase.position.y=.15;car.add(cbase);
  const ctop=new THREE.Mesh(new THREE.CylinderGeometry(2,2,.3,32,1,true),E('#ffcc33',.35));ctop.position.y=2.55;car.add(ctop);
  const pole=new THREE.Mesh(new THREE.CylinderGeometry(.18,.18,2.6,12),M('#ffcc33',{metalness:.6,roughness:.3}));pole.position.y=1.4;car.add(pole);
  const spin=new THREE.Group();car.add(spin);G3.spin=spin;const horses=[];
  for(let i=0;i<8;i++){const a=i/8*Math.PI*2,g=new THREE.Group();g.position.set(Math.cos(a)*1.45,1,Math.sin(a)*1.45);g.rotation.y=-a;spin.add(g);
    const rod=new THREE.Mesh(new THREE.CylinderGeometry(.025,.025,2.2,6),M('#ffd56b',{metalness:.7,roughness:.3}));rod.position.y=.4;g.add(rod);
    const hc=['#ffffff','#ff8fb1','#7fd3ff','#ffd56b'][i%4],hm=M(hc,{roughness:.5});const hb=new THREE.Mesh(new THREE.SphereGeometry(.24,12,10),hm);hb.scale.set(1.5,.75,.6);g.add(hb);
    const hd=new THREE.Mesh(new THREE.SphereGeometry(.13,10,8),hm);hd.position.set(.36,.22,0);hd.scale.set(1.3,.9,.7);g.add(hd);horses.push({g,ph:i})}
  G3.horses=horses;for(let k=0;k<24;k++){const a=k/24*Math.PI*2,b=new THREE.Mesh(new THREE.SphereGeometry(.05,6,5),E('#fff2b0',1.6));b.position.set(Math.cos(a)*2.02,2.55,Math.sin(a)*2.02);car.add(b)}
  // more tents further back
  [[-9,-14,2.2,'#9b6bff'],[0,-17,2.6,'#e2343f'],[9,-15,2,'#1fa86b'],[-4,-12,1.5,'#ff8a1f']].forEach(([tx,tz,rr,cc])=>{const t2=tex(256,64,(g,w,h)=>{for(let i=0;i<8;i++){g.fillStyle=i%2?'#fff1dc':cc;g.fillRect(i*w/8,0,w/8,h)}});
    const rf=new THREE.Mesh(new THREE.ConeGeometry(rr,rr*1.1,16,1,true),new THREE.MeshStandardMaterial({map:t2,side:THREE.DoubleSide,roughness:.8}));rf.position.set(tx,1.8+rr*.55,tz);far.add(rf);
    const wl=new THREE.Mesh(new THREE.CylinderGeometry(rr*.94,rr*.94,1.8,16),new THREE.MeshStandardMaterial({map:t2,roughness:.8}));wl.position.set(tx,.9,tz);far.add(wl);
    const fl=new THREE.Mesh(new THREE.ConeGeometry(.12,.3,4),E(cc,.8));fl.position.set(tx,1.8+rr*1.15,tz);far.add(fl)});
  // string of lanterns across the sky
  for(let s=0;s<2;s++){const pts=[];for(let i=0;i<=40;i++){const u=i/40,px=-12+u*24,py=6.5+s*1.4-Math.sin(u*Math.PI)*1.6,pz=-6-s*4;pts.push(new V(px,py,pz));
      if(i%2){const l=new THREE.Mesh(new THREE.SphereGeometry(.09,8,6),E(['#ff4f6d','#ffcc33','#2fd3c4','#9b6bff','#ff8a1f'][i%5],1.6));l.position.set(px,py-.12,pz);far.add(l)}}
    far.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:'#2a1640'})))}
  // crowd silhouettes milling around
  const crowd=[];const cm2=M('#0c0618',{roughness:1});for(let i=0;i<26;i++){const g=new THREE.Group(),px=(i/25-.5)*16+(Math.random()-.5),pz=-4.5-Math.random()*3.5;g.position.set(px,0,pz);
    const b2=new THREE.Mesh(new THREE.CylinderGeometry(.18,.24,.9,8),cm2);b2.position.y=.45;g.add(b2);const hd2=new THREE.Mesh(new THREE.SphereGeometry(.15,10,8),cm2);hd2.position.y=1.05;g.add(hd2);
    if(i%4===0){const bl=new THREE.Mesh(new THREE.SphereGeometry(.14,10,8),E(['#ff4f6d','#2fd3c4','#ffcc33'][i%3],.6));bl.position.set(.25,1.7,0);g.add(bl);const st=new THREE.Mesh(new THREE.CylinderGeometry(.005,.005,.6,3),M('#ddd'));st.position.set(.22,1.35,0);g.add(st)}
    g.scale.setScalar(.9+Math.random()*.4);far.add(g);crowd.push({g,ph:Math.random()*6,sp:(Math.random()-.5)*.004})}G3.crowd=crowd;
  // fireworks: bursts of glowing points that rise, open and fade
  const FW=[];G3.fw=FW;const fwM=c=>new THREE.PointsMaterial({size:.35,map:bok,color:c,transparent:true,blending:THREE.AdditiveBlending,depthWrite:false});
  G3.firework=()=>{const n=60,g2=new THREE.BufferGeometry(),pos=new Float32Array(n*3),vel=[];const cx=(Math.random()-.5)*16,cy=8+Math.random()*4,cz=-14-Math.random()*6;
    for(let i=0;i<n;i++){pos[i*3]=cx;pos[i*3+1]=cy;pos[i*3+2]=cz;const a=Math.random()*6.28,b=Math.acos(2*Math.random()-1),sp=.06+Math.random()*.04;vel.push([Math.sin(b)*Math.cos(a)*sp,Math.cos(b)*sp,Math.sin(b)*Math.sin(a)*sp])}
    g2.setAttribute('position',new THREE.BufferAttribute(pos,3));const pts2=new THREE.Points(g2,fwM(['#ff4f6d','#ffcc33','#2fd3c4','#9b6bff','#ffffff'][Math.random()*5|0]));far.add(pts2);FW.push({pts:pts2,vel,t:0})};
  // hole positions on the felt, projected to the 2D canvas so the heads line up with the 3D table
  const HP=[];[[-.9,-.7],[0,-.7],[.9,-.7],[-.98,.06],[0,.06],[.98,.06],[-1.06,.86],[0,.86],[1.06,.86]].forEach(([hx,hz])=>HP.push(new V(hx,.93,hz)));
  cam.updateMatrixWorld();cam.updateProjectionMatrix();
  G3.slots=HP.map(p=>{const a=p.clone().project(cam),b=p.clone().add(new V(.26,0,0)).project(cam),sx=(a.x+1)/2*W,sy=(1-a.y)/2*H,rx=Math.abs((b.x-a.x)/2*W);return[Math.round(sx),Math.round(sy),+(rx/60).toFixed(3)]});
  // ---------------- 3D holes, characters, bomb and hammer ----------------
  R.localClippingEnabled=true;const CLIP=[new THREE.Plane(new V(0,1,0),-.936)];
  const LINC=c=>new THREE.Color(c).convertSRGBToLinear();
  const clipM=(c,o={})=>{const m=M(c,o);m.clippingPlanes=CLIP;return m};
  const holeMat=new THREE.MeshBasicMaterial({color:'#050208'}),rimMat=M('#ffc83a',{metalness:.75,roughness:.28}),bulbM=E('#fff2b0',1.2);
  const glowT=tex(64,64,g=>{const gr=g.createRadialGradient(32,32,0,32,32,32);gr.addColorStop(0,'rgba(255,255,255,1)');gr.addColorStop(.35,'rgba(255,255,255,.5)');gr.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=gr;g.fillRect(0,0,64,64)});
  const skullT=tex(512,256,g=>{g.fillStyle='#0d0e12';g.fillRect(0,0,512,256);const cx=128,cy=124;g.fillStyle='#efe9da';g.beginPath();g.arc(cx,cy-8,34,Math.PI,0);g.lineTo(cx+26,cy+22);g.lineTo(cx-26,cy+22);g.closePath();g.fill();g.fillRect(cx-18,cy+16,36,16);
    g.fillStyle='#0d0e12';g.beginPath();g.arc(cx-13,cy-6,9,0,7);g.arc(cx+13,cy-6,9,0,7);g.fill();g.beginPath();g.moveTo(cx,cy+4);g.lineTo(cx-5,cy+13);g.lineTo(cx+5,cy+13);g.fill();
    g.fillRect(cx-8,cy+22,3,10);g.fillRect(cx+5,cy+22,3,10);g.strokeStyle='#efe9da';g.lineWidth=9;g.lineCap='round';g.beginPath();g.moveTo(cx-46,cy+44);g.lineTo(cx+46,cy+70);g.moveTo(cx+46,cy+44);g.lineTo(cx-46,cy+70);g.stroke()});
  const FCW=256,FCH=320;
  // knit polo fabric: light grey detail (tinted per shirt) and a matching normal map
  const CLOTH=(()=>{const W2=256,map=tex(W2,W2,g=>{g.fillStyle='#e9e9e9';g.fillRect(0,0,W2,W2);for(let y=0;y<W2;y+=3)for(let xx=0;xx<W2;xx+=3){g.fillStyle=((xx+y)/3%2)?'rgba(255,255,255,.35)':'rgba(0,0,0,.08)';g.fillRect(xx,y,2,2)}
      const fold=g.createLinearGradient(0,0,W2,0);fold.addColorStop(0,'rgba(0,0,0,.18)');fold.addColorStop(.25,'rgba(0,0,0,0)');fold.addColorStop(.5,'rgba(255,255,255,.12)');fold.addColorStop(.75,'rgba(0,0,0,0)');fold.addColorStop(1,'rgba(0,0,0,.18)');g.fillStyle=fold;g.fillRect(0,0,W2,W2);
      g.strokeStyle='rgba(0,0,0,.1)';g.lineWidth=3;for(let i=0;i<6;i++){g.beginPath();g.moveTo(30+i*40,W2);g.bezierCurveTo(40+i*40,W2*.6,20+i*40,W2*.4,35+i*40,W2*.15);g.stroke()}});
    const nrm=tex(W2,W2,g=>{g.fillStyle='rgb(128,128,255)';g.fillRect(0,0,W2,W2);for(let y=0;y<W2;y+=3)for(let xx=0;xx<W2;xx+=3){const o=(y/3%2)*1.5;g.fillStyle='rgba(165,165,255,.6)';g.fillRect(xx+o,y,1.5,1.5);g.fillStyle='rgba(90,90,255,.6)';g.fillRect(xx+o+1.5,y+1.5,1.5,1.5)}});
    nrm.encoding=THREE.LinearEncoding;[map,nrm].forEach(t2=>{t2.wrapS=t2.wrapT=THREE.RepeatWrapping;t2.repeat.set(3,2)});return{map,nrm}})();
  G3.chars=HP.map((hp,i)=>{const c={};const root=new THREE.Group();root.position.copy(hp);root.scale.setScalar(1.3);sc.add(root);c.root=root;
    const yaw=Math.atan2(CAM.x-hp.x,CAM.z-hp.z);
    const disk=new THREE.Mesh(new THREE.CircleGeometry(.25,40),holeMat);disk.rotation.x=-Math.PI/2;disk.position.y=.007;root.add(disk);
    const rim=new THREE.Mesh(new THREE.TorusGeometry(.256,.03,10,48),rimMat);rim.rotation.x=Math.PI/2;rim.position.y=.014;rim.castShadow=true;rim.receiveShadow=true;root.add(rim);
    for(let k=0;k<12;k++){const a=k/12*Math.PI*2,b=new THREE.Mesh(new THREE.SphereGeometry(.012,6,5),bulbM);b.position.set(Math.cos(a)*.256,.045,Math.sin(a)*.256);root.add(b)}
    const body=new THREE.Group();root.add(body);c.body=body;const turn=new THREE.Group();turn.rotation.y=yaw*.85;body.add(turn);c.turn=turn;
    // person
    const person=new THREE.Group();turn.add(person);c.person=person;
    c.shirtM=clipM('#2f6de2',{roughness:.9,map:CLOTH.map,normalMap:CLOTH.nrm,normalScale:new THREE.Vector2(.6,.6)});c.trimM=clipM('#ffcc33',{roughness:.55});c.skinM=clipM('#b88b75',{roughness:.55});
    const torso=new THREE.Mesh(new THREE.LatheGeometry([[.001,-.6],[.23,-.6],[.235,-.2],[.232,-.05],[.22,.06],[.18,.13],[.1,.17],[.001,.18]].map(([a,b])=>new THREE.Vector2(a,b)),32),c.shirtM);
    torso.scale.z=.62;torso.castShadow=true;person.add(torso);c.torso=torso;
    // collar flaps, placket band and short sleeves with ribbed cuffs
    [-1,1].forEach(d=>{const f=new THREE.Mesh(new THREE.BoxGeometry(.075,.012,.055),c.trimM);f.position.set(d*.038,.165,.075);f.rotation.set(-.55,d*.5,d*.35);f.castShadow=true;person.add(f)});
    const plk=new THREE.Mesh(new THREE.BoxGeometry(.03,.13,.006),clipM('#ffffff',{roughness:.9}));plk.position.set(0,.085,.137);plk.rotation.x=-.12;plk.material=c.shirtM;person.add(plk);
    c.sleeves=[];[-1,1].forEach(d=>{const sg=new THREE.Group();sg.position.set(d*.2,.1,0);sg.rotation.z=d*.55;person.add(sg);
      const sl=new THREE.Mesh(new THREE.CylinderGeometry(.06,.072,.16,16,1,true),c.shirtM);sl.position.y=-.06;sl.material.side=THREE.DoubleSide;sl.castShadow=true;sg.add(sl);
      const cf=new THREE.Mesh(new THREE.TorusGeometry(.071,.011,6,18),c.trimM);cf.rotation.x=Math.PI/2;cf.position.y=-.14;sg.add(cf);
      const arm=new THREE.Mesh(new THREE.CylinderGeometry(.045,.05,.12,12),c.skinM);arm.position.y=-.19;sg.add(arm);c.sleeves.push(sg)});
    c.cloth=0;c.clothV=0;c.ph=Math.random()*6;
    const collar=new THREE.Mesh(new THREE.TorusGeometry(.078,.02,8,24),c.trimM);collar.rotation.x=Math.PI/2;collar.position.y=.168;person.add(collar);c.collar=collar;
    const erm=new THREE.Mesh(new THREE.TorusGeometry(.13,.045,10,28),clipM('#fbfaf6',{roughness:.95}));erm.rotation.x=Math.PI/2;erm.scale.y=.75;erm.position.y=.15;person.add(erm);c.erm=erm;
    c.btn=[];const bm=clipM('#f4f1ea',{roughness:.4});[[.1,.128],[.03,.138],[-.04,.144]].forEach(([y,z])=>{const b=new THREE.Mesh(new THREE.SphereGeometry(.012,8,6),bm);b.position.set(0,y,z);person.add(b);c.btn.push(b)});
    const neck=new THREE.Mesh(new THREE.CylinderGeometry(.058,.066,.08,16),c.skinM);neck.position.y=.2;neck.castShadow=true;person.add(neck);
    const headG=new THREE.Group();headG.position.y=.17;headG.rotation.order='YXZ';person.add(headG);c.headG=headG;
    const fh=.46,fw=fh*FCW/FCH;c.fh=fh;
    const fg=new THREE.PlaneGeometry(fw,fh,32,40),pa=fg.attributes.position;for(let k=0;k<pa.count;k++){const px=pa.getX(k)/(fw*.5),py=pa.getY(k)/(fh*.5),q=1-px*px*.9-py*py*.75;pa.setZ(k,q>0?.1*Math.sqrt(q):0)}fg.computeVertexNormals();
    c.fc=document.createElement('canvas');c.fc.width=FCW;c.fc.height=FCH;c.fx=c.fc.getContext('2d');c.ft=new THREE.CanvasTexture(c.fc);c.ft.encoding=THREE.sRGBEncoding;
    const fm=new THREE.MeshStandardMaterial({map:c.ft,emissiveMap:c.ft,emissive:LINC('#8c8c8c'),color:LINC('#5a5a5a'),roughness:.6,transparent:true,alphaTest:.3,toneMapped:false,clippingPlanes:CLIP,side:THREE.DoubleSide});
    const face=new THREE.Mesh(fg,fm);face.position.set(0,fh*.5,.03);face.castShadow=true;face.customDepthMaterial=new THREE.MeshDepthMaterial({depthPacking:THREE.RGBADepthPacking,map:c.ft,alphaTest:.3});headG.add(face);c.face=face;
    const back=new THREE.Mesh(new THREE.SphereGeometry(1,28,20),c.skinM);back.scale.set(fw*.34,fh*.3,.1);back.position.set(0,fh*.42,-.07);back.castShadow=true;headG.add(back);
    const bump=new THREE.Mesh(new THREE.SphereGeometry(.05,16,12),clipM('#ff5a5a',{roughness:.35}));bump.position.set(.05,fh*.86,.07);headG.add(bump);c.bump=bump;
    // queen's crown
    const crown=new THREE.Group();crown.position.set(0,fh*.84,.02);crown.rotation.x=-.15;headG.add(crown);c.crown=crown;
    const gm=M('#ffc83a',{metalness:.85,roughness:.22}),pearl=M('#fffaf0',{roughness:.3});
    const vel=new THREE.Mesh(new THREE.SphereGeometry(.105,20,12,0,Math.PI*2,0,Math.PI/2),M('#8a1030',{roughness:.8}));vel.scale.y=.85;crown.add(vel);
    const band=new THREE.Mesh(new THREE.CylinderGeometry(.13,.12,.06,32,1,true),gm);band.material.side=THREE.DoubleSide;crown.add(band);
    for(let k=0;k<8;k++){const a=k/8*Math.PI*2,pt=new THREE.Mesh(new THREE.ConeGeometry(.026,.08,6),gm);pt.position.set(Math.sin(a)*.128,.07,Math.cos(a)*.128);crown.add(pt);
      const pr=new THREE.Mesh(new THREE.SphereGeometry(.013,8,6),pearl);pr.position.set(Math.sin(a)*.128,.115,Math.cos(a)*.128);crown.add(pr);
      const gem=new THREE.Mesh(new THREE.SphereGeometry(.016,10,8),E(['#e01e48','#1e7ae0','#1fbf6a','#1e7ae0'][k%4],.4));gem.position.set(Math.sin(a)*.133,0,Math.cos(a)*.133);gem.scale.z=.6;gem.lookAt(gem.position.clone().multiplyScalar(3));crown.add(gem)}
    const orb=new THREE.Mesh(new THREE.SphereGeometry(.024,12,10),gm);orb.position.y=.12;crown.add(orb);const cr1=new THREE.Mesh(new THREE.BoxGeometry(.012,.05,.012),gm);cr1.position.y=.16;crown.add(cr1);
    const cr2=new THREE.Mesh(new THREE.BoxGeometry(.035,.012,.012),gm);cr2.position.y=.165;crown.add(cr2);crown.traverse(o=>{o.castShadow=true});
    // bomb
    const bomb=new THREE.Group();turn.add(bomb);c.bomb=bomb;
    const ball=new THREE.Mesh(new THREE.SphereGeometry(.22,40,28),new THREE.MeshStandardMaterial({map:skullT,metalness:.4,roughness:.22,clippingPlanes:CLIP}));ball.position.y=.24;ball.castShadow=true;bomb.add(ball);
    const cap=new THREE.Mesh(new THREE.CylinderGeometry(.06,.065,.07,20),clipM('#aeb3bf',{metalness:.8,roughness:.3}));cap.position.y=.47;bomb.add(cap);
    const fuse=new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([new V(0,.5,0),new V(.02,.56,0),new V(.07,.6,.02),new V(.11,.6,.03)]),16,.013,6),clipM('#8a6a3a',{roughness:.9}));bomb.add(fuse);
    const spark=new THREE.Sprite(new THREE.SpriteMaterial({map:glowT,color:'#ffcc55',blending:THREE.AdditiveBlending,depthWrite:false}));spark.position.set(.11,.6,.03);spark.scale.setScalar(.16);bomb.add(spark);c.spark=spark;
    const red=new THREE.Sprite(new THREE.SpriteMaterial({map:glowT,color:'#ff3020',blending:THREE.AdditiveBlending,depthWrite:false,transparent:true,opacity:.5}));red.position.set(0,.24,-.05);red.scale.setScalar(.8);bomb.add(red);c.red=red;
    // hands gripping the rim
    const hands=new THREE.Group();hands.rotation.y=yaw;root.add(hands);c.hands=hands;
    [-1,1].forEach(d=>{const h=new THREE.Group();h.position.set(d*.2,.03,.16);h.rotation.y=d*.5;hands.add(h);const pm=new THREE.Mesh(new THREE.SphereGeometry(.05,14,10),c.skinM);pm.scale.set(1.25,.6,1);pm.castShadow=true;h.add(pm);
      for(let k=0;k<4;k++){const f=new THREE.Mesh(new THREE.CylinderGeometry(.012,.012,.05,6),c.skinM);f.position.set(-.035+k*.023,-.02,.05);f.rotation.x=1.2;h.add(f)}});
    return c});
  // wooden barrel hammer
  const woodS=tex(256,128,g=>{g.fillStyle='#c27a35';g.fillRect(0,0,256,128);for(let i=0;i<8;i++){const gr=g.createLinearGradient(i*32,0,i*32+32,0);gr.addColorStop(0,'#8a4c1c');gr.addColorStop(.5,'#e6a35c');gr.addColorStop(1,'#a45f26');g.fillStyle=gr;g.fillRect(i*32,0,31,128)}
    for(let i=0;i<60;i++){g.strokeStyle='rgba(90,40,10,.25)';g.beginPath();const x0=Math.random()*256;g.moveTo(x0,0);g.bezierCurveTo(x0+4,40,x0-4,80,x0+2,128);g.stroke()}});
  const ringT=tex(128,128,g=>{const gr=g.createRadialGradient(64,64,4,64,64,64);gr.addColorStop(0,'#f6c88a');gr.addColorStop(1,'#c47a35');g.fillStyle=gr;g.fillRect(0,0,128,128);g.strokeStyle='rgba(120,60,20,.5)';g.lineWidth=2;[50,38,26,14].forEach(r=>{g.beginPath();g.arc(64,64,r,0,7);g.stroke()});g.strokeStyle='#9aa0ad';g.lineWidth=8;g.beginPath();g.arc(64,64,60,0,7);g.stroke()});
  const handleT=tex(128,32,g=>{const gr=g.createLinearGradient(0,0,0,32);gr.addColorStop(0,'#e7a35a');gr.addColorStop(.5,'#b8692a');gr.addColorStop(1,'#6e3a14');g.fillStyle=gr;g.fillRect(0,0,128,32);for(let i=0;i<8;i++){g.strokeStyle='rgba(90,40,10,.3)';g.beginPath();g.moveTo(0,4+i*3.5);g.lineTo(128,5+i*3.5);g.stroke()}});
  const ham=new THREE.Group();ham.visible=false;ham.scale.setScalar(1.35);sc.add(ham);const swing=new THREE.Group();ham.add(swing);G3.ham=ham;
  const hdl=new THREE.Mesh(new THREE.CylinderGeometry(.024,.028,.6,14),new THREE.MeshStandardMaterial({map:handleT,roughness:.6}));hdl.rotation.z=Math.PI/2;hdl.position.x=.3;swing.add(hdl);
  const gripM=M('#d91f2e',{roughness:.5});for(let k=0;k<5;k++){const t2=new THREE.Mesh(new THREE.TorusGeometry(.03,.012,8,16),gripM);t2.rotation.y=Math.PI/2;t2.position.x=.03+k*.028;swing.add(t2)}
  const knob=new THREE.Mesh(new THREE.SphereGeometry(.034,12,10),gripM);knob.position.x=-.005;swing.add(knob);
  const hh=new THREE.Group();hh.position.x=.62;swing.add(hh);const wm=new THREE.MeshStandardMaterial({map:woodS,roughness:.55}),cm=new THREE.MeshStandardMaterial({map:ringT,roughness:.5});
  const barrel=new THREE.Mesh(new THREE.CylinderGeometry(.11,.11,.27,32),[wm,cm,cm]);barrel.castShadow=true;hh.add(barrel);
  const steel=M('#cfd4dc',{metalness:.9,roughness:.25});[-.095,.095].forEach(y=>{const b=new THREE.Mesh(new THREE.CylinderGeometry(.116,.116,.03,32),steel);b.position.y=y;hh.add(b);
    for(let k=0;k<10;k++){const a=k/10*Math.PI*2,r=new THREE.Mesh(new THREE.SphereGeometry(.007,6,5),M('#5a5f6a',{metalness:.8,roughness:.3}));r.position.set(Math.cos(a)*.118,y,Math.sin(a)*.118);hh.add(r)}});
  ham.traverse(o=>{o.castShadow=true});
  const ray=new THREE.Raycaster(),tgt=new V(0,.96,0),tmpV=new V(),PL=new THREE.Plane(new V(0,1,0),-.96),OFF=new V(.62,0,.5).normalize();
  const proj=v=>{const a=v.clone().project(cam);return{x:(a.x+1)/2*W,y:(1-a.y)/2*H}};
  G3.sync=(S,AIM)=>{
    S.forEach((p,i)=>{const c=G3.chars[i],tnt=p.type==='tnt',gold=p.type==='gold';c.body.visible=p.pop>.01;
      c.body.position.set(p.lx*.004,-(1-p.pop)*1.2,0);c.body.rotation.z=-p.rot*.9;c.body.scale.set(1+p.sq*.25,1-p.sq*.3,1+p.sq*.25);
      if(c.torso){if(p.state==='hit'&&p.t===1)c.clothV+=.5;c.clothV+=-.18*c.cloth-.12*c.clothV;c.cloth+=c.clothV;const br=reduce?0:Math.sin(T*.08+c.ph);
        c.torso.scale.set(1+br*.012+c.cloth*.06,1+br*.015-c.cloth*.04,.62*(1+c.cloth*.05));c.turn.rotation.z=reduce?0:Math.sin(T*.035+c.ph)*.025;
        c.sleeves.forEach((s,k)=>{const d=k?1:-1;s.rotation.z=d*(.55+c.cloth*.5+(reduce?0:Math.sin(T*.06+c.ph+k)*.04))})}
      c.person.visible=!tnt;c.bomb.visible=tnt;c.hands.visible=!tnt&&p.pop>.8&&p.state!=='down';
      const ph=PHOTOS[p.face]||PHOTOS[0],key=p.type+'|'+p.face+'|'+(p.i%5);
      if(c.key!==key){c.key=key;const [sh,tr]=SHIRTS[p.i%5];c.shirtM.color.copy(LINC(gold?'#5b1a8c':sh));c.trimM.color.copy(LINC(gold?'#ffcc33':tr));c.skinM.color.copy(LINC(ph.skin));
        c.erm.visible=gold;c.collar.visible=!gold;c.btn.forEach(b=>b.visible=!gold)}
      c.crown.visible=gold&&p.hat.on;c.bump.visible=(p.bump||0)>.03;c.bump.scale.setScalar(Math.max(.01,p.bump||0));
      const RX=p.react;if(RX)RX.t++;const wob=RX?Math.max(0,1-RX.t/18)*Math.sin(RX.t*1.3)*.12:0;
      c.headG.rotation.set(-.32-(p.state==='hit'?Math.min(.12,p.sq*.2):0),0,(p.dizzy>0&&!reduce?Math.sin(T*.2)*.06:0)+(RX&&RX.shape==='crooked'?-.24+wob:0));
      const sh=RX?RX.shape:null;c.headG.scale.set(sh==='flat'?1.3+wob:sh==='long'?.78-wob:sh==='wide'?1.18+wob:sh==='crooked'?1.08:1,sh==='flat'?.7-wob:sh==='long'?1.28+wob:sh==='wide'?.86:1,1);
      if(tnt){const pulse=.5+.5*Math.sin(T*.35);c.red.material.opacity=.25+pulse*.35;c.spark.scale.setScalar(.12+Math.random()*.1);c.spark.material.rotation=Math.random()*6}
      else if(c.body.visible&&ph.img.complete&&ph.img.naturalWidth){const g=c.fx,src=(p.state==='hit'||p.ouch>0?ph.frown:ph.smile)||ph.img,sw=src.width||src.naturalWidth,shh=src.height||src.naturalHeight;
        const k=Math.min(FCW/sw,FCH/shh),dw=sw*k,dh=shh*k,dx=(FCW-dw)/2,dy=FCH-dh,s2=dh/150;g.globalCompositeOperation='source-over';g.clearRect(0,0,FCW,FCH);g.drawImage(src,dx,dy,dw,dh);
        g.globalCompositeOperation='source-atop';if(p.tint>.02){g.fillStyle=`rgba(255,40,50,${p.tint*.35})`;g.fillRect(0,0,FCW,FCH)}
        (p.marks||[]).forEach(m=>handPrint(g,dx+dw/2+m.x*s2,dy+(m.y+202)*s2,m.s*s2,m.a));
        if(p.band){g.save();g.translate(dx+dw/2-26*s2,dy+90*s2);g.scale(s2,s2);g.fillStyle='#f3cf9c';g.strokeStyle='#c99a5a';g.lineWidth=1.5;[.6,-.6].forEach(a=>{g.save();g.rotate(a);g.beginPath();g.roundRect(-22,-7,44,14,6);g.fill();g.stroke();g.fillStyle='#e8bb82';g.fillRect(-6,-5,12,10);g.fillStyle='#f3cf9c';g.restore()});g.restore()}
        if(RX){const ww=dw,hh2=dh,cx=dx+dw/2,ex=ww*.2,ey=dy+hh2*.46;
          const eye=(xx,col,r2)=>{const g2=g.createRadialGradient(xx,ey,1,xx,ey,r2);g2.addColorStop(0,col);g2.addColorStop(1,'rgba(60,20,70,0)');g.fillStyle=g2;g.beginPath();g.arc(xx,ey,r2,0,7);g.fill()};
          if(RX.fx==='blackeye'){eye(cx-ex,'rgba(40,10,50,.85)',ww*.15);eye(cx+ex*.9,'rgba(90,20,80,.45)',ww*.12)}
          g.fillStyle='rgba(255,40,50,.35)';g.beginPath();g.ellipse(cx,dy+hh2*.6,ww*.07,ww*.06,0,0,7);g.fill();g.globalCompositeOperation='source-over';
          if(RX.fx==='swell')[-1,1].forEach(d=>{const sx=cx+d*ww*.29,sy=dy+hh2*.64,rr=ww*.14,g2=g.createRadialGradient(sx-d*rr*.3,sy-rr*.3,2,sx,sy,rr);g2.addColorStop(0,shade(ph.skin,40));g2.addColorStop(.7,shade(ph.skin,5));g2.addColorStop(1,shade(ph.skin,-35));
            g.fillStyle=g2;g.beginPath();g.arc(sx,sy,rr,0,7);g.fill();g.fillStyle='rgba(255,60,70,.35)';g.beginPath();g.arc(sx,sy,rr*.6,0,7);g.fill()});
          if(RX.fx==='dizzy')[-1,1].forEach(d=>{const sx=cx+d*ex,rr=ww*.1;g.fillStyle='#fff';g.strokeStyle='#1a0820';g.lineWidth=2;g.beginPath();g.arc(sx,ey,rr,0,7);g.fill();g.stroke();
            g.beginPath();for(let a=0;a<14;a+=.25){const q=a/14*rr*.9;g.lineTo(sx+Math.cos(a+T*.3*d)*q,ey+Math.sin(a+T*.3*d)*q)}g.stroke()});
          if(RX.fx==='tongue'){const ty=dy+hh2*.8;g.fillStyle='#e8556a';g.strokeStyle='#8a1a2a';g.lineWidth=2;g.beginPath();g.ellipse(cx+ww*.05,ty+ww*.09,ww*.09,ww*.13,.2,0,7);g.fill();g.stroke();
            [-1,1].forEach(d=>{g.fillStyle='#fff';g.beginPath();g.arc(cx+d*ex,ey,ww*.075,0,7);g.fill();g.fillStyle='#111';g.beginPath();g.arc(cx+d*ex+(d>0?-3:3),ey+2,ww*.03,0,7);g.fill()})}}
        g.globalCompositeOperation='source-over';c.ft.needsUpdate=true}
    });
    cam.updateMatrixWorld();sc.updateMatrixWorld();
    S.forEach((p,i)=>{const c=G3.chars[i],ref=c.person.visible?c.headG:c.bomb,h0=ref.localToWorld(tmpV.set(0,c.person.visible?c.fh*.5:.24,.06)),a=proj(h0);
      const h1=ref.localToWorld(tmpV.set(0,c.person.visible?c.fh:.48,.06)),b=proj(h1);p.fx=a.x;p.fy=a.y;p.tx=b.x;p.ty=b.y;p.s=Math.max(.2,Math.hypot(b.x-a.x,b.y-a.y)*2/150)});
    // hammer follows the pointer and lands on the head under it
    if(AIM&&AIM.vis){let hit=null;for(const p of S){if(p.state==='down'||p.pop<.45)continue;const dx=(AIM.ax-p.fx)/(70*p.s),dy=(AIM.ay-p.fy)/(105*p.s);if(dx*dx+dy*dy<=1&&(!hit||p.y>hit.y))hit=p}
      let want;if(hit){const c=G3.chars[S.indexOf(hit)];want=(c.person.visible?c.headG.localToWorld(new V(0,c.fh*.92,.04)):c.bomb.localToWorld(new V(0,.46,0)))}
      else{ray.setFromCamera({x:AIM.ax/W*2-1,y:-(AIM.ay/H*2-1)},cam);want=ray.ray.intersectPlane(PL,new V())||tgt.clone()}
      tgt.lerp(want,.45);const head=tgt.clone().add(new V(0,.135*1.35,0)),piv=head.clone().addScaledVector(OFF,.62*1.35);
      ham.visible=true;ham.position.copy(piv);ham.rotation.set(0,Math.atan2(OFF.z,-OFF.x),0);swing.rotation.z=-AIM.ang*1.05;hh.scale.set(1+AIM.sq*.2,1-AIM.sq*.28,1+AIM.sq*.2)}
    else ham.visible=false};
  // brand backdrop: the BETS Battalion art fills the sky, with its logo framed above the booth
  sc.fog=null;gond.forEach(o=>o.g.visible=false);sc.updateMatrixWorld(true);const bx=new THREE.Box3(),ctr=new V();
  sc.children.forEach(o=>{if(o.isLight)return;if(o.geometry&&o.geometry.type==='PlaneGeometry'&&o.geometry.parameters.width>=60){o.visible=false;return}
    bx.setFromObject(o);if(bx.isEmpty())return;bx.getCenter(ctr);if(ctr.z<-1.6||ctr.y>3.45)o.visible=false});
  const bgc=document.createElement('canvas');bgc.width=960;bgc.height=1240;const bgT=new THREE.CanvasTexture(bgc);bgT.encoding=THREE.sRGBEncoding;sc.background=bgT;
  const bgi=new Image();bgi.onload=()=>{const g=bgc.getContext('2d');g.filter='blur(14px)';g.drawImage(bgi,-120,-120,1240*1.0,1480);g.filter='none';
    const S=780,tc=document.createElement('canvas');tc.width=tc.height=S;const tg=tc.getContext('2d');tg.drawImage(bgi,0,0,S,S);tg.globalCompositeOperation='destination-in';const mk=tg.createLinearGradient(0,0,S,0);mk.addColorStop(0,'rgba(0,0,0,0)');mk.addColorStop(.18,'#000');mk.addColorStop(.82,'#000');mk.addColorStop(1,'rgba(0,0,0,0)');tg.fillStyle=mk;tg.fillRect(0,0,S,S);g.drawImage(tc,(960-S)/2,-190);const fade=g.createLinearGradient(0,700,0,840);fade.addColorStop(0,'rgba(0,0,0,0)');fade.addColorStop(1,'rgba(0,0,0,0)');bgT.needsUpdate=true};bgi.src=BGSRC;
  function resize(){const r=cvs.getBoundingClientRect();if(r.width)R.setSize(r.width,r.height,false)}addEventListener('resize',resize);
  G3.render=(t,shake,reduce)=>{resize();
    if(!reduce){fw.rotation.z=t*.004;gond.forEach(o=>{const a=o.a+fw.rotation.z;o.g.position.set(-3.2+Math.cos(a)*3.6,5.2+Math.sin(a)*3.6-.3,-11)});
      bulbs.forEach(o=>{o.b.material.emissiveIntensity=((o.i+(t/6|0))%3===0)?2.2:.25});lights.forEach(o=>{o.l.material.emissiveIntensity=Math.sin(t*.08+o.i)>-.3?1.8:.2});
      G3.flags.forEach(o=>{o.f.rotation.x=Math.sin(t*.07+o.i)*.35});G3.parols.forEach(o=>{o.m.rotation.y=Math.sin(t*.02+o.ph)*.35;o.m.material.emissiveIntensity=1.1+Math.sin(t*.06+o.ph)*.4});
      G3.bokeh.rotation.y=Math.sin(t*.002)*.05;G3.spin.rotation.y=t*.012;G3.horses.forEach(o=>{o.g.position.y=1+Math.sin(t*.06+o.ph*1.7)*.22});
      G3.crowd.forEach(o=>{o.g.position.x+=o.sp;if(Math.abs(o.g.position.x)>9)o.sp*=-1;o.g.position.y=Math.max(0,Math.sin(t*.1+o.ph))*.05});
      if(t%70===0)G3.firework();
      G3.fw.forEach(f=>{f.t++;const p=f.pts.geometry.attributes.position;for(let i=0;i<p.count;i++){const v=f.vel[i];v[1]-=.0012;p.setXYZ(i,p.getX(i)+v[0],p.getY(i)+v[1],p.getZ(i)+v[2]);v[0]*=.98;v[1]*=.98;v[2]*=.98}p.needsUpdate=true;f.pts.material.opacity=Math.max(0,1-f.t/90)});
      for(let i=G3.fw.length-1;i>=0;i--)if(G3.fw[i].t>90){const f=G3.fw[i];f.pts.parent.remove(f.pts);f.pts.geometry.dispose();f.pts.material.dispose();G3.fw.splice(i,1)}
      if(typeof AIM!=='undefined'){const tx=(AIM.ax/W-.5)*-1.2,ty=(AIM.ay/H-.5)*.5;G3.far.position.x+=(tx-G3.far.position.x)*.05;G3.far.position.y+=(ty-G3.far.position.y)*.05}
      for(let i=0;i<7;i++){const g=G3['toy'+i];g.rotation.y=Math.sin(t*.02+i)*.25;g.position.y=1.75+Math.max(0,Math.sin(t*.05+i*1.3))*.02}}
    cam.position.set(CAM.x+(reduce?0:Math.sin(t*.006)*.04)+(shake?(Math.random()-.5)*shake*.004:0),CAM.y+(shake?(Math.random()-.5)*shake*.004:0),CAM.z);cam.lookAt(LOOK);
    R.render(sc,cam)};
  // first draw needs the sign font
  if(document.fonts)document.fonts.ready.then(()=>{const c=signT.image,g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);const gr=g.createLinearGradient(0,0,0,c.height);gr.addColorStop(0,'#e2343f');gr.addColorStop(1,'#8f1424');g.fillStyle=gr;g.fillRect(0,0,c.width,c.height);
    g.strokeStyle='#ffcc33';g.lineWidth=12;g.strokeRect(14,14,c.width-28,c.height-28);g.font='140px "Lilita One", Impact, sans-serif';g.textAlign='center';g.textBaseline='middle';g.lineWidth=16;g.strokeStyle='#5a0a14';g.strokeText('CHAD SMASH',c.width/2,c.height/2+8);
    const tg=g.createLinearGradient(0,60,0,200);tg.addColorStop(0,'#fff3a0');tg.addColorStop(1,'#ffb21f');g.fillStyle=tg;g.fillText('CHAD SMASH',c.width/2,c.height/2+8);signT.needsUpdate=true})})();
const SLOTS=G3.slots;
const SHIRTS=[['#2f6de2','#ffcc33'],['#e2343f','#ffffff'],['#1fa86b','#ffcc33'],['#8a4fe0','#ffffff'],['#ff8a1f','#2a1450']];
const HATS=[['#ff4f6d','#ffcc33'],['#2fd3c4','#ff4f6d'],['#ffcc33','#8a4fe0'],['#9b6bff','#2fd3c4'],['#ff8a1f','#ffffff']];
function slot(i){const [sx,sy,s]=SLOTS[i];return{i,x:sx,y:sy,s,state:'down',t:0,dur:0,pop:0,popT:0,type:'head',rot:0,rotV:0,lx:0,lxV:0,sq:0,sqV:0,tint:0,marks:[],swell:0,dizzy:0,
  hat:{on:true,fly:false,x:0,y:0,vx:0,vy:0,r:0,vr:0},ko:0,hitQ:0,face:HEADS[i]}}
const S=SLOTS.map((_,i)=>slot(i));
function headTop(p){if(p.tx!=null)return{x:p.tx,y:p.ty};const rise=(1-p.pop)*280*p.s;return{x:p.x+p.lx,y:p.y+rise-160*p.s}}
function faceAt(p){if(p.fx!=null)return{x:p.fx,y:p.fy};const rise=(1-p.pop)*280*p.s;return{x:p.x+p.lx+Math.sin(p.rot)*100*p.s,y:p.y+rise-100*p.s*Math.cos(p.rot)}}

function drawHoleBack(p){const s=p.s;x.fillStyle='rgba(0,0,0,.35)';x.beginPath();x.ellipse(p.x,p.y+6*s,74*s,22*s,0,0,7);x.fill();
  const gr=x.createRadialGradient(p.x,p.y+4*s,4,p.x,p.y,66*s);gr.addColorStop(0,'#05020a');gr.addColorStop(1,'#241032');x.fillStyle=gr;x.beginPath();x.ellipse(p.x,p.y,64*s,19*s,0,0,7);x.fill()}
function drawHoleFront(p){const s=p.s;x.save();x.beginPath();x.ellipse(p.x,p.y,72*s,24*s,0,-.02,Math.PI+.02);x.ellipse(p.x,p.y-1,63*s,18*s,0,Math.PI+.02,-.02,true);x.closePath();
  const gr=x.createLinearGradient(0,p.y,0,p.y+24*s);gr.addColorStop(0,'#ffe27a');gr.addColorStop(1,'#a8640a');x.fillStyle=gr;x.fill();x.restore();
  for(let k=0;k<7;k++){const a=.25+k*.44,bx=p.x+Math.cos(a)*68*s,by=p.y+Math.sin(a)*21*s;x.fillStyle='#fff6d0';x.beginPath();x.arc(bx,by,2.2*s,0,7);x.fill()}}

function handPrint(g,px,py,sc,al){g.save();g.translate(px,py);g.scale(sc,sc);g.fillStyle=`rgba(230,25,45,${al})`;g.filter='blur(1.2px)';g.beginPath();g.ellipse(0,6,11,12,0,0,7);g.fill();
  [[-8,-9,3,10],[-3,-12,3.2,12],[3,-11.5,3.2,11],[8,-8,2.8,9]].forEach(([fx,fy,w,h])=>{g.beginPath();g.ellipse(fx,fy,w,h,0,0,7);g.fill()});g.beginPath();g.ellipse(-12,7,3,7,-.8,0,7);g.fill();g.filter='none';g.restore()}

function drawHead(p){const s=p.s,rise=(1-p.pop)*280*s;
  x.save();x.beginPath();x.rect(p.x-200,p.y-420,400,420);x.ellipse(p.x,p.y,63*s,18*s,0,0,Math.PI);x.clip();
  x.translate(p.x+p.lx,p.y+rise);x.rotate(p.rot);x.scale(s*(1+p.sq*.2),s*(1-p.sq*.25));
  if(p.type==='tnt'){// a glossy round bomb with a sparking fuse, pulsing red as it waits
    const pulse=.5+.5*Math.sin(T*.35);x.fillStyle='rgba(0,0,0,.35)';x.beginPath();x.ellipse(0,6,62,14,0,0,7);x.fill();
    if(!reduce){const gl=x.createRadialGradient(0,-74,30,0,-74,95);gl.addColorStop(0,`rgba(255,60,40,${.25*pulse})`);gl.addColorStop(1,'rgba(255,60,40,0)');x.fillStyle=gl;x.beginPath();x.arc(0,-74,95,0,7);x.fill()}
    let gr=x.createRadialGradient(-20,-100,6,0,-74,70);gr.addColorStop(0,'#5a5f70');gr.addColorStop(.35,'#23262f');gr.addColorStop(1,'#07080b');x.fillStyle=gr;x.beginPath();x.arc(0,-74,62,0,7);x.fill();
    x.fillStyle='rgba(255,255,255,.55)';x.beginPath();x.ellipse(-24,-104,16,9,-.6,0,7);x.fill();x.fillStyle='rgba(255,255,255,.9)';x.beginPath();x.ellipse(-28,-108,5,3,-.6,0,7);x.fill();
    x.strokeStyle=`rgba(255,80,60,${.35+pulse*.4})`;x.lineWidth=3;x.beginPath();x.arc(0,-74,60,.2,2.9);x.stroke();
    // skull badge
    x.fillStyle='#f1ece0';x.beginPath();x.arc(0,-70,17,Math.PI,0);x.lineTo(13,-58);x.lineTo(-13,-58);x.closePath();x.fill();x.fillRect(-9,-60,18,8);
    x.fillStyle='#07080b';x.beginPath();x.arc(-6,-70,4.5,0,7);x.arc(6,-70,4.5,0,7);x.fill();x.beginPath();x.moveTo(0,-65);x.lineTo(-2.5,-61);x.lineTo(2.5,-61);x.fill();
    x.strokeStyle='#f1ece0';x.lineWidth=4;x.lineCap='round';x.beginPath();x.moveTo(-22,-44);x.lineTo(22,-32);x.moveTo(22,-44);x.lineTo(-22,-32);x.stroke();
    // metal cap
    gr=x.createLinearGradient(-16,0,16,0);gr.addColorStop(0,'#5d6270');gr.addColorStop(.5,'#c9ced8');gr.addColorStop(1,'#4a4e5a');x.fillStyle=gr;x.beginPath();x.roundRect(-16,-146,32,18,4);x.fill();
    x.fillStyle='#8a8f9c';x.fillRect(-16,-140,32,3);
    // fuse and sparks
    const fx=14+Math.sin(T*.2)*2,fy=-178;x.strokeStyle='#8a6a3a';x.lineWidth=5;x.beginPath();x.moveTo(0,-146);x.bezierCurveTo(4,-164,22,-160,fx,fy);x.stroke();
    x.strokeStyle='#5a4220';x.lineWidth=1.5;for(let k=0;k<5;k++){x.beginPath();x.moveTo(2+k*3,-150-k*6);x.lineTo(6+k*3,-154-k*6);x.stroke()}
    x.save();x.globalCompositeOperation='lighter';const sg=x.createRadialGradient(fx,fy,0,fx,fy,22);sg.addColorStop(0,'rgba(255,255,220,1)');sg.addColorStop(.3,'rgba(255,200,60,.8)');sg.addColorStop(1,'rgba(255,120,0,0)');x.fillStyle=sg;x.beginPath();x.arc(fx,fy,22,0,7);x.fill();
    for(let i=0;i<10;i++){const a=Math.random()*6.28,l=8+Math.random()*16;x.strokeStyle=['#fff6c0','#ffcc33','#ff8a1f'][i%3];x.lineWidth=2;x.beginPath();x.moveTo(fx,fy);x.lineTo(fx+Math.cos(a)*l,fy+Math.sin(a)*l);x.stroke()}x.restore();
    for(let i=0;i<3;i++){const k=((T*.6+i*20)%60)/60;x.fillStyle=`rgba(200,200,210,${.35*(1-k)})`;x.beginPath();x.arc(fx+Math.sin(k*6+i)*6,fy-10-k*40,5+k*10,0,7);x.fill()}
    x.restore();return}
  // torso: polo shirt with collar, placket and folds (gold Chad wears a royal robe with ermine collar)
  const [shirt,trim]=SHIRTS[p.i%5],gold=p.type==='gold',base=gold?'#5b1a8c':shirt;
  let gr=x.createLinearGradient(-90,0,90,0);gr.addColorStop(0,shade(base,-60));gr.addColorStop(.3,shade(base,10));gr.addColorStop(.55,shade(base,25));gr.addColorStop(1,shade(base,-70));x.fillStyle=gr;
  x.beginPath();x.moveTo(-96,40);x.bezierCurveTo(-98,-10,-92,-42,-60,-54);x.quadraticCurveTo(-34,-62,-22,-62);x.lineTo(22,-62);x.quadraticCurveTo(34,-62,60,-54);x.bezierCurveTo(92,-42,98,-10,96,40);x.closePath();x.fill();
  // sleeves and arm shading
  x.fillStyle='rgba(0,0,0,.18)';x.beginPath();x.moveTo(-84,-28);x.quadraticCurveTo(-70,4,-74,40);x.lineTo(-96,40);x.bezierCurveTo(-98,0,-94,-24,-84,-28);x.fill();x.beginPath();x.moveTo(84,-28);x.quadraticCurveTo(70,4,74,40);x.lineTo(96,40);x.bezierCurveTo(98,0,94,-24,84,-28);x.fill();
  x.strokeStyle='rgba(0,0,0,.18)';x.lineWidth=2;[[-40,-30,-30,20],[38,-26,30,22],[-12,-8,-18,30],[14,-4,20,30]].forEach(([a,b,c,d])=>{x.beginPath();x.moveTo(a,b);x.quadraticCurveTo((a+c)/2+6,(b+d)/2,c,d);x.stroke()});
  x.fillStyle='rgba(255,255,255,.12)';x.beginPath();x.ellipse(-36,-40,26,8,-.3,0,7);x.fill();
  if(gold){// ermine collar and gold chain
    x.fillStyle='#fbfaf6';x.beginPath();x.moveTo(-70,-50);x.quadraticCurveTo(0,-20,70,-50);x.quadraticCurveTo(64,-24,0,-6);x.quadraticCurveTo(-64,-24,-70,-50);x.fill();
    x.fillStyle='#111';[[-46,-36],[-24,-26],[0,-20],[24,-26],[46,-36],[-34,-44],[34,-44]].forEach(([a,b])=>{x.beginPath();x.moveTo(a,b-4);x.lineTo(a-2,b+3);x.lineTo(a+2,b+3);x.fill()});
    x.strokeStyle='#ffcc33';x.lineWidth=3;x.setLineDash([5,3]);x.beginPath();x.moveTo(-40,-24);x.quadraticCurveTo(0,10,40,-24);x.stroke();x.setLineDash([]);
    x.fillStyle='#ffcc33';x.beginPath();x.arc(0,-2,7,0,7);x.fill();x.fillStyle='#e01e48';x.beginPath();x.arc(0,-2,3.5,0,7);x.fill()}
  else{// collar flaps, placket and buttons
    x.fillStyle=shade(base,-25);x.fillRect(-7,-48,14,46);x.fillStyle='#f4f1ea';[-38,-26,-14].forEach(b=>{x.beginPath();x.arc(0,b,2.6,0,7);x.fill()});
    const flap=d=>{const fg=x.createLinearGradient(0,-66,0,-36);fg.addColorStop(0,shade(base,30));fg.addColorStop(1,shade(base,-10));x.fillStyle=fg;x.beginPath();x.moveTo(d*4,-52);x.lineTo(d*30,-66);x.lineTo(d*40,-56);x.lineTo(d*14,-34);x.closePath();x.fill();
      x.strokeStyle=trim;x.lineWidth=2.5;x.beginPath();x.moveTo(d*30,-66);x.lineTo(d*40,-56);x.lineTo(d*14,-34);x.stroke()};flap(-1);flap(1);
    x.strokeStyle=trim;x.lineWidth=3;x.beginPath();x.moveTo(-80,28);x.quadraticCurveTo(-72,10,-84,-2);x.stroke();x.beginPath();x.moveTo(80,28);x.quadraticCurveTo(72,10,84,-2);x.stroke()}
  // photo head
  const ph=PHOTOS[p.face];if(ph.img.complete&&ph.img.naturalWidth){const hh=150,ww=hh*ph.img.naturalWidth/ph.img.naturalHeight,sour=p.state==='hit'||p.ouch>0,src=(sour?ph.frown:ph.smile)||ph.img;
    // neck in the face's own skin tone, tucked under the chin
    const ng=x.createLinearGradient(-26,0,26,0);ng.addColorStop(0,shade(ph.skin,-45));ng.addColorStop(.5,ph.skin);ng.addColorStop(1,shade(ph.skin,-50));x.fillStyle=ng;x.beginPath();x.roundRect(-25,-78,50,46,8);x.fill();
    x.fillStyle='rgba(0,0,0,.25)';x.beginPath();x.ellipse(0,-66,28,9,0,0,7);x.fill();
    const RX=p.react,top=-hh-52;if(RX)RX.t++;const wob=RX?Math.max(0,1-RX.t/18)*Math.sin(RX.t*1.3)*.12:0;x.save();
    // ugly reaction: the photo itself gets squashed, stretched or knocked crooked
    if(RX){const sh=RX.shape;x.translate(0,-52);
      if(sh==='flat')x.scale(1.3+wob,.7-wob);else if(sh==='long')x.scale(.78-wob,1.28+wob);else if(sh==='wide'){x.scale(1.18+wob,.86);}
      else{x.translate(0,-hh/2);x.transform(1,0,.34,1,0,0);x.rotate(-.14+wob);x.translate(0,hh/2)}x.translate(0,52)}
    x.drawImage(src,-ww/2,top,ww,hh);x.globalCompositeOperation='source-atop';
    if(RX){const ex=ww*.2,ey=top+hh*.46,eye=(dx,c,r2)=>{const g2=x.createRadialGradient(dx,ey,1,dx,ey,r2);g2.addColorStop(0,c);g2.addColorStop(1,'rgba(60,20,70,0)');x.fillStyle=g2;x.beginPath();x.arc(dx,ey,r2,0,7);x.fill()};
      if(RX.fx==='blackeye'){eye(-ex,'rgba(40,10,50,.85)',ww*.15);eye(ex*.9,'rgba(90,20,80,.45)',ww*.12)}
      x.fillStyle='rgba(255,40,50,.35)';x.beginPath();x.ellipse(0,top+hh*.6,ww*.07,ww*.06,0,0,7);x.fill()}
    // tints and marks only on the photo's own pixels
    x.globalCompositeOperation='source-atop';
    
    if(p.tint>.02){x.fillStyle=`rgba(255,40,50,${p.tint*.35})`;x.fillRect(-ww/2,-hh-52,ww,hh)}
    if(p.ko){x.fillStyle='rgba(40,40,70,.35)';x.fillRect(-ww/2,-hh-52,ww,hh)}
    p.marks.forEach(m=>handPrint(x,m.x,m.y,m.s,m.a));
    if(p.soot){x.fillStyle=`rgba(20,15,10,${p.soot*.7})`;x.fillRect(-ww/2,-hh-52,ww,hh)}
    x.globalCompositeOperation='source-over';
    if(RX){const ex=ww*.2,ey=top+hh*.46;
      if(RX.fx==='swell')[-1,1].forEach(d=>{const cx=d*ww*.29,cy=top+hh*.64,rr=ww*.14,g2=x.createRadialGradient(cx-d*rr*.3,cy-rr*.3,2,cx,cy,rr);g2.addColorStop(0,shade(ph.skin,40));g2.addColorStop(.7,shade(ph.skin,5));g2.addColorStop(1,shade(ph.skin,-35));
        x.fillStyle=g2;x.beginPath();x.arc(cx,cy,rr,0,7);x.fill();x.fillStyle='rgba(255,60,70,.35)';x.beginPath();x.arc(cx,cy,rr*.6,0,7);x.fill()});
      if(RX.fx==='dizzy')[-1,1].forEach(d=>{const cx=d*ex,rr=ww*.1;x.fillStyle='#fff';x.strokeStyle='#1a0820';x.lineWidth=2;x.beginPath();x.arc(cx,ey,rr,0,7);x.fill();x.stroke();
        x.beginPath();for(let a=0;a<14;a+=.25){const q=a/14*rr*.9;x.lineTo(cx+Math.cos(a+T*.3*d)*q,ey+Math.sin(a+T*.3*d)*q)}x.stroke()});
      if(RX.fx==='tongue'){const ty=top+hh*.8;x.fillStyle='#e8556a';x.strokeStyle='#8a1a2a';x.lineWidth=2;x.beginPath();x.ellipse(ww*.05,ty+ww*.09,ww*.09,ww*.13,.2,0,7);x.fill();x.stroke();
        x.beginPath();x.moveTo(ww*.05,ty+ww*.02);x.lineTo(ww*.06,ty+ww*.16);x.stroke();
        [-1,1].forEach(d=>{x.fillStyle='#fff';x.beginPath();x.arc(d*ex,ey,ww*.075,0,7);x.fill();x.fillStyle='#111';x.beginPath();x.arc(d*ex+(d>0?-3:3),ey+2,ww*.03,0,7);x.fill()})}}
    x.restore()}
  // hammer reaction: a growing bump on the crown, a cross band-aid, and an "ARAY!" bubble
  if(p.bump>.02){const b=p.bump;x.save();x.translate(14,-192);const gr2=x.createRadialGradient(-6,-8,2,0,0,26*b);gr2.addColorStop(0,'#ffd0c8');gr2.addColorStop(.6,'#ff6e6e');gr2.addColorStop(1,'#c2303a');
    x.fillStyle=gr2;x.beginPath();x.ellipse(0,0,24*b,20*b,0,0,7);x.fill();x.fillStyle='rgba(255,255,255,.7)';x.beginPath();x.ellipse(-7*b,-7*b,6*b,3.5*b,-.5,0,7);x.fill();x.restore()}
  if(p.band){x.save();x.translate(-26,-112);x.fillStyle='#f3cf9c';x.strokeStyle='#c99a5a';x.lineWidth=1.5;[.6,-.6].forEach(a=>{x.save();x.rotate(a);x.beginPath();x.roundRect(-22,-7,44,14,6);x.fill();x.stroke();
    x.fillStyle='#e8bb82';x.fillRect(-6,-5,12,10);x.fillStyle='#f3cf9c';x.restore()});x.restore()}
  if(p.ouch>0){x.save();x.translate(58,-210);x.rotate(.12);x.globalAlpha=Math.min(1,p.ouch/10);x.fillStyle='#fff';x.strokeStyle='#1a0820';x.lineWidth=3;x.beginPath();x.ellipse(0,0,40,22,0,0,7);x.fill();x.stroke();
    x.beginPath();x.moveTo(-18,16);x.lineTo(-30,32);x.lineTo(-4,20);x.fill();x.fillStyle='#e2343f';x.font='22px "Lilita One", Impact';x.textAlign='center';x.fillText(p.type==='gold'?'ARAY KO!':['ARAY!','OUCH!','AWW!'][p.i%3],0,8);x.restore()}
  // party hat or crown
  if(p.hat.on&&p.pop>.05&&p.type==='gold')drawQueenCrown(x,0,-206,1);
  x.restore()}

// a queen's crown: jewelled band, pearl-tipped points, velvet cap with arches, orb and cross on top
function drawQueenCrown(g,cx,cy,k){g.save();g.translate(cx,cy);g.scale(k,k);
  const gold=(y0,y1)=>{const gr=g.createLinearGradient(0,y0,0,y1);gr.addColorStop(0,'#fff1b0');gr.addColorStop(.35,'#ffd24a');gr.addColorStop(.7,'#c88a12');gr.addColorStop(1,'#8a5a06');return gr};
  g.fillStyle='#8a1030';g.beginPath();g.moveTo(-34,0);g.bezierCurveTo(-36,-40,36,-40,34,0);g.fill();
  g.fillStyle='#ffffff';g.globalAlpha=.25;g.beginPath();g.ellipse(-12,-22,8,5,-.4,0,7);g.fill();g.globalAlpha=1;
  g.strokeStyle=gold(-48,0);g.lineWidth=5;[-1,1].forEach(d=>{g.beginPath();g.moveTo(d*32,0);g.bezierCurveTo(d*30,-34,d*8,-44,0,-44);g.stroke()});g.beginPath();g.moveTo(0,0);g.lineTo(0,-44);g.stroke();
  for(let i=0;i<5;i++){const t=i/4;[-1,1].forEach(d=>{const px=d*(32-30*t)+(d>0?0:0),py=-t*40;g.fillStyle='#fffaf0';g.beginPath();g.arc(d*(30*(1-t)+2*t),-(44*Math.sin(t*1.4)),2.6,0,7);g.fill()})}
  g.fillStyle=gold(-62,-46);g.beginPath();g.arc(0,-52,8,0,7);g.fill();g.fillStyle='#6a2fb0';g.fillRect(-7,-52,14,2.5);
  g.fillStyle=gold(-80,-58);g.fillRect(-2.5,-76,5,18);g.fillRect(-8,-70,16,5);
  const pts=[-38,-19,0,19,38];g.fillStyle=gold(-30,6);g.beginPath();g.moveTo(-42,10);g.lineTo(-42,-4);pts.forEach((px,i)=>{g.lineTo(px,-24-(i===2?6:0));g.lineTo(px+9.5,-4)});g.lineTo(42,10);g.closePath();g.fill();
  g.strokeStyle='#7a4a00';g.lineWidth=1.2;g.stroke();
  pts.forEach((px,i)=>{g.fillStyle='#fffaf0';g.beginPath();g.arc(px,-26-(i===2?6:0),3.4,0,7);g.fill()});
  g.fillStyle=gold(-6,14);g.beginPath();g.roundRect(-44,-4,88,16,4);g.fill();g.strokeStyle='#7a4a00';g.stroke();
  [['#e01e48',-30],['#1e7ae0',-15],['#1fbf6a',0],['#1e7ae0',15],['#e01e48',30]].forEach(([c,px],i)=>{g.fillStyle=c;g.beginPath();if(i%2){g.ellipse(px,4,4,5,0,0,7)}else{g.moveTo(px,-2);g.lineTo(px+5,4);g.lineTo(px,10);g.lineTo(px-5,4);g.closePath()}g.fill();
    g.fillStyle='rgba(255,255,255,.7)';g.beginPath();g.arc(px-1.5,2,1.3,0,7);g.fill()});
  g.fillStyle='#fffaf0';for(let i=0;i<13;i++){g.beginPath();g.arc(-40+i*6.66,-6,1.6,0,7);g.fill();g.beginPath();g.arc(-40+i*6.66,14,1.6,0,7);g.fill()}
  g.restore()}
function drawHands(p){if(p.type==='tnt'||p.pop<.75)return;const s=p.s,sk=PHOTOS[p.face].skin,k=(p.pop-.75)/.25;x.save();x.globalAlpha=Math.min(1,k*1.5);
  [-1,1].forEach(d=>{const hx=p.x+p.lx*.6+d*56*s,hy=p.y-12*s+(1-k)*14*s;x.save();x.translate(hx,hy);x.scale(s,s);x.rotate(d*-.12);
    const gr=x.createLinearGradient(0,-16,0,14);gr.addColorStop(0,shade(sk,30));gr.addColorStop(1,shade(sk,-35));x.fillStyle=gr;
    x.beginPath();x.ellipse(0,-2,19,12,0,0,7);x.fill();for(let i=0;i<4;i++){x.beginPath();x.roundRect(-16+i*8.5,-2,8,20-Math.abs(i-1.5)*2,4);x.fill()}
    x.strokeStyle='rgba(60,25,10,.35)';x.lineWidth=1;for(let i=1;i<4;i++){x.beginPath();x.moveTo(-16+i*8.5,2);x.lineTo(-16+i*8.5,14);x.stroke()}
    x.fillStyle='rgba(255,230,210,.6)';for(let i=0;i<4;i++){x.beginPath();x.ellipse(-12+i*8.5,14-Math.abs(i-1.5)*2,2.6,2,0,0,7);x.fill()}x.restore()});x.restore()}
// the player's mallet follows the pointer; it is raised at rest and slams down on each tap
const AIM={x:240,y:470,ax:240,ay:470,on:false,sw:0,touch:false,idle:0,ang:-.95,angV:0,sq:0,trail:[]};
// wooden barrel mallet: grained handle with a red wrapped grip, barrel head with steel bands, rivets and a ringed end cap
function malletShape(g){
  g.save();const hx=6,hy=-4,ex=74,ey=56,ha=Math.atan2(ey-hy,ex-hx),hl=Math.hypot(ex-hx,ey-hy);g.translate(hx,hy);g.rotate(ha);
  let gr=g.createLinearGradient(0,-6,0,6);gr.addColorStop(0,'#e7a35a');gr.addColorStop(.45,'#b8692a');gr.addColorStop(1,'#6e3a14');g.fillStyle=gr;g.beginPath();g.roundRect(0,-5.5,hl-18,11,5);g.fill();
  g.strokeStyle='rgba(90,40,10,.35)';g.lineWidth=1;for(let i=0;i<3;i++){g.beginPath();g.moveTo(8,-2+i*2);g.quadraticCurveTo(30,-3+i*2.5,hl-24,-1+i*2);g.stroke()}
  for(let i=0;i<5;i++){const gx=hl-34+i*6.4;gr=g.createLinearGradient(0,-7,0,7);gr.addColorStop(0,'#ff6b6b');gr.addColorStop(.5,'#d91f2e');gr.addColorStop(1,'#7a0d16');g.fillStyle=gr;g.beginPath();g.roundRect(gx,-7.5,5.6,15,2.5);g.fill()}
  g.fillStyle='#7a0d16';g.beginPath();g.ellipse(hl-2,0,4,7.5,0,0,7);g.fill();g.restore();
  g.save();g.rotate(.72);g.scale(1+AIM.sq*.3,1-AIM.sq*.25);
  // barrel body
  gr=g.createLinearGradient(-26,0,26,0);gr.addColorStop(0,'#6e3a14');gr.addColorStop(.3,'#d9893f');gr.addColorStop(.55,'#f0b06a');gr.addColorStop(1,'#7a4018');g.fillStyle=gr;
  g.beginPath();g.moveTo(-22,-40);g.quadraticCurveTo(-28,0,-22,40);g.lineTo(22,40);g.quadraticCurveTo(28,0,22,-40);g.closePath();g.fill();
  g.strokeStyle='rgba(80,35,8,.45)';g.lineWidth=1.3;[-14,-5,5,14].forEach(sx=>{g.beginPath();g.moveTo(sx,-40);g.quadraticCurveTo(sx*1.18,0,sx,40);g.stroke()});
  // back end shadow
  g.fillStyle='#5a2c0e';g.beginPath();g.ellipse(0,40,22,7,0,0,Math.PI);g.fill();
  // steel bands with rivets
  [-31,31].forEach(by=>{gr=g.createLinearGradient(-27,0,27,0);gr.addColorStop(0,'#5d6270');gr.addColorStop(.4,'#e6eaf0');gr.addColorStop(.6,'#c3c8d2');gr.addColorStop(1,'#4a4e5a');g.fillStyle=gr;
    g.beginPath();g.moveTo(-25,by-5);g.quadraticCurveTo(0,by-1,25,by-5);g.lineTo(25,by+5);g.quadraticCurveTo(0,by+9,-25,by+5);g.closePath();g.fill();
    g.fillStyle='#3c4048';[-16,0,16].forEach(rx=>{g.beginPath();g.arc(rx,by+2+(rx===0?2:0),1.8,0,7);g.fill()})});
  // front end cap with growth rings
  g.save();g.translate(0,-40);gr=g.createRadialGradient(-6,-2,2,0,0,24);gr.addColorStop(0,'#f6c88a');gr.addColorStop(1,'#c47a35');g.fillStyle=gr;g.beginPath();g.ellipse(0,0,22,7.5,0,0,7);g.fill();
  g.strokeStyle='rgba(120,60,20,.5)';g.lineWidth=1;[16,10,5].forEach(r=>{g.beginPath();g.ellipse(0,0,r,r*.34,0,0,7);g.stroke()});
  g.strokeStyle='#9aa0ad';g.lineWidth=2.5;g.beginPath();g.ellipse(0,0,22,7.5,0,0,7);g.stroke();g.restore();
  g.fillStyle='rgba(255,255,255,.28)';g.beginPath();g.ellipse(-8,-8,4,20,0,0,7);g.fill();
  g.restore()}
function drawAim(){AIM.vis=false;if(AIM.sw>0)AIM.sw--;if(AIM.touch&&AIM.sw===0){AIM.idle++;if(AIM.idle>45)return}
  if(!AIM.on&&AIM.sw===0)return;AIM.vis=true;const k=AIM.sw;
  // smooth follow with a lean toward the direction of travel
  const dx=AIM.x-AIM.ax;AIM.ax+=dx*(k?.6:.3);AIM.ay+=(AIM.y-AIM.ay)*(k?.6:.3);
  // swing: wind up, snap down past level, then spring back to the raised rest pose
  let target=-.95+(reduce?0:Math.sin(T*.12)*.06);if(k>11)target=-1.45;else if(k>8)target=.14;
  if(k===11)AIM.angV=.75;AIM.angV+=(target-AIM.ang)*(k>8?.5:.18);AIM.angV*=k>8?.55:.78;AIM.ang+=AIM.angV;
  if(k===9)AIM.sq=1;AIM.sq*=.8;
  AIM.trail.unshift(AIM.ang);AIM.trail.length=4;
  const lean=Math.max(-.35,Math.min(.35,dx*.012)),bob=reduce||k?0:Math.sin(T*.09)*3,press=k>0&&k<=9;
  x.save();x.translate(AIM.ax,AIM.ay+bob);
  x.strokeStyle=press?'rgba(255,255,255,.95)':'rgba(255,230,140,.85)';x.lineWidth=2.5;x.beginPath();x.ellipse(0,6,press?26:18+Math.sin(T*.15)*2,press?9:6,0,0,7);x.stroke();
  if(press&&k>5){const e=(9-k)/4;x.strokeStyle=`rgba(255,255,255,${1-e})`;x.lineWidth=3;x.beginPath();x.ellipse(0,6,26+e*30,9+e*10,0,0,7);x.stroke()}
  x.restore()}
function drawFlyingHat(p){const h=p.hat;if(!h.fly)return;x.save();x.translate(h.x,h.y);x.rotate(h.r);x.scale(p.s,p.s);drawQueenCrown(x,0,0,1);x.restore()}
function drawStar(cx,cy,r,c){x.fillStyle=c;x.beginPath();for(let i=0;i<10;i++){const a=i*Math.PI/5-Math.PI/2,rr=i%2?r*.45:r;x.lineTo(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr)}x.fill()}

// ---------------- game state ----------------
const GAME_T=15;let rush=0;
let T=0,playing=false,timeLeft=GAME_T,score=0,combo=0,bestCombo=0,hits=0,perfects=0,taps=0,spawnIn=40,parts=[],texts=[],swings=[],shake=0,flash=0,hitstop=0,slow=0,acc=0,best=0;
try{best=+localStorage.getItem('peryaBest')||0}catch(e){}

function hud(){$('score').textContent=score;const tl=Math.ceil(timeLeft);$('time').textContent=Math.max(0,timeLeft).toFixed(1);$('time').classList.toggle("low",tl<=3&&playing);$('combo').textContent='Combo x'+combo;$('hits').textContent='Hits '+hits}

function spawn(){if(S.filter(p=>p.state!=='down'||p.pop>.3).length>=3)return;const free=S.filter(p=>p.state==='down'&&p.pop<.05);if(!free.length)return;const p=free[Math.random()*free.length|0],prog=1-timeLeft/GAME_T;
  const r=Math.random(),el=GAME_T-timeLeft;if(goldIdx<2&&el>=goldAt[goldIdx]){p.type='gold';goldIdx++}else p.type=prog>.15&&r<.1?'tnt':'head';const busy=S.filter(q=>q!==p&&q.pop>.05).map(q=>q.face),pool=BALD.filter(k=>!busy.includes(k));p.face=pool.length?pool[Math.random()*pool.length|0]:BALD[Math.random()*BALD.length|0];
  Object.assign(p,{react:null,bump:0,bumpT:0,band:0,ouch:0,state:'up',t:0,dur:Math.round(lerp(30,10,Math.pow(prog,1.3))*(p.type==='gold'?.8:1)),popT:1,rot:0,rotV:0,lx:0,lxV:0,tint:0,ko:0,soot:0,dizzy:0,hitQ:0});
  Object.assign(p.hat,{on:true,fly:false});sfx('pop')}

function rate(rt){return rt<=22?{t:'PERFECT!',m:3,c:'#ffffff'}:rt<=40?{t:'GREAT!',m:2,c:'#5dff8a'}:{t:'GOOD',m:1,c:'#ffd23f'}}
function slap(p){const f=faceAt(p),dirv=p.x<W/2?-1:1;taps++;
  if(p.type==='tnt'){p.state='hit';p.t=0;p.soot=1;combo=0;sfx('buzz');timeLeft=Math.max(0,timeLeft-1);hits=Math.max(0,hits-2);score=hits;texts.push({t:'-2 HITS',c:'#ff5a6e',x:f.x,y:f.y-80*p.s,l:50,s:0});
    hud();return}
  const g=rate(p.t),mult=1+combo*.1,pts=p.type==='gold'?188:Math.round(10*(g.m===3?2:g.m===2?1.4:1)*mult);
  hits++;combo++;bestCombo=Math.max(bestCombo,combo);if(g.m===3)perfects++;score=hits;p.state='hit';p.t=0;p.hitQ=g.m;
  p.rotV+=-dirv*(.06+g.m*.04);p.sq=.55+g.m*.08;p.sqV=0;p.tint=1;p.dizzy=g.m>=2?120:70;p.bumpT=1;p.band=g.m>=2?1:0;p.ouch=40;p.react={shape:['flat','crooked','long','wide'][Math.random()*4|0],fx:['blackeye','swell','dizzy','tongue'][Math.random()*4|0],t:0};
  
  shake=5+g.m*4;hitstop=g.m===3?14:5;slow=g.m===3?24:0;flash=g.m===3?.9:.35;sfx('bonk');sfx('slap',.45+g.m*.12);
  if(g.m===3&&p.type==='gold'){Object.assign(p.hat,{on:false,fly:true,x:f.x,y:f.y-90*p.s,vx:-dirv*(3+Math.random()*2),vy:-10,r:0,vr:-dirv*.3,ground:p.y+40*p.s});sfx('bonk');sfx('crowd');
    for(let i=0;i<6;i++)parts.push({x:f.x,y:f.y+10,vx:-dirv*(2+Math.random()*4),vy:-3-Math.random()*3,l:60,k:'tooth',r:0,vr:.3,fl:p.y+30*p.s});}
  for(let i=0;i<10+g.m*4;i++)parts.push({x:f.x+dirv*30*p.s,y:f.y,vx:-dirv*(2+Math.random()*6),vy:-Math.random()*5-1,l:45,k:i%3?'drop':'star',r:Math.random()*6});
  for(let i=0;i<8;i++)parts.push({x:f.x,y:f.y,vx:Math.cos(i/8*6.28)*5,vy:Math.sin(i/8*6.28)*5,l:12,k:'ring'});
  // tears squirt out sideways
  for(let i=0;i<8;i++){const sd=i%2?1:-1;parts.push({x:f.x+sd*24*p.s,y:f.y-24*p.s,vx:sd*(2+Math.random()*3),vy:-2-Math.random()*2,l:40,k:'drop',r:0})}
  
  
  
  hud()}

function tap(ev){const r=cv.getBoundingClientRect(),px=(ev.clientX-r.left)/r.width*W,py=(ev.clientY-r.top)/r.height*H;AIM.x=px;AIM.y=py;AIM.on=true;AIM.sw=14;AIM.touch=ev.pointerType!=='mouse';AIM.idle=0;if(!playing)return;
  let hit=null;for(const p of S){if(p.state!=='up'||p.pop<.45)continue;const f=faceAt(p),dx=(px-f.x)/(70*p.s),dy=(py-(f.y+10*p.s))/(105*p.s);if(dx*dx+dy*dy<=1&&(!hit||p.y>hit.y))hit=p}
  if(hit){slap(hit);return}
  taps++;combo=0;sfx('miss');;hud()}

let goldIdx=0,goldAt=[2,9];
function startGame(){goldIdx=0;goldAt=[1.5+Math.random()*4,8+Math.random()*4];ac();S.forEach((p,i)=>Object.assign(p,slot(i)));timeLeft=GAME_T;score=0;combo=0;bestCombo=0;hits=0;perfects=0;taps=0;spawnIn=4;rush=0;parts=[];texts=[];swings=[];
  $('ov').hidden=true;hud();
  setTimeout(()=>{sfx('ding');playing=true},900)}
// prize by hits in one game: 300 = 188, 150 = 88, 100 = 58, 50 = 27, anything lower = 17
function prizeFor(n){return n>=300?188:n>=150?88:n>=100?58:n>=50?27:17}
function endGame(){playing=false;S.forEach(p=>{if(p.state==='up'){p.state='down';p.popT=0}});sfx('buzz');
  const newBest=false;if(newBest){best=score;try{localStorage.setItem('peryaBest',best)}catch(e){}$('best').textContent=best}
  if(newBest)sfx('crowd');
  const acc=taps?Math.round(hits/taps*100):0,stars=hits>=25?3:hits>=15?2:hits>=6?1:0;
  setTimeout(()=>{const ov=$('ov');ov.hidden=false;ov.innerHTML=`<h2>TIME UP!</h2><div style="font-size:30px;letter-spacing:4px;color:var(--gold)">${'★'.repeat(stars)}${'☆'.repeat(3-stars)}</div>
    <div class="res"><span>Hits</span><b>${hits}</b><span>Perfect hits</span><b>${perfects}</b><span>Best combo</span><b>x${bestCombo}</b><span>Accuracy</span><b>${acc}%</b></div>${window.RG?RG.resultHTML(hits):`<div style="font:400 26px var(--display);color:var(--gold)">Your reward: ${prizeFor(hits)}</div>
    <button class="btn" id="again">PLAY AGAIN</button>`}`;if(window.RG)RG.afterResult();else $('again').onclick=startGame},1800)}

function update(){T++;
  if(playing){timeLeft-=1/60;if(timeLeft<=0){timeLeft=0;hud();endGame()}else{if(--spawnIn<=0){spawn();const prog=1-timeLeft/GAME_T;spawnIn=Math.max(2,Math.round(lerp(22,3,Math.pow(prog,1.6))*(.75+Math.random()*.5)))}if(T%3===0)hud();if(!rush&&timeLeft<=5){rush=1}}}
  S.forEach(p=>{p.t++;p.rotV+=-.1*p.rot-.13*p.rotV;p.rot+=p.rotV;p.lxV+=-.1*p.lx-.18*p.lxV;p.lx+=p.lxV;p.sqV+=-.22*p.sq-.2*p.sqV;p.sq+=p.sqV;p.tint*=.96;if(p.dizzy)p.dizzy--;if(p.ouch)p.ouch--;p.bump+=((p.bumpT||0)-(p.bump||0))*.25;
    {const pr=1-timeLeft/GAME_T,sink=.45+.3*Math.pow(Math.max(0,(pr-.5)/.5),1.5);p.pop+=(p.popT-p.pop)*(p.popT<p.pop?sink:.28);}p.marks.forEach(m=>m.a=Math.max(.25,m.a-.004));
    if(p.state==='up'&&p.t>p.dur){p.state='down';p.popT=0;if(p.type!=='tnt'&&playing){combo=0;hud();const f=faceAt(p);}}
    if(p.state==='hit'){if(p.hitQ===3&&p.t<14)p.rotV+=.05*(p.x<W/2?1:-1);const hold=p.type==='tnt'?26:p.hitQ===3?22:12;if(p.t===hold){p.popT=0;p.state='down';if(p.hitQ===3){sfx('bonk');const f=faceAt(p);
      for(let i=0;i<14;i++)parts.push({x:p.x+(Math.random()-.5)*90*p.s,y:p.y,vx:(Math.random()-.5)*5,vy:-2-Math.random()*4,l:40,k:'dust',r:3+Math.random()*3})}}}
    const h=p.hat;if(h.fly){h.vy+=.45;h.x+=h.vx;h.y+=h.vy;h.r+=h.vr;if(h.y>h.ground){h.y=h.ground;h.vy*=-.35;h.vx*=.6;h.vr*=.5;if(Math.abs(h.vy)<1&&p.state==='down'&&p.pop<.1)h.fly=false}}});
  swings.forEach(w=>w.t++);swings=swings.filter(w=>w.t<16);
  parts.forEach(p=>{p.x+=p.vx;p.y+=p.vy;if(p.k==='smoke'){p.vx*=.92;p.vy*=.92;p.vy-=.05;p.r+=.4}else if(p.k==='dust'){p.vx*=.9;p.vy*=.9;p.r+=.2}else if(p.k!=='ring'&&p.k!=='spark')p.vy+=.25;
    if(p.fl&&p.y>p.fl){p.y=p.fl;p.vy*=-.4;p.vx*=.6}if(p.k==='tooth'||p.k==='coin')p.r+=.3;p.l--});parts=parts.filter(p=>p.l>0);
  texts.forEach(p=>{p.l--;p.s=Math.min(1,p.s+.15);if(!p.big)p.y-=.5});texts=texts.filter(p=>p.l>0);
  shake*=.85;if(shake<.3)shake=0;flash*=.85}

function draw(){x.save();if(shake)x.translate((Math.random()-.5)*shake,(Math.random()-.5)*shake);x.clearRect(-60,-60,W+120,H+120);
  // the five holes, back row first so the front row overlaps
  S.forEach(p=>{if(p.ouch>0&&p.type!=='tnt'&&p.fx!=null){const s=p.s;x.save();x.translate(p.fx+62*s,p.fy-92*s);x.scale(s,s);x.rotate(.12);x.globalAlpha=Math.min(1,p.ouch/10);x.fillStyle='#fff';x.strokeStyle='#1a0820';x.lineWidth=3;
    x.beginPath();x.ellipse(0,0,40,22,0,0,7);x.fill();x.stroke();x.beginPath();x.moveTo(-18,16);x.lineTo(-30,32);x.lineTo(-4,20);x.fill();x.fillStyle='#e2343f';x.font='22px "Lilita One", Impact';x.textAlign='center';
    x.fillText(p.type==='gold'?'ARAY KO!':['ARAY!','OUCH!','AWW!'][p.i%3],0,8);x.restore()}});
  S.forEach(drawFlyingHat);
  // dizzy stars over slapped heads
  S.forEach(p=>{if(p.dizzy>0&&p.pop>.3){const f=headTop(p);for(let i=0;i<3;i++){const a=T*.15+i*2.09;drawStar(f.x+Math.cos(a)*40*p.s,f.y-10*p.s+Math.sin(a)*8,6*p.s,'#ffcc33')}}});
  // the slapping hand (your photo) swinging in from the side
  swings.forEach(w=>{const p=w.p,f=headTop(p),k=w.t,sc=p.s*1.25,side=w.side;
    // mallet pivots at the hand: raised back, whips down onto the crown, then lifts away
    const ang=k<4?-1.5+k/4*1.5:k<9?0:Math.min(.8,(k-9)*.12)*-1;x.save();x.globalAlpha=k>12?1-(k-12)/4:1;
    x.translate(f.x-side*110*sc,f.y+4*sc);x.scale(side<0?-sc:sc,sc);x.rotate(-ang);
    const hg=x.createLinearGradient(0,-6,0,6);hg.addColorStop(0,'#d9a86a');hg.addColorStop(1,'#8a5a2a');x.fillStyle=hg;x.beginPath();x.roundRect(-10,-6,108,12,5);x.fill();
    x.fillStyle='#e2343f';x.beginPath();x.roundRect(-14,-8,22,16,5);x.fill();
    const mg=x.createLinearGradient(0,-34,0,34);mg.addColorStop(0,'#ff6b6b');mg.addColorStop(.5,'#e2343f');mg.addColorStop(1,'#8f1424');x.fillStyle=mg;x.beginPath();x.roundRect(92,-34,46,68,10);x.fill();
    x.fillStyle='#ffcc33';x.fillRect(92,-34,8,68);x.fillRect(130,-34,8,68);x.fillStyle='rgba(255,255,255,.35)';x.fillRect(102,-30,26,8);
    if(k>=4&&k<8&&!reduce){x.strokeStyle='rgba(255,255,255,.6)';x.lineWidth=3;for(let i=0;i<3;i++){x.beginPath();x.arc(0,0,110+i*12,-1.2,-.2);x.stroke()}}
    x.restore()})
  parts.forEach(p=>{x.globalAlpha=Math.min(1,p.l/18);if(p.k==='star')drawStar(p.x,p.y,6,'#ffcc33');else if(p.k==='drop'){x.fillStyle='#bfe8ff';x.beginPath();x.ellipse(p.x,p.y,2.4,4,Math.atan2(p.vy,p.vx)+1.57,0,7);x.fill()}
    else if(p.k==='smoke'){x.globalAlpha=p.l/70;x.fillStyle='#3a3340';x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fill()}else if(p.k==='spark'){x.fillStyle='#ffcc33';x.beginPath();x.arc(p.x,p.y,3,0,7);x.fill()}
    else if(p.k==='dust'){x.globalAlpha=p.l/40;x.fillStyle='#f3e6d0';x.beginPath();x.arc(p.x,p.y,p.r,0,7);x.fill()}
    else if(p.k==='coin'){x.fillStyle='#ffcc33';x.beginPath();x.ellipse(p.x,p.y,6*Math.abs(Math.cos(p.r)),6,0,0,7);x.fill()}
    else if(p.k==='tooth'){x.save();x.translate(p.x,p.y);x.rotate(p.r);x.fillStyle='#fffdf0';x.beginPath();x.roundRect(-4,-5,8,10,[0,0,3,3]);x.fill();x.restore()}
    else{x.strokeStyle='#fff';x.lineWidth=3;x.beginPath();x.moveTo(p.x,p.y);x.lineTo(p.x-p.vx*3,p.y-p.vy*3);x.stroke()}});x.globalAlpha=1;
  texts.forEach(p=>{const sc=(p.big?(1.7-.7*p.s):p.s)*(p.sz||1);x.save();x.translate(p.x,p.y);x.scale(sc,sc);x.rotate(p.big?-.08:0);x.globalAlpha=Math.min(1,p.l/15);
    if(p.burst){x.save();x.rotate((p.rot||0)+T*.02);x.beginPath();for(let i=0;i<24;i++){const a=i/24*6.2832,r=i%2?32:56+((i*7)%3)*5;x.lineTo(Math.cos(a)*r*1.25,Math.sin(a)*r*.78)}x.closePath();
      x.fillStyle='#ffd23f';x.fill();x.lineWidth=4;x.strokeStyle='#e0102a';x.stroke();x.restore()}
    x.font=(p.big?36:20)+'px "Lilita One", Impact';x.textAlign='center';x.lineWidth=6;x.strokeStyle='#1a0820';x.strokeText(p.t,0,10);x.fillStyle=p.c;x.fillText(p.t,0,10);x.restore()});x.globalAlpha=1;
  drawAim();x.restore();if(flash>.02){x.fillStyle=`rgba(255,255,255,${flash*.5})`;x.fillRect(0,0,W,H)}
  if(slow>0){x.fillStyle='rgba(0,0,0,.45)';x.fillRect(0,0,W,22);x.fillRect(0,H-22,W,22)}}

let lastTs=0,stepAcc=0;const STEP=1000/60;
function loop(ts){shake=0;flash=0;slow=0;hitstop=0;parts=[];ts=ts||performance.now();if(!lastTs)lastTs=ts;stepAcc+=Math.min(250,ts-lastTs);lastTs=ts;
  let n=0;while(stepAcc>=STEP&&n<15){update();stepAcc-=STEP;n++}if(n===15)stepAcc=0;
  G3.sync(S,AIM);G3.render(T,shake,reduce);draw();requestAnimationFrame(loop)}

function faceRow(){const row=$('faceRow');row.innerHTML='';BALD.map(k=>PHOTOS[k]).forEach(ph=>{const IM=ph.smile||ph.img;const c=document.createElement('canvas');c.width=c.height=112;const g=c.getContext('2d');
  if(ph.img.complete&&ph.img.naturalWidth){const k=Math.min(112/ph.img.naturalWidth,112/ph.img.naturalHeight)*1.15,w=ph.img.naturalWidth*k,h2=ph.img.naturalHeight*k;g.drawImage(IM,(112-w)/2,(112-h2)/2+4,w,h2)}row.appendChild(c)})}
cv.addEventListener('pointerdown',tap);
cv.addEventListener('pointermove',e=>{const r=cv.getBoundingClientRect();AIM.x=(e.clientX-r.left)/r.width*W;AIM.y=(e.clientY-r.top)/r.height*H;AIM.on=true;AIM.touch=e.pointerType!=='mouse';AIM.idle=0});
cv.addEventListener('pointerleave',e=>{if(e.pointerType==='mouse')AIM.on=false});
$('start').onclick=startGame;
$('snd').onclick=()=>{soundOn=!soundOn;$('snd').textContent=soundOn?'SOUND ON':'SOUND OFF';$('snd').setAttribute('aria-pressed',soundOn);if(soundOn)ac()};
addEventListener('resize',fit);// mouth corners in each photo; smile lifts them, frown pulls them down and squeezes the brows
const MOUTH={1:{x:150,y:258,w:58,s:-4},2:{x:145,y:250,w:54,s:-5},3:{x:135,y:264,w:38,s:-14},5:{x:140,y:250,w:48,s:-9}};
function mouthWarp(img,m,A,brow){const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;const g=c.getContext('2d');g.drawImage(img,0,0);
  const top=m.y-48,bot=m.y+46,x0=Math.max(0,Math.floor(m.x-m.w*1.6)),x1=Math.min(c.width,Math.ceil(m.x+m.w*1.6));g.clearRect(x0,top,x1-x0,bot-top);
  for(let xx=x0;xx<x1;xx++){const u=(xx-m.x)/m.w,fall=Math.exp(-Math.pow(u/1.5,4)),d=A*Math.min(1.3,u*u)*fall-(A>0?A*.25*fall:0);
    g.drawImage(img,xx,top,1,m.y-top,xx,top,1,Math.max(1,m.y-top+d));g.drawImage(img,xx,m.y,1,bot-m.y,xx,m.y+d,1,Math.max(1,bot-m.y-d))}
  if(brow){const by=m.y-125,bt=by-30,bb=by+28,bx0=Math.max(0,m.x-110),bx1=Math.min(c.width,m.x+110),tmp=document.createElement('canvas');tmp.width=c.width;tmp.height=c.height;tmp.getContext('2d').drawImage(c,0,0);
    g.clearRect(bx0,bt,bx1-bx0,bb-bt);for(let xx=bx0;xx<bx1;xx++){const u=Math.abs(xx-m.x)/95,d=brow*(1-1.6*Math.min(1,u))*(1-u*u*u*u>0?1:0);
      g.drawImage(tmp,xx,bt,1,by-bt,xx,bt,1,Math.max(1,by-bt+d));g.drawImage(tmp,xx,by,1,bb-by,xx,by+d,1,Math.max(1,bb-by-d))}}
  return c}
PHOTOS.forEach((p,k)=>{const make=()=>{const m=MOUTH[k];if(!m)return;p.smile=mouthWarp(p.img,m,m.s,0);p.frown=mouthWarp(p.img,m,15,8);faceRow()};if(p.img.complete&&p.img.naturalWidth)make();else p.img.addEventListener('load',make)});
PHOTOS.forEach(p=>p.img.addEventListener('load',faceRow));
// idle attract mode: heads bob up behind the start screen
S.forEach((p,i)=>{p.popT=i%3===1?1:0;p.state=i%3===1?'idle':'down'});
fit();hud();faceRow();loop();
if(document.fonts)document.fonts.ready.then(fit);
