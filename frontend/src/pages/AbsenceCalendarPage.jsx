import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarDays, CircleAlert, ListChecks, Lock, Pencil, Printer, RefreshCw, Settings2, Trash2, UserMinus } from "lucide-react";
import { Link } from "react-router-dom";

import AgendaHomeLink from "../components/agenda/AgendaHomeLink";
import HelperAvatar from "../components/agenda/HelperAvatar";
import ReminderSettingsDialog from "../components/agenda/ReminderSettingsDialog";
import useAgendaNoNav from "../components/agenda/useAgendaNoNav";
import {
  agendaQueries,
  deleteAbsence,
  deleteEntry,
  deleteMeeting,
  elementQuery,
  invalidateAfterAbsenceChange,
  invalidateAgenda,
  moveItem,
  readStoredFilters,
  returnFromAbsence,
  writeStoredFilters,
} from "../components/agenda/agendaApi";
import { LIST_DAYS, TYPE_ORDER } from "../components/agenda/agendaConstants";
import { agendaErrorMessage, errorStatus, isNotFound } from "../components/agenda/agendaErrors";
import {
  absenceGroups,
  absencePeriodLabel,
  anchorFromParam,
  applyFilters,
  countByType,
  extendListDays,
  feedRange,
  findItem,
  helperName,
  isFilterActive,
  myPresence,
  normalizeByKind,
  normalizeFeed,
  parseElementParam,
  periodTitle,
  shiftAnchor,
  toggleFilterType,
  viewFromParam,
} from "../components/agenda/calendarModel";
import { addDaysIso, daysBetween, formatDayMedium, isIsoDate, resolveToday } from "../components/agenda/dateUtils";
import PrintPlanning from "../components/agenda/calendar/PrintPlanning";
import AbsenceDialog from "../components/agenda/calendar/AbsenceDialog";
import AddMenu from "../components/agenda/calendar/AddMenu";
import AgendaListView from "../components/agenda/calendar/AgendaListView";
import CalendarFilters from "../components/agenda/calendar/CalendarFilters";
import CalendarToolbar from "../components/agenda/calendar/CalendarToolbar";
import DayPopover from "../components/agenda/calendar/DayPopover";
import EntryDialog from "../components/agenda/calendar/EntryDialog";
import ItemDetailDrawer from "../components/agenda/calendar/ItemDetailDrawer";
import MonthView from "../components/agenda/calendar/MonthView";
import QuickAddPopover from "../components/agenda/calendar/QuickAddPopover";
import { NextEventsCard, RemindersCard } from "../components/agenda/calendar/SideCards";
import WeekView from "../components/agenda/calendar/WeekView";
import { defaultAddDate, restoreFocus, useMediaQuery } from "../components/agenda/calendar/calendarHelpers";
import MeetingDialog from "../components/agenda/meetings/MeetingDialog";
import "../components/agenda/calendar/agenda-calendar.css";

let quickCounter = 0;

function CalendarSkeleton() {
  return (
    <div className="ag-cal-skeleton" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <span key={index} className="ag-skeleton" />
      ))}
    </div>
  );
}

