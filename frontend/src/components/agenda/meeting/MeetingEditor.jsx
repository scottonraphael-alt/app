import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Ban,
  CalendarDays,
  CircleAlert,
  Clock,
  FileText,
  Gavel,
  History,
  ListChecks,
  ListTodo,
  Lock,
  LockOpen,
  MapPin,
  PenLine,
  Users,
} from "lucide-react";

import "../../../Agenda.css";
import "./meeting.css";

import AgendaHomeLink from "../AgendaHomeLink";
import { PhaseBadge, Pill } from "../TypeBadge";
import { peopleSummary } from "../HelperAvatar";
import ReminderSchedule from "../ReminderSchedule";
import MeetingDialog from "../meetings/MeetingDialog";
import TiptapSummaryEditor, { contentToPlainText, countWords, readingMinutes } from "../../TiptapSummaryEditor";
import SummaryReader from "../../SummaryReader";
import useAgendaNoNav from "../useAgendaNoNav";
import {
  agendaQueries,
  applyActionToggleResult,
  clearMeetingDraft,
  commitMeetingDetail,
  deleteMeeting,
  fetchMeeting,
  invalidateAgenda,
  invalidateAgendaLists,
  readMeetingDraft,
  setMeetingDetail,
  setMeetingLock,
  toggleMeetingAction,
  updateMeeting,
  writeMeetingDraft,
} from "../agendaApi";
import { isValidAgendaId } from "../agendaConstants";
import { agendaErrorMessage, isNotFound } from "../agendaErrors";
import { helperName } from "../calendarModel";
import {
  capitalize,
  formatDayLong,
  formatInstant,
  formatInstantRelative,
  formatTimeRange,
  resolveToday,
} from "../dateUtils";
import ActionItemsEditor from "./ActionItemsEditor";
import AgendaItemsEditor from "./AgendaItemsEditor";
import ConflictBanner from "./ConflictBanner";
import DecisionsEditor from "./DecisionsEditor";
import FocusBar from "./FocusBar";
import { CancelMeetingDialog, DeleteMeetingDialog } from "./MeetingConfirmDialogs";
import MeetingMenu from "./MeetingMenu";
import ParticipantsPanel from "./ParticipantsPanel";
import SaveStatus from "./SaveStatus";
import { docFromDetail, participantsWithAttendance } from "./meetingModel";
import useMeetingAutosave from "./useMeetingAutosave";

const UNSAVED_MESSAGE = "Enregistrez d'abord vos modifications : l'état de l'enregistrement est indiqué dans le compte-rendu.";
const SUMMARY_PLACEHOLDER = "Rédigez le compte-rendu… Tapez « / » pour un titre, une liste, un tableau ou une image.";

// Erreur à afficher telle quelle par les fenêtres (même forme qu'une réponse du serveur).
function blockedError(detail) {
  return { response: { status: 0, data: { detail } } };
}

function statsOf(content) {
  const words = countWords(contentToPlainText(content));
  return { words, characters: 0 };
}

function StateShell({ children }) {
  return (
    <main className="ag-page ag-meeting">
      <header className="ag-header">
        <div>
          <p className="ag-eyebrow">Réunion staff</p>
        </div>
        <div className="ag-header-actions">
          <AgendaHomeLink />
        </div>
      </header>
      {children}
    </main>
  );
}

