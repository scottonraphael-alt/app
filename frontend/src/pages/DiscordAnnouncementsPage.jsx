import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowRight, ArrowUp, Copy, FilePlus2, ImagePlus, Plus, Save, Send, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { api, getErrorMessage as apiErrorMessage } from '../api/client';
import { Field, Modal, Pagination } from '../components/projects/ProjectUI';
import BlockEditor from '../components/announcements/Editors';
import Preview from '../components/announcements/Preview';
import useAnnouncementAudit from '../components/announcements/useAnnouncementAudit';
import { BLOCK_LABELS, assetUrl, blockTitle, cloneDocument, compileDocument, downloadJson, newBlock, newDocument, newGroup, uid } from '../components/announcements/document';
import '../Casier.css';
import '../DiscordAnnouncements.css';
const BASE = '/responsable/annonces';
const getErrorMessage = error => {
  const message = apiErrorMessage(error);
  return typeof message === 'string' ? message : 'Les données ne sont pas valides. Vérifiez les champs et les limites du composeur.';
};
const TABS = [['compose', 'Composition'], ['distribution', 'Distribution'], ['assets', 'Fichiers'], ['history', 'Publications'], ['json', 'JSON & import']];
const STATUS = {
  scheduled: 'Programmée',
  sending: 'Envoi en cours',
  sent: 'Publiée',
  failed: 'Échec',
  unknown: 'À vérifier sur Discord',
  cancelled: 'Annulée'
};
const when = value => value ? new Date(value).toLocaleString('fr-FR', {
  timeZone: 'Europe/Paris',
  dateStyle: 'medium',
  timeStyle: 'short'
}) : '—';
const metadata = draft => ({
  id: draft.id,
  name: draft.name,
  channel_id: draft.channel_id || '',
  is_template: !!draft.is_template,
  revision: draft.revision
});
function Check({
  label,
  value,
  onChange
}) {
  return <label className="an-check"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />{label}</label>;
}
export default function DiscordAnnouncementsPage({
  helper
}) {
  const [params, setParams] = useSearchParams();
  const [meta, setMeta] = useState({
    id: null,
    name: 'Nouvelle annonce',
    channel_id: '',
    is_template: false,
    revision: null
  });
  const [doc, setDoc] = useState(() => newDocument());
  const [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false);
  const [catalogue, setCatalogue] = useState({
      channels: [],
      roles: [],
      guild_id: null
    }),
    [catalogueError, setCatalogueError] = useState(false);
  const [library, setLibrary] = useState({
      items: [],
      total: 0,
      page: 1
    }),
    [libQuery, setLibQuery] = useState(''),
    [libKind, setLibKind] = useState('all'),
    [libLoading, setLibLoading] = useState(false);
  const [assets, setAssets] = useState({}),
    [assetPage, setAssetPage] = useState({
      items: [],
      total: 0,
      page: 1
    });
  const [tab, setTab] = useState('compose'),
    [selectedGroup, setSelectedGroup] = useState(null),
    [selectedBlock, setSelectedBlock] = useState(null);
  const [history, setHistory] = useState({
      items: [],
      total: 0,
      page: 1
    }),
    [historyLoading, setHistoryLoading] = useState(false);
  const [theme, setTheme] = useState('dark'),
    [mobilePreview, setMobilePreview] = useState(false),
    [confirmation, setConfirmation] = useState(null);
  const [jsonInput, setJsonInput] = useState(''),
    [recovery, setRecovery] = useState(null);
  const recoveryKey = `iris.announcement.recovery.${helper?.id || 'responsable'}`;
  useAnnouncementAudit(meta.id);
  const result = useMemo(() => compileDocument(doc, assets), [doc, assets]);
  const group = doc.groups.find(g => g.id === selectedGroup) || doc.groups[0];
  const block = group.blocks.find(b => b.id === selectedBlock) || group.blocks[0];
  const mergeAssets = items => setAssets(current => ({
    ...current,
    ...Object.fromEntries(items.map(a => [a.id, a]))
  }));
  const editDoc = update => {
    setDoc(current => typeof update === 'function' ? update(current) : update);
    setDirty(true);
  };
  const editMeta = (key, value) => {
    setMeta(m => ({
      ...m,
      [key]: value
    }));
    setDirty(true);
  };
  const editGroup = values => editDoc(d => ({
    ...d,
    groups: d.groups.map(g => g.id === group.id ? {
      ...g,
      ...values
    } : g)
  }));
  const editBlock = next => editGroup({
    blocks: group.blocks.map(b => b.id === next.id ? next : b)
  });
  const confirmDiscard = () => !dirty || window.confirm('Ce brouillon contient des modifications non enregistrées. Continuer sans les enregistrer ?');
  const loadLibrary = async (page = 1) => {
    setLibLoading(true);
    try {
      const r = await api.get(`${BASE}/drafts`, {
        params: {
          page,
          q: libQuery,
          kind: libKind
        }
      });
      setLibrary(r.data);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setLibLoading(false);
    }
  };
  const loadAssets = async (page = 1) => {
    try {
      const r = await api.get(`${BASE}/assets`, {
        params: {
          page
        }
      });
      setAssetPage(r.data);
      mergeAssets(r.data.items);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };
  const loadCatalogue = async () => {
    setCatalogueError(false);
    try {
      const r = await api.get(`${BASE}/catalogue`);
      setCatalogue(r.data);
    } catch (error) {
      setCatalogueError(true);
      toast.error(getErrorMessage(error));
    }
  };
  const loadHistory = async (page = 1) => {
    setHistoryLoading(true);
    try {
      const r = await api.get(`${BASE}/publications`, {
        params: {
          page,
          ...(meta.id ? {
            draft_id: meta.id
          } : {})
        }
      });
      setHistory(r.data);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setHistoryLoading(false);
    }
  };
  const loadDraft = async id => {
    if (!confirmDiscard()) return;
    setBusy(true);
    try {
      const r = await api.get(`${BASE}/drafts/${id}`);
      setMeta(metadata(r.data));
      setDoc(r.data.document);
      mergeAssets(r.data.assets || []);
      setDirty(false);
      setSelectedGroup(null);
      setSelectedBlock(null);
      setParams({
        draft: id
      }, {
        replace: true
      });
      setTab('compose');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    document.body.classList.add('announcements-no-nav');
    loadCatalogue();
    loadAssets();
    try {
      const value = JSON.parse(localStorage.getItem(recoveryKey));
      if (value?.document?.groups) setRecovery(value);
    } catch {}
    return () => document.body.classList.remove('announcements-no-nav');
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const timer = setTimeout(() => loadLibrary(1), 200);
    return () => clearTimeout(timer);
  }, [libQuery, libKind]); // eslint-disable-line react-hooks/exhaustive-deps
  const requestedDraft = params.get('draft');
  useEffect(() => {
    if (requestedDraft && requestedDraft !== meta.id) loadDraft(requestedDraft);
  }, [requestedDraft]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab === 'history') loadHistory();
  }, [tab, meta.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const prevent = e => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', prevent);
    return () => window.removeEventListener('beforeunload', prevent);
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const timer = setTimeout(() => {
      try {
        localStorage.setItem(recoveryKey, JSON.stringify({
          meta,
          document: doc,
          assets: Object.values(assets)
        }));
      } catch {}
    }, 700);
    return () => clearTimeout(timer);
  }, [dirty, doc, meta, assets, recoveryKey]);
  const start = (preset = 'simple', document = null, name = 'Nouvelle annonce', channel = '') => {
    if (!confirmDiscard()) return;
    setDoc(document || newDocument(preset));
    setMeta({
      id: null,
      name,
      channel_id: channel,
      is_template: false,
      revision: null
    });
    setDirty(true);
    setSelectedGroup(null);
    setSelectedBlock(null);
    setParams({}, {
      replace: true
    });
    setTab('compose');
  };
  const save = async () => {
    setBusy(true);
    try {
      const body = {
        name: meta.name,
        channel_id: meta.channel_id || null,
        is_template: meta.is_template,
        document: doc,
        expected_revision: meta.revision
      };
      const r = meta.id ? await api.put(`${BASE}/drafts/${meta.id}`, body) : await api.post(`${BASE}/drafts`, body);
      setMeta(metadata(r.data));
      setDirty(false);
      setParams({
        draft: r.data.id
      }, {
        replace: true
      });
      try {
        localStorage.removeItem(recoveryKey);
      } catch {}
      setRecovery(null);
      loadLibrary(1);
      toast.success('Brouillon enregistré.');
      return r.data;
    } catch (error) {
      toast.error(getErrorMessage(error));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const removeDraft = async draft => {
    if (!window.confirm(`Supprimer le brouillon « ${draft.name} » ? Les messages déjà publiés resteront sur Discord.`)) return;
    setBusy(true);
    try {
      await api.delete(`${BASE}/drafts/${draft.id}`);
      if (meta.id === draft.id) {
        setDoc(newDocument());
        setMeta({
          id: null,
          name: 'Nouvelle annonce',
          channel_id: '',
          is_template: false,
          revision: null
        });
        setDirty(false);
        setParams({}, {
          replace: true
        });
      }
      loadLibrary(library.page);
      toast.success('Brouillon supprimé.');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const reorder = (index, delta) => {
    const blocks = [...group.blocks];
    [blocks[index], blocks[index + delta]] = [blocks[index + delta], blocks[index]];
    editGroup({
      blocks
    });
  };
  const upload = async file => {
    if (!file) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const r = await api.post(`${BASE}/assets`, body);
      mergeAssets([r.data]);
      loadAssets(1);
      toast.success('Fichier ajouté à la bibliothèque.');
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  };
  const openPublish = async (mode = 'create', target = null) => {
    if (meta.is_template) {
      toast.error('Utilisez ce modèle comme nouveau brouillon avant de publier.');
      return;
    }
    if (result.errors.length) {
      toast.error('Corrigez les points signalés avant de publier.');
      return;
    }
    if (!meta.channel_id) {
      setTab('distribution');
      toast.error('Choisissez le salon de destination.');
      return;
    }
    if (target && target.channel_id !== meta.channel_id) {
      setTab('distribution');
      toast.error('Choisissez le salon d’origine pour modifier cette annonce.');
      return;
    }
    const draft = dirty || !meta.id ? await save() : {
      ...meta,
      document: doc
    };
    if (!draft) return;
    setConfirmation({
      draft,
      mode,
      target,
      requestId: uid(),
      schedule: false,
      local: '',
      busy: false
    });
  };
  const publish = async () => {
    const current = confirmation;
    setConfirmation(v => ({
      ...v,
      busy: true
    }));
    try {
      const r = await api.post(`${BASE}/drafts/${current.draft.id}/publish`, {
        expected_revision: current.draft.revision,
        request_id: current.requestId,
        mode: current.mode,
        target_id: current.target?.id || null,
        schedule_local: current.schedule ? current.local : null
      });
      setConfirmation(null);
      setTab('history');
      loadHistory();
      toast[r.data.status === 'sent' || r.data.status === 'scheduled' ? 'success' : 'error'](r.data.status === 'sent' ? 'Annonce publiée.' : r.data.status === 'scheduled' ? 'Annonce programmée.' : r.data.reason || 'Vérifiez le statut de la publication.');
    } catch (error) {
      setConfirmation(v => ({
        ...v,
        busy: false
      }));
      toast.error(getErrorMessage(error));
    }
  };
  const importJson = async () => {
    setBusy(true);
    try {
      const raw = JSON.parse(jsonInput);
      const r = await api.post(`${BASE}/preview`, raw);
      if (!confirmDiscard()) return;
      editDoc(r.data.document);
      mergeAssets(r.data.assets || []);
      setSelectedGroup(null);
      setSelectedBlock(null);
      setTab('compose');
      toast.success('Document importé. Vérifiez les mentions et les fichiers avant de publier.');
    } catch (error) {
      toast.error(error instanceof SyntaxError ? 'Ce JSON n’est pas valide.' : getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const restoreVersion = async job => {
    if (!confirmDiscard()) return;
    setBusy(true);
    try {
      const r = await api.get(`${BASE}/publications/${job.id}`);
      setDoc(cloneDocument(r.data.document));
      mergeAssets(r.data.assets || []);
      setMeta({
        id: null,
        name: `${job.name} — copie`.slice(0, 160),
        channel_id: job.channel_id,
        is_template: false,
        revision: null
      });
      setDirty(true);
      setParams({}, {
        replace: true
      });
      setTab('compose');
      setSelectedGroup(null);
      setSelectedBlock(null);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  return <section className="cz-page an-page"><header className="cz-header"><div className="cz-header-copy"><p className="cz-eyebrow">ESPACE RESPONSABLE · COMMUNICATION</p><h1>Les annonces, bien composées.</h1><p className="cz-intro">Structurez votre message Discord V2, vérifiez son aperçu puis choisissez quand et où le publier.</p></div><div className="cz-header-actions"><Link to="/" className="cz-home" onClick={e => {
          if (!confirmDiscard()) e.preventDefault();
        }}>Accueil <ArrowRight size={17} /></Link><button className="an-button" disabled={busy || uploading} onClick={save}><Save size={16} /> Enregistrer</button><button className="an-button an-primary" disabled={busy || uploading || meta.is_template} onClick={() => openPublish()}><Send size={16} /> Publier</button></div></header>
    {recovery && <div className="an-notice"><p>Un brouillon local non enregistré est disponible sur ce navigateur.</p><button className="an-button" onClick={async () => {
        setBusy(true);
        try {
          const r = await api.post(`${BASE}/preview`, recovery.document);
          if (!confirmDiscard()) return;
          setDoc(r.data.document);
          setMeta(recovery.meta);
          mergeAssets([...(recovery.assets || []), ...(r.data.assets || [])]);
          setDirty(true);
          setRecovery(null);
          setParams(recovery.meta.id ? {
            draft: recovery.meta.id
          } : {}, {
            replace: true
          });
        } catch (error) {
          toast.error(getErrorMessage(error));
        } finally {
          setBusy(false);
        }
      }}>Reprendre</button><button className="an-button" onClick={() => {
        localStorage.removeItem(recoveryKey);
        setRecovery(null);
      }}>Effacer</button></div>}
    {catalogueError && <div className="an-notice"><p>Le catalogue Discord est indisponible. Vous pouvez continuer le brouillon et renseigner un ID de salon.</p><button className="an-button" onClick={loadCatalogue}>Réessayer</button></div>}
    <div className="an-workspace" inert={busy || uploading ? true : undefined}><aside className="an-library"><header><p className="cz-eyebrow">VOTRE ATELIER</p><h2>Brouillons & modèles</h2><button className="an-button" onClick={() => start()} disabled={busy}><FilePlus2 size={15} /> Nouveau</button></header><label className="an-sr-only" htmlFor="an-search">Rechercher un brouillon</label><input id="an-search" placeholder="Rechercher…" value={libQuery} onChange={e => setLibQuery(e.target.value)} /><select aria-label="Afficher les brouillons ou les modèles" value={libKind} onChange={e => setLibKind(e.target.value)}><option value="all">Tout l’atelier</option><option value="draft">Brouillons</option><option value="template">Modèles</option></select><div className="an-library-list">{libLoading ? <p className="an-help">Chargement…</p> : library.items.length ? library.items.map(draft => <article key={draft.id} className={meta.id === draft.id ? 'is-selected' : ''}><button disabled={busy} className="an-library-open" onClick={() => loadDraft(draft.id)}><strong>{draft.name}</strong><small>{draft.is_template ? 'Modèle' : 'Brouillon'} · v{draft.revision}</small><time>{when(draft.updated_at)}</time></button><button className="an-icon an-danger" aria-label={`Supprimer ${draft.name}`} disabled={busy} onClick={() => removeDraft(draft)}><Trash2 size={14} /></button></article>) : <p className="an-help">Vos brouillons enregistrés apparaîtront ici.</p>}</div><Pagination page={library.page} pageSize={20} total={library.total} label="brouillons" onChange={loadLibrary} /><details className="an-presets"><summary>Partir d’une trame</summary>{[['simple', 'Annonce simple'], ['event', 'Animation & événement'], ['maintenance', 'Informations & changements']].map(([key, label]) => <button key={key} className="an-button" onClick={() => start(key)}>{label}</button>)}</details></aside>
      <main className="an-editor"><div className="an-draft-bar"><Field label="Nom interne du brouillon"><input maxLength={160} value={meta.name} onChange={e => editMeta('name', e.target.value)} /></Field><span className={`an-save-state ${dirty ? 'is-dirty' : ''}`}>{dirty ? 'Modifications non enregistrées' : meta.id ? `Version ${meta.revision} enregistrée` : 'Nouveau brouillon'}</span><button className="an-icon" title="Dupliquer le brouillon" aria-label="Dupliquer le brouillon" onClick={() => start('simple', cloneDocument(doc), `${meta.name} — copie`.slice(0, 160), meta.channel_id)}><Copy size={16} /></button></div><nav className="an-tabs" aria-label="Rubriques du composeur">{TABS.map(([key, label]) => <button key={key} aria-current={tab === key ? 'page' : undefined} className={tab === key ? 'is-active' : ''} onClick={() => setTab(key)}>{label}</button>)}</nav>
        {tab === 'compose' && <><div className="an-group-selector"><select aria-label="Panneau à composer" value={group.id} onChange={e => {
              setSelectedGroup(e.target.value);
              setSelectedBlock(null);
            }}>{doc.groups.map((g, i) => <option key={g.id} value={g.id}>{i + 1}. {g.name}</option>)}</select><button className="an-button" disabled={doc.groups.length >= 10} onClick={() => {
              const g = newGroup();
              editDoc(d => ({
                ...d,
                groups: [...d.groups, g]
              }));
              setSelectedGroup(g.id);
              setSelectedBlock(null);
            }}><Plus size={15} /> Panneau</button></div><details className="an-group-settings"><summary>Présentation du panneau</summary><div className="an-fields"><Field label="Nom interne du panneau"><input maxLength={100} value={group.name} onChange={e => editGroup({
                  name: e.target.value
                })} /></Field><Check label="Regrouper dans un panneau Discord" value={group.boxed} onChange={boxed => editGroup({
                boxed
              })} />{group.boxed && <><Field label="Couleur d’accent"><div className="an-color"><input type="color" value={group.color || '#78618c'} onChange={e => editGroup({
                      color: e.target.value
                    })} /><span>{group.color || 'Sans accent'}</span><button className="an-button" onClick={() => editGroup({
                      color: null
                    })}>Sans couleur</button></div></Field><Check label="Panneau spoiler" value={group.spoiler} onChange={spoiler => editGroup({
                  spoiler
                })} /></>}<div className="an-inline"><button className="an-button" disabled={doc.groups.indexOf(group) === 0} onClick={() => {
                  const groups = [...doc.groups],
                    i = groups.indexOf(group);
                  [groups[i], groups[i - 1]] = [groups[i - 1], groups[i]];
                  editDoc({
                    ...doc,
                    groups
                  });
                }}>Monter le panneau</button><button className="an-button" disabled={doc.groups.indexOf(group) === doc.groups.length - 1} onClick={() => {
                  const groups = [...doc.groups],
                    i = groups.indexOf(group);
                  [groups[i], groups[i + 1]] = [groups[i + 1], groups[i]];
                  editDoc({
                    ...doc,
                    groups
                  });
                }}>Descendre le panneau</button><button className="an-button an-danger" disabled={doc.groups.length === 1} onClick={() => {
                  editDoc({
                    ...doc,
                    groups: doc.groups.filter(g => g.id !== group.id)
                  });
                  setSelectedGroup(null);
                  setSelectedBlock(null);
                }}>Supprimer le panneau</button></div></div></details>
          <div className="an-add-block">{Object.entries(BLOCK_LABELS).map(([kind, label]) => <button className="an-button" key={kind} disabled={group.blocks.length >= 40} onClick={() => {
              const b = newBlock(kind);
              editGroup({
                blocks: [...group.blocks, b]
              });
              setSelectedBlock(b.id);
            }}><Plus size={13} />{label}</button>)}</div><ol className="an-block-outline">{group.blocks.map((b, i) => <li key={b.id} className={b.id === block?.id ? 'is-active' : ''}><button className="an-outline-open" onClick={() => setSelectedBlock(b.id)}><small>{i + 1} · {BLOCK_LABELS[b.kind]}</small><strong>{blockTitle(b)}</strong></button><div><button className="an-icon" aria-label={`Monter le bloc ${i + 1}`} disabled={!i} onClick={() => reorder(i, -1)}><ArrowUp size={14} /></button><button className="an-icon" aria-label={`Descendre le bloc ${i + 1}`} disabled={i === group.blocks.length - 1} onClick={() => reorder(i, 1)}><ArrowDown size={14} /></button><button className="an-icon" aria-label={`Dupliquer le bloc ${i + 1}`} disabled={group.blocks.length >= 40} onClick={() => {
                  const next = {
                    ...JSON.parse(JSON.stringify(b)),
                    id: uid()
                  };
                  editGroup({
                    blocks: [...group.blocks.slice(0, i + 1), next, ...group.blocks.slice(i + 1)]
                  });
                  setSelectedBlock(next.id);
                }}><Copy size={14} /></button><button className="an-icon an-danger" aria-label={`Retirer le bloc ${i + 1}`} onClick={() => editGroup({
                  blocks: group.blocks.filter(v => v.id !== b.id)
                })}><Trash2 size={14} /></button></div></li>)}</ol>{block ? <BlockEditor key={block.id} block={block} onChange={editBlock} assets={assets} catalogue={catalogue} /> : <div className="an-empty">Ajoutez un bloc pour commencer ce panneau.</div>}</>}
        {tab === 'distribution' && <section className="an-panel"><header><h2>La bonne annonce, au bon endroit.</h2><p>Le nom du brouillon reste interne. Seuls vos blocs seront publiés sur Discord.</p></header><div className="an-fields"><Field label="Salon de destination"><select value={meta.channel_id} onChange={e => editMeta('channel_id', e.target.value)}><option value="">Choisir un salon…</option>{meta.channel_id && !catalogue.channels.some(c => c.id === meta.channel_id) && <option value={meta.channel_id}>Salon {meta.channel_id}</option>}{catalogue.channels.map(channel => <option key={channel.id} value={channel.id}>{channel.category ? `${channel.category} / ` : ''}#{channel.name}</option>)}</select></Field>{catalogueError && <Field label="ID du salon"><input inputMode="numeric" value={meta.channel_id} onChange={e => editMeta('channel_id', e.target.value.trim())} /></Field>}<Check label="Enregistrer comme modèle réutilisable" value={meta.is_template} onChange={value => editMeta('is_template', value)} />{meta.is_template && <button className="an-button" onClick={() => start('simple', cloneDocument(doc), meta.name, meta.channel_id)}>Utiliser ce modèle comme nouveau brouillon</button>}<Check label="Envoi discret, sans notifications push" value={doc.silent} onChange={silent => editDoc({
              ...doc,
              silent
            })} /><fieldset className="an-mentions-settings"><legend>Mentions autorisées</legend><p className="an-help">Une mention doit aussi apparaître dans vos textes. Les autres mentions resteront visibles sans être autorisées à notifier. Les permissions Discord du bot continuent de s’appliquer.</p><div className="an-role-list">{catalogue.roles.map(role => <Check key={role.id} label={`@${role.name}`} value={doc.mentions.roles.includes(role.id)} onChange={selected => editDoc({
                  ...doc,
                  mentions: {
                    ...doc.mentions,
                    roles: selected ? [...doc.mentions.roles, role.id] : doc.mentions.roles.filter(id => id !== role.id)
                  }
                })} />)}</div><Field label="Rôles autorisés · identifiants séparés par des virgules"><input value={doc.mentions.roles.join(', ')} onBlur={() => editDoc({
                  ...doc,
                  mentions: {
                    ...doc.mentions,
                    roles: doc.mentions.roles.filter(Boolean)
                  }
                })} onChange={e => editDoc({
                  ...doc,
                  mentions: {
                    ...doc.mentions,
                    roles: e.target.value.split(/[,\s]+/)
                  }
                })} placeholder="Identifiants Discord, si le catalogue est indisponible" /></Field><Field label="Utilisateurs autorisés · identifiants séparés par des virgules"><input value={doc.mentions.users.join(', ')} onBlur={() => editDoc({
                  ...doc,
                  mentions: {
                    ...doc.mentions,
                    users: doc.mentions.users.filter(Boolean)
                  }
                })} onChange={e => editDoc({
                  ...doc,
                  mentions: {
                    ...doc.mentions,
                    users: e.target.value.split(/[,\s]+/)
                  }
                })} placeholder="Ex. 123456789012345678" /></Field><Check label="Autoriser @everyone et @here" value={doc.mentions.everyone} onChange={everyone => editDoc({
                ...doc,
                mentions: {
                  ...doc.mentions,
                  everyone
                }
              })} />{doc.mentions.everyone && <p className="an-broadcast-warning">Les mentions générales pourront notifier le serveur si elles sont présentes dans le texte. Elles seront rappelées avant publication.</p>}</fieldset></div></section>}
        {tab === 'assets' && <section className="an-panel"><header><h2>Images, vidéos et documents</h2><p>Bibliothèque privée des responsables. Les fichiers sont envoyés directement à Discord avec votre annonce.</p></header><div className="an-panel-body"><label className="an-upload"><Upload size={20} /><span>{uploading ? 'Téléversement…' : 'Ajouter un fichier · 10 Mo maximum'}</span><input aria-label="Téléverser un fichier pour une annonce" type="file" disabled={uploading} onChange={e => {
                upload(e.target.files?.[0]);
                e.target.value = '';
              }} /></label><p className="an-help">Le total de fichiers joints à un message ne peut pas dépasser 10 Mo. Pour utiliser un fichier, sélectionnez-le dans un bloc média ou fichier.</p><div className="an-assets-list">{assetPage.items.map(asset => <article key={asset.id}><ImagePlus size={22} /><div><strong>{asset.original_filename}</strong><small>{asset.content_type} · {(asset.size / 1024).toFixed(0)} Ko</small></div><a href={assetUrl(api.defaults.baseURL, asset.id)} target="_blank" rel="noreferrer" className="an-button">Ouvrir</a></article>)}</div><Pagination page={assetPage.page} pageSize={20} total={assetPage.total} onChange={loadAssets} label="fichiers d’annonce" /></div></section>}
        {tab === 'history' && <section className="an-panel"><header><h2>Publications & programmation</h2><p>{meta.id ? 'Envois de ce brouillon, avec la version exacte publiée.' : 'Historique de toutes les annonces du module.'}</p><button className="an-button" onClick={() => loadHistory(history.page)} disabled={historyLoading}>Actualiser</button></header><div className="an-panel-body">{historyLoading ? <p className="an-help">Chargement…</p> : !history.items.length ? <div className="an-empty">Aucune publication dans cette sélection.</div> : <div className="an-history-list">{history.items.map(job => <article key={job.id}><div><span className={`an-status is-${job.status}`}>{STATUS[job.status] || job.status}</span><h3>{job.name}</h3><p>v{job.revision} · {job.mode === 'update' ? 'Modification' : 'Nouvel envoi'} · {job.actor.username}</p><small>{job.scheduled_at ? `Prévue le ${when(job.scheduled_at)}` : `Demandée le ${when(job.created_at)}`}</small>{job.reason && <p className="an-job-reason">{job.reason}</p>}</div><div className="an-history-actions">{job.message_url && <a className="an-button" href={job.message_url} target="_blank" rel="noreferrer">Voir sur Discord</a>}{job.status === 'unknown' && catalogue.guild_id && <a className="an-button" href={`https://discord.com/channels/${catalogue.guild_id}/${job.channel_id}`} target="_blank" rel="noreferrer">Vérifier le salon Discord</a>}{job.status === 'sent' && job.draft_id === meta.id && <button className="an-button" disabled={busy} onClick={() => openPublish('update', job)}>Mettre à jour ce message</button>}<button className="an-button" disabled={busy} onClick={() => restoreVersion(job)}>Réutiliser cette version</button>{job.status === 'scheduled' && <button className="an-button an-danger" onClick={async () => {
                    if (!window.confirm('Annuler cette publication programmée ?')) return;
                    try {
                      await api.post(`${BASE}/publications/${job.id}/cancel`);
                      loadHistory(history.page);
                    } catch (error) {
                      toast.error(getErrorMessage(error));
                    }
                  }}>Annuler la programmation</button>}</div></article>)}</div>}<Pagination page={history.page} pageSize={20} total={history.total} onChange={loadHistory} label="publications" /></div></section>}
        {tab === 'json' && <section className="an-panel"><header><h2>Votre annonce, réutilisable</h2><p>Le document Iris conserve la structure du composeur. Le payload Discord est fourni pour inspection ; les fichiers binaires restent dans la bibliothèque.</p></header><div className="an-panel-body"><div className="an-inline"><button className="an-button" onClick={() => downloadJson(doc, 'annonce-iris.json')}>Exporter le document Iris</button><button className="an-button" onClick={() => downloadJson(result.payload, 'annonce-discord-v2.json')}>Exporter le payload Discord</button><button className="an-button" disabled={busy} onClick={async () => {
                try {
                  const r = await api.post(`${BASE}/preview`, doc);
                  toast[r.data.errors.length ? 'error' : 'success'](r.data.errors.length ? r.data.errors.join(' ') : 'Le document respecte les contrôles du composeur.');
                } catch (error) {
                  toast.error(getErrorMessage(error));
                }
              }}>Vérifier côté serveur</button></div><details className="an-json"><summary>Inspecter le payload V2</summary><pre>{JSON.stringify(result.payload, null, 2)}</pre></details><Field label="Importer un document Iris JSON"><textarea rows={9} maxLength={150000} value={jsonInput} onChange={e => setJsonInput(e.target.value)} placeholder="Collez un document exporté depuis ce composeur…" /></Field><button className="an-button" disabled={busy || !jsonInput.trim()} onClick={importJson}>Importer dans le brouillon</button></div></section>}
      </main>
      <aside className={`an-preview-pane ${mobilePreview ? 'is-mobile' : ''}`}><header><div><p className="cz-eyebrow">AVANT DE PUBLIER</p><h2>Aperçu Discord</h2></div><select aria-label="Thème de l’aperçu" value={theme} onChange={e => setTheme(e.target.value)}><option value="dark">Sombre</option><option value="light">Clair</option></select></header><Check label="Largeur mobile" value={mobilePreview} onChange={setMobilePreview} /><Preview document={doc} assets={assets} catalogue={catalogue} base={api.defaults.baseURL} theme={theme} /><div className="an-counters"><span className={result.text_count > 4000 ? 'is-error' : ''}><strong>{result.text_count}</strong> / 4 000 caractères</span><span className={result.component_count > 40 ? 'is-error' : ''}><strong>{result.component_count}</strong> / 40 composants</span><span>{(result.file_size / 1024 / 1024).toFixed(1)} / 10 Mo</span></div>{result.errors.length ? <div className="an-validation" role="status"><h3>À compléter</h3><ul>{result.errors.map((error, i) => <li key={i}>{error}</li>)}</ul></div> : <div className="an-valid">La structure peut être publiée. Vérifiez aussi le salon et les mentions.</div>}<p className="an-help">Aperçu indicatif : Discord peut adapter la mise en forme, les médias et les retours à la ligne. Les limites sont vérifiées côté serveur avant l’envoi.</p></aside>
    </div>
    {confirmation && <Modal className="an-dialog" eyebrow="ANNONCES DISCORD" title={confirmation.mode === 'update' ? 'Mettre à jour cette annonce' : 'Prête pour la communauté ?'} onClose={() => setConfirmation(null)} busy={confirmation.busy}><div className="an-publish-dialog"><p><strong>{confirmation.draft.name}</strong> · version {confirmation.draft.revision}</p><p>Destination : <strong>#{catalogue.channels.find(c => c.id === confirmation.draft.channel_id)?.name || confirmation.draft.channel_id}</strong></p><p className="an-help">La version enregistrée affichée ici sera utilisée, même si le brouillon est modifié ensuite.</p>{confirmation.mode === 'update' ? <p className="an-notice">Ce message existant sera remplacé. Aucun nouveau ping ne sera autorisé lors de cette modification.</p> : <div className="an-publication-mentions"><strong>Mentions qui pourront notifier</strong><p>{confirmation.draft.document.mentions.roles.length} rôle(s) · {confirmation.draft.document.mentions.users.length} utilisateur(s)</p>{confirmation.draft.document.mentions.everyone ? <p className="an-broadcast-warning">@everyone / @here autorisés si présents dans le texte.</p> : <p className="an-help">Aucune mention générale autorisée.</p>}<p className="an-help">{confirmation.draft.document.silent ? 'Envoi discret : notifications push supprimées.' : 'Notifications habituelles, selon les réglages Discord des destinataires.'}</p></div>}<Check label="Programmer pour plus tard · heure de Paris" value={confirmation.schedule} onChange={schedule => setConfirmation(v => ({
          ...v,
          schedule
        }))} />{confirmation.schedule && <Field label="Date et heure de Paris"><input type="datetime-local" required value={confirmation.local} onChange={e => setConfirmation(v => ({
            ...v,
            local: e.target.value
          }))} /></Field>}<div className="an-inline"><button className="an-button" disabled={confirmation.busy} onClick={() => setConfirmation(null)}>Revenir au brouillon</button><button className="an-button an-primary" disabled={confirmation.busy || confirmation.schedule && !confirmation.local} onClick={publish}>{confirmation.busy ? 'Traitement…' : confirmation.schedule ? 'Programmer cette annonce' : confirmation.mode === 'update' ? 'Mettre à jour sur Discord' : 'Envoyer sur Discord'}</button></div></div></Modal>}
  </section>;
}
