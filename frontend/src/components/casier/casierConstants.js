import { Ban, DoorOpen, MegaphoneOff, MicOff, Shield, TriangleAlert } from "lucide-react";

/* ---------------------------------- */
/* Sanctions                          */
/* ---------------------------------- */

export const REMINDER_TYPE = "rappel_a_lordre";

// Ordre d'affichage (grille de la modale, résumés) ; `tone` = suffixe de la pastille `.cz-pill--<tone>`.
export const SANCTION_TYPES = [
  {
    value: "avertissement",
    label: "Avertissement",
    short: "avert.",
    shortPlural: "avert.",
    status: "averti",
    tone: "averti",
    icon: TriangleAlert,
    hasDuration: false,
    allowPermanent: false,
    hint: null,
  },
  {
    value: "mute",
    label: "Mute",
    short: "mute",
    shortPlural: "mutes",
    status: "mute",
    tone: "mute",
    icon: MicOff,
    hasDuration: true,
    allowPermanent: false,
    hint: null,
  },
  {
    value: "kick",
    label: "Kick",
    short: "kick",
    shortPlural: "kicks",
    status: "kick",
    tone: "kick",
    icon: DoorOpen,
    hasDuration: false,
    allowPermanent: false,
    hint: null,
  },
  {
    value: "bannissement",
    label: "Bannissement",
    short: "ban",
    shortPlural: "bans",
    status: "banni",
    tone: "banni",
    icon: Ban,
    hasDuration: true,
    allowPermanent: true,
    hint: null,
  },
  {
    value: REMINDER_TYPE,
    label: "Rappel à l'ordre",
    short: "rappel",
    shortPlural: "rappels",
    status: null,
    tone: "rappel",
    icon: MegaphoneOff,
    hasDuration: false,
    allowPermanent: false,
    hint: "sans effet sur le statut",
  },
];

export const SANCTION_TYPE_META = Object.fromEntries(SANCTION_TYPES.map((item) => [item.value, item]));

// Type inconnu (ancien document, futur type) : affiché tel quel, sans effet sur le statut.
export function sanctionTypeMeta(type) {
  if (type && SANCTION_TYPE_META[type]) return SANCTION_TYPE_META[type];
  return {
    value: type || "",
    label: type || "Sanction",
    short: type || "sanction",
    shortPlural: type || "sanctions",
    status: null,
    tone: "rappel",
    icon: Shield,
    hasDuration: false,
    allowPermanent: false,
    hint: null,
  };
}

export function typeHasDuration(type) {
  return Boolean(SANCTION_TYPE_META[type]?.hasDuration);
}

// Valeurs envoyées telles quelles dans `duration` (comprises par parse_duration_text côté serveur).
export const DURATION_PRESETS = [
  { value: "10 min", label: "10 min" },
  { value: "1 h", label: "1 h" },
  { value: "24 h", label: "24 h" },
  { value: "7 jours", label: "7 jours" },
];

export const PERMANENT_DURATION = { value: "permanent", label: "Permanent" };

export function durationPresetsFor(type) {
  const meta = SANCTION_TYPE_META[type];
  if (!meta?.hasDuration) return [];
  return meta.allowPermanent ? [...DURATION_PRESETS, PERMANENT_DURATION] : DURATION_PRESETS;
}

export const TIMELINE_FILTERS = [
  { value: "tout", label: "Tout" },
  { value: "sanctions", label: "Sanctions" },
  { value: "rappels", label: "Rappels à l'ordre" },
];

export const ORIGIN_LABELS = {
  discord_log: "Log Discord",
  manual: "Ajout manuel",
};

// Auteur des sanctions importées depuis les logs OasisBot (BOT_AUTHOR côté serveur).
export const BOT_AUTHOR_USERNAME = "bot";
export const BOT_DISPLAY_LABEL = "OasisBot";

/* ---------------------------------- */
/* Statut = pire sanction reçue       */
/* ---------------------------------- */

export const STATUS_ORDER = ["vierge", "averti", "mute", "kick", "banni"];

