import {
  Ban,
  BellOff,
  BellRing,
  CircleCheck,
  CircleMinus,
  Clock,
  Flag,
  Headset,
  LoaderCircle,
  PartyPopper,
  Tag,
  TriangleAlert,
  UserMinus,
  Users,
} from "lucide-react";

import {
  addDaysIso,
  formatInstant,
  formatInstantTime,
  instantToParisDate,
  parseInstant,
  resolveToday,
} from "./dateUtils";

export const AGENDA_TIMEZONE = "Europe/Paris";

// Identifiants acceptés dans les URL de l'API (même règle que le serveur).
export const AGENDA_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function isValidAgendaId(id) {
  return typeof id === "string" && AGENDA_ID_PATTERN.test(id) && id !== "undefined" && id !== "null";
}

export const TYPE_ORDER = ["absence", "reunion", "evenement", "echeance", "rappel", "permanence", "autre"];

// Types d'entrées libres (collection agenda_entries), dans l'ordre du sélecteur de EntryDialog.
export const ENTRY_TYPE_KEYS = ["evenement", "echeance", "rappel", "permanence", "autre"];

// Types qui portent sur un seul jour (pas de date de fin).
export const SINGLE_DAY_TYPES = ["echeance", "rappel"];

export const ENTRY_TYPES = {
  absence: {
    key: "absence",
    kind: "absence",
    label: "Absence",
    pluralLabel: "Absences",
    help: "Période où tu n'es pas disponible",
    icon: UserMinus,
    slug: "absence",
    pillClass: "ag-pill--absence",
    typeClass: "ag-type--absence",
    colors: { bg: "#f7e9e2", line: "#ead6ca", ink: "#945b46" },
    responsableOnly: false,
    remindable: false,
  },
  reunion: {
    key: "reunion",
    kind: "meeting",
    label: "Réunion",
    pluralLabel: "Réunions",
    help: "Réunion staff avec ordre du jour et compte-rendu",
    icon: Users,
    slug: "reunion",
    pillClass: "ag-pill--reunion",
    typeClass: "ag-type--reunion",
    colors: { bg: "#e9eff9", line: "#d9e3f1", ink: "#49658d" },
    responsableOnly: true,
    remindable: true,
  },
  evenement: {
    key: "evenement",
    kind: "entry",
    label: "Événement",
    pluralLabel: "Événements",
    help: "Animation, soirée, temps fort",
    icon: PartyPopper,
    slug: "evenement",
    pillClass: "ag-pill--evenement",
    typeClass: "ag-type--evenement",
    colors: { bg: "#ebdff5", line: "#d5bee7", ink: "#765094" },
    responsableOnly: false,
    remindable: true,
  },
  echeance: {
    key: "echeance",
    kind: "entry",
    label: "Échéance",
    pluralLabel: "Échéances",
    help: "Date limite à ne pas manquer",
    icon: Flag,
    slug: "echeance",
    pillClass: "ag-pill--echeance",
    typeClass: "ag-type--echeance",
    colors: { bg: "#f8e9e8", line: "#efd6d4", ink: "#954c50" },
    responsableOnly: false,
    remindable: true,
  },
  rappel: {
    key: "rappel",
    kind: "entry",
    label: "Rappel",
    pluralLabel: "Rappels",
    help: "Penser à faire quelque chose",
    icon: BellRing,
    slug: "rappel",
    pillClass: "ag-pill--rappel",
    typeClass: "ag-type--rappel",
    colors: { bg: "#fbefd9", line: "#efd2af", ink: "#88672e" },
    responsableOnly: false,
    remindable: true,
  },
  permanence: {
    key: "permanence",
    kind: "entry",
    label: "Permanence",
    pluralLabel: "Permanences",
    help: "Qui est de garde et quand",
    icon: Headset,
    slug: "permanence",
    pillClass: "ag-pill--permanence",
    typeClass: "ag-type--permanence",
    colors: { bg: "#e8efea", line: "#cfddd3", ink: "#4a675c" },
    responsableOnly: false,
    remindable: true,
  },
  autre: {
    key: "autre",
    kind: "entry",
    label: "Autre",
    pluralLabel: "Autres",
    help: "Avec votre propre libellé",
    icon: Tag,
    slug: "autre",
    pillClass: "ag-pill--autre",
    typeClass: "ag-type--autre",
    colors: { bg: "#f0f1ee", line: "#e2e4df", ink: "#64706a" },
    responsableOnly: false,
    remindable: true,
  },
};

