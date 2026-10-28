import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Archive, ArrowRight, Calendar, Check, ChevronDown, Plus, Search, Trash2, Users, X } from "lucide-react";
import { api, getErrorMessage } from "../api/client";
import "../QuarterlyTasks.css";

const ROLES = { tous: "Tous", staff: "Staff", helper: "Helper" };
const normalize = (v) => String(v || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; };
const date = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || "") ? new Date(`${v}T12:00:00`).toLocaleDateString("fr-FR", {day:"numeric",month:"short",year:"numeric"}) : v || "À préciser";
const person = (v) => v.display_name || v.username || "Membre";
const volunteers = (t) => t.volunteers || [];

function Avatar({ member }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [member.avatar_url]);
  return <span className="qt-avatar">{member.avatar_url && !failed ? <img src={member.avatar_url} alt="" onError={() => setFailed(true)} /> : person(member).slice(0,1).toUpperCase()}</span>;
}

function Volunteer({ member, task, admin, act }) {
  return <div className="qt-volunteer"><div className="qt-person"><Avatar member={member}/><span>{person(member)}</span>{admin && <button className="qt-icon qt-danger" aria-label={`Retirer ${person(member)}`} onClick={() => act("removeVolunteer",task.id,member.id)}><X size={15}/></button>}</div></div>;
}

function Task({ task, admin=false, members=[], helper, act, readOnly=false }) {
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const list = volunteers(task);
  const signed = helper && list.some(v=>String(v.id)===String(helper.id));
  return <article className={`qt-task ${list.length ? "qt-task--taken":"qt-task--open"}`}><div className="qt-task-top"><div className="qt-tags"><span>{task.category || "Mission"}</span><span>{ROLES[task.target_role] || "Tous"}</span></div>{admin && !readOnly && <button className="qt-icon qt-danger" aria-label={`Supprimer ${task.name}`} onClick={()=>act("deleteTask",task.id)}><Trash2 size={16}/></button>}</div><h3>{task.name}</h3><p className="qt-date"><Calendar size={14}/>{date(task.task_date)}{task.end_date && ` → ${date(task.end_date)}`}</p>{task.explanation && <p className="qt-description">{task.explanation}</p>}<div className="qt-team"><span className="qt-label">{list.length ? `${list.length} volontaire${list.length>1?"s":""}`:"Une place pour vous"}</span>{list.length ? list.map(v=><Volunteer key={v.id} member={v} task={task} admin={admin && !readOnly} act={act}/>) : <p className="qt-muted">Personne inscrit pour le moment.</p>}</div>{!readOnly && <div className="qt-task-bottom">{admin && <form className="qt-nominate" onSubmit={async e=>{e.preventDefault();if(!selected)return;setBusy(true);try{await act("nominate",task.id,selected);setSelected("");}catch{}finally{setBusy(false);}}}><select aria-label={`Nommer un membre pour ${task.name}`} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Nommer un membre</option>{members.filter(m=>!list.some(v=>String(v.id)===String(m.id))).map(m=><option key={m.id} value={m.id}>{person(m)}</option>)}</select><button className="qt-icon" disabled={!selected || busy} aria-label="Confirmer la nomination"><Plus size={16}/></button></form>}<button className={`qt-button ${signed?"":"qt-button--primary"}`} disabled={busy} onClick={async()=>{setBusy(true);try{await act("signup",task.id);}catch{}finally{setBusy(false);}}}>{signed?<Check size={15}/>:<Plus size={15}/ >}{signed?"Se désinscrire":"Je participe"}</button></div>}</article>;
}

