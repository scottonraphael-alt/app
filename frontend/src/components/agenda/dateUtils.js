import {
  addDays,
  addMonths,
  differenceInCalendarDays,
  endOfMonth,
  endOfWeek,
  format,
  isValid,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { fr } from "date-fns/locale";

// Règle de ce module : une date « jour » est une chaîne YYYY-MM-DD (heure murale de Paris).
// On ne passe jamais par toISOString() ni par new Date("YYYY-MM-DD") (lecture en UTC).

const PARIS = "Europe/Paris";
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
const WEEK_OPTIONS = { weekStartsOn: 1 };
const WEEKDAY_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MAX_DAYS_ENUMERATED = 800;

export function capitalize(text) {
  if (typeof text !== "string" || !text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function isIsoDate(value) {
  if (typeof value !== "string" || !ISO_DATE_RE.test(value)) return false;
  const parsed = parseISO(value);
  return isValid(parsed) && format(parsed, "yyyy-MM-dd") === value;
}

export function isTime(value) {
  return typeof value === "string" && TIME_RE.test(value);
}

// Minutes depuis minuit pour « HH:MM », ou null.
export function timeToMinutes(value) {
  const match = typeof value === "string" ? TIME_RE.exec(value) : null;
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

// Date locale (minuit) pour une date « jour », ou null si la valeur est invalide.
export function parseIsoDate(iso) {
  return isIsoDate(iso) ? parseISO(iso) : null;
}

// « YYYY-MM-DD » à partir d'un objet Date (lu en heure locale) ; une chaîne valide est rendue telle quelle.
export function toIsoDate(value) {
  if (typeof value === "string") return isIsoDate(value) ? value : "";
  if (value instanceof Date && isValid(value)) return format(value, "yyyy-MM-dd");
  return "";
}

function shiftIso(iso, shift) {
  const date = parseIsoDate(iso);
  return date ? toIsoDate(shift(date)) : "";
}

export function addDaysIso(iso, days) {
  return shiftIso(iso, (date) => addDays(date, Number(days) || 0));
}

export function addMonthsIso(iso, months) {
  return shiftIso(iso, (date) => addMonths(date, Number(months) || 0));
}

export function startOfWeekIso(iso) {
  return shiftIso(iso, (date) => startOfWeek(date, WEEK_OPTIONS));
}

export function endOfWeekIso(iso) {
  return shiftIso(iso, (date) => endOfWeek(date, WEEK_OPTIONS));
}

export function startOfMonthIso(iso) {
  return shiftIso(iso, startOfMonth);
}

export function endOfMonthIso(iso) {
  return shiftIso(iso, endOfMonth);
}

// Nombre de jours calendaires de `fromIso` à `toIsoValue` (négatif si `toIsoValue` est avant).
export function daysBetween(fromIso, toIsoValue) {
  const from = parseIsoDate(fromIso);
  const to = parseIsoDate(toIsoValue);
  if (!from || !to) return null;
  return differenceInCalendarDays(to, from);
}

// Tous les jours de `startIso` à `endIso` inclus (borné par sécurité).
export function eachDayIso(startIso, endIso) {
  const span = daysBetween(startIso, endIso);
  if (span === null || span < 0) return [];
  const days = [];
  const start = parseISO(startIso);
  for (let index = 0; index <= Math.min(span, MAX_DAYS_ENUMERATED); index += 1) {
    days.push(toIsoDate(addDays(start, index)));
  }
  return days;
}

export function minIso(...values) {
  const valid = values.filter(isIsoDate);
  return valid.length ? valid.reduce((a, b) => (b < a ? b : a)) : "";
}

export function maxIso(...values) {
  const valid = values.filter(isIsoDate);
  return valid.length ? valid.reduce((a, b) => (b > a ? b : a)) : "";
}

export function isPastDay(iso, today) {
  return isIsoDate(iso) && isIsoDate(today) && iso < today;
}

export function isSameDayIso(a, b) {
  return isIsoDate(a) && a === b;
}

export function isSameMonthIso(a, b) {
  return isIsoDate(a) && isIsoDate(b) && a.slice(0, 7) === b.slice(0, 7);
}

// Plage ordonnée { start, end } à partir de deux jours dans n'importe quel ordre (sélection glissée), ou null.
export function orderDayRange(a, b) {
  if (!isIsoDate(a)) return null;
  if (!isIsoDate(b)) return { start: a, end: a };
  return a <= b ? { start: a, end: b } : { start: b, end: a };
}

// Lundi = 0 … dimanche = 6.
export function weekdayIndex(iso) {
  const date = parseIsoDate(iso);
  return date ? (date.getDay() + 6) % 7 : -1;
}

export function isWeekend(iso) {
  return weekdayIndex(iso) >= 5;
}

export function weekdayShort(iso) {
  return WEEKDAY_SHORT[weekdayIndex(iso)] || "";
}

function formatIso(iso, pattern) {
  const date = parseIsoDate(iso);
  return date ? format(date, pattern, { locale: fr }) : "";
}

// « mardi 28 octobre 2026 »
export function formatDayLong(iso) {
  return formatIso(iso, "EEEE d MMMM yyyy");
}

// « Mardi 28 octobre » (année ajoutée si `withYear`)
export function formatDayTitle(iso, { withYear = false } = {}) {
  return capitalize(formatIso(iso, withYear ? "EEEE d MMMM yyyy" : "EEEE d MMMM"));
}

// « 28 oct. » ou « 28 oct. 2026 »
export function formatDayShort(iso, { withYear = false } = {}) {
  return formatIso(iso, withYear ? "d MMM yyyy" : "d MMM");
}

// « 28 octobre » ou « 28 octobre 2026 »
export function formatDayMedium(iso, { withYear = false } = {}) {
  return formatIso(iso, withYear ? "d MMMM yyyy" : "d MMMM");
}

// « 28 oct. → 2 nov. » ; un seul jour : « 28 oct. ». L'année est ajoutée si les deux années diffèrent.
export function formatRange(startIso, endIso, { withYear = false } = {}) {
  if (!isIsoDate(startIso)) return "";
  if (!isIsoDate(endIso) || endIso === startIso) return formatDayShort(startIso, { withYear });
  const differentYears = startIso.slice(0, 4) !== endIso.slice(0, 4);
  const start = formatDayShort(startIso, { withYear: withYear || differentYears });
  const end = formatDayShort(endIso, { withYear: withYear || differentYears });
  return `${start} → ${end}`;
}

// « 20 h 30 » à partir de « 20:30 » (heure murale de Paris, sans conversion).
export function formatTime(value) {
  const match = typeof value === "string" ? TIME_RE.exec(value) : null;
  if (!match) return "";
  return `${Number(match[1])} h ${match[2]}`;
}

// « 20 h 30 – 22 h 30 » ou « 20 h 30 »
export function formatTimeRange(startTime, endTime) {
  const start = formatTime(startTime);
  if (!start) return "";
  const end = formatTime(endTime);
  return end ? `${start} – ${end}` : start;
}

// « Octobre 2026 »
export function formatMonthTitle(iso) {
  return capitalize(formatIso(iso, "MMMM yyyy"));
}

// « 26 oct. – 1 nov. 2026 », « 2 – 8 nov. 2026 », « 29 déc. 2026 – 4 janv. 2027 »
export function formatWeekTitle(anchorIso) {
  const start = startOfWeekIso(anchorIso);
  const end = endOfWeekIso(anchorIso);
  if (!start || !end) return "";
  if (start.slice(0, 4) !== end.slice(0, 4)) {
    return `${formatDayShort(start, { withYear: true })} – ${formatDayShort(end, { withYear: true })}`;
  }
  if (start.slice(0, 7) === end.slice(0, 7)) {
    return `${formatIso(start, "d")} – ${formatDayShort(end, { withYear: true })}`;
  }
  return `${formatDayShort(start)} – ${formatDayShort(end, { withYear: true })}`;
}

// « À partir du 25 octobre » (année ajoutée si elle diffère de celle de `today`)
export function formatListTitle(anchorIso, today) {
  if (!isIsoDate(anchorIso)) return "";
  const withYear = isIsoDate(today) && today.slice(0, 4) !== anchorIso.slice(0, 4);
  return `À partir du ${formatDayMedium(anchorIso, { withYear })}`;
}

// « aujourd'hui », « demain », « hier », « dans 5 jours », « il y a 3 jours »
export function formatDaysUntil(iso, today) {
  const diff = daysBetween(today, iso);
  if (diff === null) return "";
  if (diff === 0) return "aujourd'hui";
  if (diff === 1) return "demain";
  if (diff === -1) return "hier";
  return diff > 0 ? `dans ${diff} jours` : `il y a ${-diff} jours`;
}

// Pastille d'un jour dans les listes : « Aujourd'hui », « Demain », sinon null.
export function relativeDayLabel(iso, today) {
  const diff = daysBetween(today, iso);
  if (diff === 0) return "Aujourd'hui";
  if (diff === 1) return "Demain";
  return null;
}

// Période complète pour le tiroir de détail :
// « Mardi 29 octobre 2026 · 20 h 30 – 22 h 30 », « Du mardi 28 octobre au dimanche 2 novembre 2026 »,
// « Depuis le mercredi 22 octobre 2026 · fin indéterminée ».
export function formatPeriodLong({ start, end, startTime, endTime, allDay, openEnded } = {}) {
  if (!isIsoDate(start)) return "";
  const timed = !allDay && isTime(startTime);
  if (openEnded) {
    return `Depuis le ${formatDayLong(start)} · fin indéterminée`;
  }
  if (!isIsoDate(end) || end <= start) {
    const day = capitalize(formatDayLong(start));
    return timed ? `${day} · ${formatTimeRange(startTime, endTime)}` : day;
  }
  const sameYear = start.slice(0, 4) === end.slice(0, 4);
  const startText = sameYear ? formatIso(start, "EEEE d MMMM") : formatDayLong(start);
  const endText = formatDayLong(end);
  if (timed) {
    const endPart = isTime(endTime) ? ` à ${formatTime(endTime)}` : "";
    return `Du ${startText} à ${formatTime(startTime)} au ${endText}${endPart}`;
  }
  return `Du ${startText} au ${endText}`;
}

// Période d'une absence (AbsenceOut) pour les listes :
// « Du 28 oct. au 2 nov. », « Depuis le 22 oct. · fin indéterminée », « Jusqu'au 2 nov. », « Le 28 oct. ».
export function formatAbsencePeriod(absence, today) {
  const start = absence?.start_date;
  if (!isIsoDate(start)) return "";
  const openEnded = Boolean(absence.open_ended) || !absence.end_date;
  const end = absence.end_date;
  const withYear = isIsoDate(today)
    ? start.slice(0, 4) !== today.slice(0, 4) || (isIsoDate(end) && end.slice(0, 4) !== today.slice(0, 4))
    : false;
  if (openEnded) return `Depuis le ${formatDayShort(start, { withYear })} · fin indéterminée`;
  if (isIsoDate(today) && start <= today && end >= today) return `Jusqu'au ${formatDayShort(end, { withYear })}`;
  if (end === start) return `Le ${formatDayShort(start, { withYear })}`;
  return `Du ${formatDayShort(start, { withYear })} au ${formatDayShort(end, { withYear })}`;
}

// ---- Fuseau de Paris (Intl, sans dépendance) ----

let parisFormatter;

function getParisFormatter() {
  if (parisFormatter === undefined) {
    try {
      parisFormatter = new Intl.DateTimeFormat("en-GB", {
        timeZone: PARIS,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      });
    } catch (error) {
      parisFormatter = null;
    }
  }
  return parisFormatter;
}

// Composantes de l'heure murale de Paris pour un instant (ms, Date ou chaîne ISO).
export function parisParts(instant) {
  const ms = parseInstant(instant);
  if (ms === null) return null;
  const formatter = getParisFormatter();
  if (!formatter) {
    const local = new Date(ms);
    return {
      year: local.getFullYear(),
      month: local.getMonth() + 1,
      day: local.getDate(),
      hour: local.getHours(),
      minute: local.getMinutes(),
      second: local.getSeconds(),
    };
  }
  const parts = {};
  for (const part of formatter.formatToParts(new Date(ms))) {
    if (part.type !== "literal") parts[part.type] = Number(part.value);
  }
  return {
    year: parts.year,
    month: parts.month,
    day: parts.day,
    hour: parts.hour === 24 ? 0 : parts.hour,
    minute: parts.minute,
    second: parts.second,
  };
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function partsToIso(parts) {
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
}

// Date et heure actuelles à Paris : { date: "YYYY-MM-DD", time: "HH:MM" }.
export function parisNow(nowMs = Date.now()) {
  const parts = parisParts(nowMs);
  return { date: partsToIso(parts), time: `${pad(parts.hour)}:${pad(parts.minute)}` };
}

// « Aujourd'hui » de secours avant la réponse du serveur : la date de Paris calculée par le navigateur.
export function fallbackTodayIso(nowMs = Date.now()) {
  return parisNow(nowMs).date;
}

// Le `today` du serveur (feed.today / upcoming.today) s'il est valide, sinon la date de secours.
export function resolveToday(serverToday) {
  return isIsoDate(serverToday) ? serverToday : fallbackTodayIso();
}

// Instant en millisecondes (UTC). Une chaîne sans fuseau est lue comme de l'UTC.
export function parseInstant(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (value instanceof Date) return isValid(value) ? value.getTime() : null;
  if (typeof value !== "string") return null;
  // Formes Python : séparateur espace, microsecondes (6 chiffres) ; on les ramène à l'ISO lu partout.
  let text = value.trim().replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:)/, "$1T$2").replace(/(\.\d{3})\d+/, "$1");
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)) text = `${text}Z`;
  const ms = Date.parse(text);
  return Number.isNaN(ms) ? null : ms;
}

function parisOffsetMs(ms) {
  const parts = parisParts(ms);
  const wall = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return wall - Math.floor(ms / 1000) * 1000;
}

// Instant UTC (ms) d'une heure murale de Paris (« 20:30 » le « 2026-10-26 »), comme `agenda_time.local_start`
// côté serveur (fold=0) : heure ambiguë (passage à l'heure d'hiver) = première occurrence ; heure inexistante
// (passage à l'heure d'été) = décalage d'avant le changement.
export function parisWallTimeToMs(dateIso, time = "00:00") {
  if (!isIsoDate(dateIso)) return null;
  const minutes = timeToMinutes(time);
  if (minutes === null) return null;
  const [year, month, day] = dateIso.split("-").map(Number);
  const naive = Date.UTC(year, month - 1, day, Math.floor(minutes / 60), minutes % 60);
  const offsetBefore = parisOffsetMs(naive - 43_200_000);
  const offsetAfter = parisOffsetMs(naive + 43_200_000);
  const first = naive - offsetBefore;
  if (parisOffsetMs(first) === offsetBefore) return first;
  const second = naive - offsetAfter;
  if (parisOffsetMs(second) === offsetAfter) return second;
  return first;
}

// Échéance d'un palier de rappel, calculée comme le serveur (heure murale de Paris).
// Renvoie un instant en ms, ou null (H-1 sans heure).
export function reminderDueAt(offsetKey, startDate, startTime, dayTime = "10:00") {
  if (!isIsoDate(startDate)) return null;
  const timed = isTime(startTime);
  if (offsetKey === "H-1") {
    if (!timed) return null;
    const start = parisWallTimeToMs(startDate, startTime);
    return start === null ? null : start - 3_600_000;
  }
  const match = /^J-(\d+)$/.exec(offsetKey || "");
  if (!match) return null;
  const day = addDaysIso(startDate, -Number(match[1]));
  return parisWallTimeToMs(day, timed ? startTime : isTime(dayTime) ? dayTime : "10:00");
}

// Vrai si l'échéance du palier est déjà passée à `nowMs` (faux si elle n'est pas calculable). Le serveur reste la référence.
export function isReminderPast(offsetKey, startDate, startTime, { dayTime = "10:00", nowMs = Date.now() } = {}) {
  const due = reminderDueAt(offsetKey, startDate, startTime, dayTime);
  return due !== null && due <= nowMs;
}

// Date de Paris (« YYYY-MM-DD ») d'un instant.
export function instantToParisDate(value) {
  const parts = parisParts(value);
  return parts ? partsToIso(parts) : "";
}

// Heure de Paris d'un instant : « 21 h 40 ».
export function formatInstantTime(value) {
  const parts = parisParts(value);
  return parts ? formatTime(`${pad(parts.hour)}:${pad(parts.minute)}`) : "";
}

// « 27 oct. à 20 h 30 » (heure de Paris). L'année est ajoutée si elle diffère de l'année en cours.
export function formatInstant(value, { withTime = true, withYear } = {}) {
  const parts = parisParts(value);
  if (!parts) return "";
  const iso = partsToIso(parts);
  const showYear = withYear === undefined ? parts.year !== parisParts(Date.now()).year : withYear;
  const day = formatDayShort(iso, { withYear: showYear });
  return withTime ? `${day} à ${formatInstantTime(value)}` : day;
}

// « à l'instant », « il y a 3 min », « aujourd'hui à 14 h 05 », « hier à 21 h 40 », « le 23 oct. »
export function formatInstantRelative(value, nowMs = Date.now()) {
  const ms = parseInstant(value);
  if (ms === null) return "";
  const elapsed = nowMs - ms;
  if (elapsed >= -60_000 && elapsed < 60_000) return "à l'instant";
  if (elapsed > 0 && elapsed < 3_600_000) return `il y a ${Math.floor(elapsed / 60_000)} min`;
  const day = instantToParisDate(ms);
  const today = parisNow(nowMs).date;
  const diff = daysBetween(today, day);
  if (diff === 0) return `aujourd'hui à ${formatInstantTime(ms)}`;
  if (diff === -1) return `hier à ${formatInstantTime(ms)}`;
  return `le ${formatInstant(ms, { withTime: false, withYear: day.slice(0, 4) !== today.slice(0, 4) })}`;
}

// Morceaux du bloc date (.ag-date-block) : { dayNumber: "28", weekday: "mar.", month: "oct." }.
export function dateBlockParts(iso) {
  if (!isIsoDate(iso)) return { dayNumber: "", weekday: "", month: "" };
  return {
    dayNumber: formatIso(iso, "d"),
    weekday: formatIso(iso, "EEE"),
    month: formatIso(iso, "MMM"),
  };
}