// Chargement du détail (une fois), puis l'état local de l'éditeur devient la source de vérité.
export default function MeetingEditor({ meetingId, isResponsable = false }) {
  useAgendaNoNav();
  const query = useQuery(agendaQueries.meetingEditor(meetingId));
  const [seed, setSeed] = useState(null);

  useEffect(() => {
    if (!seed && query.data && !query.isFetching) setSeed(query.data);
  }, [seed, query.data, query.isFetching]);

  if (!isValidAgendaId(String(meetingId || "")) || (!seed && isNotFound(query.error))) {
    return (
      <StateShell>
        <div className="ag-empty">
          <span className="ag-empty-icon">
            <CalendarDays size={28} aria-hidden="true" />
          </span>
          <h3>Réunion introuvable.</h3>
          <p>Elle a peut-être été supprimée, ou le lien est incorrect.</p>
          <Link to="/staff/meetings" className="ag-button">
            Voir toutes les réunions
          </Link>
        </div>
      </StateShell>
    );
  }

  if (!seed) {
    if (query.isError && !query.data) {
      return (
        <StateShell>
          <div className="ag-error" role="alert">
            <span className="ag-error-text">
              <CircleAlert size={15} aria-hidden="true" />
              {agendaErrorMessage(query.error, "Impossible de charger la réunion.")}
            </span>
            <button type="button" className="ag-error-retry" onClick={() => query.refetch()}>
              Réessayer
            </button>
          </div>
        </StateShell>
      );
    }
    return (
      <StateShell>
        <div className="ag-skeleton-stack" aria-busy="true" aria-label="Chargement de la réunion">
          <span className="ag-skeleton ag-skeleton-line" style={{ width: "46%", height: 38 }} />
          <span className="ag-skeleton" style={{ height: 160 }} />
          <span className="ag-skeleton" style={{ height: 320 }} />
        </div>
      </StateShell>
    );
  }

  return <MeetingWorkspace meetingId={meetingId} seed={seed} isResponsable={isResponsable} />;
}