function PanelError({ message, onRetry }) {
  return (
    <div className="ag-error" role="alert">
      <span className="ag-error-text">
        <CircleAlert size={15} aria-hidden="true" />
        {message}
      </span>
      {onRetry ? (
        <button type="button" className="ag-error-retry" onClick={onRetry}>
          <RefreshCw size={13} aria-hidden="true" />
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

// Calendrier du staff : absences, réunions et autres entrées (vues Mois, Semaine et Liste).
export default function AbsenceCalendarPage({ isResponsable = false, currentHelperId = null }) {
  useAgendaNoNav();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const narrow = useMediaQuery("(max-width: 899px)");
  const phone = useMediaQuery("(max-width: 639px)");

  const [filters, setFilters] = useState(() =>
    searchParams.get("categorie") === "taches" ? { types: ["taches"], onlyMine: false } : readStoredFilters(),
  );
  useEffect(() => {
    writeStoredFilters(filters);
  }, [filters]);

  const [listState, setListState] = useState({ anchor: "", days: LIST_DAYS });
  const [dialog, setDialog] = useState(null);
  const [quick, setQuick] = useState(null);
  const [dayPop, setDayPop] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const pickedKey = useRef(null);

  // Données de la page. « Aujourd'hui » vient du serveur (date de Paris), avec un repli calculé à Paris.
  const upcomingQuery = useQuery(agendaQueries.upcoming());
  const settingsQuery = useQuery(agendaQueries.settings());
  const today = resolveToday(upcomingQuery.data?.today);

  const view = viewFromParam(searchParams.get("vue"), { narrow });
  const anchor = anchorFromParam(searchParams.get("date"), today);
  const listDays = listState.anchor === anchor ? listState.days : LIST_DAYS;
  const range = feedRange(view, anchor, { listDays });
  const feedQuery = useQuery(agendaQueries.feed(range?.start, range?.end));

  const viewerId = feedQuery.data?.viewer?.id ?? upcomingQuery.data?.viewer?.id ?? currentHelperId ?? null;

  const allItems = useMemo(() => normalizeFeed(feedQuery.data, { viewerId }), [feedQuery.data, viewerId]);
  const visibleItems = useMemo(() => applyFilters(allItems, filters, viewerId), [allItems, filters, viewerId]);
  const counts = useMemo(
    () =>
      countByType(applyFilters(allItems, { types: TYPE_ORDER, onlyMine: filters.onlyMine }, viewerId), {
        from: range?.start,
        to: range?.end,
      }),
    [allItems, filters.onlyMine, range?.end, range?.start, viewerId],
  );

  const patchParams = useCallback(
    (changes) => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === undefined || value === "") next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // ---- Élément ouvert dans le tiroir (?element=kind:id) ----

  const elementParam = searchParams.get("element");
  const element = useMemo(() => parseElementParam(elementParam), [elementParam]);
  const feedItem = element ? findItem(allItems, element.key, pickedKey.current) : null;
  const detailQuery = useQuery({
    ...elementQuery(element),
    enabled: Boolean(element) && !feedItem && !feedQuery.isPending,
  });
  const fetchedItem = useMemo(
    () => (element && detailQuery.data ? normalizeByKind(element.kind, detailQuery.data, { today, viewerId }) : null),
    [detailQuery.data, element, today, viewerId],
  );
  const selectedItem = feedItem || fetchedItem;

  const handledParam = useRef("");
  useEffect(() => {
    if (!elementParam) {
      handledParam.current = "";
      return;
    }
    const failed = Boolean(element) && !feedItem && detailQuery.isError;
    if ((element && !failed) || handledParam.current === elementParam) return;
    handledParam.current = elementParam;
    toast.error(!element || isNotFound(detailQuery.error) ? "Élément introuvable." : agendaErrorMessage(detailQuery.error));
    patchParams({ element: null });
  }, [detailQuery.error, detailQuery.isError, element, elementParam, feedItem, patchParams]);

  // Lien partagé sans `date` : la vue se place sur la date de l'élément une fois chargé.
  const jumpedTo = useRef("");
  const hasDateParam = Boolean(searchParams.get("date"));
  useEffect(() => {
    if (!fetchedItem || feedItem || hasDateParam || jumpedTo.current === fetchedItem.key) return;
    jumpedTo.current = fetchedItem.key;
    patchParams({ date: fetchedItem.start });
  }, [fetchedItem, feedItem, hasDateParam, patchParams]);

  const triggerRef = useRef(null);
  const openItem = useCallback(
    (item) => {
      if (item.kind === "task") {
        navigate(`/animateur/projects/${encodeURIComponent(item.raw.project_id)}?task=${encodeURIComponent(item.id)}`);
        return;
      }
      triggerRef.current = typeof document !== "undefined" ? document.activeElement : null;
      setDayPop(null);
      // Une occurrence d'une série s'ouvre par l'identifiant de la série ; on retient laquelle a été cliquée.
      pickedKey.current = item.key;
      patchParams({ element: `${item.kind}:${item.id}` });
    },
    [navigate, patchParams],
  );
  const openElement = useCallback(
    (kind, id) => {
      triggerRef.current = typeof document !== "undefined" ? document.activeElement : null;
      patchParams({ element: `${kind}:${id}` });
    },
    [patchParams],
  );
  const closeItem = useCallback(() => patchParams({ element: null }), [patchParams]);

  // ---- Navigation ----

  const goTo = useCallback((iso) => patchParams({ date: iso === today ? null : iso }), [patchParams, today]);
  const handleViewChange = (next) => patchParams({ vue: next });
  const handlePrevious = () => goTo(shiftAnchor(view, anchor, -1, { listDays }));
  const handleNext = () => goTo(shiftAnchor(view, anchor, 1, { listDays }));

  const nextListDays = view === "liste" ? extendListDays(listDays) : null;
  const handleExtend = () => {
    if (nextListDays) setListState({ anchor, days: nextListDays });
  };

  // Une création hors de la période affichée : la vue se place sur sa date.
  const ensureVisible = useCallback(
    (iso) => {
      if (!range || !isIsoDate(iso)) return;
      if (iso < range.start || iso > range.end) goTo(iso);
    },
    [goTo, range],
  );

  // ---- Filtres ----

  const handleToggleType = (type) => setFilters((old) => toggleFilterType(old, type));
  const handleToggleMine = (onlyMine) => setFilters((old) => ({ ...old, onlyMine }));
  const handleResetFilters = () => setFilters({ types: [...TYPE_ORDER], onlyMine: false });
  const showAllAbsences = () => {
    setFilters({ types: ["absence"], onlyMine: false });
    patchParams({ vue: "liste", date: null });
  };

  // ---- Ajouts et modifications ----

  const handleAddSelect = (type) => {
    const date = defaultAddDate(range, anchor, today);
    if (type === "absence") setDialog({ kind: "absence", defaults: { start: date } });
    else if (type === "reunion") setDialog({ kind: "meeting", date });
    else setDialog({ kind: "entry", type, defaults: { start: date } });
  };

  const handleQuickAdd = (request) => {
    quickCounter += 1;
    setDayPop(null);
    setQuick({ ...request, nonce: quickCounter });
  };

  const handleOpenDay = (day, anchorEl) => setDayPop({ day, anchorEl: anchorEl || null });

  const handleAddDay = (day) => {
    quickCounter += 1;
    setQuick({ start: day, end: day, fromRange: false, anchorEl: dayPop?.anchorEl || null, nonce: quickCounter });
    setDayPop(null);
  };

  const handleOpenFull = (values) => {
    if (values.type === "absence") {
      setDialog({
        kind: "absence",
        defaults: { start: values.start, end: values.end, openEnded: values.openEnded, reason: values.reason },
      });
    } else if (values.type === "reunion") {
      setDialog({ kind: "meeting", date: values.start });
    } else {
      setDialog({
        kind: "entry",
        type: values.type,
        defaults: {
          title: values.title,
          start: values.start,
          end: values.end,
          allDay: values.allDay,
          startTime: values.startTime,
          endTime: values.endTime,
        },
      });
    }
  };

  const handleEdit = (item, detail) => {
    if (item.kind === "absence") setDialog({ kind: "absence", absence: item.raw });
    else if (item.kind === "entry") setDialog({ kind: "entry", entry: item.raw });
    else if (detail) setDialog({ kind: "meeting", meeting: detail });
  };
  const handleDuplicate = (item) => setDialog({ kind: "entry", template: item.raw });
  const closeDialog = (next) => {
    if (!next) setDialog(null);
  };

  // ---- Actions sur les éléments ----

  const removeAbsence = useCallback(
    async (absenceId) => {
      if (!window.confirm("Supprimer cette absence ?")) return;
      setBusyKey(`absence:${absenceId}`);
      try {
        await deleteAbsence(absenceId);
        toast.success("Absence supprimée.");
        if (elementParam === `absence:${absenceId}`) closeItem();
        await invalidateAfterAbsenceChange(queryClient);
      } catch (error) {
        toast.error(agendaErrorMessage(error));
      } finally {
        setBusyKey("");
      }
    },
    [closeItem, elementParam, queryClient],
  );

  const removeItem = useCallback(
    async (item) => {
      if (item.kind === "absence") {
        await removeAbsence(item.id);
        return;
      }
      const isMeeting = item.kind === "meeting";
      if (!window.confirm(isMeeting ? "Supprimer cette réunion ?" : "Supprimer cet élément ?")) return;
      setBusyKey(item.key);
      try {
        if (isMeeting) await deleteMeeting(item.id);
        else await deleteEntry(item.id);
        toast.success(isMeeting ? "Réunion supprimée." : "Élément supprimé.");
        if (elementParam === item.key) closeItem();
        await invalidateAgenda(queryClient);
      } catch (error) {
        toast.error(agendaErrorMessage(error));
      } finally {
        setBusyKey("");
      }
    },
    [closeItem, elementParam, queryClient, removeAbsence],
  );

  const returnNow = useCallback(
    async (absence) => {
      setBusyKey(`return:${absence.id}`);
      try {
        await returnFromAbsence(absence.id);
        toast.success("Bon retour parmi nous !");
        await invalidateAfterAbsenceChange(queryClient);
      } catch (error) {
        toast.error(agendaErrorMessage(error));
      } finally {
        setBusyKey("");
      }
    },
    [queryClient],
  );

  // ---- Glisser-déposer : changer la date, avec annulation par toast ----

  const handleMove = useCallback(
    async (item, fromDay, toDay) => {
      if (!isIsoDate(fromDay) || !isIsoDate(toDay) || busyKey) return;
      const delta = daysBetween(fromDay, toDay);
      if (!delta) return;
      setBusyKey(`move:${item.key}`);
      try {
        const moved = await moveItem(item.kind, item.id, delta);
        await invalidateAgenda(queryClient);
        const series = item.recurrence ? "Série décalée : " : "";
        toast.success(`${series}« ${item.title} » déplacé au ${formatDayMedium(moved.start_date || addDaysIso(item.start, delta))}.`, {
          duration: 8000,
          action: {
            label: "Annuler",
            onClick: async () => {
              try {
                await moveItem(item.kind, item.id, -delta);
                await invalidateAgenda(queryClient);
                toast.success("Déplacement annulé.");
              } catch (error) {
                toast.error(agendaErrorMessage(error));
              }
            },
          },
        });
      } catch (error) {
        toast.error(agendaErrorMessage(error));
      } finally {
        setBusyKey("");
      }
    },
    [busyKey, queryClient],
  );

  const handlePrint = () => {
    if (typeof window !== "undefined" && typeof window.print === "function") window.print();
  };

  // ---- Panneau latéral ----

  const upcoming = upcomingQuery.data;
  const groups = useMemo(() => (upcoming ? absenceGroups(upcoming) : []), [upcoming]);
  const presence = useMemo(
    () => (upcoming ? myPresence(upcoming.absences_current, viewerId, today) : null),
    [today, upcoming, viewerId],
  );
  const canReturn = Boolean(presence?.absence) && presence.absence.start_date < today;

  const forbidden = errorStatus(feedQuery.error) === 403 || errorStatus(upcomingQuery.error) === 403;

  if (forbidden) {
    return (
      <main className="ag-page ag-cal-page">
        <header className="ag-header">
          <div>
            <p className="ag-eyebrow">Espace staff</p>
            <h1>Calendrier</h1>
          </div>
          <div className="ag-header-actions">
            <AgendaHomeLink />
          </div>
        </header>
        <div className="ag-panel">
          <div className="ag-empty">
            <span className="ag-empty-icon">
              <Lock size={28} aria-hidden="true" />
            </span>
            <h3>Cette page est réservée au staff.</h3>
            <p>Le rôle Discord Staff est nécessaire pour voir le calendrier.</p>
          </div>
        </div>
      </main>
    );
  }

  const feedLoading = feedQuery.isPending && !feedQuery.data;
  const feedRefreshing = feedQuery.isFetching && !feedLoading;

  return (
    <main className="ag-page ag-cal-page">
      <header className="ag-header">
        <div>
          <p className="ag-eyebrow">Espace staff</p>
          <h1>Calendrier</h1>
          <p className="ag-intro">Absences, réunions et temps forts de l'équipe, au même endroit.</p>
          <div className="ag-header-meta">
            {presence ? (
              <span className={`ag-presence ag-presence--${presence.status}`} role="status">
                <span className="ag-presence-dot" aria-hidden="true" />
                {presence.label}
              </span>
            ) : (
              <span className="ag-skeleton ag-cal-presence-skeleton" aria-hidden="true" />
            )}
            {canReturn ? (
              <button
                type="button"
                className="ag-button ag-button--secondary ag-button--small"
                disabled={busyKey === `return:${presence.absence.id}`}
                onClick={() => returnNow(presence.absence)}
              >
                Je suis de retour
              </button>
            ) : null}
          </div>
        </div>
        <div className="ag-header-actions">
          <AgendaHomeLink />
          {phone ? null : (
            <button type="button" className="ag-button ag-button--secondary" onClick={handlePrint}>
              <Printer size={16} aria-hidden="true" />
              Imprimer le planning
            </button>
          )}
          <Link to="/staff/sondages" className="ag-button ag-button--secondary">
            <ListChecks size={16} aria-hidden="true" />
            Sondages de créneaux
          </Link>
          {phone ? null : <AddMenu canManage={isResponsable} onSelect={handleAddSelect} />}
          {isResponsable ? (
            <button
              type="button"
              className="ag-icon-button"
              aria-label="Réglages des rappels Discord"
              title="Réglages des rappels Discord"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 size={18} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      </header>

      <div className="ag-layout">
        <section className="ag-panel ag-cal" aria-label="Calendrier" aria-busy={feedLoading || feedRefreshing}>
          <CalendarToolbar
            title={periodTitle(view, anchor, today)}
            view={view}
            onViewChange={handleViewChange}
            onPrevious={handlePrevious}
            onNext={handleNext}
            onToday={() => patchParams({ date: null })}
          />
          <CalendarFilters
            filters={filters}
            counts={counts}
            onToggleType={handleToggleType}
            onToggleMine={handleToggleMine}
            onReset={handleResetFilters}
          />
          {feedQuery.isError && !feedQuery.data ? (
            <PanelError message="Impossible de charger le calendrier." onRetry={() => feedQuery.refetch()} />
          ) : feedLoading ? (
            <CalendarSkeleton />
          ) : (
            <div className={feedRefreshing ? "ag-cal-body is-refreshing" : "ag-cal-body"}>
              {view === "mois" ? (
                <MonthView
                  anchor={anchor}
                  today={today}
                  items={visibleItems}
                  mobile={phone}
                  onOpenItem={openItem}
                  onOpenDay={handleOpenDay}
                  onQuickAdd={handleQuickAdd}
                  onNavigateDate={goTo}
                  onMoveItem={handleMove}
                />
              ) : null}
              {view === "semaine" ? (
                <WeekView
                  anchor={anchor}
                  today={today}
                  items={visibleItems}
                  stacked={narrow}
                  onOpenItem={openItem}
                  onOpenDay={handleOpenDay}
                  onQuickAdd={handleQuickAdd}
                  onMoveItem={handleMove}
                />
              ) : null}
              {view === "liste" ? (
                <AgendaListView
                  range={range}
                  today={today}
                  items={visibleItems}
                  onOpenItem={openItem}
                  onAdd={() => handleAddSelect("evenement")}
                  onExtend={handleExtend}
                  canExtend={Boolean(nextListDays)}
                  extendLabel={nextListDays ? `Afficher les ${nextListDays - listDays} jours suivants` : ""}
                />
              ) : null}
              {feedQuery.isError ? (
                <PanelError message="Mise à jour du calendrier impossible." onRetry={() => feedQuery.refetch()} />
              ) : null}
              {isFilterActive(filters) && !visibleItems.length && view !== "liste" ? (
                <p className="ag-cal-filtered-note" role="status">
                  <CalendarDays size={14} aria-hidden="true" />
                  Aucun élément ne correspond aux filtres sur cette période.
                </p>
              ) : null}
            </div>
          )}
        </section>

        <aside className="ag-side" aria-label="Informations complémentaires">
          <section className="ag-panel ag-cal-side-card" aria-labelledby="ag-cal-absences-title" aria-busy={upcomingQuery.isPending}>
            <div className="ag-panel-header">
              <span className="ag-panel-icon">
                <UserMinus size={20} aria-hidden="true" />
              </span>
              <div className="ag-panel-heading">
                <p className="ag-eyebrow">Absences</p>
                <h2 className="ag-panel-title" id="ag-cal-absences-title">
                  Qui est absent ?
                </h2>
              </div>
            </div>
            {upcomingQuery.isError ? (
              <PanelError message="Impossible de charger les absences." onRetry={() => upcomingQuery.refetch()} />
            ) : upcomingQuery.isPending ? (
              <div className="ag-skeleton-stack" aria-hidden="true">
                <span className="ag-skeleton ag-skeleton-line" style={{ width: "40%" }} />
                <span className="ag-skeleton" style={{ height: 48 }} />
                <span className="ag-skeleton" style={{ height: 48 }} />
              </div>
            ) : (
              <div className="ag-panel-body ag-cal-absences">
                {groups.map((group) => (
                  <div key={group.key} className="ag-cal-abs-group">
                    <h3 className="ag-cal-abs-heading">
                      {group.title}
                      <span className="ag-count">{group.total}</span>
                    </h3>
                    {group.items.length ? (
                      <ul className="ag-cal-abs-list">
                        {group.items.map((entry) => (
                          <li key={entry.id} className="ag-cal-abs-item">
                            <HelperAvatar person={entry.helper} size={30} decorative />
                            <button type="button" className="ag-cal-abs-main" onClick={() => openElement("absence", entry.id)}>
                              <strong>{helperName(entry.helper)}</strong>
                              <small>{absencePeriodLabel(entry, today)}</small>
                              {entry.reason ? <span className="ag-cal-abs-reason">{entry.reason}</span> : null}
                            </button>
                            <div className="ag-cal-abs-actions">
                              {entry.can_edit ? (
                                <button
                                  type="button"
                                  className="ag-icon-button ag-icon-button--small"
                                  aria-label={`Modifier l’absence de ${helperName(entry.helper)}`}
                                  onClick={() => setDialog({ kind: "absence", absence: entry })}
                                >
                                  <Pencil size={14} aria-hidden="true" />
                                </button>
                              ) : null}
                              {(isResponsable || (currentHelperId && entry.helper?.id === currentHelperId)) && (
                                <button
                                  onClick={() => removeAbsence(entry.id)}
                                  type="button"
                                  className="ag-icon-button ag-icon-button--small ag-icon-button--danger"
                                  aria-label="Supprimer l’absence"
                                  disabled={busyKey === `absence:${entry.id}`}
                                >
                                  <Trash2 size={15} aria-hidden="true" />
                                </button>
                              )}
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="ag-cal-abs-empty">{group.emptyLabel}</p>
                    )}
                    {group.hasMore ? (
                      <button type="button" className="ag-link-button" onClick={showAllAbsences}>
                        Tout voir ({group.total})
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </section>

          <NextEventsCard
            events={upcoming?.next_events}
            today={today}
            loading={upcomingQuery.isPending}
            error={upcomingQuery.isError}
            onRetry={() => upcomingQuery.refetch()}
            onOpen={openItem}
          />

          <RemindersCard
            settings={settingsQuery.data}
            loading={settingsQuery.isPending}
            error={settingsQuery.isError}
            isResponsable={isResponsable}
            onRetry={() => settingsQuery.refetch()}
            onConfigure={() => setSettingsOpen(true)}
          />
        </aside>
      </div>

      <PrintPlanning
        view={view}
        anchor={anchor}
        range={range}
        today={today}
        items={visibleItems}
        title={periodTitle(view, anchor, today)}
      />

      {phone ? <AddMenu canManage={isResponsable} onSelect={handleAddSelect} floating /> : null}

      <ItemDetailDrawer
        open={Boolean(element) && !(detailQuery.isError && !selectedItem)}
        onOpenChange={(next) => {
          if (!next) closeItem();
        }}
        item={selectedItem}
        loading={Boolean(element) && !selectedItem}
        today={today}
        isResponsable={isResponsable}
        viewerId={viewerId}
        busy={Boolean(busyKey)}
        onEdit={handleEdit}
        onDuplicate={handleDuplicate}
        onReturn={returnNow}
        onDelete={removeItem}
        onCloseAutoFocus={(event) => restoreFocus(event, triggerRef.current)}
      />

      <DayPopover
        open={Boolean(dayPop)}
        onOpenChange={(next) => {
          if (!next) setDayPop(null);
        }}
        day={dayPop?.day || ""}
        anchorEl={dayPop?.anchorEl || null}
        items={visibleItems}
        today={today}
        sheet={phone}
        onOpenItem={openItem}
        onAddDay={handleAddDay}
      />

      <QuickAddPopover
        request={quick}
        canManage={isResponsable}
        onClose={() => setQuick(null)}
        onOpenFull={handleOpenFull}
        onCreated={ensureVisible}
      />

      <AbsenceDialog
        open={dialog?.kind === "absence"}
        onOpenChange={closeDialog}
        absence={dialog?.absence || null}
        defaults={dialog?.defaults || null}
        today={today}
        isResponsable={isResponsable}
        viewerId={viewerId}
        onSaved={(saved) => ensureVisible(saved?.start_date)}
      />
      <EntryDialog
        open={dialog?.kind === "entry"}
        onOpenChange={closeDialog}
        entry={dialog?.entry || null}
        template={dialog?.template || null}
        defaults={dialog?.defaults || null}
        type={dialog?.type || "evenement"}
        today={today}
        isResponsable={isResponsable}
        onSaved={(saved) => ensureVisible(saved?.start_date)}
      />
      {isResponsable ? (
        <MeetingDialog
          open={dialog?.kind === "meeting"}
          onOpenChange={closeDialog}
          meeting={dialog?.meeting || null}
          defaultDate={dialog?.date || ""}
          today={today}
          onSaved={(detail) => ensureVisible(detail?.meeting_date)}
        />
      ) : null}
      {isResponsable ? <ReminderSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} /> : null}
    </main>
  );
}