export const STATUS_META = {
  vierge: { value: "vierge", label: "Vierge", rank: 0, tone: "vierge" },
  averti: { value: "averti", label: "Averti", rank: 1, tone: "averti" },
  mute: { value: "mute", label: "Mute", rank: 2, tone: "mute" },
  kick: { value: "kick", label: "Kick", rank: 3, tone: "kick" },
  banni: { value: "banni", label: "Banni", rank: 4, tone: "banni" },
};

// Puces de filtre, du plus grave au moins grave.
export const STATUS_FILTERS = [...STATUS_ORDER].reverse().map((value) => STATUS_META[value]);

export const TYPE_TO_STATUS = {
  avertissement: "averti",
  mute: "mute",
  kick: "kick",
  bannissement: "banni",
};

// Anciennes valeurs (avant la refonte) : seulement pour un affichage lisible si l'API en renvoie encore.
const LEGACY_STATUS_LABELS = {
  bloque: "Banni",
  sanctionne: "Sanctionné",
  surveillance: "Surveillance",
  vigilance: "Vigilance",
};

export function statusMeta(status) {
  if (status && STATUS_META[status]) return STATUS_META[status];
  return {
    value: status || "",
    label: LEGACY_STATUS_LABELS[status] || status || "Inconnu",
    rank: 0,
    tone: "rappel",
  };
}

// Statut après ajout d'une sanction de ce type (aperçu de la modale, même règle que le serveur).
export function projectedStatus(currentStatus, sanctionType) {
  const current = STATUS_META[currentStatus] ? currentStatus : "vierge";
  const target = TYPE_TO_STATUS[sanctionType];
  if (!target) return current;
  return STATUS_META[target].rank > STATUS_META[current].rank ? target : current;
}

/* ---------------------------------- */
/* Recherche et liste                 */
/* ---------------------------------- */

export const SEARCH_SCOPES = [
  { value: "tout", label: "Tout" },
  { value: "membre", label: "Membre" },
  { value: "staff", label: "Staff" },
  { value: "contenu", label: "Contenu" },
];

export const DEFAULT_SCOPE = "tout";

export const SORT_OPTIONS = [
  { value: "recent", label: "Activité récente" },
  { value: "gravite", label: "Gravité" },
  { value: "nom", label: "Nom" },
];

export const DEFAULT_SORT = "recent";

// Bascules de la barre de recherche : activée → `true`, désactivée → paramètre absent (jamais `false`).
export const CASIER_TOGGLE_FILTERS = [
  { key: "has_active_fiche_s", label: "Fiche S active" },
  { key: "prevention", label: "Prévention" },
  { key: "has_open_ai_flags", label: "Signalements à traiter" },
];

export const SEARCH_MAX_LENGTH = 100;
export const SEARCH_MAX_TERMS = 5;
export const SEARCH_DEBOUNCE_MS = 300;
export const CASIER_LIST_PAGE_SIZE = 150;
export const LIST_MATCHES_SHOWN = 2;

export const MEMBER_SEARCH_MIN_LENGTH = 2;
export const MEMBER_SEARCH_DEBOUNCE_MS = 250;

/* ---------------------------------- */
/* Paramètres d'URL de la page        */
/* ---------------------------------- */

export const CASIER_PAGE_PATH = "/moderation/casiers";

export const CASIER_VIEWS = { casiers: "casiers", signalements: "signalements" };
export const DEFAULT_VIEW = "casiers";

export const DETAIL_TABS = ["historique", "fiches", "signalements"];
export const DEFAULT_DETAIL_TAB = "historique";

/* ---------------------------------- */
/* Fichiers                           */
/* ---------------------------------- */

export const UPLOAD_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "pdf", "txt"];
export const UPLOAD_ACCEPT = UPLOAD_EXTENSIONS.map((ext) => `.${ext}`).join(",");
// Indicatif (le serveur fait foi : CASIER_UPLOAD_MAX_BYTES).
export const UPLOAD_MAX_BYTES = 10 * 1024 * 1024;
export const LOG_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024;
export const MAX_ATTACHMENTS_PER_SANCTION = 10;

export const ATTACHMENT_STATUS_META = {
  pending: { label: "Copie en cours…", tone: "pending" },
  stored: { label: "Disponible", tone: "stored" },
  failed: { label: "Copie impossible", tone: "failed" },
  too_large: { label: "Trop volumineux (25 Mo max)", tone: "too_large" },
};

