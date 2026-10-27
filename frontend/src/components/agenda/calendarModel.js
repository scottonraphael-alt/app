// Modèle du calendrier : fonctions pures (aucun appel réseau, aucun accès au DOM ni au stockage).
import {
  ABSENCE_UPCOMING_LIMIT,
  AGENDA_VIEWS,
  DEFAULT_FILTERS,
  ENTRY_TYPES,
  LIST_DAYS,
  LIST_MAX_DAYS,
  MAX_FEED_SPAN_DAYS,
  MOBILE_MAX_DOTS,
  MONTH_MAX_LANES,
  OPEN_END_DISPLAY_DAYS,
  TYPE_ORDER,
  isValidAgendaId,
  typeLabel,
} from "./agendaConstants";
import {
  addDaysIso,
  addMonthsIso,
  capitalize,
  daysBetween,
  eachDayIso,
  endOfMonthIso,
  endOfWeekIso,
  formatAbsencePeriod,
  formatDayLong,
  formatDayShort,
  formatMonthTitle,
  formatListTitle,
  formatPeriodLong,
  formatRange,
  formatTime,
  formatWeekTitle,
  isIsoDate,
  isPastDay,
  isSameMonthIso,
  isTime,
  isWeekend,
  maxIso,
  minIso,
  relativeDayLabel,
  resolveToday,
  startOfMonthIso,
  startOfWeekIso,
  weekdayShort,
} from "./dateUtils";

const ELEMENT_KINDS = ["entry", "meeting", "absence"];