// Métadonnées d'un type, avec repli sur « autre » pour une valeur inconnue.
export function typeMeta(type) {
  return ENTRY_TYPES[type] || ENTRY_TYPES.autre;
}

// Libellé affiché d'un élément : libellé libre pour « autre », sinon celui du type.
export function typeLabel(type, customLabel) {
  if (type === "autre" && typeof customLabel === "string" && customLabel.trim()) {
    return customLabel.trim();
  }
  return typeMeta(type).label;
}

export const OFFSET_KEYS = ["J-7", "J-2", "J-1", "H-1"];

export const OFFSETS = [
  { key: "J-7", label: "7 jours avant", shortLabel: "J-7", days: 7, needsTime: false },
  { key: "J-2", label: "2 jours avant", shortLabel: "J-2", days: 2, needsTime: false },
  { key: "J-1", label: "La veille", shortLabel: "J-1", days: 1, needsTime: false },
  { key: "H-1", label: "1 heure avant", shortLabel: "H-1", days: 0, needsTime: true },
];

export const OFFSET_LABELS = Object.fromEntries(OFFSETS.map((offset) => [offset.key, offset.label]));

export const DEFAULT_DAY_REMINDER_TIME = "10:00";

export const DEFAULT_REMINDERS = Object.freeze({
  enabled: true,
  offsets: [...OFFSET_KEYS],
  ping_role: false,
});

export const DISABLED_REMINDERS = Object.freeze({
  enabled: false,
  offsets: [],
  ping_role: false,
});

// Même normalisation que le serveur : doublons retirés, ordre J-7 → H-1, activé sans palier = désactivé.
export function normalizeReminders(value) {
  const source = value && typeof value === "object" ? value : DEFAULT_REMINDERS;
  const requested = Array.isArray(source.offsets) ? source.offsets : [];
  const offsets = OFFSET_KEYS.filter((key) => requested.includes(key));
  return {
    enabled: source.enabled !== false && offsets.length > 0,
    offsets,
    ping_role: Boolean(source.ping_role),
  };
}

// Charge utile `reminders` d'un POST/PATCH (sans `schedule`).
export function remindersPayload(value) {
  const { enabled, offsets, ping_role: pingRole } = normalizeReminders(value);
  return { enabled, offsets, ping_role: pingRole };
}

export const MEETING_PHASE_ORDER = ["a_venir", "a_rediger", "redige", "annulee"];

export const MEETING_PHASES = {
  a_venir: { key: "a_venir", label: "À venir", filterLabel: "À venir", slug: "a-venir", pillClass: "ag-pill--a-venir", phaseClass: "ag-phase--a-venir" },
  a_rediger: { key: "a_rediger", label: "À rédiger", filterLabel: "À rédiger", slug: "a-rediger", pillClass: "ag-pill--a-rediger", phaseClass: "ag-phase--a-rediger" },
  redige: { key: "redige", label: "Rédigé", filterLabel: "Rédigées", slug: "redige", pillClass: "ag-pill--redige", phaseClass: "ag-phase--redige" },
  annulee: { key: "annulee", label: "Annulée", filterLabel: "Annulées", slug: "annulee", pillClass: "ag-pill--annulee", phaseClass: "ag-phase--annulee" },
};

// Filtres de la liste des réunions : `countKey` désigne la clé de `counts` renvoyée par l'API.
export const MEETING_FILTERS = [
  { key: "", label: "Toutes", countKey: "all" },
  { key: "a_venir", label: "À venir", countKey: "a_venir" },
  { key: "a_rediger", label: "À rédiger", countKey: "a_rediger" },
  { key: "redige", label: "Rédigées", countKey: "redige" },
  { key: "annulee", label: "Annulées", countKey: "annulee" },
];

