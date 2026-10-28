// Effect thumbnails: a tiny live preview of each lane's current effect, drawn on the
// prop's own (front-view) points with the chosen colours and parameters. Generic, so
// it shows what seqtool means, not a pixel-exact xLights render.
const THUMB_W=34,THUMB_H=18;
function _hash(a,b){let h=(a*374761393+b*668265263)|0;h=(h^(h>>>13))*1274126177|0;return((h^(h>>>16))>>>0)/4294967295;}
function _hex(c){c=(c||'#ffffff').replace('#','');return[parseInt(c.slice(0,2),16),parseInt(c.slice(2,4),16),parseInt(c.slice(4,6),16)];}
function _mix(a,b,f){return[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f,a[2]+(b[2]-a[2])*f];}
function _pv(v,f){if(v&&typeof v==='object'&&v.ramp)return v.ramp[0]+(v.ramp[1]-v.ramp[0])*f;return typeof v==='number'?v:(v==null?0.5:v);}
function _frac(x){return x-Math.floor(x);}
// -> [r,g,b,brightness] for point k at (x,y) in 0..1, effect time ph (s) of len (s)
function effectColor(eff,P,cols,k,n,x,y,ph,len,beat){
  const C=cols.map(_hex),c0=C[0]||[255,255,255],f=len>0?Math.min(1,ph/len):0,p=(key,d)=>{const v=P[key];return v==null?d:_pv(v,f);};
  switch(eff){
    case 'off':case 'transparent':case 'dark':return[0,0,0,0];
    case 'color_wash':{const sp=p('transition_speed',0.3)*0.6,t=_frac(ph*sp),i=Math.floor(t*C.length),j=(i+1)%C.length;
      return[..._mix(C[i%C.length]||c0,C[j]||c0,_frac(t*C.length)),p('brightness',0.9)];}
    case 'pulse':{let l;if(P.start_level!=null){const a=p('start_level',1),b=p('end_level',0);l=a+(b-a)*f;}
      else l=1-_frac(ph/beat)*(1-p('intensity',0.8)*0.3);return[...c0,Math.max(0,l)];}
    case 'chase':{const sp=0.5+p('speed',0.6)*2,w=Math.max(0.06,p('width',0.3)*0.5);let pos=_frac(ph*sp/1.5);
      if(P.direction==='bounce')pos=1-Math.abs(1-2*pos);const u=P.direction==='reverse'?1-k/n:k/n;
      return Math.abs(u-pos)<w/2||Math.abs(u-pos)>1-w/2?[...c0,1]:[0,0,0,0];}
    case 'bars':{const cnt=1+Math.round(p('count',0.5)*4),sp=p('speed',0.5)*1.5,d=P.direction||'up';
      const u=(d==='left'||d==='right')?x:(d==='expand'||d==='compress')?Math.abs(y-0.5)*2:y,s=(d==='down'||d==='left'||d==='compress')?-1:1;
      const v=_frac(u*cnt-s*ph*sp);const i=Math.floor(u*cnt-s*ph*sp);return[...(C[((i%C.length)+C.length)%C.length]||c0),v<0.7?1:0.15];}
    case 'wipe':{const sp=0.3+p('speed',0.5),pos=_frac(ph*sp/2),d=P.direction||'left';
      const u=d==='right'?1-x:d==='center_out'?Math.abs(x-0.5)*2:d==='edges_in'?1-Math.abs(x-0.5)*2:x;return u<pos?[...c0,1]:[0,0,0,0];}
    case 'spirals':case 'pinwheel':{const a=Math.atan2(y-0.5,x-0.5)/(2*Math.PI)+0.5,arms=1+Math.round(p('arms',0.4)*(eff==='spirals'?4:7)),
      rot=(P.direction==='clockwise'?-1:1)*(0.3+p('rotation_speed',0.5)*1.5),tw=eff==='spirals'?y:Math.hypot(x-0.5,y-0.5)*0.4;
      const v=_frac(a*arms+tw-ph*rot*0.5);const i=Math.floor(a*arms+tw-ph*rot*0.5);
      return v<(eff==='spirals'?Math.max(0.2,p('thickness',0.5)):0.5)?[...(C[((i%C.length)+C.length)%C.length]||c0),1]:[0,0,0,0];}
    case 'twinkle':{const h=_hash(k,7),on=h<0.15+p('density',0.4)*0.8,r=0.5+p('rate',0.4)*2;
      return on?[...(C[k%C.length]||c0),Math.max(0,Math.sin(ph*r*4+h*40))]:[0,0,0,0];}
    case 'sparkles':{const fr=Math.floor(ph*(6+p('rate',0.6)*20));return _hash(k,fr)<0.25+p('intensity',0.7)*0.4?[...c0,1]:[...c0,0.15];}
    case 'meteors':{const sp=0.3+p('speed',0.5)*1.2,col=Math.floor(x*8),d=P.direction||'down',s=d==='up'?-1:1;
      const v=_frac((d==='left'||d==='right'?x:y)*s+ph*sp+_hash(col,3));const tr=0.1+p('trail',0.5)*0.4;
      return v<tr?[...(C[col%C.length]||c0),1-v/tr]:[0,0,0,0];}
    case 'fire':{const h=0.35+p('height',0.6)*0.65,fl=_hash(k,Math.floor(ph*12))*0.35;const v=1-y/h-fl;
      return v>0?[255,Math.min(255,80+v*170),Math.max(0,v*60),Math.min(1,v*1.5+0.2)]:[0,0,0,0];}
    case 'fill':{const pos=p('position',0.6),u=P.direction==='down'?1-y:y;return u<=pos?[...c0,1]:[0,0,0,0];}
    case 'face':{const e=Math.hypot(x-0.35,y-0.33)<0.09||Math.hypot(x-0.65,y-0.33)<0.09,o=0.04+0.12*Math.abs(Math.sin(ph*9)),m=((x-0.5)/0.2)**2+((y-0.68)/o)**2<=1;return (e||m)?[...c0,1]:[0,0,0,0];}
    case 'vu_meter':{const b=Math.floor(x*10),hgt=0.3+0.6*Math.abs(Math.sin(ph*7+b*1.7))*p('sensitivity',0.7);return y<hgt?[...c0,1]:[0,0,0,0];}
    default:return[...c0,0.6];
  }
}
function drawThumb(ctx,x0,y0,lane,t,beat,W,H,fixedSeg){
  W=W||THUMB_W;H=H||THUMB_H;
  ctx.fillStyle='#000';ctx.fillRect(x0,y0,W,H);
  const pts=lane&&lane.shape;if(!pts||!pts.length)return;
  const seg=fixedSeg||lane.segments.find(g=>g.start<=t&&t<g.end);if(!seg)return;
  const len=seg.end-seg.start,loop=fixedSeg||au.paused,ph=loop?(performance.now()/1000)%Math.max(0.5,len):t-seg.start;
  const n=pts.length,big=W>80,r=big?Math.max(2,Math.min(7,Math.sqrt(W*H/n)*0.55)):Math.max(1,Math.min(2.2,Math.sqrt(W*H/n)*0.45));
  for(let k=0;k<n;k++){const [px,py]=pts[k];
    const c=effectColor(seg.effect,seg.params||{},seg.colors||['#FFFFFF'],k,n,px,py,ph,len,beat);
    if(c[3]<=0.02)continue;const b=Math.min(1,c[3]);
    ctx.fillStyle=`rgb(${c[0]*b|0},${c[1]*b|0},${c[2]*b|0})`;
    const cx=x0+r+px*(W-2*r),cy=y0+H-r-py*(H-2*r);
    if(big){ctx.beginPath();ctx.arc(cx,cy,r/2,0,6.283);ctx.fill();}else ctx.fillRect(cx-r/2,cy-r/2,r,r);}
  if(big){ctx.fillStyle='#fffa';ctx.font='11px system-ui';ctx.fillText(`${seg.effect}  ${seg.start.toFixed(1)}-${seg.end.toFixed(1)} s`,x0+6,y0+14);}
}
// Larger previews: hovering a small thumbnail shows a big one next to the pointer; the
// explanation panel shows the clicked effect (or the lane's current one) above its text.
const BIG_W=300,BIG_H=180;let hoverLane=null,panelPreview=null;
function previewTick(){
  const beat=60/(D&&D.tempo||120),t=au.currentTime||0;
  const hv=document.getElementById('hoverthumb');
  if(hoverLane&&hv){hv.style.display='block';drawThumb(hv.getContext('2d'),0,0,hoverLane,t,beat,BIG_W,BIG_H);}
  else if(hv)hv.style.display='none';
  const pv=document.getElementById('panelthumb');
  if(pv){const show=panelPreview&&document.getElementById('panel').style.display==='block'&&panelPreview.lane.shape&&panelPreview.lane.shape.length;
    pv.style.display=show?'block':'none';
    if(show)drawThumb(pv.getContext('2d'),0,0,panelPreview.lane,t,beat,BIG_W,BIG_H,panelPreview.seg);}
}
function showPanel(text,lane,seg){setTagged(document.getElementById('exp'),text);panelPreview=lane&&!(seg&&['off','transparent','dark'].includes(seg.effect))?{lane,seg}:null;
  document.getElementById('panel').style.display='block';previewTick();}

