import {useEffect,useRef,useState} from 'react';
import './KaraokeScore.css';
const format=value=>Math.round(value||0).toLocaleString('fr-FR');
export default function KaraokeScore({score}){
 const previous=useRef(null),[shown,setShown]=useState(score?.points||0),[award,setAward]=useState(null);
 const points=score?.points||0,maximum=score?.points_max||0,run=score?.run_id;
 useEffect(()=>{
  const before=previous.current;
  previous.current={points,maximum,run};
  if(!before||before.run!==run||points<before.points){setShown(points);setAward(null);return;}
  const delta=points-before.points,possible=maximum-before.maximum;
  if(delta<=0)return;
  setAward({value:delta,tier:possible>0&&delta>=possible?'perfect':possible>0&&delta>possible/2?'good':'low',id:Date.now()});
  let frame,start;
  const tick=now=>{start??=now;const p=Math.min(1,(now-start)/650);setShown(before.points+delta*(1-Math.pow(1-p,3)));if(p<1)frame=requestAnimationFrame(tick);};
  frame=requestAnimationFrame(tick);
  const timer=setTimeout(()=>setAward(null),1500);
  return()=>{cancelAnimationFrame(frame);clearTimeout(timer);};
 },[points,maximum,run]);
 return <div className="ks-counter" aria-label="Points de chant">
  <span className="ks-star" aria-hidden="true">✦</span><strong>{format(shown)}</strong><span className="ks-unit">PTS</span>
  {award&&<span key={award.id} className={'ks-award ks-'+award.tier}>+{format(award.value)}<small>{award.tier==='perfect'?'Parfait !':award.tier==='good'?'Bien joué !':'Continue !'}</small></span>}
 </div>;
}
