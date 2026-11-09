import {lazy,Suspense,useEffect,useState} from 'react';
const Cinema=lazy(()=>import('./ActivityPage'));
const Games=lazy(()=>import('./OasisGamePage'));
export default function DiscordActivityEntry(){
 const explicit=window.location.pathname.startsWith('/games');
 const [games,setGames]=useState(explicit?true:null);
 useEffect(()=>{
  if(explicit)return;
  let live=true;
  fetch('/.proxy/backend/api/games/config').then(r=>r.ok?r.json():{}).then(config=>{if(live)setGames(Boolean(config.client_id&&window.location.hostname.split('.')[0]===config.client_id));}).catch(()=>{if(live)setGames(false);});
  return()=>{live=false;};
 },[explicit]);
 if(games===null)return <p role="status">Ouverture de l’activité…</p>;
 return <Suspense fallback={<p role="status">Ouverture de l’activité…</p>}>{games?<Games/>:<Cinema/>}</Suspense>;
}
