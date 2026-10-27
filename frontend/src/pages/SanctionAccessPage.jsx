import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Copy, Eye, EyeOff, KeyRound, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage } from '../api/client';
import { Field, Modal, Pagination } from '../components/projects/ProjectUI';
import '../Casier.css';
import '../SanctionAccess.css';
const BASE = '/responsable/acces-sanctions';
const date = value => value ? new Date(value).toLocaleString('fr-FR', {
  timeZone: 'Europe/Paris',
  dateStyle: 'short',
  timeStyle: 'short'
}) : 'Jamais';
const errorMessage = error => typeof getErrorMessage(error) === 'string' ? getErrorMessage(error) : 'Le code doit contenir exactement 6 lettres ou chiffres.';
export default function SanctionAccessPage() {
  const [members, setMembers] = useState([]),
    [loading, setLoading] = useState(true),
    [failure, setFailure] = useState('');
  const [search, setSearch] = useState(''),
    [filter, setFilter] = useState('all'),
    [page, setPage] = useState(1);
  const [editing, setEditing] = useState(null),
    [code, setCode] = useState(''),
    [show, setShow] = useState(false),
    [saved, setSaved] = useState(false),
    [busy, setBusy] = useState(false);
  const load = async () => {
    setLoading(true);
    setFailure('');
    try {
      const r = await api.get(BASE);
      setMembers(r.data.items);
    } catch (error) {
      setFailure(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    document.body.classList.add('sanction-access-no-nav');
    load();
    return () => document.body.classList.remove('sanction-access-no-nav');
  }, []);
  useEffect(() => setPage(1), [search, filter]);
  const filtered = useMemo(() => members.filter(member => {
    const matches = `${member.display_name} ${member.username} ${member.id}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
    return matches && (filter === 'all' || filter === 'active' && member.access?.enabled || filter === 'missing' && !member.access || filter === 'revoked' && member.access && !member.access.enabled || filter === 'former' && !member.is_staff);
  }), [members, search, filter]);
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filtered.length / 20)));
  const close = () => {
    setEditing(null);
    setCode('');
    setShow(false);
    setSaved(false);
  };
  const open = member => {
    setEditing(member);
    setCode('');
    setShow(false);
    setSaved(false);
  };
  const generate = () => {
    try {
      const values = new Uint8Array(6);
      globalThis.crypto.getRandomValues(values);
      const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
      setCode([...values].map(v => alphabet[v % 32]).join(''));
      setShow(true);
    } catch {
      toast.error('La génération sécurisée n’est pas disponible dans ce navigateur.');
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      toast.success('Code copié.');
    } catch {
      toast.error('Copie impossible. Tu peux afficher et recopier le code.');
    }
  };
  const save = async () => {
    if (!/^[A-Z0-9]{6}$/.test(code)) return;
    setBusy(true);
    try {
      await api.put(`${BASE}/${editing.id}`, {
        code,
        expected_version: editing.access?.version || null
      });
      setSaved(true);
      load();
      toast.success('Accès enregistré. Les anciennes sessions sont révoquées.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const revoke = async member => {
    if (!window.confirm(`Révoquer l’accès de ${member.display_name} ? Ses parcours /sanction ouverts seront invalidés.`)) return;
    setBusy(true);
    try {
      await api.delete(`${BASE}/${member.id}`, {
        params: {
          expected_version: member.access.version
        }
      });
      await load();
      toast.success('Accès révoqué.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return <section className="cz-page sa-page"><header className="cz-header"><div className="cz-header-copy"><p className="cz-eyebrow">ESPACE RESPONSABLE · SÉCURITÉ</p><h1>Les accès modération.</h1><p className="cz-intro">Un code personnel pour chaque membre du staff, avant d’ouvrir le panel Discord /sanction.</p></div><div className="cz-header-actions"><Link to="/" className="cz-home">Accueil <ArrowRight size={17} /></Link><button className="sa-button" disabled={loading || busy} onClick={load}><RefreshCw size={16} />Actualiser</button></div></header>
 <div className="sa-guide"><KeyRound size={25} /><div><h2>6 caractères. Un accès personnel.</h2><p>Lettres et chiffres, sans distinction entre majuscules et minuscules. Le rôle Staff reste obligatoire. Remplacer ou révoquer un code invalide les accès ouverts.</p></div><span><ShieldCheck size={16} /> Codes stockés sous forme hachée</span></div>
 <section className="sa-directory"><header><div><p className="cz-eyebrow">GÉRER LES AUTORISATIONS</p><h2>Le staff et ses accès</h2><p>{members.filter(m => m.is_staff).length} membres Staff · {members.filter(m => m.access?.enabled).length} accès actifs</p></div><div className="sa-filters"><label><Search size={16} /><input aria-label="Rechercher un membre du staff" value={search} onChange={e => setSearch(e.target.value)} placeholder="Pseudo ou ID Discord…" /></label><select aria-label="Filtrer les accès" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Tous les accès</option><option value="missing">Sans code</option><option value="active">Actifs</option><option value="revoked">Révoqués</option><option value="former">Anciens membres du staff</option></select></div></header>
 {failure ? <div className="sa-empty" role="alert">{failure}<button className="sa-button" onClick={load}>Réessayer</button></div> : loading ? <div className="sa-empty" role="status">Chargement des accès…</div> : !filtered.length ? <div className="sa-empty">Aucun membre dans cette sélection.</div> : <div className="sa-rows">{filtered.slice((currentPage - 1) * 20, currentPage * 20).map(member => {
          const locked = member.access?.locked_until && new Date(member.access.locked_until) > new Date();
          return <article key={member.id}><div className="sa-person"><strong>{member.display_name}</strong><small>{member.id}{!member.is_staff ? ' · Rôle Staff absent' : ''}</small></div><span className={`sa-state ${member.access?.enabled ? 'is-active' : ''}`}>{locked ? 'Tentatives bloquées' : member.access?.enabled ? 'Actif' : member.access ? 'Révoqué' : 'À définir'}</span><div className="sa-last-used"><small>Dernier accès</small><span>{date(member.access?.last_used_at)}</span>{member.access?.updated_at && <small>Modifié le {date(member.access.updated_at)}</small>}</div><div className="sa-actions"><button className="sa-button" disabled={busy || !member.is_staff} onClick={() => open(member)}><KeyRound size={14} />{member.access ? 'Remplacer le code' : 'Définir le code'}</button>{member.access?.enabled && <button className="sa-button sa-danger" disabled={busy} onClick={() => revoke(member)}>Révoquer</button>}</div></article>;
        })}</div>}
 <Pagination page={currentPage} pageSize={20} total={filtered.length} onChange={setPage} label="accès" />
 </section>
 <p className="sa-footnote">Les codes existants ne sont jamais réaffichés. En cas d’oubli, remplace le code. Après 5 tentatives incorrectes, l’accès est bloqué pour la fenêtre de 15 minutes.</p>
 {editing && <Modal title={saved ? 'Accès enregistré' : 'Code personnel'} eyebrow="ACCÈS À /SANCTION" busy={busy} onClose={close} className="sa-modal"><div className="sa-modal-body"><p>Pour <strong>{editing.display_name}</strong> · {editing.id}</p><Field label="Code · exactement 6 lettres ou chiffres"><div className="sa-code-field"><input autoComplete="new-password" spellCheck={false} aria-label="Code personnel de modération" type={show ? 'text' : 'password'} minLength={6} maxLength={6} value={code} readOnly={saved} onChange={e => setCode(e.target.value.toUpperCase())} /><button className="sa-button" aria-label={show ? 'Masquer le code' : 'Afficher le code'} onClick={() => setShow(v => !v)}>{show ? <EyeOff size={16} /> : <Eye size={16} />}</button></div></Field><p className="sa-help">Transmets ce code personnel au membre par un canal privé. Il ne sera pas récupérable depuis Iris une fois cette fenêtre fermée.</p>{!saved && <button className="sa-button" onClick={generate}>Générer un code sécurisé</button>}{saved && <p className="sa-success" role="status">Le nouveau code est actif. Les anciennes sessions sont invalidées.</p>}<div className="sa-actions"><button className="sa-button" disabled={!/^[A-Z0-9]{6}$/.test(code)} onClick={copy}><Copy size={15} />Copier le code</button>{saved ? <button className="sa-button sa-primary" onClick={close}>Terminer</button> : <button className="sa-button sa-primary" disabled={busy || !/^[A-Z0-9]{6}$/.test(code)} onClick={save}>Enregistrer l’accès</button>}</div></div></Modal>}
 </section>;
}
