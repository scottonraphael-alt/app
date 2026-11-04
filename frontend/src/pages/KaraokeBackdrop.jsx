import {useEffect,useRef} from 'react';
import './KaraokeBackdrop.css';
export default function KaraokeBackdrop({audioRef,theme='neon',playing}){
 const root=useRef(null);
 useEffect(()=>{
  const audio=audioRef.current;if(!audio)return;
  let context,analyser,source,frame,closed=false;
  async function start(){
   if(closed||!window.AudioContext)return;
   context=context||new window.AudioContext();
   try{await context.resume();}catch{return;}
   if(closed||context.state!=='running')return;
   if(!source){source=context.createMediaElementSource(audio);analyser=context.createAnalyser();analyser.fftSize=256;source.connect(analyser);analyser.connect(context.destination);}
   const bins=new Uint8Array(analyser.frequencyBinCount);
   const tick=()=>{if(closed)return;analyser.getByteFrequencyData(bins);const energy=bins.slice(0,32).reduce((sum,v)=>sum+v,0)/(32*255);root.current?.style.setProperty('--energy',String(energy));frame=requestAnimationFrame(tick);};
   cancelAnimationFrame(frame);tick();
  }
  audio.addEventListener('play',start);window.addEventListener('pointerdown',start,{once:true});
  return()=>{closed=true;audio.removeEventListener('play',start);window.removeEventListener('pointerdown',start);cancelAnimationFrame(frame);
   // A MediaElementSource cannot be recreated for this element. Keep its route alive
   // until its owning audio element is unmounted, then release the audio context.
   context?.close().catch(()=>{});
  };
 },[audioRef]);
 return <div ref={root} className={`kb-root kb-${theme} ${playing?'kb-playing':''}`} aria-hidden="true"><div className="kb-orbit a"/><div className="kb-orbit b"/><div className="kb-orbit c"/>{Array.from({length:18},(_,i)=><i key={i} style={{'--i':i}}/>)}</div>;
}