// Inline colour codes ({ok}...{/}, see common/color.py) -> coloured spans.
const TAG_CLASS={err:'c-red',warn:'c-yellow',ok:'c-green',do:'c-pink',note:'c-blue',head:'c-teal',b:'c-bold',
  red:'c-red',yellow:'c-yellow',green:'c-green',pink:'c-pink',blue:'c-blue',teal:'c-teal',bold:'c-bold'};
const TAG_RE=/\{(err|warn|ok|do|note|head|b|red|yellow|green|pink|blue|teal|bold|copy|#[0-9A-Fa-f]{6}|\/)\}/g;   // {#RRGGBB}: 0.24.25
TAG_CLASS.copy='c-copy';
function copyText(t,b){                              // the clipboard, with the old way as a fallback; b: the button to say 'Copied'
  const done=()=>{if(!b)return;const was=b.textContent;b.textContent='Copied';setTimeout(()=>b.textContent=was,1500);};
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(done,()=>{
    const ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');done();}catch(e){}ta.remove();});}
function copyBox(el){                                  // {copy}...{/}: a box with a Copy button (0.19.2)
  const box=document.createElement('span');box.className='copybox';
  const b=document.createElement('button');b.className='copybtn';b.textContent='Copy';
  const body=document.createElement('span');body.className='copytext';
  b.onclick=ev=>{ev.stopPropagation();copyText(body.textContent,b);};
  box.appendChild(b);box.appendChild(body);el.appendChild(box);return body;}
function appendTagged(el,text,stack,extraCls){       // stack: open classes, kept by the caller across calls
  stack=stack||[];let last=0,m,into=el;TAG_RE.lastIndex=0;
  const put=s=>{if(!s)return;const sp=document.createElement('span');const c=stack.filter(x=>x[0]!=='#');if(extraCls)c.push(extraCls);
    const hx=[...stack].reverse().find(x=>x[0]==='#');if(hx)sp.style.color=hx;
    if(c.length)sp.className=c.join(' ');sp.textContent=s;into.appendChild(sp);};
  while((m=TAG_RE.exec(text))){put(text.slice(last,m.index));last=TAG_RE.lastIndex;
    if(m[1]==='/'){if(stack.pop()==='c-copy')into=el;}
    else{stack.push(m[1][0]==='#'?m[1]:TAG_CLASS[m[1]]);if(m[1]==='copy')into=copyBox(el);}}
  put(text.slice(last));return stack;}
function setTagged(el,text){el.textContent='';appendTagged(el,text,[]);}
function plainText(text){return String(text).replace(TAG_RE,'');}

// waveform colours as in trackED: vocals green, instrumental blue, mixed teal
// (D.vocal_regions: [[start, end, v/m/i]] from music/vocals.py)
function waveColor(i,n,plain){
  const R=D.vocal_regions;
  if(!R||!R.length)return plain;
  const t=D.peaks_step?(i+0.5)*D.peaks_step:(i+0.5)/n*D.duration;   // 0.24.19: the bucket's real time
  let j=waveColor.j||0;if(j>=R.length||R[j][0]>t)j=0;           // columns are drawn left to right
  while(j<R.length-1&&R[j][1]<=t)j++;waveColor.j=j;
  const c={v:'--wv-voc',i:'--wv-ins',m:'--wv-mix'}[R[j][2]];
  return getComputedStyle(document.documentElement).getPropertyValue(c).trim()||plain;
}
function vocalLegend(){
  if(!D.vocal_regions||!D.vocal_regions.length)return '';
  return '<span style="color:var(--wv-voc)">&#9632; vocals</span><span style="color:var(--wv-mix)">&#9632; mixed</span>'+
         '<span style="color:var(--wv-ins)">&#9632; instrumental</span>';
}
// small icons on effects: a push-pin (solid = pinned) and a die (new random choices)
function drawPinIcon(ctx,x,y,on){
  const c=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()||'#ffd34d';
  ctx.save();ctx.translate(x,y);
  ctx.fillStyle=on?c:'#0008';ctx.strokeStyle=on?'#000':c;ctx.lineWidth=1;
  ctx.beginPath();ctx.arc(5,4,3.6,0,7);ctx.fill();ctx.stroke();                         // head
  ctx.beginPath();ctx.moveTo(2,6.5);ctx.lineTo(8,6.5);ctx.lineTo(5,9);ctx.closePath();ctx.fill();ctx.stroke();
  ctx.strokeStyle=on?c:'#ddd';ctx.lineWidth=1.4;ctx.beginPath();ctx.moveTo(5,9);ctx.lineTo(5,13);ctx.stroke();  // needle
  ctx.restore();
}
function drawDieIcon(ctx,x,y){
  ctx.save();ctx.translate(x,y);ctx.fillStyle='#fff';ctx.strokeStyle='#000';ctx.lineWidth=1;
  ctx.beginPath();if(ctx.roundRect)ctx.roundRect(0.5,0.5,12,12,2.5);else ctx.rect(0.5,0.5,12,12);ctx.fill();ctx.stroke();
  ctx.fillStyle='#000';[[3.5,3.5],[9.5,3.5],[6.5,6.5],[3.5,9.5],[9.5,9.5]].forEach(([a,b])=>{ctx.beginPath();ctx.arc(a,b,1.2,0,7);ctx.fill();});
  ctx.restore();
}

// the passages again, in the page (same rules as music/vocals.py), for the vocal sliders
function vocalRegions(L,P){
  const n=L.stem.length,fi=L.fi,k=Math.max(0,Math.round(P.gap/2/fi)),gate=(P.gate==='auto'?L.auto_gate:+P.gate);
  const loud=L.stem.map(x=>x>=gate),wide=new Array(n),sing=new Array(n),cls=new Array(n);
  const win=(arr,i,f)=>{let r=f==='max'?false:true;for(let j=Math.max(0,i-k);j<=Math.min(n-1,i+k);j++)r=f==='max'?(r||arr[j]):(r&&arr[j]);return r;};
  for(let i=0;i<n;i++)wide[i]=win(loud,i,'max');                 // close gaps between words (widen, shrink back)
  for(let i=0;i<n;i++)sing[i]=win(wide,i,'min');
  for(let i=0;i<n;i++)cls[i]=!sing[i]?'i':(L.stem[i]-L.mix[i]>=P.lead?'v':'m');
  let runs=[];for(let i=0;i<n;i++){const r=runs[runs.length-1];if(r&&r[2]===cls[i])r[1]=(i+1)*fi;else runs.push([i*fi,(i+1)*fi,cls[i]]);}
  while(runs.length>1){let j=0;for(let r=1;r<runs.length;r++)if(runs[r][1]-runs[r][0]<runs[j][1]-runs[j][0])j=r;
    if(runs[j][1]-runs[j][0]>=P.min_region)break;
    const l=j>0?runs[j-1]:null,rt=j+1<runs.length?runs[j+1]:null;
    const into=(!rt||(l&&l[1]-l[0]>=rt[1]-rt[0]))?l:rt;runs[j][2]=into[2];
    const m=[];runs.forEach(r=>{const t=m[m.length-1];if(t&&t[2]===r[2])t[1]=r[1];else m.push(r.slice());});runs=m;}
  return runs;
}
