import { sanctionTypeMeta } from "../casierConstants";

export const ACTION_LABELS = {
  created: "Création",
  updated: "Modification",
  deleted: "Suppression",
  note_added: "Information ajoutée",
  note_updated: "Information modifiée",
  note_deleted: "Information supprimée",
  closed: "Clôture",
  revert: "Annulation",
};

export const ENTITY_LABELS = { casier: "Casier", sanction: "Sanction", fiche: "Fiche S" };

const FIELD_LABELS = {
  statut: "Statut",
  status: "Statut",
  type: "Type",
  reason: "Motif",
  duration: "Durée",
  permanent: "Permanent",
  until: "Jusqu'au",
  title: "Titre",
  content: "Contenu",
  active: "Active",
  is_prevention: "Casier de prévention",
  discord_id: "ID Discord",
  notes: "Informations",
  created_at: "Créée le",
  closed_at: "Clôturée le",
  attachments: "Pièces jointes",
};

const STATUS_LABELS = {
  vierge: "Vierge",
  averti: "Averti",
  mute: "Mute",
  kick: "Kick",
  banni: "Banni",
};

// « notes[abc].content » → « Informations · content » ; champ inconnu : affiché tel quel.
export function fieldLabel(field) {
  const text = String(field || "");
  const match = text.match(/^([^[.]+)(?:\[[^\]]*\])?(?:\.(.+))?$/);
  if (!match) return text;
  const head = FIELD_LABELS[match[1]] || match[1];
  const tail = match[2] ? (FIELD_LABELS[match[2]] || match[2]) : "";
  return tail ? `${head} · ${tail}` : head;
}

export function displayValue(field, value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Oui" : "Non";
  const key = String(field || "");
  if (key === "statut" || key === "status") return STATUS_LABELS[value] || String(value);
  if (key === "type" || key.endsWith(".type")) return sanctionTypeMeta(String(value)).label;
  return String(value);
}