// Sonde du détail tant qu'un fichier est `pending` : toutes les 4 s, arrêt après 2 min.
export const PENDING_POLL_INTERVAL_MS = 4000;
export const PENDING_POLL_MAX_MS = 2 * 60 * 1000;

/* ---------------------------------- */
/* Limites de saisie (miroir de l'API)*/
/* ---------------------------------- */

export const REASON_MAX_LENGTH = 1000;
export const DURATION_MAX_LENGTH = 80;
export const NOTE_MAX_LENGTH = 4000;
export const FICHE_TITLE_MAX_LENGTH = 160;
export const FICHE_CONTENT_MAX_LENGTH = 200000;
export const REVIEW_COMMENT_MAX_LENGTH = 500;

/* ---------------------------------- */
/* Fiches S                           */
/* ---------------------------------- */

export const FICHE_EDITOR_PLACEHOLDER = "Faits observés, contexte, raisons du suivi… Tapez / pour les commandes.";
export const FICHE_DRAFT_PREFIX = "iris.casier.fiche.";
export const FICHE_DRAFT_SAVE_INTERVAL_MS = 2000;

/* ---------------------------------- */
/* Signalements IA                    */
/* ---------------------------------- */

export const AI_CATEGORY_LABELS = {
  insulte: "Insulte",
  harcelement: "Harcèlement",
  haine: "Haine",
  menace: "Menace",
  sexuel: "Contenu sexuel",
  spam: "Spam",
  donnees_personnelles: "Données personnelles",
  arnaque: "Arnaque",
  contournement: "Contournement",
  autre: "Autre",
  aucune: "Aucune",
};

export const AI_CATEGORY_OPTIONS = Object.entries(AI_CATEGORY_LABELS).map(([value, label]) => ({ value, label }));

export function aiCategoryLabel(category) {
  if (!category) return "Non classé";
  return AI_CATEGORY_LABELS[category] || String(category).replace(/_/g, " ");
}

export const REVIEW_META = {
  a_traiter: { value: "a_traiter", label: "À traiter", tone: "review-a_traiter" },
  pertinent: { value: "pertinent", label: "Pertinent", tone: "review-pertinent" },
  faux_positif: { value: "faux_positif", label: "Faux positif", tone: "review-faux_positif" },
};

export function reviewMeta(status) {
  return REVIEW_META[status] || REVIEW_META.a_traiter;
}

// `countKey` : clé de `counts` dans la réponse de GET /ai-flags.
export const REVIEW_FILTERS = [
  { value: "a_traiter", label: "À traiter", countKey: "a_traiter" },
  { value: "pertinent", label: "Pertinents", countKey: "pertinent" },
  { value: "faux_positif", label: "Faux positifs", countKey: "faux_positif" },
  { value: "tous", label: "Tous", countKey: "total" },
];

export const DEFAULT_REVIEW_FILTER = "a_traiter";

export const KIND_LABELS = {
  violation: "Violation",
  refus: "Refus du modèle",
  illisible: "Analyse illisible",
};

export function kindLabel(kind) {
  return KIND_LABELS[kind] || kind || "Signalement";
}

// Valeur vide = pas de filtre.
export const KIND_FILTERS = [
  { value: "", label: "Tous" },
  { value: "violation", label: "Violations" },
  { value: "refus", label: "Refus du modèle" },
  { value: "illisible", label: "Analyses illisibles" },
];

// `null` = toutes les gravités.
export const GRAVITY_FILTERS = [
  { value: null, label: "Toutes" },
  { value: 1, label: "1" },
  { value: 2, label: "2" },
  { value: 3, label: "3" },
];

export const GRAVITY_MAX = 3;

// Suffixe de pastille / barre latérale de la carte (`ia-1` or, `ia-2` argile, `ia-3` rouge).
export function gravityTone(gravity) {
  const value = Number(gravity);
  if (!Number.isFinite(value) || value < 1) return "ia-0";
  return `ia-${Math.min(GRAVITY_MAX, Math.round(value))}`;
}

