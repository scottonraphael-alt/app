import {useEffect,useState} from 'react';
export default function KaraokeWelcome({value,players=[],plays,setPlays,onCatalog,onRankings}){
 const [now,setNow]=useState(Date.now()/1000);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),250);return()=>clearInterval(timer);},[]);
 if(!value)return null;
 const remaining=Math.max(0,Math.ceil(value.deadline-now)),joined=players.filter(player=>player.plays);
 return <div className="ki-scrim kw-scrim"><section className="ki-card kw-card" aria-label="Accueil du karaoké">
  <span>LE SALON MUSICAL</span><div className="kw-symbol" aria-hidden="true">♫</div><h2>À vous de chanter</h2>
  <p>Rejoins la scène. Le premier morceau démarre dans quelques instants.</p>
  <div className="kw-countdown">{remaining}<small>secondes</small></div>
  <button className={'kc-badge ki-next '+(plays?'kc-selected':'')} aria-pressed={plays} onClick={()=>setPlays(v=>!v)}>{plays?'✓ Je participe':'Je participe'}</button>
  <div className="kw-players">{joined.length?joined.map(player=><span key={player.id}>{player.name}</span>):<span>La scène vous attend…</span>}</div>
  <div><button className="kc-badge" onClick={onCatalog}>Catalogue</button><button className="kc-badge" onClick={onRankings}>Classements</button></div>
 </section></div>;
}
