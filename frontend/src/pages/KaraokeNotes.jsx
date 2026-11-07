import {useEffect,useRef} from 'react';
import {karaokeRequest} from './KaraokeTools';

const name=midi=>['Do','Do♯','Ré','Ré♯','Mi','Fa','Fa♯','Sol','Sol♯','La','La♯','Si'][((Math.round(midi)%12)+12)%12]+(Math.floor(midi/12)-1);
export default function KaraokeNotes({notes,audioRef,octave,session,consented,score}){
 const canvas=useRef(null),own=useRef(null);
 const token=session.videoToken,apiRoot=session.apiRoot,instanceId=session.instanceId;
 useEffect(()=>{
  if(!consented){own.current=null;return;}
  let live=true,controller=null,pending=false;
  const poll=async()=>{
   if(pending)return;pending=true;
   controller=new AbortController();
   try{const value=await karaokeRequest({videoToken:token,apiRoot},'/voice/pitch',{query:{instance_id:instanceId},signal:controller.signal});if(live)own.current={...value,at:performance.now()};}catch{if(live)own.current=null;}finally{pending=false;}
  };
  poll();const timer=setInterval(poll,400);
  return()=>{live=false;controller?.abort();clearInterval(timer);own.current=null;};
 },[token,apiRoot,instanceId,consented]);
 useEffect(()=>{
  const element=canvas.current;
  if(!element||!notes?.length)return;
  const context=element.getContext('2d');if(!context)return;
  let frame,previous=0;
  const pitch=notes.map(note=>note.midi+octave*12);
  const min=Math.min(...pitch)-2,max=Math.max(...pitch)+2;
  const paint=stamp=>{
   frame=requestAnimationFrame(paint);if(stamp-previous<33)return;previous=stamp;
   const width=element.clientWidth,height=element.clientHeight,ratio=Math.min(window.devicePixelRatio||1,2);
   if(element.width!==width*ratio||element.height!==height*ratio){element.width=width*ratio;element.height=height*ratio;}
   context.setTransform(ratio,0,0,ratio,0,0);context.clearRect(0,0,width,height);
   const y=midi=>height-18-(midi-min)/(max-min)*(height-36),now=audioRef.current?.currentTime||0;
   const anchor=width*.24,scale=(width-anchor)/8;
   context.font='10px system-ui';
   for(let midi=Math.ceil(min);midi<=max;midi++){
    context.strokeStyle='rgba(255,255,255,.09)';context.beginPath();context.moveTo(38,y(midi));context.lineTo(width,y(midi));context.stroke();
    if(midi%Math.max(2,Math.ceil((max-min)/8))===0){context.fillStyle='#c7bddc';context.fillText(name(midi),3,y(midi)+3);}
   }
   for(const note of notes){
    if(note.e<now-3||note.s>now+8)continue;
    const left=Math.max(39,anchor+(note.s-now)*scale),right=Math.min(width,anchor+(note.e-now)*scale);
    if(right<=left)continue;
    context.fillStyle=note.e<now?'#ff7dc8':'#a6e2cd';
    context.fillRect(left,y(note.midi+octave*12)-3,Math.max(2,right-left-1),6);
   }
   context.strokeStyle='#fff';context.beginPath();context.moveTo(anchor,8);context.lineTo(anchor,height-8);context.stroke();
   const live=own.current;
   if(live&&performance.now()-live.at<1800){
    context.fillStyle='#ffd75e';
    for(const brick of live.history||[]){
     if(brick.e<now-3||brick.s>now+.2||!(brick.pitch>0))continue;
     const left=Math.max(39,anchor+(brick.s-now)*scale),right=Math.min(width,anchor+(brick.e-now)*scale);
     if(right<=left)continue;
     const midi=69+12*Math.log2(brick.pitch/440);
     context.fillRect(left,Math.max(9,Math.min(height-9,y(midi)))-3,Math.max(2,right-left-.5),6);
    }
   }
  };
  frame=requestAnimationFrame(paint);return()=>cancelAnimationFrame(frame);
 },[notes,audioRef,octave]);
 return <section className="kn-root" aria-label="Guide de mélodie" style={{position:"relative",zIndex:1,flexShrink:0,padding:'8px 16px',border:'1px solid #ffffff25',borderRadius:12,background:'#100e25aa'}}>
  <div style={{display:'flex',justifyContent:'space-between',gap:12,fontSize:12}}>
   <span>Guide mélodique · extraction automatique</span>
   {score?.pitch!=null?<span style={{display:"flex",alignItems:"center",gap:8}}><progress aria-label="Justesse vocale indicative" max="100" value={score.pitch} style={{width:70,height:8,accentColor:"#ffae57"}}/><strong>Justesse : {score.pitch} % · score indicatif</strong></span>:<span>{consented?'Ta voix : briques jaunes':'Guide de référence · sans micro'}</span>}
  </div>
  {score?.techniques && <p style={{fontSize:11,opacity:.75,margin:'4px 0'}}>Techniques indicatives · vibratos : {score.techniques.vibrato} · glissandos : {score.techniques.glissando}</p>}
  <canvas className="kn-canvas" ref={canvas} style={{display:'block',width:'100%',height:130}} role="img" aria-label="Notes de référence et historique vocal jaune ; le repère blanc marque le présent"/>
 </section>;
}