function sameId(a, b) {
  return a !== null && a !== undefined && b !== null && b !== undefined && String(a) === String(b);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function helperName(person) {
  return person?.display_name || person?.username || "Membre du staff";
}

export function itemKey(kind, id) {
  return `${kind}:${id}`;
}

// « entry:<id> » | « meeting:<id> » | « absence:<id> » → { kind, id, key }, ou null si invalide.
export function parseElementParam(value) {
  if (typeof value !== "string") return null;
  const separator = value.indexOf(":");
  if (separator <= 0) return null;
  const kind = value.slice(0, separator);
  const id = value.slice(separator + 1);
  if (!ELEMENT_KINDS.includes(kind) || !isValidAgendaId(id)) return null;
  return { kind, id, key: itemKey(kind, id) };
}

// Phase d'une absence : a_venir, en_cours ou passee (`today` = date du jour à Paris).
export function absencePhase(absence, today) {
  const day = resolveToday(today);
  if (!absence || !isIsoDate(absence.start_date)) return "passee";
  if (absence.start_date > day) return "a_venir";
  const openEnded = Boolean(absence.open_ended) || !absence.end_date;
  if (openEnded || absence.end_date >= day) return "en_cours";
  return "passee";
}

function context(options) {
  return {
    today: resolveToday(options?.today),
    viewerId: options?.viewerId ?? null,
  };
}

export function normalizeAbsence(absence, options = {}) {
  const { today, viewerId } = context(options);
  const start = absence.start_date;
  const openEnded = Boolean(absence.open_ended) || !absence.end_date;
  const visibleFrom = maxIso(today, start);
  // Une fin antérieure au début (donnée abîmée) est ramenée au jour de début.
  const end = openEnded ? null : maxIso(start, absence.end_date) || absence.end_date;
  return {
    key: itemKey("absence", absence.id),
    kind: "absence",
    type: "absence",
    id: String(absence.id),
    title: helperName(absence.helper),
    label: "Absence",
    start,
    end,
    displayEnd: openEnded ? addDaysIso(visibleFrom, OPEN_END_DISPLAY_DAYS) : end,
    tailStart: openEnded ? addDaysIso(visibleFrom, 1) : null,
    startTime: null,
    endTime: null,
    allDay: true,
    openEnded,
    location: "",
    description: absence.reason || "",
    people: absence.helper ? [absence.helper] : [],
    cancelled: false,
    phase: absence.phase || absencePhase(absence, today),
    mine: sameId(absence.helper?.id, viewerId),
    canEdit: Boolean(absence.can_edit),
    raw: absence,
  };
}

function meetingParticipantIds(meeting) {
  if (Array.isArray(meeting.participant_ids)) return meeting.participant_ids.map(String);
  return asArray(meeting.participants).map((person) => String(person?.id));
}

export function normalizeMeeting(meeting, options = {}) {
  const { viewerId } = context(options);
  const startTime = isTime(meeting.start_time) ? meeting.start_time : null;
  const participantIds = meetingParticipantIds(meeting);
  const mine = viewerId !== null && viewerId !== undefined
    ? participantIds.includes(String(viewerId)) || Boolean(meeting.is_participant)
    : Boolean(meeting.is_participant);
  return {
    key: itemKey("meeting", meeting.id),
    kind: "meeting",
    type: "reunion",
    id: String(meeting.id),
    title: meeting.title || "Réunion",
    label: "Réunion",
    start: meeting.meeting_date,
    end: meeting.meeting_date,
    displayEnd: meeting.meeting_date,
    tailStart: null,
    startTime,
    endTime: startTime && isTime(meeting.end_time) ? meeting.end_time : null,
    allDay: !startTime,
    openEnded: false,
    location: meeting.location || "",
    description: "",
    people: asArray(meeting.participants),
    cancelled: Boolean(meeting.cancelled) || meeting.phase === "annulee",
    phase: meeting.phase || null,
    mine,
    canEdit: Boolean(meeting.can_manage),
    raw: meeting,
  };
}

export function normalizeEntry(entry, options = {}) {
  const { viewerId } = context(options);
  const type = ENTRY_TYPES[entry.type] && ENTRY_TYPES[entry.type].kind === "entry" ? entry.type : "autre";
  const startTime = !entry.all_day && isTime(entry.start_time) ? entry.start_time : null;
  const end = isIsoDate(entry.end_date) && entry.end_date > entry.start_date ? entry.end_date : entry.start_date;
  const people = asArray(entry.participants);
  return {
    key: itemKey("entry", entry.id),
    kind: "entry",
    type,
    id: String(entry.id),
    title: entry.title || typeLabel(type, entry.custom_label),
    label: typeLabel(type, entry.custom_label),
    start: entry.start_date,
    end,
    displayEnd: end,
    tailStart: null,
    startTime,
    endTime: startTime && isTime(entry.end_time) ? entry.end_time : null,
    allDay: !startTime,
    openEnded: false,
    location: entry.location || "",
    description: entry.description || "",
    people,
    cancelled: false,
    phase: null,
    mine: sameId(entry.created_by?.id, viewerId) || people.some((person) => sameId(person?.id, viewerId)),
    canEdit: Boolean(entry.can_edit),
    raw: entry,
  };
}

// Tâche de projet à rendre (feed.tasks) : un jour, sans horaire, ouvre le projet au clic.
export function normalizeTask(task, options = {}) {
  const { viewerId } = context(options);
  const assignee = isRecord(task.assignee) ? task.assignee : null;
  const project = task.project_title || "";
  return {
    key: itemKey("task", task.id),
    kind: "task",
    type: "taches",
    id: String(task.id),
    title: task.title || "Tâche",
    label: "Tâche à rendre",
    start: task.due_date,
    end: task.due_date,
    displayEnd: task.due_date,
    tailStart: null,
    startTime: null,
    endTime: null,
    allDay: true,
    openEnded: false,
    location: "",
    description: [project, assignee ? helperName(assignee) : ""].filter(Boolean).join(" · "),
    people: assignee ? [assignee] : [],
    cancelled: false,
    phase: null,
    mine: sameId(assignee?.id, viewerId),
    canEdit: false,
    raw: task,
  };
}

// Élément de `upcoming.next_events` (forme réduite) → CalendarItem, ou null si ce n'est pas un objet.
export function normalizeNextEvent(event) {
  if (!isRecord(event)) return null;
  const isMeeting = event.kind === "meeting";
  const type = isMeeting ? "reunion" : ENTRY_TYPES[event.type] ? event.type : "autre";
  const startTime = !event.all_day && isTime(event.start_time) ? event.start_time : null;
  const end = isIsoDate(event.end_date) && event.end_date > event.start_date ? event.end_date : event.start_date;
  return {
    key: itemKey(isMeeting ? "meeting" : "entry", event.id),
    kind: isMeeting ? "meeting" : "entry",
    type,
    id: String(event.id),
    title: event.title || typeLabel(type, event.custom_label),
    label: typeLabel(type, event.custom_label),
    start: event.start_date,
    end,
    displayEnd: end,
    tailStart: null,
    startTime,
    endTime: null,
    allDay: !startTime,
    openEnded: false,
    location: event.location || "",
    description: "",
    people: [],
    cancelled: Boolean(event.cancelled),
    phase: null,
    mine: false,
    canEdit: false,
    raw: event,
  };
}

// `upcoming.next_events` → CalendarItem[] dans l'ordre du serveur (éléments invalides retirés).
export function normalizeNextEvents(events) {
  return asArray(events)
    .map(normalizeNextEvent)
    .filter((item) => item && isIsoDate(item.start) && isIsoDate(item.displayEnd));
}

// Élément lu par son endpoint de détail (lien profond) → CalendarItem. Sans `viewerId`, on prend
// `viewer.id` de la réponse quand elle en a un (MeetingDetailOut).
export function normalizeByKind(kind, data, options = {}) {
  if (!isRecord(data)) return null;
  const ctx = { ...options, viewerId: options?.viewerId ?? data.viewer?.id ?? null };
  if (kind === "absence") return normalizeAbsence(data, ctx);
  if (kind === "meeting") return normalizeMeeting(data, ctx);
  if (kind === "entry") return normalizeEntry(data, ctx);
  return null;
}

export function itemSpanDays(item) {
  const span = daysBetween(item.start, item.displayEnd);
  return span === null ? 1 : span + 1;
}

export function isMultiDay(item) {
  return item.openEnded || item.displayEnd > item.start;
}

function typeRank(type) {
  const index = TYPE_ORDER.indexOf(type);
  return index === -1 ? TYPE_ORDER.length : index;
}

// Ordre d'affichage : début, journée entière avant les horaires, heure, durée décroissante, type, titre.
export function compareItems(a, b) {
  if (a.start !== b.start) return a.start < b.start ? -1 : 1;
  if (a.allDay !== b.allDay) return a.allDay ? -1 : 1;
  const timeA = a.startTime || "";
  const timeB = b.startTime || "";
  if (timeA !== timeB) return timeA < timeB ? -1 : 1;
  const spanDiff = itemSpanDays(b) - itemSpanDays(a);
  if (spanDiff) return spanDiff;
  const rankDiff = typeRank(a.type) - typeRank(b.type);
  if (rankDiff) return rankDiff;
  return String(a.title).localeCompare(String(b.title), "fr", { sensitivity: "base" });
}

export function sortItems(items) {
  return [...asArray(items)].sort(compareItems);
}

// Réponse de GET /agenda/feed → CalendarItem[] triés (absences, réunions, entrées).
export function normalizeFeed(feed, options = {}) {
  if (!feed || typeof feed !== "object") return [];
  const ctx = {
    today: resolveToday(options.today ?? feed.today),
    viewerId: options.viewerId ?? feed.viewer?.id ?? null,
  };
  const items = [
    ...asArray(feed.absences).filter(isRecord).map((absence) => normalizeAbsence(absence, ctx)),
    ...asArray(feed.meetings).filter(isRecord).map((meeting) => normalizeMeeting(meeting, ctx)),
    ...asArray(feed.entries).filter(isRecord).map((entry) => normalizeEntry(entry, ctx)),
    ...asArray(feed.tasks).filter(isRecord).map((task) => normalizeTask(task, ctx)),
  ];
  const seen = new Set();
  const valid = items.filter((item) => {
    if (!isIsoDate(item.start) || !isIsoDate(item.displayEnd) || seen.has(item.key)) return false;
    seen.add(item.key);
    return true;
  });
  return valid.sort(compareItems);
}

// L'élément couvre-t-il ce jour ? `visual` : une absence sans fin s'arrête à `displayEnd`.
export function itemCoversDay(item, iso, { visual = true } = {}) {
  if (!item || !isIsoDate(iso) || iso < item.start) return false;
  if (item.openEnded && !visual) return true;
  return iso <= item.displayEnd;
}

export function itemOverlaps(item, from, to, { visual = true } = {}) {
  if (!item || item.start > to) return false;
  if (item.openEnded && !visual) return true;
  return item.displayEnd >= from;
}

function compareWithinDay(a, b) {
  const multiA = isMultiDay(a);
  const multiB = isMultiDay(b);
  if (a.allDay !== b.allDay) return a.allDay ? -1 : 1;
  if (multiA !== multiB) return multiA ? -1 : 1;
  return compareItems(a, b);
}

// Éléments d'un jour (vue Mois : popover du jour, points sur mobile), triés.
export function itemsOnDay(items, iso, options = {}) {
  return asArray(items).filter((item) => itemCoversDay(item, iso, options)).sort(compareWithinDay);
}

// Map<"YYYY-MM-DD", CalendarItem[]> pour une liste de jours.
export function itemsByDay(items, days, options = {}) {
  const map = new Map();
  for (const day of asArray(days)) map.set(day, itemsOnDay(items, day, options));
  return map;
}

// Vue Mois sur mobile : points de couleur d'un jour (`max` au plus), plus le nombre d'éléments restants.
export function dotsForDay(items, iso, max = MOBILE_MAX_DOTS) {
  const dayItems = itemsOnDay(items, iso);
  return {
    dots: dayItems.slice(0, max).map((item) => ({ key: item.key, type: item.type, cancelled: item.cancelled })),
    extra: Math.max(0, dayItems.length - max),
    total: dayItems.length,
  };
}

// Élément du flux par sa clé (« meeting:<id> »), ou null.
export function findItem(items, key) {
  return asArray(items).find((item) => item.key === key) || null;
}

// Vue Semaine : barres (journée entière ou plusieurs jours) et éléments horaires d'un seul jour.
export function splitWeekItems(items) {
  const bars = [];
  const timed = [];
  for (const item of asArray(items)) {
    if (item.allDay || isMultiDay(item)) bars.push(item);
    else timed.push(item);
  }
  return { bars, timed };
}

// Map<"YYYY-MM-DD", CalendarItem[]> des éléments horaires d'un seul jour, triés par heure.
export function timedItemsByDay(items, days) {
  const { timed } = splitWeekItems(items);
  const map = new Map();
  for (const day of asArray(days)) {
    map.set(day, timed.filter((item) => item.start === day).sort(compareItems));
  }
  return map;
}

function chunk(list, size) {
  const result = [];
  for (let index = 0; index < list.length; index += size) result.push(list.slice(index, index + size));
  return result;
}

// Semaines (lundi → dimanche) qui couvrent le mois de `anchor` : string[][] de 7 jours.
export function buildMonthWeeks(anchor) {
  const range = monthRange(anchor);
  if (!range) return [];
  return chunk(eachDayIso(range.start, range.end), 7);
}

// Les 7 jours (lundi → dimanche) de la semaine de `anchor`.
export function buildWeek(anchor) {
  const range = weekRange(anchor);
  return range ? eachDayIso(range.start, range.end) : [];
}

// Informations d'une cellule de jour : { iso, dayNumber, weekday, inMonth, isToday, isPast, isWeekend }.
// `anchor` = date d'ancrage de la vue Mois (pour griser les jours hors du mois).
export function describeDay(iso, { anchor, today } = {}) {
  const day = resolveToday(today);
  return {
    iso,
    dayNumber: isIsoDate(iso) ? String(Number(iso.slice(8, 10))) : "",
    weekday: weekdayShort(iso),
    inMonth: isIsoDate(anchor) ? isSameMonthIso(iso, anchor) : true,
    isToday: iso === day,
    isPast: isPastDay(iso, day),
    isWeekend: isWeekend(iso),
  };
}

// Déplacement du focus dans la grille au clavier : jour cible, ou null pour une autre touche.
// Flèches : ±1 jour / ±7 jours ; Début / Fin : lundi / dimanche ; Page préc. / suiv. : ±1 mois.
export function dayForKey(iso, key) {
  if (!isIsoDate(iso)) return null;
  switch (key) {
    case "ArrowLeft":
      return addDaysIso(iso, -1);
    case "ArrowRight":
      return addDaysIso(iso, 1);
    case "ArrowUp":
      return addDaysIso(iso, -7);
    case "ArrowDown":
      return addDaysIso(iso, 7);
    case "Home":
      return startOfWeekIso(iso);
    case "End":
      return endOfWeekIso(iso);
    case "PageUp":
      return addMonthsIso(iso, -1);
    case "PageDown":
      return addMonthsIso(iso, 1);
    default:
      return null;
  }
}

export function monthRange(anchor) {
  if (!isIsoDate(anchor)) return null;
  return {
    start: startOfWeekIso(startOfMonthIso(anchor)),
    end: endOfWeekIso(endOfMonthIso(anchor)),
  };
}

export function weekRange(anchor) {
  if (!isIsoDate(anchor)) return null;
  return { start: startOfWeekIso(anchor), end: endOfWeekIso(anchor) };
}

// Vue Liste : de `anchor` à `anchor + days - 1`, dans la limite acceptée par le flux.
export function listRange(anchor, days = LIST_DAYS) {
  if (!isIsoDate(anchor)) return null;
  const length = Math.max(1, Math.min(Number(days) || LIST_DAYS, LIST_MAX_DAYS));
  return { start: anchor, end: addDaysIso(anchor, length - 1) };
}

// « Afficher les 60 jours suivants » : nouvelle durée de la vue Liste, ou null si la limite est atteinte.
export function extendListDays(days, step = LIST_DAYS) {
  const current = Math.max(1, Math.min(Number(days) || LIST_DAYS, LIST_MAX_DAYS));
  if (current >= LIST_MAX_DAYS) return null;
  return Math.min(current + (Number(step) || LIST_DAYS), LIST_MAX_DAYS);
}

// Écart maximal accepté par GET /agenda/feed.
export function clampRange(range) {
  if (!range || !isIsoDate(range.start) || !isIsoDate(range.end)) return null;
  const end = minIso(range.end, addDaysIso(range.start, MAX_FEED_SPAN_DAYS));
  return { start: range.start, end: maxIso(end, range.start) };
}

// Période à charger pour une vue (paramètres `start` / `end` du flux).
export function feedRange(view, anchor, { listDays = LIST_DAYS } = {}) {
  if (view === "semaine") return weekRange(anchor);
  if (view === "liste") return listRange(anchor, listDays);
  return clampRange(monthRange(anchor));
}

export function isValidView(view) {
  return AGENDA_VIEWS.includes(view);
}

// `?vue=` : valeur valide, sinon « liste » sur écran étroit et « mois » ailleurs.
export function viewFromParam(value, { narrow = false } = {}) {
  if (isValidView(value)) return value;
  return narrow ? "liste" : "mois";
}

// `?date=` : date valide, sinon `today`.
export function anchorFromParam(value, today) {
  return isIsoDate(value) ? value : resolveToday(today);
}

// Période précédente (-1) ou suivante (+1).
export function shiftAnchor(view, anchor, direction, { listDays = LIST_DAYS } = {}) {
  const step = direction < 0 ? -1 : 1;
  if (!isIsoDate(anchor)) return anchor;
  if (view === "semaine") return addDaysIso(anchor, 7 * step);
  if (view === "liste") return addDaysIso(anchor, (Number(listDays) || LIST_DAYS) * step);
  return addMonthsIso(anchor, step);
}

// « Octobre 2026 » / « 26 oct. – 1 nov. 2026 » / « À partir du 25 octobre »
export function periodTitle(view, anchor, today) {
  if (view === "semaine") return formatWeekTitle(anchor);
  if (view === "liste") return formatListTitle(anchor, resolveToday(today));
  return formatMonthTitle(anchor);
}

// Répartition en couloirs des barres d'une semaine (attribution gloutonne : début croissant,
// puis durée décroissante, premier couloir libre). Les éléments sans place vont dans `hiddenByDay`.
export function layoutLanes(weekDays, items, maxLanes = MONTH_MAX_LANES) {
  const days = asArray(weekDays).filter(isIsoDate);
  const hiddenByDay = new Map();
  if (!days.length) return { lanes: [], hiddenByDay };
  const first = days[0];
  const last = days[days.length - 1];
  const count = days.length;
  const candidates = asArray(items)
    .filter((item) => isIsoDate(item?.start) && isIsoDate(item?.displayEnd) && item.start <= last && item.displayEnd >= first)
    .sort((a, b) => {
      if (a.start !== b.start) return a.start < b.start ? -1 : 1;
      const spanDiff = itemSpanDays(b) - itemSpanDays(a);
      return spanDiff || compareItems(a, b);
    });
  const occupancy = [];
  const lanes = [];
  for (const item of candidates) {
    const startIndex = item.start < first ? 0 : daysBetween(first, item.start);
    const endIndex = item.displayEnd > last ? count - 1 : daysBetween(first, item.displayEnd);
    let laneIndex = -1;
    for (let lane = 0; lane < maxLanes; lane += 1) {
      if (!occupancy[lane]) {
        occupancy[lane] = new Array(count).fill(false);
        lanes[lane] = [];
      }
      let free = true;
      for (let col = startIndex; col <= endIndex; col += 1) {
        if (occupancy[lane][col]) {
          free = false;
          break;
        }
      }
      if (free) {
        laneIndex = lane;
        break;
      }
    }
    if (laneIndex === -1) {
      for (let col = startIndex; col <= endIndex; col += 1) {
        const day = days[col];
        if (!hiddenByDay.has(day)) hiddenByDay.set(day, []);
        hiddenByDay.get(day).push(item);
      }
      continue;
    }
    for (let col = startIndex; col <= endIndex; col += 1) occupancy[laneIndex][col] = true;
    const segmentStart = days[startIndex];
    const segmentEnd = days[endIndex];
    let tailOffset = null;
    if (item.tailStart && item.tailStart <= segmentEnd) {
      tailOffset = Math.max(0, daysBetween(segmentStart, item.tailStart));
    }
    lanes[laneIndex].push({
      key: `${item.key}@${first}`,
      item,
      lane: laneIndex,
      colStart: startIndex + 1,
      colSpan: endIndex - startIndex + 1,
      continuesBefore: item.start < first,
      continuesAfter: item.displayEnd > last,
      tailOffset,
    });
  }
  for (const segments of lanes) segments.sort((a, b) => a.colStart - b.colStart);
  return { lanes: lanes.filter((segments) => segments.length > 0), hiddenByDay };
}

// Vue Liste : section « En cours » (commencés avant `from`, toujours en cours) puis un groupe par jour.
// Un élément borné sur plusieurs jours est répété sur chaque jour (« J2/5 ») sauf si `repeatMultiDay` est faux.
export function groupForList(items, from, to, { today, repeatMultiDay = true } = {}) {
  const day = resolveToday(today);
  const ongoing = [];
  const groupsByDate = new Map();
  const addRow = (date, row) => {
    if (!groupsByDate.has(date)) groupsByDate.set(date, []);
    groupsByDate.get(date).push(row);
  };
  if (!isIsoDate(from) || !isIsoDate(to)) {
    return { ongoing, groups: [], todayMarkerIndex: null, isEmpty: true };
  }
  for (const item of sortItems(items)) {
    if (!isIsoDate(item.start)) continue;
    if (item.start < from) {
      if (itemCoversDay(item, from, { visual: false })) ongoing.push(item);
      continue;
    }
    if (item.start > to) continue;
    const span = item.openEnded ? null : itemSpanDays(item);
    if (item.openEnded || !repeatMultiDay || span === 1) {
      addRow(item.start, { key: `${item.key}@${item.start}`, item, dayIndex: 1, dayCount: span });
      continue;
    }
    eachDayIso(item.start, minIso(item.displayEnd, to)).forEach((date, index) => {
      addRow(date, { key: `${item.key}@${date}`, item, dayIndex: index + 1, dayCount: span });
    });
  }
  const groups = [...groupsByDate.keys()].sort().map((date) => ({
    date,
    isToday: date === day,
    isTomorrow: daysBetween(day, date) === 1,
    relativeLabel: relativeDayLabel(date, day),
    rows: groupsByDate.get(date).sort((a, b) => {
      const continuingA = a.dayIndex > 1 || a.item.allDay;
      const continuingB = b.dayIndex > 1 || b.item.allDay;
      if (continuingA !== continuingB) return continuingA ? -1 : 1;
      return compareItems(a.item, b.item);
    }),
  }));
  let todayMarkerIndex = null;
  if (day >= from && day <= to && !groupsByDate.has(day)) {
    const index = groups.findIndex((group) => group.date > day);
    todayMarkerIndex = index === -1 ? groups.length : index;
  }
  return { ongoing, groups, todayMarkerIndex, isEmpty: ongoing.length === 0 && groups.length === 0 };
}

// Colonne gauche d'une ligne de la vue Liste : « 20 h 30 », « Journée » ou « J2/5 ».
export function listRowTimeLabel(row) {
  if (row?.dayCount > 1) return `J${row.dayIndex}/${row.dayCount}`;
  if (row?.item && !row.item.allDay && row.item.startTime) return formatTime(row.item.startTime);
  return "Journée";
}

// Heure affichée dans une barre de la vue Mois (« 20:30 »), vide pour la journée entière.
export function barTimeLabel(item) {
  return item && !item.allDay && item.startTime ? item.startTime : "";
}

// Plage courte d'un élément : « 28 oct. → 2 nov. », « Depuis le 22 oct. · fin indéterminée », ou "" pour un seul jour.
export function formatItemRange(item, today) {
  if (!item) return "";
  if (item.openEnded) return `Depuis le ${formatDayShort(item.start)} · fin indéterminée`;
  if (item.end && item.end > item.start) {
    const year = resolveToday(today).slice(0, 4);
    return formatRange(item.start, item.end, { withYear: item.start.slice(0, 4) !== year });
  }
  return "";
}

// Période complète (tiroir) : « Mardi 29 octobre 2026 · 20 h 30 – 22 h 30 ».
export function formatItemWhen(item) {
  if (!item) return "";
  return formatPeriodLong({
    start: item.start,
    end: item.end,
    startTime: item.startTime,
    endTime: item.endTime,
    allDay: item.allDay,
    openEnded: item.openEnded,
  });
}

// Libellé accessible d'une barre : « Réunion : Réunion mensuelle de novembre, jeudi 30 octobre à 20 h 30 ».
export function itemAriaLabel(item) {
  if (!item) return "";
  let when;
  if (item.openEnded) {
    when = `depuis le ${formatDayShort(item.start)}, fin indéterminée`;
  } else if (item.end && item.end > item.start) {
    when = `du ${formatDayShort(item.start)} au ${formatDayShort(item.end)}`;
  } else {
    const day = formatDayLong(item.start).replace(/ \d{4}$/, "");
    when = item.allDay ? day : `${day} à ${formatTime(item.startTime)}`;
  }
  const cancelled = item.cancelled ? ", annulée" : "";
  return `${item.label} : ${item.title}, ${when}${cancelled}`;
}

// « Mardi 28 octobre 2026, 2 éléments »
export function dayCellAriaLabel(iso, count) {
  const label = capitalize(formatDayLong(iso));
  if (!count) return `${label}, aucun élément`;
  return `${label}, ${count} élément${count > 1 ? "s" : ""}`;
}

export function sanitizeFilters(raw) {
  const source = raw && typeof raw === "object" ? raw : DEFAULT_FILTERS;
  const types = Array.isArray(source.types)
    ? TYPE_ORDER.filter((type) => source.types.includes(type))
    : [...TYPE_ORDER];
  return { types, onlyMine: Boolean(source.onlyMine) };
}

export function isFilterActive(filters) {
  const clean = sanitizeFilters(filters);
  return clean.onlyMine || clean.types.length !== TYPE_ORDER.length;
}

export function toggleFilterType(filters, type) {
  const clean = sanitizeFilters(filters);
  const types = clean.types.includes(type)
    ? clean.types.filter((key) => key !== type)
    : TYPE_ORDER.filter((key) => key === type || clean.types.includes(key));
  return { ...clean, types };
}

// « Seulement moi » : mes absences, les réunions où je participe, les entrées que j'ai créées ou où je participe.
export function isMine(item, viewerId) {
  if (!item) return false;
  if (viewerId === null || viewerId === undefined || viewerId === "") return Boolean(item.mine);
  const raw = item.raw || {};
  if (item.kind === "absence") return sameId(raw.helper?.id, viewerId);
  if (item.kind === "meeting") {
    return Boolean(raw.is_participant) || meetingParticipantIds(raw).includes(String(viewerId));
  }
  if (item.kind === "task") return sameId(raw.assignee?.id, viewerId);
  if (item.kind === "entry") {
    return sameId(raw.created_by?.id, viewerId) || asArray(raw.participants).some((person) => sameId(person?.id, viewerId));
  }
  return Boolean(item.mine);
}

export function applyFilters(items, filters, viewerId) {
  const clean = sanitizeFilters(filters);
  const types = new Set(clean.types);
  return asArray(items).filter((item) => item && types.has(item.type) && (!clean.onlyMine || isMine(item, viewerId)));
}

// Compteurs des pastilles de type, éventuellement limités à une période visible.
export function countByType(items, { from, to } = {}) {
  const counts = Object.fromEntries(TYPE_ORDER.map((type) => [type, 0]));
  const bounded = isIsoDate(from) && isIsoDate(to);
  for (const item of asArray(items)) {
    if (!item || (bounded && !itemOverlaps(item, from, to))) continue;
    if (item.type in counts) counts[item.type] += 1;
  }
  return counts;
}

function byStartDate(a, b) {
  if (a.start_date !== b.start_date) return a.start_date < b.start_date ? -1 : 1;
  return helperName(a.helper).localeCompare(helperName(b.helper), "fr", { sensitivity: "base" });
}

// Les deux groupes du panneau « Absences », filtrés à nouveau côté client (une absence terminée n'y figure jamais).
export function absenceGroups(upcoming, { limit = ABSENCE_UPCOMING_LIMIT } = {}) {
  const today = resolveToday(upcoming?.today);
  const current = asArray(upcoming?.absences_current)
    .filter((absence) => absencePhase(absence, today) === "en_cours")
    .sort(byStartDate);
  const future = asArray(upcoming?.absences_upcoming)
    .filter((absence) => absencePhase(absence, today) === "a_venir")
    .sort(byStartDate);
  return [
    {
      key: "current",
      title: "En ce moment",
      items: current,
      total: current.length,
      hasMore: false,
      emptyLabel: "Personne n'est absent en ce moment.",
    },
    {
      key: "upcoming",
      title: "À venir",
      items: future.slice(0, limit),
      total: future.length,
      hasMore: future.length > limit,
      emptyLabel: "Aucune absence prévue.",
    },
  ];
}

// Ma pastille de présence d'après `upcoming.absences_current`.
export function myPresence(absencesCurrent, viewerId, today) {
  const day = resolveToday(today);
  const mine = asArray(absencesCurrent).filter(
    (absence) => isRecord(absence) && sameId(absence.helper?.id, viewerId) && absencePhase(absence, day) === "en_cours",
  );
  if (!mine.length) return { status: "available", label: "Disponible", absence: null, openEnded: false, until: null };
  const openEnded = mine.find((absence) => absence.open_ended || !absence.end_date);
  if (openEnded) {
    return { status: "away", label: "En absence · fin indéterminée", absence: openEnded, openEnded: true, until: null };
  }
  const latest = mine.reduce((a, b) => (b.end_date > a.end_date ? b : a));
  const withYear = latest.end_date.slice(0, 4) !== day.slice(0, 4);
  return {
    status: "away",
    label: `En absence jusqu'au ${formatDayShort(latest.end_date, { withYear })}`,
    absence: latest,
    openEnded: false,
    until: latest.end_date,
  };
}

// Période d'une absence (AbsenceOut) pour le panneau latéral.
export function absencePeriodLabel(absence, today) {
  return formatAbsencePeriod(absence, resolveToday(today));
}

// Liste des réunions groupée par mois, dans l'ordre reçu : [{ key: "2026-10", label: "Octobre 2026", items }].
export function groupMeetingsByMonth(meetings) {
  const groups = [];
  const byKey = new Map();
  for (const meeting of asArray(meetings)) {
    const valid = isIsoDate(meeting?.meeting_date);
    const key = valid ? meeting.meeting_date.slice(0, 7) : "";
    if (!byKey.has(key)) {
      const group = { key, label: valid ? formatMonthTitle(meeting.meeting_date) : "Sans date", items: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    byKey.get(key).items.push(meeting);
  }
  return groups;
}