function ArchivedPeriod({ period, admin, remove }) {
  const [open,setOpen]=useState(false);
  const [items,setItems]=useState(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(false);
  const load=async()=>{setBusy(true);setError(false);try{const r=await api.get("/staff/tasks",{params:{period_id:period.id}});setItems(r.data);}catch(e){setError(true);toast.error(getErrorMessage(e));}finally{setBusy(false);}};
  return <div className="qt-archive"><div className="qt-archive-head"><button className="qt-archive-toggle" aria-expanded={open} onClick={()=>{setOpen(!open);if(!open && items===null)load();}}><Archive size={17}/><span>{date(period.start_date)} — {date(period.end_date)}</span><ChevronDown size={17} style={{transform:open?"rotate(180deg)":undefined}}/></button>{admin && <button className="qt-icon qt-danger" aria-label="Supprimer la période archivée" onClick={()=>remove(period.id)}><Trash2 size={16}/></button>}</div>{open && <div className="qt-archive-body">{busy?<p>Chargement…</p>:error?<button className="qt-button" onClick={load}>Réessayer</button>:items?.length?<div className="qt-task-grid">{items.map(t=><Task key={t.id} task={t} readOnly/>)}</div>:<p className="qt-muted">Aucune tâche enregistrée.</p>}</div>}</div>;
}

export default function QuarterlyTasksPage({ isResponsable=false, helper }) {
  const [period,setPeriod]=useState(null), [tasks,setTasks]=useState([]), [archives,setArchives]=useState([]), [members,setMembers]=useState([]);
  const [loading,setLoading]=useState(true), [error,setError]=useState("");
  const [view,setView]=useState("active"), [search,setSearch]=useState(""), [role,setRole]=useState("tous"), [scope,setScope]=useState("all");
  const [creating,setCreating]=useState(false), [busy,setBusy]=useState(false), [periodStart,setPeriodStart]=useState(today);
  const empty={name:"",category:"",explanation:"",task_date:today(),end_date:today(),target_role:"tous"};
  const [form,setForm]=useState(empty);
  const field=(k)=>(e)=>setForm(f=>({...f,[k]:e.target.value}));
  const event=normalize(form.category).includes("event"), editorial=normalize(form.category).includes("redactionnel");
  useEffect(()=>{document.body.classList.add("quarterly-no-nav");return()=>document.body.classList.remove("quarterly-no-nav");},[]);
  const load=useCallback(async()=>{setLoading(true);setError("");try{const [p,a]=await Promise.all([api.get("/staff/tasks/period"),api.get("/staff/tasks/periods/archived")]);setPeriod(p.data);setArchives(a.data);setTasks(p.data?(await api.get("/staff/tasks",{params:{period_id:p.data.id}})).data:[]);}catch(e){setError(getErrorMessage(e));}finally{setLoading(false);}},[]);
  useEffect(()=>{load();},[load]);
  useEffect(()=>{if(isResponsable)api.get("/staff/members").then(r=>setMembers(r.data)).catch(e=>toast.error(getErrorMessage(e)));},[isResponsable]);
  const act=async(type,id,member)=>{try{
    if(type==="deleteTask"){if(!window.confirm("Supprimer définitivement cette tâche ?"))return;await api.delete(`/staff/tasks/${id}`);setTasks(t=>t.filter(x=>x.id!==id));return;}
    let r;
    if(type==="signup")r=await api.post(`/staff/tasks/${id}/signup`);
    if(type==="nominate")r=await api.post(`/staff/tasks/${id}/nominate/${member}`);
    if(type==="removeVolunteer")r=await api.delete(`/staff/tasks/${id}/volunteers/${member}`);
    if(r)setTasks(t=>t.map(x=>x.id===id?r.data:x));
  }catch(e){toast.error(getErrorMessage(e));throw e;}};
  const mutatePeriod=async(e)=>{e.preventDefault();setBusy(true);try{const r=await api.post("/staff/tasks/period",{start_date:periodStart});setPeriod(r.data);setTasks([]);toast.success("Période déclarée.");}catch(e){toast.error(getErrorMessage(e));}finally{setBusy(false);}};
  const archive=async()=>{if(!period || !window.confirm("Archiver la période en cours ?"))return;setBusy(true);try{await api.post(`/staff/tasks/period/${period.id}/archive`);await load();toast.success("Période archivée.");}catch(e){toast.error(getErrorMessage(e));}finally{setBusy(false);}};
  const removePeriod=async(id)=>{if(!window.confirm("Supprimer définitivement cette période archivée ?"))return;try{await api.delete(`/staff/tasks/period/${id}`);setArchives(a=>a.filter(x=>x.id!==id));}catch(e){toast.error(getErrorMessage(e));}};
  const add=async(e)=>{e.preventDefault();if(!period || !form.name.trim() || !form.category.trim() || !form.task_date)return;if(event && !editorial && (!form.end_date || form.end_date<form.task_date)){toast.error("Vérifiez la date de fin de l’événement.");return;}setBusy(true);try{const r=await api.post("/staff/tasks",{...form,period_id:period.id,end_date:event&&!editorial?form.end_date:null});setTasks(t=>[...t,r.data]);setForm({...empty});setCreating(false);toast.success("Tâche ajoutée.");}catch(e){toast.error(getErrorMessage(e));}finally{setBusy(false);}};
  const mine=t=>helper && volunteers(t).some(v=>String(v.id)===String(helper.id));
  const myTasks=helper?tasks.filter(mine):[];
  const visible=useMemo(()=>tasks.filter(t=>(role==="tous" || t.target_role===role || !t.target_role || t.target_role==="tous") && (scope!=="open" || !volunteers(t).length) && (scope!=="mine" || (helper && volunteers(t).some(v=>String(v.id)===String(helper.id)))) && normalize([t.name,t.category,t.explanation].join(" ")).includes(normalize(search.trim()))),[tasks,role,scope,search,helper]);
  return <section className="qt-page" data-testid="quarterly-tasks-page"><header className="qt-header"><div><p className="qt-eyebrow">ESPACE STAFF · ENGAGEMENTS</p><h1>Chaque mission compte.</h1><p className="qt-intro">Les tâches du trimestre, les talents de l’équipe et une place pour contribuer.</p></div><div className="qt-header-actions"><Link to="/" className="qt-home">Accueil <ArrowRight size={18}/></Link>{isResponsable && period && <button className="qt-button qt-button--primary" onClick={()=>{setView("active");setCreating(!creating);}}><Plus size={16}/>Nouvelle tâche</button>}</div></header>
  {loading?<div className="qt-empty" role="status">Chargement des engagements…</div>:error?<div className="qt-empty" role="alert"><p>{error}</p><button className="qt-button" onClick={load}>Réessayer</button></div>:<>
  <section className="qt-overview"><div className="qt-period"><span className="qt-pill"><span className="qt-dot"/>{period?"Période en cours":"Prochain trimestre"}</span><h2>{period?`${date(period.start_date)} — ${date(period.end_date)}`:"Un nouveau cycle à préparer"}</h2><p>{period?"Choisissez une mission et construisons la suite ensemble.":"Aucune période n’est encore déclarée."}</p>{isResponsable && (period?<button className="qt-text-button" onClick={archive} disabled={busy}><Archive size={15}/>Archiver cette période</button>:<form className="qt-period-form" onSubmit={mutatePeriod}><label>Date de début<input type="date" value={periodStart} onChange={e=>setPeriodStart(e.target.value)} required/></label><button className="qt-button qt-button--primary" disabled={busy}>Déclarer la période</button></form>)}</div><div className="qt-stat"><span className="qt-label">Missions proposées</span><strong>{tasks.length}</strong><span>sur la période active</span></div><div className="qt-stat qt-stat--amber"><span className="qt-label">À rejoindre</span><strong>{tasks.filter(t=>!volunteers(t).length).length}</strong><span>sans volontaire</span></div><div className="qt-stat"><span className="qt-label">Mes engagements</span><strong>{helper?myTasks.length:"—"}</strong><span className="qt-stat-list" title={myTasks.map(t=>t.name).join(", ")}>{!helper?"profil non transmis":myTasks.length?myTasks.map(t=>t.name).join(" · "):"aucune mission rejointe"}</span></div></section>
  <div className="qt-tabs" role="group" aria-label="Vue des engagements"><button aria-pressed={view==="active"} onClick={()=>setView("active")}><Users size={16}/>Missions du trimestre <span>{tasks.length}</span></button><button aria-pressed={view==="archives"} onClick={()=>setView("archives")}><Archive size={16}/>Périodes passées <span>{archives.length}</span></button></div>
  {view==="archives"?<section className="qt-panel"><div className="qt-section-heading"><div><p className="qt-eyebrow">MÉMOIRE COLLECTIVE</p><h2>Les trimestres précédents</h2></div></div>{archives.length?archives.map(p=><ArchivedPeriod key={p.id} period={p} admin={isResponsable} remove={removePeriod}/>):<div className="qt-empty">Aucune période archivée.</div>}</section>:<div className={`qt-layout ${creating && isResponsable && period?"qt-layout--editing":""}`}><section className="qt-panel"><div className="qt-section-heading"><div><p className="qt-eyebrow">PASSER À L’ACTION</p><h2>Trouvez votre prochaine mission</h2></div><span className="qt-pill">{visible.length} résultat{visible.length>1?"s":""}</span></div><div className="qt-toolbar"><label className="qt-search"><Search size={17}/><input aria-label="Rechercher une tâche" placeholder="Un sujet, une mission, une catégorie…" value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label="Rôle concerné" value={role} onChange={e=>setRole(e.target.value)}>{Object.entries(ROLES).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select><select aria-label="Disponibilité" value={scope} onChange={e=>setScope(e.target.value)}><option value="all">Toutes les missions</option><option value="open">Sans volontaire</option>{helper && <option value="mine">Mes engagements</option>}</select></div>{visible.length?<div className="qt-task-grid">{visible.map(t=><Task key={t.id} task={t} admin={isResponsable} members={members} helper={helper} act={act}/>)}</div>:<div className="qt-empty"><Users size={30}/><h3>Aucune mission à afficher</h3><p>Modifiez les filtres ou attendez les prochaines propositions.</p><button className="qt-button" onClick={()=>{setSearch("");setRole("tous");setScope("all");}}>Effacer les filtres</button></div>}</section>
  {creating && isResponsable && period && <aside className="qt-panel qt-editor"><div className="qt-section-heading"><div><p className="qt-eyebrow">PROPOSER UNE MISSION</p><h2>Nouvelle tâche</h2></div><button className="qt-icon" aria-label="Fermer la création" onClick={()=>setCreating(false)}><X size={17}/></button></div><form onSubmit={add}><label>Intitulé<input value={form.name} onChange={field("name")} maxLength={160} required placeholder="Que souhaitez-vous réaliser ?"/></label><label>Catégorie<input value={form.category} onChange={field("category")} maxLength={80} required placeholder="Communication, Event, Rédactionnel…"/></label><label>Public concerné<select value={form.target_role} onChange={field("target_role")}>{Object.entries(ROLES).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>Description<textarea value={form.explanation} onChange={field("explanation")} rows={4} placeholder="Objectif, contexte et résultat attendu…"/></label><label>{editorial?"Date ou repère libre":"Date de début"}<input type={editorial?"text":"date"} value={form.task_date} onChange={field("task_date")} required/></label>{event&&!editorial&&<label>Date de fin<input type="date" min={form.task_date} value={form.end_date} onChange={field("end_date")} required/></label>}<button className="qt-button qt-button--primary" disabled={busy}><Plus size={16}/>{busy?"Enregistrement…":"Publier la mission"}</button></form></aside>}</div>}</>}
  </section>;
}
