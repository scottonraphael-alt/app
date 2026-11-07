import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,RefreshCw,Search,Scale} from 'lucide-react';
import {api,getErrorMessage} from '../api/client';
import {Modal} from '../components/projects/ProjectUI';
import '../Casier.css';
import '../Casework.css';
import '../Resolutions.css';
const KINDS={suggestion:'Suggestion',staff_suggestion:'Suggestion Staff',permanent_ban:'Bannissement définitif'};
const EXECUTION={pending:'Bannissement en attente d’application',applied:'Bannissement exécuté et enregistré au casier',recording:'Bannissement confirmé · finalisation du casier ou des logs',blocked:'Bannissement non appliqué',uncertain:'Exécution à vérifier · aucun nouvel envoi automatique'};
const LABELS={open:'En attente de décision',approved:'Approuvée',rejected:'Rejetée'};
const date=v=>v?new Date(v).toLocaleString('fr-FR',{timeZone:'Europe/Paris',dateStyle:'medium',timeStyle:'short'}):'—';
const discord=(row,channel,message)=>`https://discord.com/channels/${row.guild_id}/${channel}/${message}`;
export default function ResolutionsPage(){
 const [data,setData]=useState(null),[status,setStatus]=useState(''),[query,setQuery]=useState(''),[search,setSearch]=useState(''),
 [offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0),[selected,setSelected]=useState(null),[error,setError]=useState(''),
 [counter,setCounter]=useState(null),[next,setNext]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 useEffect(()=>{document.body.classList.add('casier-no-nav');return()=>document.body.classList.remove('casier-no-nav');},[]);
 useEffect(()=>{let live=true;setData(null);setError('');api.get('/resolutions',{params:{status,q:search,offset,limit:25}})
 .then(r=>{if(live){setData(r.data);setSelected(old=>old?r.data.items.find(row=>row._id===old._id)||null:null);}})
 .catch(e=>{if(live)setError(getErrorMessage(e));});return()=>{live=false;};},[status,search,offset,refresh]);
 const canManage=Boolean(data?.can_manage_counter);
 useEffect(()=>{if(!canManage)return;let live=true;api.get('/resolutions/counter').then(r=>{if(live){setCounter(r.data);setNext(String(r.data.next_number));}})
 .catch(e=>{if(live)setError(getErrorMessage(e));});return()=>{live=false;};},[canManage,refresh]);
 async function saveCounter(e){e.preventDefault();setBusy(true);setNotice('');setError('');try{
 const r=await api.put('/resolutions/counter',{year:counter.year,expected_value:counter.value,next_number:Number(next)});
 setCounter(r.data);setNext(String(r.data.next_number));setNotice(`Le prochain numéro sera ${r.data.year}-${String(r.data.next_number).padStart(2,'0')}.`);
 }catch(err){setError(getErrorMessage(err));}finally{setBusy(false);}}
 return <main className="cz-page cw-page rz-page"><header className="cz-header"><div><p className="cz-eyebrow">GOUVERNANCE · MÉMOIRE DU SERVEUR</p><h1>Les résolutions</h1><p className="cz-intro">Les propositions, les avis du Conseil et les décisions des Responsables, réunis dans un même registre.</p></div><nav className="cz-header-actions"><button className="cw-button" onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16}/>Actualiser</button><Link className="cw-button" to="/">Accueil <ArrowRight size={16}/></Link></nav></header>
 <section className="cw-guide"><Scale/><div><h2>Un avis consultatif, une décision responsable</h2><p>Le Conseil s’exprime pendant 3 jours. Seuls les Responsables approuvent ou rejettent, à tout moment, depuis Discord.</p></div><span className="cw-guide-count"><strong>{data?.total??'—'}</strong>résolutions dans cette vue</span></section>
 {canManage&&counter&&<section className="cw-card rz-counter"><div><h2>Numérotation {counter.year}</h2><p>Choisis le prochain numéro. Les archives conservent leur référence et les numéros réservés ne sont jamais réutilisés.</p></div><form onSubmit={saveCounter}><label htmlFor="rz-next">Prochain numéro</label><div className="cw-toolbar"><input id="rz-next" type="number" min={counter.value+1} max={999999} required value={next} onChange={e=>setNext(e.target.value)}/><button className="cw-button" disabled={busy||!next||Number(next)===counter.next_number}>Enregistrer</button></div><small>Prochaine référence : {counter.year}-{String(next||counter.next_number).padStart(2,'0')}</small></form></section>}
 {notice&&<p role="status">{notice}</p>}{error&&<p className="cw-alert" role="alert">{error}</p>}
 <div className="cw-toolbar" aria-label="Filtrer les résolutions">{[['','Toutes'],...Object.entries(LABELS)].map(([value,label])=><button className="cw-button" key={value} aria-pressed={status===value} onClick={()=>{setStatus(value);setOffset(0);}}>{label}</button>)}</div>
 <form className="cw-search" onSubmit={e=>{e.preventDefault();setSearch(query);setOffset(0);}}><Search size={18}/><input aria-label="Rechercher une résolution" placeholder="Un numéro, un titre, un mot…" maxLength={100} value={query} onChange={e=>setQuery(e.target.value)}/><button className="cw-button">Rechercher</button></form>
 {!data&&!error&&<p role="status">Chargement des résolutions…</p>}
 {data&&<section className="cw-card"><div className="cw-table-wrap"><table className="cw-table"><thead><tr><th>Référence</th><th>Proposition</th><th>Décision</th><th>Conseil</th><th>Date</th><th/></tr></thead><tbody>{data.items.map(row=><tr key={row._id}><td><strong>{row.number}</strong><small className="rz-kind">{KINDS[row.source_kind]||row.source_kind}</small></td><td className="rz-title">{row.title}{row.target&&<small className="rz-kind">{row.target.display_name||row.target.username} · {row.target.id}</small>}</td><td><span className={'cw-state rz-state-'+row.status}>{LABELS[row.status]}</span></td><td><span className="rz-positive">{row.positive} pour</span> · <span className="rz-negative">{row.negative} contre</span></td><td>{date(row.decided_at||row.created_at)}</td><td><button className="cw-button" onClick={()=>setSelected(row)}>Consulter</button></td></tr>)}</tbody></table></div>{!data.items.length&&<p className="cw-empty">Aucune résolution dans cette vue.</p>}
 <footer className="cw-pagination"><button className="cw-button" disabled={!offset} onClick={()=>setOffset(n=>Math.max(0,n-25))}>Précédent</button><span>Page {Math.floor(offset/25)+1} sur {Math.max(1,Math.ceil(data.total/25))}</span><button className="cw-button" disabled={offset+25>=data.total} onClick={()=>setOffset(n=>n+25)}>Suivant</button></footer></section>}
 {selected&&<Modal title={'Résolution '+selected.number} eyebrow="REGISTRE DES RÉSOLUTIONS" onClose={()=>setSelected(null)}><div className="cw-modal cz-dialog-root rz-detail"><span className={'cw-state rz-state-'+selected.status}>{LABELS[selected.status]}</span><h2>{selected.title}</h2><p>{KINDS[selected.source_kind]||selected.source_kind}</p>
 {selected.target&&<p><strong>Compte concerné : {selected.target.display_name||selected.target.username}</strong> · {selected.target.id}</p>}
 {selected.execution&&<section className="cw-guide" role="status"><div><strong>{EXECUTION[selected.execution.status]||selected.execution.status}</strong>{selected.execution.error&&<p>{selected.execution.error}</p>}
 {selected.execution.casier_id&&<Link className="cw-button" to={`/moderation/casiers?casier=${encodeURIComponent(selected.execution.casier_id)}`}>Consulter le casier IRIS</Link>}</div></section>}<p>Demandé par {selected.author_id} · {date(selected.created_at)}</p><p className="rz-explanation">{selected.explanation}</p>
 <p>Consultation jusqu’au {date(selected.vote_until)}</p>{selected.decided_by&&<p><strong>Décision de {selected.decided_by}</strong> · {date(selected.decided_at)}</p>}
 <h3>Avis du Conseil · {selected.positive} pour / {selected.negative} contre</h3><div className="cw-table-wrap"><table className="cw-table"><thead><tr><th>Membre Discord</th><th>Avis</th><th>Dernière expression</th></tr></thead><tbody>{selected.votes.map(v=><tr key={v.member_id}><td>{v.member_id}</td><td>{v.choice==='yes'?'Pour':'Contre'}</td><td>{date(v.at)}</td></tr>)}</tbody></table></div>{!selected.votes.length&&<p>Aucun avis exprimé.</p>}
 <div className="cw-toolbar">{selected.message_id&&<a className="cw-button" target="_blank" rel="noreferrer" href={discord(selected,selected.channel_id,selected.message_id)}>Panneau Discord ↗</a>}{selected.journal_message_id&&<a className="cw-button" target="_blank" rel="noreferrer" href={discord(selected,selected.journal_channel_id,selected.journal_message_id)}>Journal des résolutions ↗</a>}</div>
 {selected.sync_error&&<p className="cw-alert">{selected.sync_error}</p>}{selected.status!=='open'&&!selected.journal_message_id&&<p role="status">Publication dans le journal en attente.</p>}</div></Modal>}
 </main>;
}
