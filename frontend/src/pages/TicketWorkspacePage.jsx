import { Archive, ArrowRight, Bot, CalendarDays, Check, ChevronLeft, ChevronRight, ChevronsUpDown, ListFilter, Search, FilePlus2, FileText, HeartHandshake, LoaderCircle, MoreHorizontal, RefreshCw, Save, ShieldCheck, Trash2, UserRoundCheck, X } from "lucide-react";
import * as Tabs from "@radix-ui/react-tabs";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import { ticketEvent } from "../utils/ticketEvents";
import { resolveAvatarUrl } from "../utils/avatar";
import "@/TicketWorkspace.css";


const formatTime = (timestamp) => new Date(timestamp).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });


function MessageAvatar({ author }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [author.avatar_url]);
  return <span className="tw-author-avatar">{author.avatar_url && !failed
    ? <img src={resolveAvatarUrl(author.avatar_url)} alt="" onError={() => setFailed(true)} />
    : (author.display_name || author.username).slice(0, 1).toUpperCase()}</span>;
}


export default function TicketWorkspacePage({ onTicketUpdate, onTicketDeleted, isAdmin, helper }) {
  const { ticketId } = useParams();

  useEffect(() => {
    document.body.classList.add("ticket-workspace-no-nav");
    return () => document.body.classList.remove("ticket-workspace-no-nav");
  }, []);
  const navigate = useNavigate();
  const [ticket, setTicket] = useState(null);
  const [page, setPage] = useState(1);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(true);
  const [messagesError, setMessagesError] = useState("");
  const [messagesVersion, setMessagesVersion] = useState(0);
  const transcriptRef = useRef(null);
  const lastSyncRef = useRef(null);
  const openingRequest = useRef(null);
  const searchController = useRef(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchFrom, setSearchFrom] = useState("");
  const [searchTo, setSearchTo] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [highlightedMessage, setHighlightedMessage] = useState(null);
  lastSyncRef.current = ticket?.last_synced_at;
  const pageSize = 50;

  const [vocalSummary, setVocalSummary] = useState("");
  const [personTriggers, setPersonTriggers] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [followUpStatus, setFollowUpStatus] = useState("en attente de réponse");
  const [helpers, setHelpers] = useState([]);
  const [summaryProgress, setSummaryProgress] = useState("");
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [addingNote, setAddingNote] = useState(false);
  const [noteComposerOpen, setNoteComposerOpen] = useState(false);
  const [mobileView, setMobileView] = useState("messages");

  useEffect(() => {
    let active = true;
    setSearchOpen(false);
    setSearchResults(null);
    setHighlightedMessage(null);
    setSearchLoading(false);
    const loadTicket = async () => {
      setLoading(true);
      setError("");
      try {
        if (openingRequest.current?.id !== ticketId) {
          openingRequest.current = { id: ticketId, promise: api.post(`/tickets/${ticketId}/view`) };
        }
        const response = await openingRequest.current.promise;
        if (!active) return;
        onTicketUpdate?.(response.data);
        setTicket(response.data);
        setVocalSummary(response.data.vocal_summary || "");
        setPersonTriggers(response.data.person_triggers || "");
        setFollowUpStatus(response.data.follow_up_status || "en attente de réponse");
      } catch (requestError) {
        if (active) setError(getErrorMessage(requestError));
      } finally {
        if (active) setLoading(false);
      }
    };
    setPage(1);
    loadTicket();
    return () => { active = false; searchController.current?.abort(); };
  }, [ticketId]);

  useEffect(() => {
    if (!isAdmin) return;
    api.get("/admin/helpers").then((response) => setHelpers(response.data)).catch(() => undefined);
  }, [isAdmin]);

  useEffect(() => {
    const controller = new AbortController();
    setMessagesLoading(true);
    setMessagesError("");
    api.get(`/tickets/${ticketId}/messages`, { params: { page, page_size: pageSize }, signal: controller.signal })
      .then(({ data }) => {
        if (controller.signal.aborted) return;
        const lastPage = Math.max(1, Math.ceil(data.total / pageSize));
        if (page > lastPage) { setPage(lastPage); return; }
        setMessages(data.messages);
        setTicket((current) => current ? { ...current, message_count: data.total } : current);
        transcriptRef.current?.scrollTo?.({ top: 0 });
      })
      .catch((requestError) => { if (!controller.signal.aborted) setMessagesError(getErrorMessage(requestError)); })
      .finally(() => { if (!controller.signal.aborted) setMessagesLoading(false); });
    return () => controller.abort();
  }, [ticketId, page, messagesVersion]);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const { data } = await api.get(`/tickets/${ticketId}`, { params: { include_transcript: false }, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (data.last_synced_at !== lastSyncRef.current) setMessagesVersion((version) => version + 1);
        setTicket((current) => current ? { ...current, ai_summary: data.ai_summary, last_synced_at: data.last_synced_at, message_count: data.message_count, sync_status: data.sync_status, sync_error: data.sync_error, last_sync_attempt_at: data.last_sync_attempt_at, summary_status: data.summary_status, summary_error: data.summary_error } : current);
      } catch {
        // Les erreurs de lecture ponctuelles ne doivent pas interrompre la saisie.
      }
    };
    const interval = window.setInterval(refresh, 30 * 1000);
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [ticketId]);

  useEffect(() => {
    if (!messagesLoading && highlightedMessage && !searchOpen) {
      document.getElementById(`tw-message-${highlightedMessage}`)?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }
  }, [messagesLoading, messages, highlightedMessage, searchOpen]);

  const changePage = (value) => {
    setPage(value);
    setHighlightedMessage(null);
    ticketEvent("messages.page_changed", ticketId, value);
  };
  const searchMessages = async (event, resultPage = 1) => {
    event?.preventDefault();
    searchController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    setSearchLoading(true);
    setSearchError("");
    try {
      const { data } = await api.get(`/tickets/${ticketId}/messages/search`, { params: { q: searchTerm, from_day: searchFrom || undefined, to_day: searchTo || undefined, search_page: resultPage }, signal: controller.signal });
      if (!controller.signal.aborted) { setSearchResults(data); transcriptRef.current?.scrollTo?.({ top: 0 }); }
    } catch (requestError) { if (!controller.signal.aborted) setSearchError(getErrorMessage(requestError)); }
    finally { if (!controller.signal.aborted) setSearchLoading(false); }
  };
  const openSearchResult = (item) => {
    setPage(item.message_page);
    setHighlightedMessage(item.message_id);
    setSearchOpen(false);
    ticketEvent("search.result_opened", ticketId, item.message_id);
  };

  const save = async () => {
    setSaving(true);
    try {
      const response = await api.patch(`/tickets/${ticketId}`, {
        vocal_summary: vocalSummary,
        follow_up_status: followUpStatus,
        person_triggers: personTriggers,
      });
      setTicket(response.data);
      onTicketUpdate?.(response.data);
      toast.success("Dossier enregistré.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const addNote = async (event) => {
    event.preventDefault();
    if (!noteTitle.trim() || !noteContent.trim()) return;
    setAddingNote(true);
    try {
      const response = await api.post(`/tickets/${ticketId}/notes`, { title: noteTitle, content: noteContent });
      setTicket((current) => ({ ...current, notes_entries: [...(current.notes_entries || []), response.data] }));
      setNoteTitle("");
      setNoteContent("");
      setNoteComposerOpen(false);
      toast.success("Note ajoutée.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setAddingNote(false);
    }
  };

  const deleteNote = async (noteId) => {
    try {
      await api.delete(`/tickets/${ticketId}/notes/${noteId}`);
      setTicket((current) => ({ ...current, notes_entries: current.notes_entries.filter((note) => note.id !== noteId) }));
      toast.success("Note supprimée.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  const deleteTicket = async () => {
    if (!window.confirm("Supprimer définitivement ce dossier et sa transcription ? Cette action est irréversible.")) return;
    try {
      await api.delete(`/admin/tickets/${ticketId}`);
      onTicketDeleted?.(ticketId);
      toast.success("Dossier supprimé.");
      navigate("/");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const response = await api.post(`/tickets/${ticketId}/sync`);
      setTicket(response.data);
      onTicketUpdate?.(response.data);
      setMessagesVersion((version) => version + 1);
      toast.success("Transcription actualisée.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSyncing(false);
    }
  };

  const archive = async () => {
    try {
      const response = await api.patch(`/tickets/${ticketId}`, { status: ticket.status === "active" ? "archived" : "active" });
      setTicket(response.data);
      onTicketUpdate?.(response.data);
      toast.success(response.data.status === "archived" ? "Ticket archivé." : "Ticket réactivé.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  const assignHelper = async (helperId) => {
    try {
      const response = await api.patch(`/admin/tickets/${ticketId}/assignment`, { helper_id: helperId || null });
      setTicket(response.data);
      onTicketUpdate?.(response.data);
      toast.success("Helper principal mis à jour.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  const generateSummary = async () => {
    setGeneratingSummary(true);
    setSummaryProgress("Préparation de la synthèse…");
    try {
      const response = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/tickets/${ticketId}/ai-summary/stream`, { method: "POST", credentials: "include" });
      if (!response.ok || !response.body) throw new Error("La génération du résumé est indisponible.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        events.forEach((eventBlock) => {
          const eventType = eventBlock.match(/^event: (.+)$/m)?.[1];
          const data = eventBlock.match(/^data: (.+)$/m)?.[1];
          if (!data) return;
          const payload = JSON.parse(data);
          if (eventType === "progress") setSummaryProgress(payload.message);
          if (eventType === "complete") {
            completed = true;
            setTicket((current) => ({ ...current, ai_summary: payload, summary_status: "ready", summary_error: null }));
            setSummaryProgress("");
            toast.success("Résumé Claude enregistré.");
          }
          if (eventType === "error") {
            setTicket((current) => ({ ...current, summary_status: "error", summary_error: payload.message }));
            throw new Error(payload.message);
          }
        });
      }
      if (!completed) throw new Error("La connexion a été interrompue avant la confirmation du résumé. Actualise le dossier pour vérifier son enregistrement.");
    } catch (requestError) {
      toast.error(requestError.message || "La génération Claude a échoué.");
    } finally {
      setGeneratingSummary(false);
      setSummaryProgress("");
    }
  };

  if (loading) return <div className="tw-desk tw-loading" data-testid="ticket-loading"><LoaderCircle className="spin" size={26} /> Chargement du dossier…</div>;
  if (error || !ticket) return <div className="tw-desk tw-loading tw-error" data-testid="ticket-load-error">{error || "Ticket introuvable."}</div>;


  // Le message d’ouverture du bot reste dans le dossier pour l’import et l’IA,
  // mais son contenu V2 n’est pas présenté dans la conversation.
  const visibleMessages = page === 1 && messages[0]?.author?.is_bot ? messages.slice(1) : messages;
  const pageCount = Math.max(1, Math.ceil(ticket.message_count / pageSize));
  const dirty = vocalSummary !== (ticket.vocal_summary || "") || personTriggers !== (ticket.person_triggers || "") || followUpStatus !== (ticket.follow_up_status || "en attente de réponse");
  const noteCount = (ticket.notes_entries || []).length + (ticket.notes ? 1 : 0);
  const pageRange = ticket.message_count ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, ticket.message_count)}` : "0";

  return (
    <section className="tw-desk" data-testid="ticket-workspace-page" data-mobile-view={mobileView}>
      <header className="tw-topbar">
        <div className="tw-identity" data-testid="ticket-member-header">
          <p>ACCOMPAGNEMENT · DOSSIER {ticket.status === "active" ? "OUVERT" : "ARCHIVÉ"}</p>
          <h1>{ticket.member.display_name || ticket.member.username}</h1>
          <p className="tw-intro">Historique des échanges et suivi de l’accompagnement.</p>
        </div>
        <div className="tw-top-actions">
          <Link to="/" className="tw-button tw-home" data-testid="ticket-back-link">Accueil <ArrowRight size={17} /></Link>
          <button className="tw-button" disabled={syncing} onClick={sync} type="button" data-testid="sync-ticket-button">{syncing ? <LoaderCircle className="tw-spin" size={15} /> : <RefreshCw size={15} />} Actualiser</button>
          <button className="tw-button" onClick={archive} type="button" data-testid="archive-ticket-button"><Archive size={15} /> {ticket.status === "active" ? "Archiver" : "Réactiver"}</button>
          <button className="tw-button tw-button-primary" disabled={saving || !dirty} onClick={save} type="button" data-testid="save-ticket-button">{saving ? <LoaderCircle className="tw-spin" size={15} /> : <Save size={15} />} {saving ? "Enregistrement…" : "Enregistrer"}</button>
          {isAdmin && <details className="tw-menu"><summary aria-label="Actions du dossier"><MoreHorizontal size={20} /></summary><div className="tw-menu-content"><button className="tw-danger" onClick={deleteTicket} type="button" data-testid="delete-ticket-button"><Trash2 size={15} /> Supprimer le dossier</button></div></details>}
        </div>
      </header>

      <div className="tw-contextbar" data-testid="ticket-metadata">
        <label className="tw-context-control" htmlFor="follow-up-status">
          <span className="tw-context-label">Suivi</span>
          <span className="tw-select-wrap"><ListFilter size={17} aria-hidden="true" /><select id="follow-up-status" value={followUpStatus} onChange={(event) => setFollowUpStatus(event.target.value)} data-testid="follow-up-status-select"><option value="en attente de réponse">En attente de réponse</option><option value="en cours">En cours</option><option value="à conclure">À conclure</option></select><ChevronsUpDown className="tw-select-chevron" size={16} aria-hidden="true" /></span>
        </label>
        <div className="tw-context-control" data-testid="helper-assignment-panel">
          <label className="tw-context-label" htmlFor={isAdmin ? "tw-helper-assignment" : undefined}>Interlocuteur</label>
          {isAdmin ? <span className="tw-select-wrap"><UserRoundCheck size={17} aria-hidden="true" /><select id="tw-helper-assignment" disabled={ticket.status === "archived"} aria-label="Helper principal" value={ticket.assigned_helper?.id || ""} onChange={(event) => assignHelper(event.target.value)} data-testid="helper-assignment-select"><option value="">Non attribué</option>{helpers.map((person) => <option value={person.id} key={person.id}>{person.display_name || person.username}</option>)}</select><ChevronsUpDown className="tw-select-chevron" size={16} aria-hidden="true" /></span> : <strong className="tw-context-person" data-testid="assigned-helper-readonly"><UserRoundCheck size={17} aria-hidden="true" />{ticket.assigned_helper?.display_name || ticket.assigned_helper?.username || "Non attribué"}</strong>}
        </div>
        <span className="tw-context-date"><CalendarDays size={16} aria-hidden="true" /> Ouvert le {ticket.created_at ? new Date(ticket.created_at).toLocaleDateString("fr-FR") : "—"}</span>
        <span className="tw-private"><span className="tw-save-state" role="status">{dirty ? "Modifications non enregistrées" : <><Check size={13} /> À jour</>}</span><ShieldCheck size={13} /> Dossier privé</span>
      </div>

      <div className="tw-mobile-nav" aria-label="Vue du dossier"><button type="button" aria-pressed={mobileView === "messages"} onClick={() => { setMobileView("messages"); ticketEvent("workspace.mobile_view_changed", ticketId, "messages"); }}>Conversation <span>{ticket.message_count}</span></button><button type="button" aria-pressed={mobileView === "dossier"} onClick={() => { setMobileView("dossier"); ticketEvent("workspace.mobile_view_changed", ticketId, "dossier"); }}>Dossier et suivi</button></div>

      <div className="tw-layout">
        <section className="tw-conversation" data-testid="transcript-panel" aria-label="Conversation">
          <header className="tw-panel-heading"><span className="tw-panel-icon"><HeartHandshake size={22} /></span><div><h2>Conversation <span>{ticket.message_count}</span></h2><p>{ticket.last_synced_at ? `Synchronisé le ${formatTime(ticket.last_synced_at)}` : "Historique des échanges"}</p></div><button type="button" className="tw-button" aria-expanded={searchOpen} onClick={() => { setSearchOpen((open) => !open); ticketEvent(searchOpen ? "search.closed" : "search.opened", ticketId); }}><Search size={15} /> Rechercher</button></header>
          <div className={`tw-sync-status ${ticket.sync_status === "error" ? "is-error" : ""}`} role="status">
            <RefreshCw size={13} className={syncing || ticket.sync_status === "syncing" ? "tw-spin" : ""} />
            <span>{syncing || ticket.sync_status === "syncing" ? "Synchronisation des messages en cours…" : ticket.sync_status === "error" ? ticket.sync_error || "Synchronisation en échec" : ticket.last_synced_at ? "Messages synchronisés" : "Aucune synchronisation effectuée"}</span>
          </div>
          {searchOpen && <form className="tw-search-form" onSubmit={searchMessages}>
            <label><span>Dans toute la conversation</span><input type="search" value={searchTerm} maxLength={120} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Mot ou expression…" aria-label="Rechercher dans toute la conversation" /></label>
            <div><label>Du<input type="date" value={searchFrom} onChange={(event) => setSearchFrom(event.target.value)} /></label><label>Au<input type="date" value={searchTo} onChange={(event) => setSearchTo(event.target.value)} /></label><button type="submit" className="tw-button tw-button-primary" disabled={searchLoading || (!searchTerm.trim() && !searchFrom && !searchTo)}>{searchLoading ? "Recherche…" : "Rechercher"}</button></div>
          </form>}

          <div className="tw-messages" ref={transcriptRef} aria-busy={messagesLoading}>
            {searchOpen && <div className="tw-search-results">{searchError && <p role="alert">{searchError}</p>}{searchResults && <><p className="tw-caption">{searchResults.total} résultat(s) dans tout le dossier</p>{searchResults.items.map((item) => <button type="button" className="tw-search-result" key={item.message_id} onClick={() => openSearchResult(item)}><strong>{item.author_name}</strong><time>{formatTime(item.timestamp)}</time><p>{item.excerpt}</p><span>Ouvrir à la page {item.message_page} →</span></button>)}<div className="tw-search-pages"><button className="tw-button" type="button" disabled={searchLoading || searchResults.page <= 1} onClick={() => searchMessages(null, searchResults.page - 1)}>Résultats précédents</button><button className="tw-button" type="button" disabled={searchLoading || searchResults.page * 20 >= searchResults.total} onClick={() => searchMessages(null, searchResults.page + 1)}>Résultats suivants</button></div></>}</div>}
            {!searchOpen && !messagesLoading && !messagesError && visibleMessages.length === 0 && <div className="tw-empty" data-testid="empty-transcript"><HeartHandshake size={26} /><h3>La conversation commence ici</h3><p>Les échanges de l’accompagnement apparaîtront ici.</p></div>}
            {!searchOpen && messagesLoading && <div className="tw-empty" role="status"><LoaderCircle className="tw-spin" size={24} /><p>Chargement des messages…</p></div>}
            {!searchOpen && messagesError && <div className="tw-empty tw-error" role="alert"><p>{messagesError}</p><button className="tw-button" type="button" onClick={() => setMessagesVersion((value) => value + 1)}>Réessayer</button></div>}
            {!searchOpen && !messagesLoading && !messagesError && visibleMessages.map((message, index) => {
              const day = new Date(message.timestamp).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
              const previousDay = index ? new Date(visibleMessages[index - 1].timestamp).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : null;
              const body = <><p className="tw-message-text">{message.content}</p>{(message.attachments || []).map((attachment) => <a className="tw-attachment" href={attachment.url} key={attachment.id} target="_blank" rel="noreferrer" onClick={() => ticketEvent("attachment.opened", ticketId, attachment.id)} data-testid={`attachment-${attachment.id}`}><FileText size={14} />{attachment.filename}</a>)}</>;
              return <div key={message.id}>
                {day !== previousDay && <div className="tw-day"><span>{day}</span></div>}
                <article id={`tw-message-${message.id}`} className={`tw-message${highlightedMessage === message.id ? " is-search-hit" : ""}${message.author.is_bot ? " is-bot" : ""}${message.author.id === ticket.member.id ? " is-member" : ""}`} data-testid={`transcript-message-${message.id}`}>
                  <MessageAvatar author={message.author} />
                  <div className="tw-message-body"><header><strong>{message.author.display_name || message.author.username}</strong>{message.author.is_bot && <span className="tw-bot-tag">BOT</span>}<time dateTime={message.timestamp}>{new Date(message.timestamp).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</time></header>
                  {message.author.is_bot && message.content.length > 400 ? <details className="tw-system-message" open={highlightedMessage === message.id || undefined}><summary>Message automatique · {message.content.slice(0, 85).replace(/\s+/g, " ")}…</summary>{body}</details> : body}
                  </div>
                </article>
              </div>;
            })}
          </div>
          {!searchOpen && <nav className="tw-pagination" aria-label="Pagination des messages"><span className="tw-range">{pageRange} sur {ticket.message_count}</span><div><button type="button" disabled={page === 1 || messagesLoading} onClick={() => changePage(page - 1)} aria-label="Page précédente" title="Page précédente"><ChevronLeft size={16} /></button><label className="tw-page-select"><span className="tw-sr-only">Page de messages</span><select aria-label="Page de messages" value={page} disabled={messagesLoading} onChange={(event) => changePage(Number(event.target.value))}>{Array.from({ length: pageCount }, (_, i) => <option value={i + 1} key={i + 1}>Page {i + 1} sur {pageCount}</option>)}</select></label><button type="button" disabled={page >= pageCount || messagesLoading} onClick={() => changePage(page + 1)} aria-label="Page suivante" title="Page suivante"><ChevronRight size={16} /></button></div><button className="tw-latest" type="button" disabled={page === pageCount || messagesLoading} onClick={() => changePage(pageCount)}>Plus récents <ChevronRight size={14} /></button></nav>}
        </section>

        <aside className="tw-dossier" data-testid="vocal-panel" aria-label="Dossier et suivi">
          <Tabs.Root defaultValue="resume" className="tw-dossier-tabs" key={ticketId} onValueChange={(value) => ticketEvent("workspace.tab_changed", ticketId, value)}>
            <Tabs.List className="tw-tabs" aria-label="Contenu du dossier"><Tabs.Trigger className="tw-tab" value="resume"><Bot size={15} /> Résumé</Tabs.Trigger><Tabs.Trigger className="tw-tab" value="notes"><FileText size={15} /> Notes <span>{noteCount}</span></Tabs.Trigger><Tabs.Trigger className="tw-tab" value="reperes"><HeartHandshake size={15} /> Repères</Tabs.Trigger></Tabs.List>
            <div className="tw-dossier-content">
              <Tabs.Content value="resume" className="tw-tab-content">
                <section className="tw-summary" data-testid="ai-summary-panel"><header className="tw-section-title tw-section-title--violet"><span className="tw-panel-icon"><Bot size={22} /></span><h2>Synthèse du dossier</h2><span className="tw-claude">Claude</span></header>
                {ticket.summary_status === "generating" && <p className="tw-summary-state" role="status"><LoaderCircle size={14} className="tw-spin" /> Actualisation de la synthèse en cours…</p>}
                {ticket.summary_status === "error" && <p className="tw-summary-state is-error" role="alert">{ticket.summary_error || "La synthèse quotidienne a échoué."}</p>}
                {ticket.ai_summary ? <><p className="tw-caption">Générée le {formatTime(ticket.ai_summary.generated_at)}</p><div className="tw-summary-content" data-testid="ai-summary-content">{[["Contexte", "context"], ["Besoins exprimés", "expressed_needs"], ["Actions engagées", "actions"], ["Prochain suivi", "next_follow_up"]].map(([title, key]) => <section key={key}><h3>{title}</h3><p>{ticket.ai_summary[key]}</p></section>)}</div></> : <div className="tw-summary-empty" data-testid="ai-summary-empty"><span><Bot size={24} /></span><h3>L’essentiel, au même endroit</h3><p>Retrouvez le contexte, les besoins et les prochaines étapes sans relire toute la conversation.</p></div>}
                <button className="tw-button tw-generate" type="button" onClick={generateSummary} disabled={generatingSummary || ticket.summary_status === "generating"} data-testid="generate-ai-summary-button">{generatingSummary ? <LoaderCircle size={15} className="tw-spin" /> : <Bot size={15} />}{generatingSummary ? summaryProgress || "Génération…" : ticket.ai_summary ? "Actualiser la synthèse" : "Générer la synthèse"}</button><p className="tw-ai-foot" data-testid="ai-privacy-notice">À relire par l’aidant · Aucun diagnostic</p></section>
                {personTriggers && <section className="tw-trigger-reminder"><h3><HeartHandshake size={14} /> Points de vigilance</h3><p>{personTriggers}</p></section>}
              </Tabs.Content>

              <Tabs.Content value="notes" className="tw-tab-content"><section data-testid="notes-panel"><header className="tw-section-title tw-section-title--sage"><span className="tw-panel-icon"><FileText size={22} /></span><h2>Notes privées</h2><button className="tw-button tw-button-small" type="button" onClick={() => { setNoteComposerOpen(true); ticketEvent("note.composer_opened", ticketId); }}><FilePlus2 size={14} /> Ajouter</button></header>
              {noteComposerOpen && <form className="tw-note-form" onSubmit={addNote} data-testid="new-ticket-note-form"><label htmlFor="tw-note-title">Titre<input id="tw-note-title" autoFocus value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="Objet de la note" maxLength={120} required data-testid="ticket-note-title-input" /></label><label htmlFor="tw-note-content">Note<textarea id="tw-note-content" rows={5} value={noteContent} onChange={(event) => setNoteContent(event.target.value)} placeholder="Les informations utiles au suivi…" required data-testid="ticket-note-content-input" /></label><div><button className="tw-button" type="button" onClick={() => { setNoteComposerOpen(false); ticketEvent("note.composer_closed", ticketId); }}><X size={14} /> Fermer</button><button className="tw-button tw-button-primary" type="submit" disabled={addingNote || !noteTitle.trim() || !noteContent.trim()} data-testid="add-ticket-note-button">{addingNote ? "Ajout…" : "Ajouter la note"}</button></div></form>}
              <div className="tw-notes" data-testid="ticket-notes-list">{ticket.notes && <article className="tw-note" data-testid="legacy-ticket-note"><h3>Note générale</h3><p>{ticket.notes}</p></article>}{[...(ticket.notes_entries || [])].reverse().map((note) => <article className="tw-note" key={note.id} data-testid={`ticket-note-${note.id}`}><header><h3>{note.title}</h3>{(isAdmin || note.author.id === helper?.id) && <button className="tw-icon-button tw-danger" type="button" onClick={() => deleteNote(note.id)} data-testid={`delete-note-${note.id}`} aria-label="Supprimer la note"><Trash2 size={14} /></button>}</header><p className="tw-note-byline">{note.author.display_name || note.author.username} · {formatTime(note.updated_at)}</p><p>{note.content}</p></article>)}</div>
              {!noteCount && !noteComposerOpen && <div className="tw-empty-notes"><FileText size={24} /><h3>Gardez une trace utile</h3><p>Ajoutez une observation ou une décision pour le prochain échange.</p><button className="tw-button" onClick={() => { setNoteComposerOpen(true); ticketEvent("note.composer_opened", ticketId); }} type="button"><FilePlus2 size={14} /> Première note</button></div>}</section></Tabs.Content>

              <Tabs.Content value="reperes" className="tw-tab-content"><section className="tw-fields" data-testid="person-triggers-panel"><header className="tw-section-title tw-section-title--clay"><span className="tw-panel-icon"><HeartHandshake size={22} /></span><h2>Repères de l’accompagnement</h2></header><label htmlFor="tw-person-triggers">Points de vigilance<span>Sujets, situations ou formulations sensibles.</span><textarea id="tw-person-triggers" rows={4} value={personTriggers} onChange={(event) => setPersonTriggers(event.target.value)} placeholder="Ce qui aide à adapter l’écoute…" data-testid="person-triggers-input" /></label><label htmlFor="tw-vocal-summary">Compte-rendu d’échange<span>Les éléments à garder pour la suite.</span><textarea id="tw-vocal-summary" rows={6} value={vocalSummary} onChange={(event) => setVocalSummary(event.target.value)} placeholder="Repères et synthèse de l’échange…" data-testid="ticket-vocal-input" /></label><p className="tw-caption">Utilisez « Enregistrer » pour conserver vos modifications.</p></section></Tabs.Content>
            </div>
            <footer className="tw-dossier-footer"><ShieldCheck size={13} /><span>{ticket.status === "active" ? "Messages et résumé actualisés chaque jour" : "Dossier archivé · Actualisation manuelle"}</span></footer>
          </Tabs.Root>
        </aside>
      </div>
    </section>
  );
}