function MeetingWorkspace({ meetingId, seed, isResponsable }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const focus = searchParams.get("focus") === "1";
  const live = useQuery(agendaQueries.meetingEditor(meetingId));
  const detail = live.data || seed;
  const today = resolveToday();

  // État local : source de vérité tant que la page est montée (docRef donne la valeur courante à la file d'envoi).
  const docRef = useRef(null);
  if (!docRef.current) docRef.current = docFromDetail(seed);
  const [doc, setDocState] = useState(docRef.current);
  const updateDoc = useCallback((mutate) => {
    const next = mutate(docRef.current);
    if (next === docRef.current) return;
    docRef.current = next;
    setDocState(next);
  }, []);

  const [resetKey, setResetKey] = useState(0);
  const [stats, setStats] = useState(() => statsOf(docRef.current.content));
  const [draft, setDraft] = useState(() => {
    const stored = readMeetingDraft(meetingId);
    return stored && stored.content && stored.content !== docRef.current.content ? stored : null;
  });
  const [forcedLocked, setForcedLocked] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [conflictBusy, setConflictBusy] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busyActions, setBusyActions] = useState(() => new Set());
  const [agendaOpen, setAgendaOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1100);
  const editorRef = useRef(null);
  const lastTitleRef = useRef(docRef.current.title);

  const viewerIsResponsable = detail.viewer?.is_responsable ?? Boolean(isResponsable);
  const locked = Boolean(detail.is_locked) || forcedLocked;
  const cancelled = Boolean(detail.cancelled);
  const canEdit = detail.can_edit !== false && !locked;

  const handleLocked = useCallback(async () => {
    toast.error("Ce compte-rendu vient d'être verrouillé. Vos dernières modifications n'ont pas été enregistrées.");
    setForcedLocked(true);
    try {
      const fresh = await fetchMeeting(meetingId);
      setMeetingDetail(queryClient, fresh);
      invalidateAgendaLists(queryClient);
    } catch (error) {
      // Le verrou reste affiché localement ; la prochaine lecture le confirmera.
    }
  }, [meetingId, queryClient]);

  const autosave = useMeetingAutosave({
    meetingId,
    initialRevision: seed.revision,
    getDoc: () => docRef.current,
    onLocked: handleLocked,
  });

  // ---- Modifications locales ----

  const setTitle = (value) => {
    updateDoc((old) => ({ ...old, title: value }));
    if (value.trim()) {
      lastTitleRef.current = value.trim();
      autosave.touch("title");
    }
  };
  const settleTitle = () => {
    if (!docRef.current.title.trim()) updateDoc((old) => ({ ...old, title: lastTitleRef.current }));
  };

  const onContentChange = useCallback(
    (json) => {
      updateDoc((old) => ({ ...old, content: json }));
      writeMeetingDraft(meetingId, { revision: autosave.getRevision(), content: json });
      autosave.touch("content_markdown");
    },
    [autosave, meetingId, updateDoc],
  );

  const setAgendaItems = (items) => {
    updateDoc((old) => ({ ...old, agenda_items: items }));
    autosave.touch("agenda_items");
  };
  const setDecisions = (items) => {
    updateDoc((old) => ({ ...old, decisions: items }));
    autosave.touch("decisions");
  };
  const setActions = (items) => {
    updateDoc((old) => ({ ...old, action_items: items }));
    autosave.touch("action_items");
  };
  const setAttendance = (personId, value) => {
    updateDoc((old) => ({ ...old, attendance: { ...old.attendance, [personId]: value } }));
    autosave.touchAttendance(personId, value);
  };

  const patchAction = useCallback(
    (actionId, patch) =>
      updateDoc((old) => ({
        ...old,
        action_items: old.action_items.map((item) => (item.id === actionId ? { ...item, ...patch } : item)),
      })),
    [updateDoc],
  );

  // Case « faite » : par la file d'enregistrement tant que la réunion est modifiable, sinon par l'endpoint dédié.
  const toggleAction = async (item, done) => {
    const doneAt = done ? new Date().toISOString() : null;
    if (!locked) {
      patchAction(item.id, { done, done_at: doneAt, done_by: null });
      autosave.touchDone(item.id, done);
      return;
    }
    if (busyActions.has(item.id)) return;
    setBusyActions((old) => new Set(old).add(item.id));
    patchAction(item.id, { done, done_at: doneAt });
    try {
      const result = await toggleMeetingAction(meetingId, item.id, done);
      applyActionToggleResult(queryClient, result);
      const saved = result?.item;
      if (saved) {
        patchAction(item.id, {
          done: Boolean(saved.done),
          done_at: saved.done_at || null,
          done_by: saved.done_by || null,
        });
      }
      invalidateAgendaLists(queryClient);
    } catch (error) {
      patchAction(item.id, { done: !done, done_at: item.done_at, done_by: item.done_by });
      toast.error(agendaErrorMessage(error));
    } finally {
      setBusyActions((old) => {
        const next = new Set(old);
        next.delete(item.id);
        return next;
      });
    }
  };

  // ---- Brouillon local, conflit, verrouillage ----

  const restoreDraft = () => {
    if (!draft) return;
    updateDoc((old) => ({ ...old, content: draft.content }));
    setResetKey((key) => key + 1);
    setStats(statsOf(draft.content));
    autosave.touch("content_markdown");
    setDraft(null);
  };
  const ignoreDraft = () => {
    clearMeetingDraft(meetingId);
    setDraft(null);
  };

  const reloadTheirs = async () => {
    setConflictBusy(true);
    try {
      const fresh = await autosave.reloadTheirs();
      const next = docFromDetail(fresh);
      lastTitleRef.current = next.title;
      docRef.current = next;
      setDocState(next);
      setResetKey((key) => key + 1);
      setStats(statsOf(next.content));
      setForcedLocked(false);
      invalidateAgendaLists(queryClient);
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    } finally {
      setConflictBusy(false);
    }
  };

  const keepMine = async () => {
    setConflictBusy(true);
    try {
      await autosave.keepMine();
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    } finally {
      setConflictBusy(false);
    }
  };

  const flushOrFail = async () => {
    const result = await autosave.flush();
    if (!result.ok) throw blockedError(UNSAVED_MESSAGE);
    return result.revision;
  };

  const toggleLock = async () => {
    if (lockBusy) return;
    setLockBusy(true);
    try {
      await flushOrFail();
      const next = await setMeetingLock(meetingId, !locked);
      autosave.setRevision(next.revision);
      setForcedLocked(false);
      commitMeetingDetail(queryClient, next);
      if (next.is_locked && focus) setFocus(false);
      toast.success(next.is_locked ? "Compte-rendu verrouillé." : "Compte-rendu déverrouillé.");
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    } finally {
      setLockBusy(false);
    }
  };

  const changeDetails = async (patch) => {
    const revision = await flushOrFail();
    const next = await updateMeeting(meetingId, { expected_revision: revision, ...patch });
    autosave.setRevision(next.revision);
    commitMeetingDetail(queryClient, next);
    return next;
  };

  const cancelMeeting = async (reason) => {
    await changeDetails({ cancelled: true, cancel_reason: reason });
    toast.success("Réunion annulée.");
  };
  const restoreMeeting = async () => {
    try {
      await changeDetails({ cancelled: false, cancel_reason: "" });
      toast.success("Réunion rétablie.");
    } catch (error) {
      toast.error(agendaErrorMessage(error));
    }
  };

  const removeMeeting = async () => {
    await deleteMeeting(meetingId);
    autosave.discard();
    clearMeetingDraft(meetingId);
    invalidateAgenda(queryClient, { exceptMeetingId: meetingId, includeDashboard: true });
    toast.success("Réunion supprimée.");
    navigate("/staff/meetings", { replace: true });
  };

  const onInfoSaved = (next) => {
    autosave.setRevision(next.revision);
    updateDoc((old) => {
      const attendance = {};
      for (const person of Array.isArray(next.participants) ? next.participants : []) {
        const id = String(person.id);
        attendance[id] = old.attendance[id] || person.attendance || "invite";
      }
      return { ...old, title: next.title || old.title, attendance };
    });
    lastTitleRef.current = next.title || lastTitleRef.current;
  };

  const copyMarkdown = async () => {
    const editor = editorRef.current;
    try {
      const markdown = editor ? (await editor.blocksToMarkdownLossy(editor.document)).trim() : "";
      if (!markdown) {
        toast.info("Le compte-rendu est vide : rien à copier.");
        return;
      }
      await navigator.clipboard.writeText(markdown);
      toast.success("Compte-rendu copié en Markdown.");
    } catch (error) {
      toast.error("Impossible de copier le compte-rendu.");
    }
  };

  // ---- Mode concentration ----

  const setFocus = useCallback(
    (on) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (on) next.set("focus", "1");
          else next.delete("focus");
          return next;
        },
        { replace: false },
      );
    },
    [setSearchParams],
  );

  useEffect(() => {
    if (!focus) return undefined;
    window.scrollTo({ top: 0 });
    const timer = window.setTimeout(() => {
      try {
        if (canEdit) editorRef.current?.focus?.();
      } catch (error) {
        // L'éditeur n'est pas encore prêt : le focus se fera au clic.
      }
    }, 80);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        autosave.flush();
        return;
      }
      if (event.key === "Escape" && focus && !event.defaultPrevented) {
        if (document.querySelector('[role="dialog"], [role="listbox"], .bn-suggestion-menu, .bn-toolbar')) return;
        setFocus(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [autosave, focus, setFocus]);

  // ---- Affichage ----

  const participants = useMemo(() => participantsWithAttendance(detail, doc.attendance), [detail, doc.attendance]);
  const absentPeople = useMemo(() => {
    const ids = new Set(detail.participants_absent || []);
    return participants.filter((person) => ids.has(person.id));
  }, [detail.participants_absent, participants]);

  const words = stats.words;
  const minutes = readingMinutes(words);
  const saveProps = {
    status: autosave.status,
    online: autosave.online,
    savedAt: autosave.savedAt,
    message: autosave.message,
    retryIn: autosave.retryIn,
    hasUnsaved: autosave.hasUnsaved(),
    onRetry: autosave.retryNow,
  };

  const title = doc.title;
  const lockedBy = detail.locked_by ? helperName(detail.locked_by) : "un responsable";
  const lockedAt = detail.locked_at ? formatInstant(detail.locked_at, { withTime: false }) : "";
  const hasAgendaPanel = doc.agenda_items.length > 0 || canEdit;
  const classes = ["ag-page", "ag-meeting", focus ? "is-focus" : "", focus && agendaOpen ? "has-agenda" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <main className={classes}>
      {focus ? (
        <FocusBar
          title={title}
          words={words}
          saveProps={saveProps}
          agendaOpen={agendaOpen}
          hasAgenda={hasAgendaPanel}
          onToggleAgenda={() => setAgendaOpen((open) => !open)}
          onExit={() => setFocus(false)}
        />
      ) : null}

      <header className="ag-header ag-meeting-normal">
        <div>
          <p className="ag-eyebrow">Réunion staff</p>
          <div className="ag-header-meta ag-meeting-badges">
            <PhaseBadge phase={detail.phase} />
            {locked ? (
              <Pill icon={Lock} tone="neutral">
                Verrouillée
              </Pill>
            ) : null}
          </div>
          <h1 className="ag-meeting-title">
            {canEdit ? (
              <input
                type="text"
                className="ag-meeting-title-input"
                value={title}
                maxLength={160}
                aria-label="Titre de la réunion"
                onChange={(event) => setTitle(event.target.value)}
                onBlur={settleTitle}
              />
            ) : (
              title
            )}
          </h1>
          <div className="ag-header-meta">
            <Pill icon={CalendarDays} tone="white">
              {capitalize(formatDayLong(detail.meeting_date))}
            </Pill>
            <Pill icon={Clock} tone="white">
              {detail.start_time ? formatTimeRange(detail.start_time, detail.end_time) : "Horaire non précisé"}
            </Pill>
            {detail.location ? (
              <Pill icon={MapPin} tone="white">
                {detail.location}
              </Pill>
            ) : null}
            <Pill icon={Users} tone="white">
              {participants.length} participant{participants.length > 1 ? "s" : ""}
            </Pill>
          </div>
        </div>
        <div className="ag-header-actions">
          <AgendaHomeLink />
          {canEdit ? (
            <button type="button" className="ag-button" onClick={() => setFocus(true)}>
              <PenLine size={16} aria-hidden="true" />
              Rédiger
            </button>
          ) : null}
          {viewerIsResponsable ? (
            <button
              type="button"
              className="ag-button ag-button--secondary"
              onClick={toggleLock}
              disabled={lockBusy}
            >
              {locked ? <LockOpen size={16} aria-hidden="true" /> : <Lock size={16} aria-hidden="true" />}
              {locked ? "Déverrouiller" : "Verrouiller"}
            </button>
          ) : null}
          <MeetingMenu
            meetingId={meetingId}
            meetingDate={detail.meeting_date}
            isResponsable={viewerIsResponsable}
            locked={locked}
            cancelled={cancelled}
            onEdit={() => setInfoOpen(true)}
            onCopyMarkdown={copyMarkdown}
            onCancel={() => setCancelOpen(true)}
            onRestore={restoreMeeting}
            onDelete={() => setDeleteOpen(true)}
          />
        </div>
      </header>

      <div className="ag-meeting-banners">
        {autosave.status === "conflict" ? (
          <ConflictBanner conflict={autosave.conflict} busy={conflictBusy} onReload={reloadTheirs} onKeep={keepMine} />
        ) : null}
        {autosave.status === "locked" ? (
          <div className="ag-callout ag-callout--warning ag-meeting-banner" role="alert">
            <Lock size={17} aria-hidden="true" />
            <p>
              Ce compte-rendu vient d'être verrouillé : vos dernières modifications n'ont pas été enregistrées. Elles
              restent dans un brouillon de ce navigateur.
            </p>
          </div>
        ) : null}
        {draft ? (
          <div className="ag-callout ag-callout--info ag-meeting-banner" role="status">
            <History size={17} aria-hidden="true" />
            <div className="ag-meeting-banner-body">
              <p>
                Un brouillon non enregistré du {formatInstant(draft.saved_at, { withYear: false })} a été retrouvé.
              </p>
            </div>
            <div className="ag-meeting-banner-actions">
              <button type="button" className="ag-button ag-button--small" onClick={restoreDraft}>
                Restaurer
              </button>
              <button type="button" className="ag-button ag-button--secondary ag-button--small" onClick={ignoreDraft}>
                Ignorer
              </button>
            </div>
          </div>
        ) : null}
        {locked ? (
          <div className="ag-callout ag-callout--info ag-meeting-banner ag-meeting-secondary-banner">
            <Lock size={17} aria-hidden="true" />
            <p>
              Ce compte-rendu est verrouillé par {lockedBy}
              {lockedAt ? ` le ${lockedAt}` : ""}. Les actions à suivre restent cochables.
            </p>
          </div>
        ) : null}
        {cancelled ? (
          <div className="ag-callout ag-callout--danger ag-meeting-banner ag-meeting-secondary-banner">
            <Ban size={17} aria-hidden="true" />
            <p>Réunion annulée{detail.cancel_reason ? ` : ${detail.cancel_reason}` : ""}.</p>
          </div>
        ) : null}
        {absentPeople.length && detail.phase === "a_venir" ? (
          <div className="ag-callout ag-callout--warning ag-meeting-banner ag-meeting-secondary-banner">
            <CalendarDays size={17} aria-hidden="true" />
            <p>
              {peopleSummary(absentPeople)} {absentPeople.length > 1 ? "sont absents" : "est absent(e)"} ce jour-là.
            </p>
          </div>
        ) : null}
      </div>

      <div className="ag-meeting-grid">
        <div className="ag-meeting-main">
          {hasAgendaPanel ? (
            <section className="ag-panel ag-meeting-agenda-panel" id="ordre-du-jour" aria-labelledby="ag-meeting-agenda-title">
              <div className="ag-panel-header">
                <span className="ag-panel-icon">
                  <ListChecks size={20} aria-hidden="true" />
                </span>
                <div className="ag-panel-heading">
                  <h2 id="ag-meeting-agenda-title">Ordre du jour</h2>
                </div>
              </div>
              <div className="ag-panel-body">
                <AgendaItemsEditor items={doc.agenda_items} onChange={setAgendaItems} readOnly={!canEdit} />
              </div>
            </section>
          ) : null}

          <section className="ag-panel ag-meeting-summary" aria-labelledby="ag-meeting-summary-title">
            <div className="ag-panel-header ag-meeting-summary-header">
              <span className="ag-panel-icon">
                <FileText size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <h2 id="ag-meeting-summary-title">Compte-rendu</h2>
              </div>
            </div>
            <div className="ag-meeting-summary-body">
              {canEdit ? (
                <TiptapSummaryEditor
                  value={doc.content}
                  onChange={onContentChange}
                  placeholder={SUMMARY_PLACEHOLDER}
                  variant={focus ? "focus" : "default"}
                  resetKey={resetKey}
                  onStats={setStats}
                  onEditorReady={(editor) => {
                    editorRef.current = editor;
                  }}
                  extraSlashItems
                />
              ) : (
                <SummaryReader
                  content={doc.content}
                  emptyLabel="Aucun compte-rendu rédigé pour l'instant."
                  onEditorReady={(editor) => {
                    editorRef.current = editor;
                  }}
                />
              )}
            </div>
            <div className="ag-panel-footer ag-meeting-summary-footer">
              {canEdit ? <SaveStatus {...saveProps} /> : <span>{locked ? "Verrouillé" : "Lecture seule"}</span>}
              <span className="ag-meeting-words">
                {words} mot{words > 1 ? "s" : ""} · ~{minutes} min de lecture
              </span>
            </div>
          </section>

          <section className="ag-panel ag-meeting-secondary" aria-labelledby="ag-meeting-decisions-title">
            <div className="ag-panel-header">
              <span className="ag-panel-icon">
                <Gavel size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <h2 id="ag-meeting-decisions-title">Décisions</h2>
              </div>
              <span className="ag-count">{doc.decisions.length}</span>
            </div>
            <div className="ag-panel-body">
              <DecisionsEditor items={doc.decisions} onChange={setDecisions} readOnly={!canEdit} />
            </div>
          </section>

          <section className="ag-panel ag-meeting-secondary" aria-labelledby="ag-meeting-actions-title">
            <div className="ag-panel-header ag-panel-header--actions">
              <span className="ag-panel-icon">
                <ListTodo size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <h2 id="ag-meeting-actions-title">Actions à suivre</h2>
              </div>
              <span className="ag-count">{doc.action_items.length}</span>
            </div>
            <div className="ag-panel-body">
              <ActionItemsEditor
                items={doc.action_items}
                onChange={setActions}
                onToggleDone={toggleAction}
                readOnly={!canEdit}
                today={today}
                busyIds={busyActions}
              />
            </div>
          </section>
        </div>

        <aside className="ag-side ag-meeting-side" aria-label="Informations de la réunion">
          <ParticipantsPanel
            participants={participants}
            absentIds={detail.participants_absent}
            readOnly={!canEdit}
            canManage={viewerIsResponsable && !locked}
            onChange={setAttendance}
            onManage={() => setInfoOpen(true)}
          />

          <section className="ag-panel ag-meeting-side-panel" aria-labelledby="ag-meeting-reminders-title">
            <div className="ag-panel-header">
              <span className="ag-panel-icon">
                <CalendarDays size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <h2 id="ag-meeting-reminders-title">Rappels Discord</h2>
              </div>
            </div>
            <div className="ag-panel-body">
              <ReminderSchedule reminders={detail.reminders} />
              {viewerIsResponsable && !locked ? (
                <button
                  type="button"
                  className="ag-button ag-button--secondary ag-button--small ag-meeting-side-button"
                  onClick={() => setInfoOpen(true)}
                >
                  Modifier
                </button>
              ) : null}
            </div>
          </section>

          <section className="ag-panel ag-meeting-side-panel" aria-labelledby="ag-meeting-history-title">
            <div className="ag-panel-header">
              <span className="ag-panel-icon">
                <History size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <h2 id="ag-meeting-history-title">Historique</h2>
              </div>
            </div>
            <div className="ag-panel-body">
              <ul className="ag-meeting-history">
                {detail.author || detail.created_at ? (
                  <li>
                    Créée{detail.author ? ` par ${helperName(detail.author)}` : ""}
                    {detail.created_at ? ` le ${formatInstant(detail.created_at, { withTime: false })}` : ""}
                  </li>
                ) : null}
                {detail.updated_at ? (
                  <li>
                    Modifiée{detail.updated_by ? ` par ${helperName(detail.updated_by)}` : ""}{" "}
                    {formatInstantRelative(detail.updated_at)}
                  </li>
                ) : null}
                <li>Révision {detail.revision ?? 0}</li>
              </ul>
            </div>
          </section>
        </aside>
      </div>

      {viewerIsResponsable ? (
        <MeetingDialog
          open={infoOpen}
          onOpenChange={setInfoOpen}
          meeting={detail}
          today={today}
          beforeSubmit={flushOrFail}
          onSaved={onInfoSaved}
        />
      ) : null}
      <CancelMeetingDialog open={cancelOpen} onOpenChange={setCancelOpen} onConfirm={cancelMeeting} />
      <DeleteMeetingDialog open={deleteOpen} onOpenChange={setDeleteOpen} title={title} onConfirm={removeMeeting} />
    </main>
  );
}

export { MeetingEditor, MeetingWorkspace };