export const ABSENCE_PHASES = {
  en_cours: { key: "en_cours", label: "En cours", slug: "en-cours", pillClass: "ag-pill--en-cours", phaseClass: "ag-phase--en-cours" },
  a_venir: { key: "a_venir", label: "À venir", slug: "a-venir", pillClass: "ag-pill--a-venir", phaseClass: "ag-phase--a-venir" },
  passee: { key: "passee", label: "Passée", slug: "passee", pillClass: "ag-pill--passee", phaseClass: "ag-phase--passee" },
};

export const ATTENDANCE = {
  invite: { key: "invite", label: "Invité" },
  present: { key: "present", label: "Présent" },
  absent: { key: "absent", label: "Absent" },
  excuse: { key: "excuse", label: "Excusé" },
};

// Choix du sélecteur segmenté de présence (Présent · Absent · Excusé).
export const ATTENDANCE_CHOICES = ["present", "absent", "excuse"];

export const REMINDER_STATUSES = {
  pending: { key: "pending", label: "Prévu", tone: "muted", icon: Clock },
  sending: { key: "sending", label: "Envoi en cours", tone: "muted", icon: LoaderCircle },
  sent: { key: "sent", label: "Envoyé", tone: "sage", icon: CircleCheck },
  skipped: { key: "skipped", label: "Ignoré", tone: "muted", icon: CircleMinus },
  failed: { key: "failed", label: "Échec d'envoi", tone: "danger", icon: TriangleAlert },
  cancelled: { key: "cancelled", label: "Annulé", tone: "muted", icon: Ban },
};

export const SKIP_REASON_LABELS = {
  past_at_creation: "Ignoré : déjà passé",
  no_time: "Ignoré : sans heure",
  superseded: "Ignoré : remplacé par un rappel plus proche",
  too_late: "Ignoré : l'élément avait commencé",
  rescheduled: "Annulé : date modifiée",
  disabled: "Annulé : rappel désactivé",
  target_deleted: "Annulé : élément supprimé",
  target_cancelled: "Annulé : réunion annulée",
  invalid_target: "Annulé : élément invalide",
};

// Texte d'une ligne de `reminders.schedule` (heures affichées à l'heure de Paris).
export function reminderStatusText(item) {
  if (!item || typeof item !== "object") return "";
  const status = item.status;
  if (status === "pending") {
    const when = formatInstant(item.due_at);
    return when ? `Prévu le ${when}` : "Prévu";
  }
  if (status === "sending") return "Envoi en cours…";
  if (status === "sent") {
    const when = formatInstant(item.sent_at || item.due_at);
    return when ? `Envoyé le ${when}` : "Envoyé";
  }
  if (status === "failed") return "Échec d'envoi";
  if (status === "skipped" || status === "cancelled") {
    return SKIP_REASON_LABELS[item.skip_reason] || REMINDER_STATUSES[status].label;
  }
  return "";
}

// Métadonnées d'état (icône, ton) d'une ligne de `schedule`.
export function reminderStatusMeta(item) {
  return REMINDER_STATUSES[item?.status] || REMINDER_STATUSES.pending;
}

// « aujourd'hui à 20 h 30 », « demain à 20 h 30 », « le 27 oct. à 20 h 30 » (heure de Paris).
function relativeInstantText(value, today) {
  const day = instantToParisDate(value);
  if (!day) return "";
  const time = formatInstantTime(value);
  if (day === today) return `aujourd'hui à ${time}`;
  if (day === addDaysIso(today, 1)) return `demain à ${time}`;
  return `le ${formatInstant(value)}`;
}

// Version courte d'une ligne de `schedule` : « Rappel J-2 envoyé », « J-1 demain à 20 h 30 »… ou "" (ignoré, annulé).
export function reminderShortText(item, { today } = {}) {
  if (!item || typeof item !== "object") return "";
  const day = resolveToday(today);
  if (item.status === "sent") return `Rappel ${item.offset} envoyé`;
  if (item.status === "pending") {
    const when = relativeInstantText(item.due_at, day);
    return when ? `${item.offset} ${when}` : `${item.offset} prévu`;
  }
  if (item.status === "sending") return `${item.offset} : envoi en cours`;
  if (item.status === "failed") return `${item.offset} : échec d'envoi`;
  return "";
}