export const PLANNED_ACTION_LABELS = {
  delete: "Suppression du message",
  timeout: "Timeout",
  alert: "Alerte au staff",
};

export const MODE_LABELS = {
  log: "Journalisation seule",
  act: "Action automatique",
};

export const AI_FLAGS_PAGE_SIZE = 30;

/* ---------------------------------- */
/* Journal auth_logs (casier.*)       */
/* ---------------------------------- */

// Réutilisé par ResponsableAuthLogsPage (libellés, groupe « Casiers » du filtre).
export const CASIER_EVENT_LABELS = {
  "casier.access.management.viewed": "Accès de modération consultés",
  "casier.access.management.failed": "Gestion des accès refusée ou échouée",
  "casier.access.updated": "Code personnel de modération défini ou remplacé",
  "casier.access.revoked": "Accès personnel de modération révoqué",
  "casier.access.granted": "Accès au panel de sanction autorisé",
  "casier.access.failed": "Code personnel incorrect",
  "casier.access.locked": "Tentatives d’accès temporairement bloquées",
  "casier.command.history.viewed": "Historique des sanctions consulté dans Discord",

  "casier.command.opened": "Commande /sanction ouverte",
  "casier.command.member.selected": "Membre sélectionné pour une sanction",
  "casier.command.member.changed": "Sélection du membre changée",
  "casier.command.type.selected": "Type de sanction sélectionné",
  "casier.command.modal.submitted": "Sanction préparée dans Discord",
  "casier.command.evidence.uploaded": "Justificatif de sanction enregistré sur Iris",
  "casier.command.confirmed": "Application de sanction confirmée",
  "casier.command.cancelled": "Parcours de sanction annulé",
  "casier.command.expired": "Préparation de sanction expirée",
  "casier.command.view.expired": "Parcours privé de sanction expiré",
  "casier.command.denied": "Commande de sanction refusée",
  "casier.command.failed": "Exécution de sanction interrompue ou à vérifier",
  "casier.command.discord.applied": "Action de modération confirmée par Discord",
  "casier.command.reconciled": "Bannissement confirmé après vérification",
  "casier.command.ban.released": "Fin de bannissement temporaire traitée",
  "casier.command.role.granted": "Rôle temporaire de sanction attribué",
  "casier.command.role.revoked": "Rôle temporaire de sanction retiré",
  "casier.command.role.failed": "Retrait du rôle temporaire à reprendre",
  "casier.command.notification.sent": "Notification de sanction envoyée par MP",
  "casier.command.notification.failed": "Notification de sanction non remise ou à vérifier",
  "casier.command.notification.corrected": "Notification MP corrigée après refus de sanction",
  "casier.command.log.sent": "Log de sanction publié sur Discord",
  "casier.command.log.failed": "Publication du log de sanction à reprendre",

  "casier.created": "Casier créé",
  "casier.sanction.created": "Sanction ajoutée",
  "casier.sanction.note.created": "Information ajoutée",
  "casier.sanction.note.updated": "Information modifiée",
  "casier.sanction.note.deleted": "Information supprimée",
  "casier.sanction.attachment.uploaded": "Fichier ajouté",
  "casier.sanction.attachment.deleted": "Fichier retiré",
  "casier.sanction.attachments.resynced": "Fichiers du log récupérés",
  "casier.fiche_s.created": "Fiche S rédigée",
  "casier.fiche_s.updated": "Fiche S modifiée",
  "casier.fiche_s.closed": "Fiche S clôturée",
  "casier.ai_flag.reviewed": "Signalement IA traité",
};

export const CASIER_EVENT_TYPES = Object.keys(CASIER_EVENT_LABELS);

export function isCasierEvent(eventType) {
  return typeof eventType === "string" && eventType.startsWith("casier.");
}

// Classe de badge de la page des logs : status-done | status-pending | status-bad | "".
export function casierEventTone(eventType) {
  if (!isCasierEvent(eventType)) return "";
  if (/\.(created|uploaded|resynced)$/.test(eventType)) return "status-done";
  if (/\.(updated|closed|reviewed)$/.test(eventType)) return "status-pending";
  if (/\.(deleted|failed|denied|locked)$/.test(eventType)) return "status-bad";
  return "";
}
