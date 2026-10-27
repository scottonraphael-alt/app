export const GENERIC_ERROR_MESSAGE = "Une erreur est survenue. Réessayez.";
export const INVALID_FIELDS_MESSAGE = "Certains champs sont invalides.";
export const LOCKED_MESSAGE = "Ce résumé est verrouillé.";

export function errorStatus(error) {
  const status = error?.response?.status;
  return typeof status === "number" ? status : null;
}

function errorDetail(error) {
  return error?.response?.data?.detail;
}

// Message affichable : `detail` texte du serveur, « Certains champs sont invalides. » pour une erreur
// de structure Pydantic (liste), sinon le message générique.
export function agendaErrorMessage(error, fallback = GENERIC_ERROR_MESSAGE) {
  const detail = errorDetail(error);
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) return INVALID_FIELDS_MESSAGE;
  return fallback;
}

export function isRevisionConflict(error) {
  return errorStatus(error) === 409 && error?.response?.data?.code === "revision_conflict";
}

// Détails du 409 de révision, ou null.
export function revisionConflictInfo(error) {
  if (!isRevisionConflict(error)) return null;
  const data = error.response.data;
  return {
    message: agendaErrorMessage(error),
    currentRevision: typeof data.current_revision === "number" ? data.current_revision : null,
    updatedAt: data.updated_at || null,
    updatedBy: data.updated_by || null,
  };
}

export function isCancelledRequest(error) {
  return error?.code === "ERR_CANCELED" || error?.name === "CanceledError" || error?.name === "AbortError";
}

// Pas de réponse du serveur (réseau coupé, délai dépassé), hors annulation volontaire.
export function isNetworkError(error) {
  return Boolean(error) && !error.response && !isCancelledRequest(error);
}

export function isUnauthorized(error) {
  return errorStatus(error) === 401;
}

export function isForbidden(error) {
  return errorStatus(error) === 403;
}

export function isNotFound(error) {
  return errorStatus(error) === 404;
}

export function isValidationError(error) {
  return errorStatus(error) === 422;
}

// 403 « Ce résumé est verrouillé. » (verrouillage pendant la rédaction).
export function isLockedError(error) {
  return isForbidden(error) && errorDetail(error) === LOCKED_MESSAGE;
}

// Erreur passagère : réseau, 429 ou 5xx (dont la 503 « Liste du staff indisponible »).
export function isRetryableError(error) {
  if (isCancelledRequest(error)) return false;
  if (isNetworkError(error)) return true;
  const status = errorStatus(error);
  return status === 429 || (status !== null && status >= 500);
}

// Politique `retry` de React Query : jamais pour 4xx, deux essais au plus pour une erreur passagère.
export function shouldRetryAgendaQuery(failureCount, error) {
  return failureCount < 2 && isRetryableError(error) && errorStatus(error) !== 429;
}

const normalizeQuotes = (text) => text.replace(/[’‘]/g, "'");

// Début du message d'erreur du serveur → champ du formulaire concerné.
const FIELD_RULES = [
  ["Indiquez un libellé pour ce type", "custom_label"],
  ["Une entrée sur la journée n'a pas d'heure", "start_time"],
  ["Indiquez une heure de début", "start_time"],
  ["L'heure de fin doit suivre l'heure de début", "end_time"],
  ["La date de fin doit suivre la date de début", "end_date"],
  ["Une entrée ne peut pas dépasser 3 mois", "end_date"],
  ["Une absence ne peut pas dépasser un an", "end_date"],
  ["Une échéance ou un rappel porte sur un seul jour", "end_date"],
  ["Indiquez une date de fin ou cochez", "end_date"],
  ["Une absence sans date de fin ne peut pas avoir de date de fin", "end_date"],
  ["Date de début hors limites", "start_date"],
  ["Date hors limites", "start_date"],
  ["Participant inconnu", "participant_ids"],
  ["Seul un responsable peut activer la mention du rôle", "reminders"],
  ["Membre introuvable parmi le staff", "helper_id"],
  ["Seul un responsable peut déclarer l'absence d'un autre membre", "helper_id"],
  ["L'absence n'a pas encore commencé", "return_date"],
  ["La date de retour ne peut pas être dans le futur", "return_date"],
  ["Salon introuvable ou hors du serveur", "channel_id"],
  ["Choisissez un salon textuel", "channel_id"],
  ["Contenu illisible", "content_markdown"],
  ["Période invalide", "range"],
];

const REQUIRED_FIELD_LABELS = {
  titre: "title",
  type: "type",
  "date de début": "start_date",
  date: "meeting_date",
  "toute la journée": "all_day",
  "fin indéterminée": "open_ended",
  annulation: "cancelled",
  rappels: "reminders",
  révision: "expected_revision",
};

// Champ concerné par un message d'erreur du serveur (pour l'afficher sous ce champ), ou null.
export function errorFieldFromMessage(message) {
  if (typeof message !== "string" || !message) return null;
  const text = normalizeQuotes(message);
  const required = /^Champ obligatoire : (.+?)\.?$/.exec(text);
  if (required) return REQUIRED_FIELD_LABELS[required[1].trim()] || null;
  const rule = FIELD_RULES.find(([prefix]) => text.startsWith(normalizeQuotes(prefix)));
  return rule ? rule[1] : null;
}

// { field, message } pour une erreur de formulaire : `field` vaut null quand on ne peut pas le déduire
// (afficher alors le message en bandeau).
export function splitAgendaError(error) {
  const message = agendaErrorMessage(error);
  const field = isValidationError(error) || isForbidden(error) || isNotFound(error) || errorStatus(error) === 409
    ? errorFieldFromMessage(message)
    : null;
  return { field, message };
}
