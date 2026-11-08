import {useEffect,useRef} from 'react';
import { preparedEnergy, readEnergy } from './karaokeAudio';
import './KaraokeBackdrop.css';

export default function KaraokeBackdrop({audioRef,graphRef,energyMap,visualRef,theme='neon',playing}){
 const root=useRef(null);
 useEffect(()=>{
  let frame, lastTick=0, average=.1, lastBurst=-10, lastTime=0;
  let smoothEnergy=0,smoothVoice=0,smoothTension=0;
  const visual=visualRef?.current, host=root.current, effects=new Set();
  const animate=(node,frames,options)=>{const effect=node?.animate?.(frames,options);if(effect){effects.add(effect);effect.onfinish=()=>effects.delete(effect);effect.oncancel=()=>effects.delete(effect);}};
  const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const buffers=()=>({wave:new Float32Array(1024),bins:new Uint8Array(512)});
  const main=buffers(), inst=buffers(), voice=buffers();
  const tick=stamp=>{
   frame=requestAnimationFrame(tick);
   if(stamp-lastTick<33)return;
   const dt=Math.min(.15,Math.max(.001,(stamp-lastTick)/1000));
   lastTick=stamp;
   const audio=audioRef.current, time=audio?.currentTime||0;
   const active=audio&&!audio.paused&&!audio.ended;
   const reduced=media?.matches;
   let energy=0,vocals=0,tension=0,drop=false;
   if(active&&!reduced){
    const prepared=preparedEnergy(energyMap,time);
    if(prepared){energy=Math.min(1,prepared.energy+(prepared.beat ? .035 : 0));vocals=prepared.vocals;tension=prepared.tension;drop=prepared.drop;}
    else{
     const channels=graphRef?.current?.channels;
     const separated=Boolean(channels&&channels[1].gain.gain.value>.001);
     const measured=readEnergy(channels?.[separated?1:0]?.analyser,separated?inst:main);
     energy=measured.energy;
     vocals=separated?readEnergy(channels[2].analyser,voice).energy:0;
     average=average*.97+energy*.03;
     drop=energy>Math.max(.5,average*1.8)&&energy-average>.2&&measured.bass>.35;
    }
   }
   if(time<lastTime-.5){average=.1;lastBurst=stamp/1000;}
   lastTime=time;
   const ease=(current,target,attack,release)=>current+(target-current)*(1-Math.exp(-dt/(target>current?attack:release)));
   smoothEnergy=ease(smoothEnergy,energy,.32,1.1);
   smoothVoice=ease(smoothVoice,vocals,.16,.65);
   smoothTension=ease(smoothTension,tension,.65,1.2);
   root.current?.style.setProperty('--energy',String(smoothEnergy));
   root.current?.style.setProperty('--tension',String(smoothTension));
   visualRef?.current?.style.setProperty('--vocal-energy',String(smoothVoice));
   if(drop&&stamp/1000-lastBurst>7){
    lastBurst=stamp/1000;
    const burst=root.current?.querySelector('.kb-burst');
    animate(burst,[{opacity:0,transform:'scale(.3)'},{opacity:.08,offset:.3},{opacity:0,transform:'scale(1.8)'}],{duration:2200,easing:'ease-in-out'});
    root.current?.querySelectorAll('.kb-spark').forEach((spark,i)=>animate(spark,
     [{opacity:.24,transform:'translate(0,0) scale(1)'},{opacity:0,transform:`translate(${Math.cos(i*Math.PI/6)*230}px,${Math.sin(i*Math.PI/6)*160}px) scale(0)`}],{duration:2000,easing:'ease-out'}));
   }
  };
  frame=requestAnimationFrame(tick);
  return()=>{cancelAnimationFrame(frame);visual?.style.setProperty('--vocal-energy','0');host?.style.setProperty('--energy','0');effects.forEach(animation=>animation.cancel());};
 },[audioRef,graphRef,energyMap,visualRef]);
 return <div ref={root} className={`kb-root kb-${theme} ${playing?'kb-playing':''}`} aria-hidden="true">
  <div className="kb-orbit a"/><div className="kb-orbit b"/><div className="kb-orbit c"/>
  <div className="kb-burst"/>{Array.from({length:12},(_,i)=><b className="kb-spark" key={i}/>)}
  {Array.from({length:18},(_,i)=><i key={i} style={{'--i':i}}/>)}
 </div>;
}
