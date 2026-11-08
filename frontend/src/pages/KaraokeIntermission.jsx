import {useEffect,useState} from 'react';
import KaraokeScore from './KaraokeScore';
export default function KaraokeIntermission({value,score,canControl,send,onRankings}){
 const [now,setNow]=useState(Date.now()/1000);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),250);return()=>clearInterval(timer);},[]);
 if(!value)return null;
 const remaining=Math.max(0,Math.ceil(value.paused?value.remaining:value.deadline-now));
 return <div className="ki-scrim"><section className="ki-card" role="region" aria-label="Chanson terminée">
  <span>FIN DU MORCEAU</span><h2>Bravo pour la chanson !</h2>
  {score&&<KaraokeScore score={score}/>}
  <div className="ki-time">{value.paused?'En pause':`${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')}`}</div>
  <p>{value.paused?'Le lancement automatique est suspendu.':'Le prochain morceau démarre à la fin du compte à rebours.'}</p>
  {canControl&&<button className="kc-badge ki-next" onClick={()=>send({type:'next_song',id:value.id})}>Passer au suivant →</button>}
  {onRankings&&<button className="kc-badge" onClick={onRankings}>Voir les classements</button>}
  <button className="kc-badge" aria-pressed={value.paused} onClick={()=>send({type:'autoplay_pause',id:value.id,paused:!value.paused})}>{value.paused?'▶ Reprendre le compte à rebours':'Ⅱ Mettre en pause'}</button>
 </section></div>;
}
