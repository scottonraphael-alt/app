import {useEffect,useRef,useState} from 'react';
import './KaraokeTools.css';
const ROOT='/.proxy/backend/api';
const normalize=v=>(v||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
export async function karaokeRequest(session,path,options={}){
 const query=new URLSearchParams({t:session.videoToken,...options.query});
 const body=options.body;
 const response=await fetch(`${session.apiRoot||ROOT}/activity/karaoke${path}?${query}`,{
 method:options.method||'GET',headers:body instanceof FormData?{}:body?{'Content-Type':'application/json'}:{},
 body:body instanceof FormData?body:body?JSON.stringify(body):undefined});
 const data=await response.json();
 if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Action indisponible.');
 return data;
}
function Draw({draw,players,serverTime}){
 const [elapsed,setElapsed]=useState(0),anchor=useRef(null);
 useEffect(()=>{anchor.current={at:performance.now(),base:Math.max(0,(serverTime||Date.now()/1000)-(draw?.starts_at||0))};
 const tick=()=>setElapsed(anchor.current.base+(performance.now()-anchor.current.at)/1000);tick();const timer=setInterval(tick,80);return()=>clearInterval(timer);
 },[draw?.id,draw?.starts_at,serverTime]);
 if(!draw)return null;
 const finished=elapsed>=draw.duration;
 return <div className={'kt-draw '+(finished?'done':'')} role="status"><small>{finished?'À vous de chanter':'La roulette tourne…'}</small><strong>{finished?draw.selected.map(p=>p.name).join(' & '):(players[Math.floor(elapsed*12)%Math.max(1,players.length)]?.name||'♪')}</strong></div>;
}
export default function KaraokeTools({session,state,library,favorites,send,setLibrary,track,plays,setPlays,onPrepared}){
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[lang,setLang]=useState(''),[source,setSource]=useState(''),[onlyFav,setOnlyFav]=useState(false),
 [duo,setDuo]=useState(false),[excluded,setExcluded]=useState([]),[error,setError]=useState(''),[notice,setNotice]=useState(''),
 [voice,setVoice]=useState(null),[latency,setLatency]=useState(0),[channel,setChannel]=useState(session.channelId||''),[prep,setPrep]=useState(null),[busy,setBusy]=useState(false);
 const host=session.canControl;
 const trackId=track?.id, preview=track?.preview;
 useEffect(()=>{if(state?.mode==='karaoke')send({type:'browse'});},[send,state?.mode]);
 useEffect(()=>{let live=true;async function refresh(){try{
 const v=await karaokeRequest(session,'/voice/status',{query:{instance_id:session.instanceId}});if(live)setVoice(v);
 if(trackId&&!preview){const p=await karaokeRequest(session,'/preparation',{query:{id:trackId}});if(live)setPrep(p);}
 }catch(e){if(live)setError(e.message);}}
 refresh();const timer=setInterval(refresh,3000);return()=>{live=false;clearInterval(timer);};},[session,trackId,preview]);
 useEffect(()=>{if(prep?.status==='ready'){send({type:'browse'});onPrepared?.();}},[prep?.status,track?.id,send,onPrepared]);
 async function action(path,body,queryParams={}){setBusy(true);setError('');setNotice('');try{const data=await karaokeRequest(session,path,{method:'POST',body,query:queryParams});setNotice('Demande enregistrée.');return data;}catch(e){setError(e.message);return null;}finally{setBusy(false);}}
 const tracks=library.filter(t=>(!onlyFav||favorites.includes(t.id))&&(!lang||t.lang===lang)&&(!source||normalize(t.source).includes(normalize(source)))&&normalize(`${t.title} ${t.artist} ${t.source}`).includes(normalize(query)));
 async function searchDeezer(){setBusy(true);setError('');try{const data=await karaokeRequest(session,'/catalog/search',{query:{q:query}});setLibrary(data.tracks);}catch(e){setError(e.message);}finally{setBusy(false);}}
 async function upload(e){e.preventDefault();const form=new FormData(e.currentTarget);const data=await action('/import',form);if(data){setNotice('Morceau importé. Préparation CPU en file d’attente.');send({type:'browse'});}}
 return <div className="kt-root"><div className="kt-strip">{session.apiRoot&&<a href="/" className="kt-home">Accueil Iris ↗</a>}<button onClick={()=>{setOpen(!open);send({type:'browse'});}}>🎶 Catalogue & file d’attente</button><button onClick={()=>{setOpen(true);}}>🎙 Score vocal</button><label><input type="checkbox" checked={plays} onChange={e=>setPlays(e.target.checked)}/>Je participe à la roulette</label>{host&&<select aria-label="Fond animé" value={state?.theme||'neon'} onChange={e=>send({type:'theme',value:e.target.value})}><option value="neon">Néon</option><option value="ocean">Océan</option><option value="aurora">Aurore</option></select>}</div>
 <Draw draw={state?.roulette} players={state?.players||[]} serverTime={state?.server_time}/>
 {open&&<section className="kt-panel" aria-label="Catalogue, réservations et score vocal"><header><h2>Le salon musical</h2><button aria-label="Fermer le salon musical" onClick={()=>setOpen(false)}>✕</button></header>
 {error&&<p role="alert" className="kt-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
 <div className="kt-grid"><section><h3>Choisir et réserver</h3><input aria-label="Rechercher une chanson" placeholder="Titre ou artiste…" value={query} onChange={e=>setQuery(e.target.value)}/><div className="kt-filters"><select aria-label="Langue" value={lang} onChange={e=>setLang(e.target.value)}><option value="">Toutes les langues</option>{[...new Set(library.map(t=>t.lang).filter(Boolean))].map(l=><option key={l} value={l}>{l}</option>)}</select><input aria-label="Source" placeholder="Source, anime…" value={source} onChange={e=>setSource(e.target.value)}/><label><input type="checkbox" checked={onlyFav} onChange={e=>setOnlyFav(e.target.checked)}/>Favoris</label></div>
 {host&&<button disabled={busy||query.trim().length<2} onClick={searchDeezer}>Rechercher aussi sur Deezer · blind test</button>}
 <ul className="kt-catalog">{tracks.slice(0,100).map(t=><li key={t.id}><div><strong>{t.title}</strong><small>{t.artist} {t.lang?`· ${t.lang}`:''} {t.preview?'· Extrait blind test':''}</small></div><button aria-label={(favorites.includes(t.id)?'Retirer des favoris ':'Ajouter aux favoris ')+t.title} onClick={()=>send({type:'favorite',id:t.id,enabled:!favorites.includes(t.id)})}>{favorites.includes(t.id)?'★':'☆'}</button>{!t.preview&&<button onClick={()=>send({type:'queue_add',id:t.id})}>Réserver</button>}{host&&!t.preview&&<button onClick={()=>{send({type:'select',id:t.id});setOpen(false);}}>Chanter</button>}</li>)}</ul>{!tracks.length&&<p>Aucun titre ne correspond. Les morceaux complets sont importés par l’animateur.</p>}
 <h3>Prochains morceaux</h3><ol>{(state?.queue||[]).map(q=><li key={q.id}>{q.track.title} · {q.name}{(host||q.uid===session.userId)&&<button aria-label={'Retirer '+q.track.title} onClick={()=>send({type:'queue_remove',id:q.id})}>Retirer</button>}</li>)}</ol>{!(state?.queue||[]).length&&<p>La file est libre. Réserve ta chanson.</p>}{host&&<button disabled={!state?.queue?.length} onClick={()=>send({type:'queue_next'})}>Lancer la prochaine réservation</button>}
 {host&&<><h3>Qui chante ?</h3><label><input type="checkbox" checked={duo} onChange={e=>setDuo(e.target.checked)}/>Duo</label><div>{(state?.players||[]).filter(p=>p.plays).map(p=><label className="kt-exclude" key={p.id}><input type="checkbox" checked={excluded.includes(p.id)} onChange={e=>setExcluded(old=>e.target.checked?[...old,p.id]:old.filter(id=>id!==p.id))}/>Exclure {p.name}</label>)}</div><button onClick={()=>send({type:'roulette',duo,excluded})}>Tourner la roulette</button></>}
 </section><section><h3>Score vocal avec OasisLink</h3><p>OasisLink analyse le rythme et la hauteur de ta voix dans le salon vocal. Aucun enregistrement n’est conservé. Porte un casque. Tu peux jouer sans analyse ou retirer ton accord à tout moment.</p>
 {host&&<div className="kt-filters"><input aria-label="Identifiant du salon vocal" placeholder="Identifiant du salon vocal" value={channel} onChange={e=>setChannel(e.target.value)}/><button disabled={busy||!/^\d{17,20}$/.test(channel)||voice?.connected||voice?.connecting} onClick={()=>action('/voice/start',{instance_id:session.instanceId,channel_id:channel})}>Connecter OasisLink</button>{(voice?.connected||voice?.connecting)&&<button disabled={busy} onClick={()=>action('/voice/stop',{})}>Déconnecter</button>}</div>}
 <p role="status">{voice?.connected?'OasisLink connecté':voice?.connecting?'Connexion vocale à vérifier':'Le score vocal n’est pas actif.'}</p><label>Compensation de latence (ms)<input type="number" min="-500" max="2000" step="50" value={latency} onChange={e=>setLatency(Number(e.target.value))}/></label>
 <button disabled={busy||(!voice?.connected&&!voice?.consented)} onClick={async()=>{const data=await action('/voice/consent',{enabled:!voice?.consented,latency_ms:latency},{instance_id:session.instanceId});if(data)setVoice(v=>({...v,consented:data.enabled}));}}>{voice?.consented?'Retirer mon accord et arrêter mon analyse':'J’accepte l’analyse de ma voix'}</button>
 <p>Pour calibrer : chante une note au début d’une ligne, puis ajuste la compensation si le score arrive en retard. Un score reste indicatif ; le chant et le micro Discord varient.</p>
 {(voice?.scores||[]).map(score=><p className="kt-score" key={score.id}><strong>{score.name} · {score.score}/100</strong><span>Rythme {score.rhythm}/100 · {score.pitch===null?'Justesse indisponible':`Justesse ${score.pitch}/100`}</span></p>)}
 {!voice?.reference_ready&&<p>Prépare le morceau pour activer un score fondé sur des paroles alignées.</p>}
 <h3>Préparation du morceau</h3><p>{prep?.status==='ready'?`Prêt · langue ${prep.language}${prep.pitch_available?' · mélodie de référence disponible':''}`:prep?.status==='running'?'Whisper traite ce morceau sur CPU…':prep?.status==='pending'?'Dans la file de préparation CPU':prep?.status==='failed'?`Échec : ${prep.error}`:'Alignement automatique non préparé.'}</p>{host&&track&&!track.preview&&<button disabled={busy||['pending','running'].includes(prep?.status)} onClick={()=>action('/prepare',{}, {id:track.id})}>Préparer / réessayer ce morceau</button>}
 {host&&<form onSubmit={upload}><h3>Importer une chanson complète</h3><label>Titre<input name="title" maxLength="100" required/></label><label>Artiste<input name="artist" maxLength="100"/></label><label>Source · anime, film…<input name="source" maxLength="100"/></label><label>Fichier audio<input type="file" name="file" accept="audio/*" required/></label><small>200 Mo et 20 minutes maximum. Whisper détecte la langue, aligne les paroles LRCLIB ou transcrit le morceau. La préparation CPU peut prendre plusieurs minutes.</small><button disabled={busy}>Importer et préparer</button></form>}
 </section></div></section>}
 </div>;
}
