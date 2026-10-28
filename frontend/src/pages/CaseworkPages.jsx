// Prepared routes: mount each page behind the existing Staff access guard at integration.
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, RefreshCw, Search, FileText, LockKeyhole } from 'lucide-react';
import { api, getErrorMessage } from '../api/client';
import { Modal } from '../components/projects/ProjectUI';
import '../Casier.css';
import '../Casework.css';

const BASE = '/casework';
const ROOT = '/staff/dossiers';
const FAMILIES = {
  verification: { title: 'Les tickets de vérification', short: 'Vérifications', intro: 'Les échanges complémentaires autour de l’admission, reliés au parcours du membre.', tone: 'violet' },
  summons: { title: 'Les convocations', short: 'Convocations', intro: 'Retrouvez les échanges demandés par l’équipe et leur historique.', tone: 'gold' },
  contact_staff: { title: 'Les contacts Staff', short: 'Contacts Staff', intro: 'Questions, signalements et demandes confidentielles, avec les accès adaptés.', tone: 'sage' },
  bubble: { title: 'Les bulles d’échange', short: 'Bulles', intro: 'Un espace pour discuter sereinement, sans présumer d’un problème ou d’une faute.', tone: 'blue' },
};
const STATES = { reopening: 'Rétablissement des accès', open: 'Ouvert', suspended: 'Suspendu', restricted: 'Accès restreint', closing: 'Clôture en cours', archived: 'Archivé' };
const ACTIONS = { cancel_close: 'Annuler la clôture et rétablir les accès', claim: 'Prendre en charge', assign: 'Réattribuer', note: 'Ajouter une note', sync: 'Actualiser les messages', archive: 'Clôturer et archiver' };
const EVENTS = { discovered: 'Dossier ajouté depuis Discord', archived: 'Dossier archivé', action: 'Action manuelle', 'visibility.tightened': 'Accès du dossier restreint' };
const date = value => value ? new Date(value).toLocaleString('fr-FR', { timeZone: 'Europe/Paris', dateStyle: 'medium', timeStyle: 'short' }) : 'Pas encore disponible';
const errorText = error => typeof getErrorMessage(error) === 'string' ? getErrorMessage(error) : 'Vérifie les champs renseignés.';
const pathFor = kind => `${ROOT}/${kind}`;
const mediaUrl = path => {
  if (!path?.startsWith('/api/casework/')) return null;
  return (api.defaults?.baseURL?.replace(/\/api\/?$/, '') || '') + path;
};

function Frame({ kind, title, children, back, refresh }) {
  const family = FAMILIES[kind];
  useEffect(() => {
    document.body.classList.add('casier-no-nav');
    return () => document.body.classList.remove('casier-no-nav');
  }, []);
  return <main className={`cz-page cw-page cw-${family.tone}`}>
    <header className="cz-header">
      <div><p className="cz-eyebrow">ESPACE STAFF · DOSSIERS</p><h1>{title || family.title}</h1><p className="cz-intro">{family.intro}</p></div>
      <nav className="cz-header-actions" aria-label="Navigation du dossier">
        {back && <Link className="cw-button" to={pathFor(kind)}><ArrowLeft size={16} /> {family.short}</Link>}
        <button className="cw-button" onClick={refresh}><RefreshCw size={16} /> Actualiser la vue</button>
        <Link className="cw-button" to="/">Accueil <ArrowRight size={16} /></Link>
      </nav>
    </header>
    <nav className="cw-families" aria-label="Familles de dossiers">{Object.entries(FAMILIES).map(([value, item]) =>
      <Link key={value} to={pathFor(value)} aria-current={kind === value ? 'page' : undefined}>{item.short}</Link>)}</nav>
    {children}
  </main>;
}

function State({ row }) {
  return <span className={`cw-state cw-state-${row.status}`}>{STATES[row.status] || row.status}</span>;
}

