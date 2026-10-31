import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,RefreshCw,Search,ShieldCheck,MessageSquare,Eye} from 'lucide-react';
import {api,getErrorMessage} from '../api/client';
import {Modal} from '../components/projects/ProjectUI';
import '../Casier.css';
import '../Casework.css';
const LABELS={pending:'En attente',approved:'Publication en cours',published:'Publié',rejected:'Refusé'};
const date=value=>value?new Date(value).toLocaleString('fr-FR',{timeZone:'Europe/Paris',dateStyle:'medium',timeStyle:'short'}):'—';
export default function AnonymousMessagesPage(){
 const [data,setData]=useState(null),[status,setStatus]=useState(''),[query,setQuery]=useState(''),[search,setSearch]=useState(''),
 [offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0),[selected,setSelected]=useState(null),
 [identity,setIdentity]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 useEffect(()=>{document.body.classList.add('casier-no-nav');return()=>document.body.classList.remove('casier-no-nav');},[]);
 useEffect(()=>{let live=true;setData(null);setError('');api.get('/anonymous-messages',{params:{status,q:search,offset,limit:25}})
 .then(r=>{if(live)setData(r.data);}).catch(e=>{if(live)setError(getErrorMessage(e));});return()=>{live=false;};},[status,search,offset,refresh]);
 async function reveal(){setBusy(true);setError('');try{const r=await api.post('/anonymous-messages/'+encodeURIComponent(selected._id)+'/reveal');setIdentity(r.data);}catch(e){setError(getErrorMessage(e));}finally{setBusy(false);}}
 return <main className="cz-page cw-page"><header className="cz-header"><div><p className="cz-eyebrow">ESPACE ÉQUIPE · EXPRESSION ANONYME</p><h1>Les messages anonymes</h1><p className="cz-intro">Retrouvez les propositions, leur décision et leur publication, sous leur identifiant anonyme.</p></div><nav className="cz-header-actions"><button className="cw-button" onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={16}/>Actualiser</button><Link className="cw-button" to="/">Accueil <ArrowRight size={16}/></Link></nav></header>
 <section className="cw-guide"><ShieldCheck/><div><h2>Une identité protégée</h2><p>Seuls les Responsables peuvent révéler un auteur. Chaque révélation est journalisée. La validation et le refus se font depuis le panneau Discord.</p></div><span className="cw-guide-count"><strong>{data?.total??'—'}</strong>messages dans cette vue</span></section>
 <div className="cw-toolbar" role="group" aria-label="Filtrer les messages">{[['','Tous'],...Object.entries(LABELS)].map(([value,label])=><button className="cw-button" key={value} aria-pressed={status===value} onClick={()=>{setStatus(value);setOffset(0);}}>{label}</button>)}</div>
 <form className="cw-search" onSubmit={e=>{e.preventDefault();setSearch(query);setOffset(0);}}><Search size={18}/><input aria-label="Rechercher un message ou un identifiant" placeholder="Un identifiant ANO, un mot du message…" maxLength={100} value={query} onChange={e=>setQuery(e.target.value)}/><button className="cw-button">Rechercher</button></form>
 {error&&<p className="cw-alert" role="alert">{error}</p>}{!data&&!error&&<p role="status">Chargement de l’historique…</p>}
 {data&&<section className="cw-card"><div className="cw-table-wrap"><table className="cw-table"><thead><tr><th>Identifiant</th><th>Message</th><th>État</th><th>Proposé le</th><th>Décision</th><th/></tr></thead><tbody>{data.items.map(row=><tr key={row._id}><td><strong>{row.alias}</strong></td><td style={{maxWidth:420,whiteSpace:'normal',overflowWrap:'anywhere'}}>{row.text.length>140?row.text.slice(0,140)+'…':row.text}</td><td><span className="cw-state">{LABELS[row.status]}</span></td><td>{date(row.created_at)}</td><td>{date(row.decided_at)}</td><td><button className="cw-button" onClick={()=>{setSelected(row);setIdentity(null);}}><MessageSquare size={16}/>Lire</button></td></tr>)}</tbody></table></div>{!data.items.length&&<p className="cw-empty">Aucun message dans cette vue.</p>}
 <footer className="cw-pagination"><button className="cw-button" disabled={!offset} onClick={()=>setOffset(n=>Math.max(0,n-25))}>Précédent</button><span>Page {Math.floor(offset/25)+1} sur {Math.max(1,Math.ceil(data.total/25))}</span><button className="cw-button" disabled={offset+25>=data.total} onClick={()=>setOffset(n=>n+25)}>Suivant</button></footer></section>}
 {selected&&<Modal title={'Message de '+selected.alias} eyebrow="HISTORIQUE ANONYME" onClose={()=>{setSelected(null);setIdentity(null);}}><div className="cw-modal cz-dialog-root"><span className="cw-state">{LABELS[selected.status]}</span><p>{selected.text}</p><p>Proposé le {date(selected.created_at)}</p>{selected.reviewer_id&&<p>Traité par {selected.reviewer_id} · {date(selected.decided_at)}</p>}{selected.reason&&<p><strong>Motif du refus :</strong> {selected.reason}</p>}{selected.sync_error&&<p className="cw-alert">{selected.sync_error}</p>}
 {selected.public_message_id&&<a className="cw-button" target="_blank" rel="noreferrer" href={'https://discord.com/channels/'+data?.guild_id+'/'+data?.public_channel_id+'/'+selected.public_message_id}>Voir la publication Discord ↗</a>}
 {data?.can_reveal&&!identity&&<button className="cw-button cw-danger" disabled={busy} onClick={reveal}><Eye size={16}/>Révéler l’auteur · action journalisée</button>}
 {identity&&<div className="cw-alert"><strong>Identité révélée : {identity.username?'@'+identity.username:(identity.display_name||'Pseudo indisponible')} · {identity.member_id}</strong><p>Cette consultation a été enregistrée.</p></div>}{error&&<p role="alert">{error}</p>}</div></Modal>}
 </main>;
}
