import {useEffect,useState} from 'react';
import {karaokeRequest} from './karaokeRequest';
export default function KaraokeRankings({session,open,onClose,track,tracks=[]}){
 const [scope,setScope]=useState('song'),[selected,setSelected]=useState(track?.id||''),[rows,setRows]=useState([]),[loading,setLoading]=useState(false),[error,setError]=useState('');
 const [revision,setRevision]=useState(0);
 const firstTrackId=tracks[0]?.id||'';
 useEffect(()=>{if(open){setSelected(track?.id||firstTrackId);setScope(track?'song':'overall');}},[open,track?.id,firstTrackId]);
 useEffect(()=>{
  if(!open)return;
  const close=e=>{if(e.key==='Escape')onClose();};document.addEventListener('keydown',close);
  return()=>document.removeEventListener('keydown',close);
 },[open,onClose]);
 useEffect(()=>{
  if(!open)return;
  const controller=new AbortController();let live=true;
  setLoading(true);setError('');setRows([]);
  karaokeRequest(session,'/rankings',{query:scope==='song'&&selected?{track_id:selected}:{},signal:controller.signal}).then(value=>{if(live)setRows(value.rows);}).catch(e=>{if(live)setError(e.message);}).finally(()=>{if(live)setLoading(false);});
  return()=>{live=false;controller.abort();};
 },[open,scope,selected,session.videoToken,session.apiRoot,revision]);
 if(!open)return null;
 return <div className="kt-root kt-scrim kr-scrim" onClick={e=>{if(e.target===e.currentTarget)onClose();}}><section className="kt-panel kr-panel" role="dialog" aria-modal="true" aria-label="Classements du karaoké">
  <header className="kt-header"><div><small>LES VOIX DE L’OASIS</small><h2>Le classement</h2></div><button autoFocus aria-label="Fermer les classements" onClick={onClose}>×</button></header>
  <div className="kr-tabs"><button aria-pressed={scope==='song'} onClick={()=>setScope('song')}>Par chanson</button><button aria-pressed={scope==='overall'} onClick={()=>setScope('overall')}>Général</button><button aria-label="Actualiser les classements" onClick={()=>setRevision(v=>v+1)}>↻</button></div>
  {scope==='song'&&<label className="kr-song">Chanson<select aria-label="Chanson du classement" value={selected} onChange={e=>setSelected(e.target.value)}>{tracks.map(song=><option key={song.id} value={song.id}>{song.title} — {song.artist}</option>)}</select></label>}
  <p className="kr-rule">{scope==='song'?'Le meilleur score de chaque joueur sur cette chanson.':'La somme de tes meilleurs scores sur chaque chanson.'}</p>
  {loading?<p role="status">Chargement du classement…</p>:error?<p role="alert">{error}</p>:rows.length?<ol className="kr-list">{rows.map(row=><li key={row.id} className={String(row.id)===String(session.userId)?'is-you':''}><span className="kr-rank">{row.rank<=3?['🥇','🥈','🥉'][row.rank-1]:row.rank}</span><div><strong>{row.name}</strong>{scope==='overall'&&<small>{row.songs} chanson{row.songs>1?'s':''}</small>}</div><b>{row.points.toLocaleString('fr-FR')}<small> pts</small></b></li>)}</ol>:<p className="kr-empty">La première place vous attend. Termine une chanson avec les scores activés !</p>}
 </section></div>;
}