function CaseList({ kind }) {
  const [archived, setArchived] = useState(false), [attention, setAttention] = useState(false), [offset, setOffset] = useState(0);
  const [data, setData] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const [importing, setImporting] = useState(false), [channelId, setChannelId] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setLoading(true); setData(null); setError('');
    api.get(BASE, { params: { kind, archived, attention, offset, limit: 25 } }).then(r => { if (live) setData(r.data); })
      .catch(e => { if (live) setError(errorText(e)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [kind, archived, attention, offset, refresh]);
  async function importChannel(e) {
    e.preventDefault(); setBusy(true); setError('');
    try { await api.post(`${BASE}/imports`, { channel_id: channelId, kind }); setImporting(false); setChannelId(''); setRefresh(n => n + 1); }
    catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  return <Frame kind={kind} refresh={() => setRefresh(n => n + 1)}>
    <section className="cw-guide"><FileText size={22} /><div><h2>Du salon au dossier</h2><p>Les conversations restent dans Iris après la suppression du salon Discord. Les archives signalent si leur dernière sauvegarde est incomplète.</p></div></section>
    <div className="cw-toolbar">
      <div className="cw-toolbar" role="group" aria-label="État des dossiers">{[[false, 'Ouverts'], [true, 'Archives']].map(([value, label]) =>
        <button className="cw-button" key={label} aria-pressed={archived === value} onClick={() => { setArchived(value); setOffset(0); }}>{label}</button>)}</div>
      {!archived && <button className="cw-button" aria-pressed={attention} onClick={() => { setAttention(x => !x); setOffset(0); }}>À traiter</button>}
      <span className="cw-spacer" /><button className="cw-button" onClick={() => setImporting(true)}>Ajouter un salon existant</button>
    </div>
    {error && <p role="alert" className="cw-alert">{error}</p>}{loading && <p role="status">Chargement des dossiers…</p>}
    {data && <section className="cw-card"><div className="cw-table-wrap"><table className="cw-table"><thead><tr><th>Membre</th><th>Suivi</th><th>Intervenant</th><th>Conversation</th><th>Dernière actualisation</th></tr></thead>
      <tbody>{data.items.map(row => <tr key={row.id}><td><Link to={`${pathFor(kind)}/${row.id}`}>{row.member?.display_name || row.member?.username || row.member?.id}</Link>
        {row.visibility !== 'staff' && <small className="cw-private"><LockKeyhole size={12} /> {row.visibility === 'leadership' ? 'Administration et Responsables' : 'Accès restreint'}</small>}</td>
        <td><State row={row} /></td><td>{row.assigned?.display_name || row.assigned?.id || 'À attribuer'}</td><td>{row.message_count || 0} messages</td><td>{date(row.sync?.at)}</td></tr>)}</tbody></table></div>
      {!data.items.length && <p className="cw-empty">Aucun dossier dans cette vue.</p>}
      <footer className="cw-toolbar"><button className="cw-button" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 25))}>Précédent</button>
        <span>Page {Math.floor(offset / 25) + 1} sur {Math.max(1, Math.ceil(data.total / 25))} · {data.total} dossiers</span>
        <button className="cw-button" disabled={offset + 25 >= data.total} onClick={() => setOffset(n => n + 25)}>Suivant</button></footer>
    </section>}
    {importing && <Modal title="Ajouter un salon existant" eyebrow="DOSSIERS IRIS" onClose={() => setImporting(false)} busy={busy}>
      <form className="cw-modal" onSubmit={importChannel}><p>Le salon doit appartenir aux catégories autorisées et posséder un panneau d’ouverture reconnu. Cette opération ne crée aucun salon Discord.</p>
        {error && <p role="alert">{error}</p>}<label>Identifiant du salon<input required pattern="[0-9]{17,20}" value={channelId} onChange={e => setChannelId(e.target.value)} /></label>
        <button className="cw-button cw-primary" disabled={busy}>{busy ? 'Vérification…' : 'Vérifier et ajouter'}</button></form>
    </Modal>}
  </Frame>;
}