// Résumé d'un `schedule` : dernier rappel envoyé puis prochain prévu, « Rappel J-2 envoyé · J-1 demain à 20 h 30 ».
// Chaîne vide s'il n'y a rien à dire (rappels désactivés, tous ignorés).
export function reminderScheduleSummary(schedule, { today } = {}) {
  const rows = (Array.isArray(schedule) ? schedule : [])
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({ item, index, ms: parseInstant(item.due_at) }))
    .sort((a, b) => (a.ms ?? 0) - (b.ms ?? 0) || a.index - b.index)
    .map((row) => row.item);
  const sent = rows.filter((item) => item.status === "sent");
  const next = rows.find((item) => item.status === "pending" || item.status === "sending");
  const failed = rows.filter((item) => item.status === "failed");
  const parts = [];
  if (sent.length) parts.push(reminderShortText(sent[sent.length - 1], { today }));
  if (failed.length && !next) parts.push(reminderShortText(failed[failed.length - 1], { today }));
  if (next) parts.push(reminderShortText(next, { today }));
  return parts.filter(Boolean).join(" · ");
}

// État des réglages Discord (GET /agenda/settings) pour la carte latérale : { key, label, tone, icon }.
export function settingsStatus(settings) {
  if (!settings || typeof settings !== "object") {
    return { key: "unknown", label: "État des rappels inconnu", tone: "muted", icon: BellOff };
  }
  if (settings.disabled_by_env) {
    return { key: "disabled_by_env", label: "Désactivés par la configuration du serveur", tone: "muted", icon: BellOff };
  }
  if (!settings.enabled) return { key: "disabled", label: "Désactivés", tone: "muted", icon: BellOff };
  if (settings.channel_status === "inaccessible") {
    return { key: "inaccessible", label: "Salon inaccessible", tone: "danger", icon: TriangleAlert };
  }
  if (!settings.configured || settings.channel_status === "non_configure") {
    return { key: "not_configured", label: "Non configurés", tone: "muted", icon: BellOff };
  }
  const label = settings.channel_name ? `Actifs dans #${settings.channel_name}` : "Actifs";
  return { key: "active", label, tone: "sage", icon: BellRing };
}

export const AGENDA_VIEWS = ["mois", "semaine", "liste"];

export const VIEW_LABELS = { mois: "Mois", semaine: "Semaine", liste: "Liste" };

export const WEEKDAY_LABELS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

export const MONTH_MAX_LANES = 3;
export const WEEK_MAX_LANES = 4;
export const LIST_DAYS = 60;
export const UPCOMING_DAYS = 60;
export const MAX_FEED_SPAN_DAYS = 189;
// Vue Liste : 190 jours affichés au plus (« Afficher les 60 jours suivants » masqué au-delà).
export const LIST_MAX_DAYS = MAX_FEED_SPAN_DAYS + 1;
export const MOBILE_MAX_DOTS = 4;
export const OPEN_END_DISPLAY_DAYS = 6;
export const ABSENCE_UPCOMING_LIMIT = 8;
export const MEETINGS_PAGE_SIZE = 50;
export const SEARCH_DEBOUNCE_MS = 300;
export const AGENDA_STALE_TIME = 30_000;

export const DATE_LIMITS = {
  pastDays: 366,
  futureDays: 731,
  absenceMaxDays: 366,
  entryMaxDays: 92,
};

export const TEXT_LIMITS = {
  title: 160,
  customLabel: 40,
  description: 2000,
  location: 200,
  reason: 500,
  agendaItem: 200,
  decision: 500,
  action: 300,
  cancelReason: 300,
  search: 100,
  listItems: 50,
  participants: 50,
};

export const FILTERS_STORAGE_KEY = "iris.agenda.filters";

export const DEFAULT_FILTERS = Object.freeze({
  types: [...TYPE_ORDER],
  onlyMine: false,
});

export const MEETING_DRAFT_STORAGE_PREFIX = "iris.meeting-draft.";
