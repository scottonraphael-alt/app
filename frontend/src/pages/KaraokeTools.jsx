import {useEffect,useRef,useState} from 'react';
import './KaraokeTools.css';
export {karaokeRequest} from './karaokeRequest';
const normalize=v=>(v||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function Draw({draw,players,serverTime}){
 const [elapsed,setElapsed]=useState(0),anchor=useRef(null);
 useEffect(()=>{anchor.current={at:performance.now(),base:Math.max(0,(serverTime||Date.now()/1000)-(draw?.starts_at||0))};
 const tick=()=>setElapsed(anchor.current.base+(performance.now()-anchor.current.at)/1000);tick();const timer=setInterval(tick,80);return()=>clearInterval(timer);
 },[draw?.id,draw?.starts_at,serverTime]);
 if(!draw)return null;
 const finished=elapsed>=draw.duration;
 return <div className={'kt-draw '+(finished?'done':'')} role="status"><small>{finished?'À vous de chanter':'La roulette tourne…'}</small><strong>{finished?draw.selected.map(p=>p.name).join(' & '):(players[Math.floor(elapsed*12)%Math.max(1,players.length)]?.name||'♪')}</strong></div>;
}
export default function KaraokeTools({session,state,library,favorites,send,plays,open,onClose}){
 const [query,setQuery]=useState(''),[lang,setLang]=useState(''),[onlyFav,setOnlyFav]=useState(false),
 [duo,setDuo]=useState(false),[excluded,setExcluded]=useState([]);
 const host=session.canControl;
 useEffect(()=>{if(open)send({type:'browse'});},[open,send]);
 useEffect(()=>{
  if(!open)return;
  const key=e=>{if(e.key==='Escape')onClose();};
  document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);
 },[open,onClose]);
 const prepared=library.filter(t=>t.prepared===true&&!t.preview);
 const tracks=prepared.filter(t=>(!onlyFav||favorites.includes(t.id))&&(!lang||t.lang===lang)&&normalize(`${t.title} ${t.artist} ${t.source}`).includes(normalize(query)));
 return <div className="kt-root">
 <Draw draw={state?.roulette} players={state?.players||[]} serverTime={state?.server_time}/>
 {open&&<div className="kt-scrim" onClick={onClose}><section className="kt-panel" role="dialog" aria-modal="true" aria-label="Catalogue et file d’attente" onClick={e=>e.stopPropagation()}><header><div><small>LE SALON MUSICAL</small><h2>À vous de chanter</h2></div><button aria-label="Fermer le catalogue" onClick={onClose}>✕</button></header>
 <div className="kt-grid"><section><h3>Catalogue <small>{prepared.length} morceaux</small></h3><input autoFocus aria-label="Rechercher une chanson" placeholder="Titre, artiste ou anime…" value={query} onChange={e=>setQuery(e.target.value)}/><div className="kt-filters"><select aria-label="Langue" value={lang} onChange={e=>setLang(e.target.value)}><option value="">Toutes les langues</option>{[...new Set(prepared.map(t=>t.lang).filter(Boolean))].map(l=><option key={l} value={l}>{l}</option>)}</select><label><input type="checkbox" checked={onlyFav} onChange={e=>setOnlyFav(e.target.checked)}/>Favoris</label></div>
 <ul className="kt-catalog">{tracks.map(t=><li key={t.id}><div><strong>{t.title}</strong><small>{t.artist}{t.lang?` · ${t.lang.toUpperCase()}`:''}</small></div><button aria-label={(favorites.includes(t.id)?'Retirer des favoris ':'Ajouter aux favoris ')+t.title} onClick={()=>send({type:'favorite',id:t.id,enabled:!favorites.includes(t.id)})}>{favorites.includes(t.id)?'★':'☆'}</button><button onClick={()=>send({type:'queue_add',id:t.id})}>Réserver</button>{host&&<button onClick={()=>{send({type:'select',id:t.id});onClose();}}>Chanter</button>}</li>)}</ul>{!tracks.length&&<p>{prepared.length?'Aucun morceau ne correspond à ta recherche.':'Aucun morceau préparé disponible pour le moment.'}</p>}
 </section><section><h3>File d’attente</h3><ol className="kt-queue">{(state?.queue||[]).map(q=><li key={q.id}><div><strong>{q.track.title}</strong><small>{q.name}</small></div>{(host||q.uid===session.userId)&&<button aria-label={'Retirer '+q.track.title} onClick={()=>send({type:'queue_remove',id:q.id})}>Retirer</button>}</li>)}</ol>{!(state?.queue||[]).length&&<p>La scène est libre. Réserve ta chanson.</p>}{host&&<button disabled={!state?.queue?.length} onClick={()=>send({type:'queue_next'})}>Lancer la prochaine réservation</button>}
 {host&&<div className="kt-roulette"><h3>Qui prend le micro ?</h3><label><input type="checkbox" checked={duo} onChange={e=>setDuo(e.target.checked)}/>Chanter en duo</label><div>{(state?.players||[]).filter(p=>p.plays).map(p=><label className="kt-exclude" key={p.id}><input type="checkbox" checked={excluded.includes(p.id)} onChange={e=>setExcluded(old=>e.target.checked?[...old,p.id]:old.filter(id=>id!==p.id))}/>Exclure {p.name}</label>)}</div><button onClick={()=>send({type:'roulette',duo,excluded})}>Lancer la roulette</button></div>}
 <p className="kt-participation">{plays?'Tu participes à la roulette.':'Tu regardes le spectacle.'}</p>
 </section></div></section></div>}
 </div>;
}
