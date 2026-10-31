import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {api,getErrorMessage} from '../api/client';
import '../Casier.css';
import '../Casework.css';
import '../WorkflowSettings.css';
export default function CommandDescriptionsPage(){
 const [data,setData]=useState(null),[draft,setDraft]=useState({}),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[search,setSearch]=useState('');
 async function load(){try{const r=await api.get('/responsable/command-descriptions');setData(r.data);setDraft(r.data.overrides||{});setError('');}catch(e){setError(getErrorMessage(e));}}
 useEffect(()=>{document.body.classList.add('casier-no-nav');load();return()=>document.body.classList.remove('casier-no-nav');},[]);
 async function save(e){e.preventDefault();setBusy(true);setError('');setNotice('');try{const r=await api.put('/responsable/command-descriptions',{revision:data.revision,overrides:draft});setData(r.data);setDraft(r.data.overrides);setNotice('Descriptions enregistrées. Discord sera actualisé automatiquement dans les prochaines secondes.');}catch(e){setError(getErrorMessage(e));}finally{setBusy(false);}}
 return <main className="cz-page wf-page"><header className="cz-header"><div><p className="cz-eyebrow">ESPACE RESPONSABLE · DISCORD</p><h1>Les descriptions des commandes</h1><p className="cz-intro">Personnalisez les textes visibles dans le menu des commandes OasisLink, y compris les sous-commandes et leurs paramètres.</p></div><nav className="cz-header-actions"><button className="cw-button" disabled={busy} onClick={load}>Actualiser</button><Link className="cw-button" to="/">Accueil →</Link></nav></header>
 {error&&<p role="alert" className="cw-alert">{error}</p>}{notice&&<p role="status" className="wf-notice">{notice}</p>}
 <section className="cw-guide"><p>Chaque description accepte 100 caractères sur une ligne. Les noms, les permissions et le comportement des commandes restent gérés par le bot. « Texte d’origine » rétablit la description prévue dans Iris.</p></section>
 <label>Rechercher une commande<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="/panel, /anonyme, membre…"/></label>
 {data&&<form onSubmit={save}><section className="cw-card"><div className="wf-grid">{data.items.filter(item=>item.path.toLowerCase().includes(search.toLowerCase())).map(item=><article className="wf-block" key={item.path}><p className="cz-eyebrow">{item.kind}</p><label>/{item.path.replaceAll('/',' ')}<input required maxLength={100} value={draft[item.path]??item.default} onChange={e=>setDraft({...draft,[item.path]:e.target.value})}/></label><small>{(draft[item.path]??item.default).length} / 100 caractères</small><div className="cw-toolbar"><button className="cw-button" type="button" onClick={()=>{const next={...draft};delete next[item.path];setDraft(next);}}>Texte d’origine</button></div></article>)}</div>{!data.items.length&&<p>Le bot n’a pas encore chargé ses commandes. Réessaie après sa connexion.</p>}</section>
 {Object.entries(data.sync_errors||{}).map(([name,text])=><p key={name} className="cw-alert">/{name} : {text}</p>)}
 <button className="cw-button cw-primary" disabled={busy||!data.items.length}>{busy?'Enregistrement…':'Enregistrer les descriptions'}</button></form>}
 </main>;
}