function CaseDetail({ kind, caseId, canReassign = false, canSeeMember360 = false }) {
  const [row, setRow] = useState(null), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  const [messages, setMessages] = useState(null), [messageError, setMessageError] = useState(''), [offset, setOffset] = useState(0), [query, setQuery] = useState(''), [search, setSearch] = useState('');
  const [tab, setTab] = useState('notes'), [draftNote, setDraftNote] = useState(''), [assignee, setAssignee] = useState(''), [reason, setReason] = useState('');
  const [confirm, setConfirm] = useState(null), [busy, setBusy] = useState(false);
  const request = useRef(null);
  useEffect(() => {
    let live = true; setError('');
    api.get(`${BASE}/${caseId}`).then(r => {
      if (!live) return;
      if (r.data.kind !== kind) { setRow(null); setError('Ce dossier appartient à une autre famille.'); return; }
      setRow(r.data);
    }).catch(e => { if (live) { setRow(null); setError(errorText(e)); } });
    return () => { live = false; };
  }, [caseId, kind, refresh]);
  const generation = row?.sync?.generation;
  useEffect(() => {
    if (!row) return;
    let live = true; setMessages(null); setMessageError('');
    api.get(`${BASE}/${caseId}/messages`, { params: { offset, limit: 50, q: search } }).then(r => { if (live) setMessages(r.data); })
      .catch(e => { if (live) setMessageError(errorText(e)); });
    return () => { live = false; };
    // Reload a page after a completed snapshot, not after every metadata change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, Boolean(row), generation, offset, search]);
  useEffect(() => {
    if (!row || !(row.sync?.due || row.sync?.status === 'running' || row.status === 'closing' || row.status === 'reopening')) return;
    const timer = setInterval(() => { if (document.visibilityState !== 'hidden') setRefresh(n => n + 1); }, 10000);
    return () => clearInterval(timer);
  }, [row]);
  async function send(data) {
    const serialized = JSON.stringify(data);
    if (request.current?.serialized !== serialized) request.current = { serialized, id: globalThis.crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      const r = await api.post(`${BASE}/${caseId}/actions`, { ...data, request_id: request.current.id });
      setRow(r.data); setConfirm(null); request.current = null; if (data.action === 'note') setDraftNote('');
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const action = (name, extra = {}) => setConfirm({ action: name, revision: row.revision, ...extra });
  return <Frame kind={kind} title={row?.member?.display_name || row?.member?.username || 'Dossier du membre'} back refresh={() => setRefresh(n => n + 1)}>
    {error && <p role="alert" className="cw-alert">{error}</p>}{!row && !error && <p role="status">Chargement du dossier…</p>}
    {row && <><section className="cw-strip"><State row={row} /><span>Intervenant : {row.assigned?.display_name || row.assigned?.id || 'À attribuer'}</span><span>Ouvert le {date(row.created_at)}</span>
      {row.visibility !== 'staff' && <strong><LockKeyhole size={14} /> Accès confidentiel</strong>}</section>
      {row.discord_actions_enabled===false && <p className="cw-guide">La collecte et le suivi sont disponibles. La clôture Discord sera accessible après la bascule des commandes BotGhost vers Iris.</p>}
      {(row.closure?.error_type||row.closure?.cancel_error) && <p className="cw-alert">La clôture demande une vérification des accès, des fichiers ou des derniers messages. Le salon n’est pas annoncé comme supprimé. Un Responsable ou Administrateur peut reprendre l’action.</p>}
      {row.status === 'archived' && row.archive && <section className={`cw-archive ${row.archive.complete ? 'is-complete' : ''}`}><h2>{row.archive.complete ? 'Conversation archivée dans Iris' : 'Dernière sauvegarde conservée'}</h2>
        <p>{row.archive.complete ? 'Les messages et fichiers ont été vérifiés avant la suppression du salon.' : 'Le salon Discord a disparu avant une clôture confirmée. Des messages ou fichiers peuvent manquer ; les données déjà récupérées restent consultables.'}</p></section>}
      <div className="cw-layout"><section className="cw-card cw-conversation"><header className="cw-section-head"><div><p className="cz-eyebrow">CONVERSATION</p><h2>Les échanges</h2></div><span>{messages?.total ?? row.message_count} messages</span></header>
        <form className="cw-search" onSubmit={e => { e.preventDefault(); setSearch(query); setOffset(0); }}><Search size={17} /><input aria-label="Rechercher dans toute la conversation" maxLength={200} placeholder="Un mot, un auteur… dans toute la conversation" value={query} onChange={e => setQuery(e.target.value)} /><button className="cw-button">Rechercher</button></form>
        {messageError && <p role="alert" className="cw-alert">{messageError}</p>}{!messages && !messageError && <p role="status">Chargement des échanges…</p>}
        <div className="cw-messages">{messages?.items.map(item => <article className="cw-message" key={item.id}><div className="cw-avatar">{mediaUrl(item.author?.avatar_url) ? <img src={mediaUrl(item.author.avatar_url)} alt="" onError={e => { e.currentTarget.hidden = true; }} /> : <span>{(item.author?.display_name || item.author?.username || '?').slice(0, 1)}</span>}</div>
          <div><header><strong>{item.author?.display_name || item.author?.username}</strong><time>{date(item.timestamp)}</time></header><p>{item.content}</p>
            {item.attachments?.map(file => <div className="cw-file" key={file.id}>{mediaUrl(file.url) ? <a href={mediaUrl(file.url)}>{file.filename} · Télécharger</a> : <span>{file.filename} · Fichier non conservé</span>}</div>)}</div></article>)}</div>
        {messages && !messages.items.length && <p className="cw-empty">{search ? 'Aucun message ne correspond à cette recherche.' : 'Aucun échange à afficher. Le panneau d’ouverture est conservé dans l’archive et masqué ici.'}</p>}
        {messages && <footer className="cw-pagination"><button className="cw-button" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 50))}>Précédent</button><span>Page {Math.floor(offset / 50) + 1} sur {Math.max(1, Math.ceil(messages.total / 50))}</span><button className="cw-button" disabled={offset + 50 >= messages.total} onClick={() => setOffset(n => n + 50)}>Suivant</button></footer>}
      </section><aside className="cw-aside"><section className="cw-card"><header className="cw-section-head"><div><p className="cz-eyebrow">ACTUALISATION</p><h2>Le lien avec Discord</h2></div></header>
        <p>{row.sync?.status === 'error' ? 'Actualisation à reprendre' : row.sync?.status === 'running' ? 'Récupération des messages en cours…' : row.sync?.due ? 'Actualisation demandée' : 'Dernière sauvegarde : ' + date(row.sync?.at)}</p>
        {row.sync?.files_complete === false && <p className="cw-alert">Les pièces jointes ne sont pas toutes conservées. Une clôture automatique sera bloquée.</p>}
        {row.status !== 'archived' && <div className="cw-actions"><button className="cw-button" disabled={busy} onClick={() => send({ action: 'sync', revision: row.revision })}>Actualiser les messages</button>
          {!row.assigned && <button className="cw-button" disabled={busy} onClick={() => action('claim')}>Prendre en charge</button>}
          {canReassign && <form onSubmit={e => { e.preventDefault(); action('assign', { assignee_id: assignee || null }); }}><label>Réattribuer à un intervenant<input pattern="[0-9]{17,20}" placeholder="Identifiant Discord, ou vide pour désattribuer" value={assignee} onChange={e => setAssignee(e.target.value)} /></label><button className="cw-button" disabled={busy}>Vérifier la réattribution</button></form>}
          {(row.status !== 'closing' || canReassign) && <form onSubmit={e => { e.preventDefault(); action('archive', { text: reason }); }}><label>Motif de clôture<textarea required minLength={10} maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label><button className="cw-button cw-danger" disabled={busy||row.discord_actions_enabled===false}>{row.status === 'closing' ? 'Reprendre la clôture' : 'Préparer la clôture'}</button></form>}
          {row.status==='closing'&&canReassign&&row.closure?.stage!=='deleting'&&<button className="cw-button" disabled={busy||reason.trim().length<10||row.native_workflows_enabled===false} onClick={()=>action('cancel_close',{text:reason})}>Annuler la clôture et rétablir les accès</button>}
        </div>}</section>
        <section className="cw-card cw-followup"><header className="cw-section-head"><div><p className="cz-eyebrow">SUIVI DU DOSSIER</p><h2>Repères et historique</h2></div></header>
          <div className="cw-tabs" role="group" aria-label="Informations du dossier">{[['notes', 'Notes'], ['history', 'Historique'], ['links', 'Parcours']].map(([value, label]) => <button className="cw-button" key={value} aria-pressed={tab === value} onClick={() => setTab(value)}>{label}</button>)}</div>
          {tab === 'notes' && <>{row.opening_context?.reason && <details className="cw-note"><summary>Motif d’ouverture</summary><p>{row.opening_context.reason}</p></details>}{row.status !== 'archived' && <form className="cw-note-form" onSubmit={e => { e.preventDefault(); send({ action: 'note', revision: row.revision, text: draftNote }); }}><label>Nouvelle note interne<textarea required maxLength={25000} value={draftNote} onChange={e => setDraftNote(e.target.value)} /></label><button className="cw-button cw-primary" disabled={busy}>Ajouter la note</button></form>}{[...(row.notes || [])].reverse().map(note => <article className="cw-note" key={note.id}><p>{note.text}</p><small>{date(note.at)} · {note.actor_id}</small></article>)}</>}
          {tab === 'history' && <ol className="cw-history">{[...(row.events || [])].reverse().map(item => <li key={item.id}><strong>{item.action ? ACTIONS[item.action] : EVENTS[item.kind] || 'Événement du dossier'}</strong><time>{date(item.at)}</time>{item.actor_id && <small>Par {item.actor_id}</small>}</li>)}</ol>}
          {tab === 'links' && <div className="cw-actions"><p>Le dossier reste relié au membre après la fermeture du salon.</p>{canSeeMember360 && <Link className="cw-button" to={`/moderation/membres/${row.member?.id}`}>Vue membre 360°</Link>}
            {kind === 'verification' && <Link className="cw-button" to={`/staff/verifications/${row.member?.id}`}>Formulaires d’admission</Link>}
            {row.status !== 'archived' && <a className="cw-button" href={`https://discord.com/channels/${row.guild_id}/${row.channel_id}`} target="_blank" rel="noreferrer">Ouvrir le salon Discord</a>}</div>}
        </section>
      </aside></div></>}
    {confirm && <Modal title="Confirmer l’action" eyebrow={FAMILIES[kind].short.toUpperCase()} busy={busy} onClose={() => setConfirm(null)}><div className="cw-modal"><h3>{ACTIONS[confirm.action]}</h3>
      {error && <p role="alert" className="cw-alert">{error}</p>}
      {confirm.action === 'archive' ? <><p>La conversation et ses fichiers seront vérifiés dans Iris avant la suppression du salon Discord. Une pièce jointe manquante bloque cette suppression. Le dossier restera consultable dans les archives et le parcours du membre.</p><p>{confirm.text}</p></> : <p>L’attribution sera enregistrée sans réduire l’accès des autres intervenants autorisés.</p>}
      <button className="cw-button cw-primary" disabled={busy} onClick={() => send(confirm)}>{busy ? 'Enregistrement…' : 'Confirmer'}</button></div></Modal>}
  </Frame>;
}

function FamilyPage({ kind, canReassign = false, canSeeMember360 = false }) {
  const { caseId } = useParams();
  return caseId ? <CaseDetail key={`${kind}:${caseId}`} kind={kind} caseId={caseId} canReassign={canReassign} canSeeMember360={canSeeMember360} /> : <CaseList key={kind} kind={kind} />;
}
export const VerificationTicketsPage = props => <FamilyPage kind="verification" {...props} />;
export const ConvocationsPage = props => <FamilyPage kind="summons" {...props} />;
export const ContactsStaffPage = props => <FamilyPage kind="contact_staff" {...props} />;
export const BullesPage = props => <FamilyPage kind="bubble" {...props} />;
