import { ANNOUNCEMENT_AUDIT_LABELS, announcementLogSummary } from '../components/announcements/auditLabels';
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowRight,
  ChevronRight,
  Download,
  FileText,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Shield,
} from "lucide-react";

import { api, getErrorMessage } from "../api/client";
import { PROJECT_AUDIT_LABELS, projectLogSummary } from "../components/projects/projectLogSummary";
import {
  CASIER_EVENT_LABELS,
  casierEventTone,
  isCasierEvent,
  reviewMeta,
  sanctionTypeMeta,
  statusMeta,
} from "../components/casier/casierConstants";
import { casierLogLink, formatBytes } from "../components/casier/formatters";

import "@/Casier.css";
import "@/ResponsableAuthLogs.css";

/* ---------------------------------- */
/* Constantes                         */
/* ---------------------------------- */

const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;
const TIME_ZONE = "Europe/Paris";

// Clés acceptées par `categories` côté API (routers/responsable.py).
const CATEGORIES = [
  {
    key: "connexions",
    label: "Connexions",
    hint: "Connexions, déconnexions et sessions",
  },
  {
    key: "acces_refuses",
    label: "Accès refusés",
    hint: "Accès refusés et connexions échouées",
  },
  { key: "casiers", label: "Casiers", hint: "Modifications de casiers" },
  { key: "annonces", label: "Annonces", hint: "Composition, fichiers, publications et programmations Discord" },
  { key: "projets", label: "Projets", hint: "Projets, tâches et ressources" },
  { key: "tickets", label: "Tickets", hint: "Consultations, recherches et actions manuelles sur les suivis" },
  { key: "autres", label: "Autres", hint: "Tous les autres événements" },
];

const PERIODS = [
  { key: "today", label: "Aujourd’hui", days: 1 },
  { key: "7d", label: "7 jours", days: 7 },
  { key: "30d", label: "30 jours", days: 30 },
  { key: "all", label: "Tout", days: null },
];

const DEFAULT_PERIOD = "7d";

const SUMMARY_ITEMS = [
  { key: "access_denied", label: "Accès refusés", alert: true },
  { key: "login_success", label: "Connexions réussies" },
  { key: "login_failure", label: "Connexions échouées" },
  { key: "casier_changes", label: "Modifications de casiers" },
];

const AGENDA_EVENT_LABELS = {
  "agenda.settings.updated": "Agenda : réglages des rappels modifiés",
  "agenda.settings.test_sent": "Agenda : message de test envoyé",
};

const TICKET_EVENT_LABELS = {
  "ticket.ui.coordination.filter_changed": "Filtre des attributions modifié", "ticket.ui.coordination.ticket_selected": "Dossier sélectionné pour attribution",
  "ticket.ui.coordination.helper_selected": "Interlocuteur sélectionné", "ticket.ui.coordination.search_submitted": "Recherche dans les attributions",
  "ticket.ui.archives.filter_changed": "Filtre des archives modifié", "ticket.ui.archives.search_submitted": "Recherche dans les archives",
  "ticket.ui.workspace.mobile_view_changed": "Vue mobile du dossier changée", "ticket.ui.search.opened": "Recherche ouverte",
  "ticket.archived": "Dossier archivé", "ticket.reactivated": "Dossier réactivé",
  "ticket.created": "Ticket importé manuellement", "ticket.viewed": "Dossier ouvert et suivi actualisé",
  "ticket.updated": "Dossier modifié", "ticket.deleted": "Dossier supprimé",
  "ticket.note.created": "Note ajoutée", "ticket.note.deleted": "Note supprimée",
  "ticket.assignment.changed": "Interlocuteur modifié", "ticket.sync.completed": "Synchronisation manuelle",
  "ticket.ai_summary.requested": "Synthèse IA demandée", "ticket.ai_summary.completed": "Synthèse IA enregistrée",
  "ticket.ai_summary.failed": "Synthèse IA échouée", "ticket.search": "Recherche dans la conversation",
  "ticket.reminder.test_sent": "Test du rappel Discord envoyé",
  "ticket.ui.list.viewed": "Liste des suivis consultée", "ticket.ui.list.filter_changed": "Filtre des suivis modifié",
  "ticket.ui.list.search_submitted": "Recherche dans la liste des suivis",
  "ticket.ui.archives.viewed": "Archives des suivis consultées", "ticket.ui.coordination.viewed": "Attributions consultées",
  "ticket.ui.workspace.tab_changed": "Onglet du dossier consulté", "ticket.ui.messages.page_changed": "Page de messages consultée",
  "ticket.ui.note.composer_opened": "Rédaction de note ouverte", "ticket.ui.note.composer_closed": "Rédaction de note fermée",
  "ticket.ui.attachment.opened": "Pièce jointe ouverte", "ticket.ui.search.closed": "Recherche fermée",
  "ticket.ui.search.result_opened": "Résultat de recherche ouvert",
};

const EVENT_LABELS = {
  ...ANNOUNCEMENT_AUDIT_LABELS,
  ...PROJECT_AUDIT_LABELS,
  "auth.login.started": "Connexion démarrée",
  "auth.login.success": "Connexion réussie",
  "auth.login.failure": "Connexion échouée",
  "auth.logout": "Déconnexion",
  "auth.session.invalid": "Session invalide",
  "auth.session.check_failed": "Vérification session échouée",
  "authz.forbidden": "Accès refusé",

  "project.settings.updated": "Paramètres du projet modifiés",
  "project.task.updated": "Tâche mise à jour",
  "project.member.removed": "Membre retiré du projet",
  "project.comment.added": "Note publiée dans le journal du projet",
  "project.viewed": "Projet consulté",
  "project.created": "Projet créé",
  "project.details.updated": "Projet modifié",
  "project.content.updated": "Projet modifié",
  "project.deleted": "Projet supprimé",
  "project.member.added": "Membre ajouté",
  "project.task.created": "Tâche créée",
  "project.task.submitted": "Tâche rendue",
  "project.task.validated": "Tâche validée",
  "project.task.deleted": "Tâche supprimée",
  "project.resource.uploaded": "Ressource ajoutée",
  "project.resource.deleted": "Ressource supprimée",

  ...TICKET_EVENT_LABELS,
  ...CASIER_EVENT_LABELS,
  ...AGENDA_EVENT_LABELS,
};

// Motifs techniques consignés dans `details.reason`.
const REASON_LABELS = {
  role_removed_or_not_allowed: "rôle insuffisant",
  ticket_access_requires_helper_or_responsable: "rôle Helper ou Responsable requis",
  missing_or_invalid_session: "session absente ou invalide",
  invalid_or_expired_cookie: "session invalide ou expirée",
  invalid_oauth_state: "état de connexion invalide",
  missing_oauth_state_cookie: "cookie de connexion manquant",
};

const PROJECT_CHANGE_LABELS = [
  ["title_changed", "titre"],
  ["description_changed", "description"],
  ["content_changed", "contenu"],
  ["end_date_changed", "échéance"],
  ["status_changed", "statut"],
];

/* ---------------------------------- */
/* Dates                              */
/* ---------------------------------- */

// L’API renvoie des dates UTC ; sans « Z » le navigateur les lirait en heure locale.
function parseDate(value) {
  if (!value) return null;

  const text = String(value);
  const date = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text}Z`);

  return Number.isNaN(date.getTime()) ? null : date;
}

// Jour calendaire courant à Paris, « AAAA-MM-JJ ».
function parisToday() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: TIME_ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(new Date())
      .map((part) => [part.type, part.value]),
  );

  return `${parts.year}-${parts.month}-${parts.day}`;
}

function shiftDay(day, delta) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + delta);

  return date.toISOString().slice(0, 10);
}

// Une saisie de date incomplète (« 0002-10-26 » en cours de frappe) n’est pas envoyée.
function usableDay(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || "") && Number(value.slice(0, 4)) >= 2000;
}

function relativeTime(date, now) {
  const seconds = Math.floor((now - date.getTime()) / 1000);

  if (seconds < 45) return "à l’instant";

  const minutes = Math.max(1, Math.floor(seconds / 60));
  if (minutes < 60) return `il y a ${minutes} min`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;

  const days = Math.floor(hours / 24);
  if (days < 7) return `il y a ${days} j`;

  return date.toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: TIME_ZONE,
  });
}

function exactDate(date) {
  return date.toLocaleString("fr-FR", {
    dateStyle: "full",
    timeStyle: "medium",
    timeZone: TIME_ZONE,
  });
}

function shortDate(date) {
  return date.toLocaleString("fr-FR", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: TIME_ZONE,
  });
}

function useNow(intervalMs) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);

    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}

/* ---------------------------------- */
/* Requête API                        */
/* ---------------------------------- */

function buildParams({ search, categories, period, dateFrom, dateTo }, skip) {
  const params = { skip, limit: PAGE_SIZE };

  if (search) params.q = search;
  if (categories) params.categories = categories;

  let from = "";
  let to = "";

  if (period === "custom") {
    from = usableDay(dateFrom) ? dateFrom : "";
    to = usableDay(dateTo) ? dateTo : "";
    if (from && to && from > to) [from, to] = [to, from];
  } else {
    const preset = PERIODS.find((item) => item.key === period);
    if (preset?.days) from = shiftDay(parisToday(), 1 - preset.days);
  }

  if (from) params.date_from = from;
  if (to) params.date_to = to;

  return params;
}

/* ---------------------------------- */
/* Phrases                            */
/* ---------------------------------- */

const strong = (text) => ({ strong: text });
const muted = (text) => ({ muted: text });
const quote = (text) => `« ${text} »`;

const VOWEL_START = /^[aeiouyàâäéèêëîïôöùûüœ]/i;

// « de pixel_renard » / « d’Inès ».
const of = (name) => [VOWEL_START.test(name) ? "d’" : "de ", strong(name)];

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function humanize(type) {
  const text = String(type || "").replace(/[._]+/g, " ").trim();

  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Événement inconnu";
}

function partsText(parts) {
  return parts
    .map((part) =>
      typeof part === "string" ? part : (part.strong ?? part.muted ?? ""),
    )
    .join("");
}

function lengthText(count) {
  return `${count} caractère${Number(count) > 1 ? "s" : ""}`;
}

// Lignes secondaires sous la phrase (motif, statut, fichiers…).
function buildExtras(details) {
  const d = details;
  const extras = [];

  if (d.reason_excerpt) extras.push(["Motif", d.reason_excerpt]);

  if (d.status_before && d.status_after && d.status_before !== d.status_after) {
    extras.push([
      "Statut",
      `${statusMeta(d.status_before).label} → ${statusMeta(d.status_after).label}`,
    ]);
  }

  if (d.review_before && d.review_after && d.review_before !== d.review_after) {
    extras.push([
      "Revue",
      `${reviewMeta(d.review_before).label} → ${reviewMeta(d.review_after).label}`,
    ]);
  }

  if (d.files_found !== undefined || d.files_queued !== undefined) {
    extras.push([
      "Fichiers",
      `${d.files_found ?? 0} trouvé${Number(d.files_found) > 1 ? "s" : ""} · ${d.files_queued ?? 0} en copie`,
    ]);
  }

  const size = formatBytes(d.size);
  if (size) extras.push(["Taille", size]);

  const before = d.before_length ?? d.before?.content_length;
  const after = d.after_length ?? d.after?.content_length;

  if (before !== undefined || after !== undefined) {
    extras.push(["Contenu", `${before ?? 0} → ${after ?? 0} caractères`]);
  } else if (d.content_length !== undefined) {
    extras.push(["Contenu", lengthText(d.content_length)]);
  }

  if (d.comment_length > 0) {
    extras.push(["Commentaire", lengthText(d.comment_length)]);
  }

  return extras;
}

// Phrase française construite depuis event_type + details.
// `parts` = textes, { strong } (noms) et { muted } (précisions discrètes).
function describeEvent(log) {
  const type = log.event_type || "";
  const d = isPlainObject(log.details) ? log.details : {};

  const actor = log.username ? strong(log.username) : "Un utilisateur";
  const by = log.username ? [muted(` · ${log.username}`)] : [];

  const reason = d.reason
    ? REASON_LABELS[d.reason] || String(d.reason)
    : "";
  const reasonSuffix = reason ? ` : ${reason}` : "";

  const member = d.member_username || d.member_id || "";
  const casier = member ? ["casier ", ...of(member)] : ["casier d’un membre"];
  const forMember = member ? [" pour ", strong(member)] : [];

  const title = d.title || d.after?.title || d.before?.title || "";
  const project = title ? ["le projet ", quote(title)] : ["un projet"];

  const file = d.original_filename ? [" ", quote(d.original_filename)] : [];
  const fiche = d.fiche_title
    ? ["la fiche S ", quote(d.fiche_title)]
    : ["une fiche S"];

  if (type.startsWith("ticket.")) {
    const failed = type.endsWith(".failed");
    const label = TICKET_EVENT_LABELS[type] || (failed ? `${TICKET_EVENT_LABELS[type.slice(0, -7)] || "Action sur le ticket"} : échec` : humanize(type));
    const extras = [];
    if (d.ticket_id) extras.push(["Dossier", d.ticket_id]);
    if (d.fields?.length) extras.push(["Champs", d.fields.join(", ")]);
    if (d.helper_id) extras.push(["Interlocuteur", d.helper_id]);
    if (d.value) extras.push(["Sélection", d.value]);
    if (d.query_length !== undefined) extras.push(["Recherche", `${d.query_length} caractères`]);
    if (d.total !== undefined) extras.push(["Résultats", d.total]);
    return { parts: [actor, " · ", label, ...forMember], extras };
  }

  if (type.startsWith("casier.command.")) {
    return {parts:[actor," · ",CASIER_EVENT_LABELS[type] || "Action de la commande /sanction",...forMember],
      extras:[...buildExtras(d),...Object.entries({command_id:"Commande Discord",role_id:"Rôle temporaire",result:"Résultat"}).filter(([key])=>d[key]!=null).map(([key,label])=>[label,String(d[key])])]};
  }

  if (type.startsWith("announcement.")) {
    const description = announcementLogSummary(type,d);
    return {parts:[actor," · ",description.text],extras:description.extras};
  }

  if (type.startsWith("project.")) {
    const description = projectLogSummary(type,d);
    if (description) return {parts:[actor," ",description.text],extras:description.extras};
  }
  let parts;

  switch (type) {
    case "auth.login.started":
      parts = ["Connexion Discord démarrée"];
      break;
    case "auth.login.success":
      parts = ["Connexion réussie", ...by];
      break;
    case "auth.login.failure":
      parts = ["Connexion échouée", reasonSuffix, ...by];
      break;
    case "auth.logout":
      parts = [
        d.had_session === false
          ? "Déconnexion sans session active"
          : "Déconnexion",
        ...by,
      ];
      break;
    case "auth.session.invalid":
      parts = ["Session invalide", reasonSuffix, ...by];
      break;
    case "auth.session.check_failed":
      parts = ["Vérification de la session échouée", reasonSuffix, ...by];
      break;
    case "authz.forbidden":
      parts = ["Accès refusé", reasonSuffix, ...by];
      break;

    case "project.viewed":
      parts = [actor, " a consulté ", ...project];
      break;
    case "project.created":
      parts = [actor, " a créé ", ...project];
      break;
    case "project.details.updated":
      parts =
        d.before?.title && d.after?.title && d.before.title !== d.after.title
          ? [
              actor,
              " a renommé le projet ",
              quote(d.before.title),
              " en ",
              quote(d.after.title),
            ]
          : [actor, " a modifié la description de ", ...project];
      break;
    case "project.content.updated": {
      const changes = PROJECT_CHANGE_LABELS.filter(([key]) => d[key]).map(
        ([, label]) => label,
      );
      parts = [
        actor,
        " a modifié ",
        ...project,
        changes.length ? ` (${changes.join(", ")})` : "",
      ];
      break;
    }
    case "project.deleted":
      parts = [actor, " a supprimé ", ...project];
      break;
    case "project.member.added":
      parts = [
        actor,
        " a ajouté ",
        member ? strong(member) : "un membre",
        " à un projet",
      ];
      break;
    case "project.task.created":
      parts = [
        actor,
        " a créé ",
        ...(title ? ["la tâche ", quote(title)] : ["une tâche"]),
      ];
      break;
    case "project.task.submitted":
      parts = [
        actor,
        " a rendu une tâche",
        d.has_file ? " avec un fichier" : "",
      ];
      break;
    case "project.task.validated":
      parts = [actor, " a validé une tâche"];
      break;
    case "project.task.deleted":
      parts = [actor, " a supprimé une tâche"];
      break;
    case "project.resource.uploaded": {
      const name = title || d.original_filename;
      parts = [
        actor,
        " a ajouté ",
        ...(name ? ["la ressource ", quote(name)] : ["une ressource"]),
      ];
      break;
    }
    case "project.resource.deleted":
      parts = [actor, " a supprimé une ressource"];
      break;

    case "casier.created":
      parts = [
        actor,
        " a créé le ",
        ...casier,
        d.is_prevention ? " (prévention)" : "",
      ];
      break;
    case "casier.sanction.created": {
      const kind = d.sanction_type
        ? `un ${sanctionTypeMeta(d.sanction_type).label.toLowerCase()}`
        : "une sanction";
      parts = [
        actor,
        ` a ajouté ${kind} au `,
        ...casier,
        d.duration ? ` (${d.duration})` : "",
      ];
      break;
    }
    case "casier.sanction.note.created":
      parts = [actor, " a ajouté une information au ", ...casier];
      break;
    case "casier.sanction.note.updated":
      parts = [actor, " a modifié une information du ", ...casier];
      break;
    case "casier.sanction.note.deleted":
      parts = [actor, " a supprimé une information du ", ...casier];
      break;
    case "casier.sanction.attachment.uploaded":
      parts = [
        actor,
        d.original_filename ? " a ajouté le fichier" : " a ajouté un fichier",
        ...file,
        " au ",
        ...casier,
      ];
      break;
    case "casier.sanction.attachment.deleted":
      parts = [
        actor,
        d.original_filename ? " a retiré le fichier" : " a retiré un fichier",
        ...file,
        " du ",
        ...casier,
      ];
      break;
    case "casier.sanction.attachments.resynced":
      parts = [actor, " a récupéré les fichiers du log du ", ...casier];
      break;
    case "casier.fiche_s.created":
      parts = [actor, " a rédigé ", ...fiche, ...forMember];
      break;
    case "casier.fiche_s.updated":
      parts = [actor, " a modifié ", ...fiche, ...forMember];
      break;
    case "casier.fiche_s.closed":
      parts = [actor, " a clôturé ", ...fiche, ...forMember];
      break;
    case "casier.ai_flag.reviewed":
      parts = [
        actor,
        " a traité un signalement IA",
        member ? [" concernant ", strong(member)] : "",
        d.review_after
          ? ` (${reviewMeta(d.review_after).label.toLowerCase()})`
          : "",
      ].flat();
      break;

    case "agenda.settings.updated":
      parts = [actor, " a modifié les réglages des rappels de l’agenda"];
      break;
    case "agenda.settings.test_sent":
      parts = [actor, " a envoyé un message de test de l’agenda"];
      break;

    default:
      // Événement inconnu : libellé lisible + clé brute.
      parts = [humanize(type), muted(type ? ` (${type})` : ""), ...by];
  }

  return { parts, extras: buildExtras(d) };
}

function isAlertEvent(type) {
  return type === "authz.forbidden" || type === "auth.login.failure";
}

// Catégorie principale d’une ligne (colonne du CSV).
function categoryLabel(type) {
  if (isAlertEvent(type)) return "Accès refusés";
  if (/^auth\.(login\.|session\.|logout$)/.test(type)) return "Connexions";
  if (/^casier\./.test(type)) return "Casiers";
  if (/^announcement\./.test(type)) return "Annonces";
  if (/^project\./.test(type)) return "Projets";
  if (/^ticket\./.test(type)) return "Tickets";

  return "Autres";
}

/* ---------------------------------- */
/* Export CSV                         */
/* ---------------------------------- */

// Préfixe « ' » : une cellule qui commence par = + - @ serait lue comme une formule par Excel.
function csvCell(value) {
  let text = value === null || value === undefined ? "" : String(value);

  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;

  return /[;"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function buildCsv(logs) {
  const header = [
    "Date (Paris)",
    "Date (UTC)",
    "Utilisateur",
    "ID utilisateur",
    "Catégorie",
    "Événement",
    "Type d’événement",
    "Description",
    "IP",
    "Méthode",
    "Chemin",
    "Code HTTP",
    "Détails (JSON)",
  ];

  const rows = logs.map((log) => {
    const date = parseDate(log.created_at);

    return [
      date
        ? date.toLocaleString("fr-FR", {
            dateStyle: "short",
            timeStyle: "medium",
            timeZone: TIME_ZONE,
          })
        : "",
      date ? date.toISOString() : "",
      log.username,
      log.helper_id,
      categoryLabel(log.event_type),
      EVENT_LABELS[log.event_type] || humanize(log.event_type),
      log.event_type,
      partsText(describeEvent(log).parts),
      log.ip,
      log.method,
      log.path,
      log.status_code,
      log.details && Object.keys(log.details).length
        ? JSON.stringify(log.details)
        : "",
    ];
  });

  const lines = [header, ...rows].map((row) => row.map(csvCell).join(";"));

  return `﻿${lines.join("\r\n")}\r\n`;
}

function downloadCsv(content, filename) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------------------------------- */
/* Composants                         */
/* ---------------------------------- */

function EventBadge({ eventType }) {
  const tone =
    eventType === "auth.login.success" ||
    eventType === "project.created" ||
    eventType === "project.task.created" ||
    eventType === "project.task.validated" ||
    eventType === "project.resource.uploaded"
      ? "status-done"
      : eventType === "auth.logout" ||
          eventType === "project.viewed" ||
          eventType === "project.details.updated" ||
          eventType === "project.content.updated" ||
          eventType === "project.member.added" ||
          eventType === "project.task.submitted"
        ? "status-pending"
        : eventType?.endsWith(".failed") || eventType === "auth.login.failure" ||
            eventType === "authz.forbidden" ||
            eventType === "project.deleted" ||
            eventType === "project.task.deleted" ||
            eventType === "project.resource.deleted"
          ? "status-bad"
          : isCasierEvent(eventType)
            ? casierEventTone(eventType)
            : AGENDA_EVENT_LABELS[eventType]
              ? "status-pending"
              : "";

  return (
    <span className={`status-badge ${tone}`}>
      {EVENT_LABELS[eventType] || (eventType?.startsWith("ticket.") && eventType.endsWith(".failed") ? `${TICKET_EVENT_LABELS[eventType.slice(0, -7)] || "Action ticket"} : échec` : humanize(eventType))}
    </span>
  );
}

function Sentence({ parts }) {
  return (
    <p className="ral-sentence">
      {parts.map((part, index) => {
        if (typeof part === "string") return part;

        if (part.strong !== undefined) {
          return (
            <b key={index} className="ral-name">
              {part.strong}
            </b>
          );
        }

        return (
          <span key={index} className="ral-muted">
            {part.muted}
          </span>
        );
      })}
    </p>
  );
}

function DetailLine({ label, value }) {
  if (value === undefined || value === null || value === "") return null;

  return (
    <span className="ral-detail">
      <b>{label}</b>
      {String(value)}
    </span>
  );
}

function TechnicalDetails({ log }) {
  const hasDetails =
    isPlainObject(log.details) && Object.keys(log.details).length > 0;

  const rows = [
    [
      "Utilisateur",
      log.username
        ? `${log.username}${log.helper_id ? ` (${log.helper_id})` : ""}`
        : log.helper_id,
    ],
    ["Type d’événement", log.event_type],
    ["Adresse IP", log.ip],
    ["Méthode", log.method],
    ["Chemin", log.path],
    ["Code HTTP", log.status_code],
    ["Navigateur", log.user_agent],
    ["Identifiant du log", log.id],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");

  return (
    <details className="ral-tech">
      <summary>
        <ChevronRight size={13} aria-hidden="true" />
        Détails techniques
      </summary>

      <dl className="ral-tech-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{String(value)}</dd>
          </div>
        ))}
      </dl>

      {hasDetails && (
        <pre className="ral-tech-json">{JSON.stringify(log.details, null, 2)}</pre>
      )}
    </details>
  );
}

function LogRow({ log, now }) {
  const date = parseDate(log.created_at);
  const { parts, extras } = describeEvent(log);
  const link = log.event_type?.startsWith("ticket.") && log.details?.ticket_id && !log.event_type.startsWith("ticket.deleted") ? `/tickets/${encodeURIComponent(log.details.ticket_id)}` : casierLogLink(log.event_type, log.details);

  return (
    <tr className={isAlertEvent(log.event_type) ? "ral-row--alert" : undefined}>
      <td className="ral-when" title={date ? exactDate(date) : undefined}>
        {date ? (
          <time dateTime={date.toISOString()}>
            <strong>{relativeTime(date, now)}</strong>
            <small>{shortDate(date)}</small>
          </time>
        ) : (
          "—"
        )}
      </td>

      <td className="ral-kind">
        <EventBadge eventType={log.event_type} />
      </td>

      <td className="ral-activity">
        <Sentence parts={parts} />

        {(extras.length > 0 || link) && (
          <div className="ral-details">
            {extras.map(([label, value]) => (
              <DetailLine key={label} label={label} value={value} />
            ))}

            {link && (
              <Link to={link} className="ral-detail-link">
                {log.details?.ticket_id ? "Ouvrir le dossier" : log.details?.casier_id ? "Ouvrir le casier" : "Voir le signalement"}
                <ArrowRight size={13} aria-hidden="true" />
              </Link>
            )}
          </div>
        )}

        <TechnicalDetails log={log} />
      </td>
    </tr>
  );
}

/* ---------------------------------- */
/* Page                               */
/* ---------------------------------- */

export default function ResponsableAuthLogsPage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [summary, setSummary] = useState(null);

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [categories, setCategories] = useState([]);
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [reloadToken, setReloadToken] = useState(0);

  // Change à chaque nouvelle recherche : une réponse « Charger plus » périmée est ignorée.
  const generationRef = useRef(0);
  const now = useNow(60000);

  const categoriesKey = categories.join(",");
  const filters = {
    search: debouncedSearch,
    categories: categoriesKey,
    period,
    dateFrom,
    dateTo,
  };

  useEffect(() => {
    document.body.classList.add("casier-no-nav");

    return () => {
      document.body.classList.remove("casier-no-nav");
    };
  }, []);

  // Recherche : appliquée 300 ms après la dernière frappe.
  useEffect(() => {
    const timer = setTimeout(
      () => setDebouncedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );

    return () => clearTimeout(timer);
  }, [search]);

  // Première page : se relance à chaque changement de filtre.
  useEffect(() => {
    const controller = new AbortController();

    generationRef.current += 1;
    setLoading(true);
    setLoadingMore(false);
    setLoadFailed(false);

    api
      .get("/responsable/auth-logs", {
        params: buildParams(
          { search: debouncedSearch, categories: categoriesKey, period, dateFrom, dateTo },
          0,
        ),
        signal: controller.signal,
      })
      .then((response) => {
        setItems(response.data.items || []);
        setTotal(response.data.total || 0);
        setLoading(false);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;

        toast.error(getErrorMessage(error));
        setLoadFailed(true);
        setLoading(false);
      });

    return () => controller.abort();
  }, [debouncedSearch, categoriesKey, period, dateFrom, dateTo, reloadToken]);

  // Résumé du jour.
  useEffect(() => {
    let active = true;

    api
      .get("/responsable/auth-logs/summary")
      .then((response) => {
        if (active) setSummary(response.data);
      })
      .catch(() => {
        if (active) setSummary(null);
      });

    return () => {
      active = false;
    };
  }, [reloadToken]);

  const hasMore = items.length < total;

  const loadMore = async () => {
    if (loading || loadingMore || !hasMore) return;

    const generation = generationRef.current;
    setLoadingMore(true);

    try {
      const response = await api.get("/responsable/auth-logs", {
        params: buildParams(filters, items.length),
      });

      if (generation !== generationRef.current) return;

      const next = response.data.items || [];

      // Des logs ont pu arriver entre-temps : on écarte les doublons.
      setItems((current) => {
        const seen = new Set(current.map((log) => log.id));
        return [...current, ...next.filter((log) => !seen.has(log.id))];
      });
      setTotal(response.data.total || 0);
    } catch (error) {
      if (generation === generationRef.current) toast.error(getErrorMessage(error));
    } finally {
      if (generation === generationRef.current) setLoadingMore(false);
    }
  };

  const toggleCategory = (key) => {
    setCategories((current) => {
      const selected = new Set(current);

      if (selected.has(key)) selected.delete(key);
      else selected.add(key);

      return CATEGORIES.map((item) => item.key).filter((item) => selected.has(item));
    });
  };

  const choosePeriod = (key) => {
    setPeriod(key);
    setDateFrom("");
    setDateTo("");
  };

  const changeDate = (field, value) => {
    const from = field === "from" ? value : dateFrom;
    const to = field === "to" ? value : dateTo;

    setDateFrom(from);
    setDateTo(to);
    setPeriod(from || to ? "custom" : DEFAULT_PERIOD);
  };

  const filtersActive =
    search.trim() !== "" || categories.length > 0 || period !== DEFAULT_PERIOD;

  const resetFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setCategories([]);
    setPeriod(DEFAULT_PERIOD);
    setDateFrom("");
    setDateTo("");
  };

  const exportCsv = () => {
    if (items.length === 0) return;

    downloadCsv(buildCsv(items), `journal-activite-${parisToday()}.csv`);
    toast.success(
      `${items.length} ligne${items.length > 1 ? "s" : ""} exportée${items.length > 1 ? "s" : ""}.`,
    );
  };

  const todayLabel = new Date(now).toLocaleDateString("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: TIME_ZONE,
  });

  return (
    <section
      className="cz-page ral-page"
      data-testid="responsable-auth-logs-page"
    >
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE RESPONSABLE</p>

          <h1>Journal d’activité</h1>

          <p className="cz-intro">
            Consultez les connexions, accès refusés et actions
            enregistrées dans Iris.
          </p>
        </div>

        <div className="cz-header-actions">
          <Link to="/" className="cz-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <section className="ral-summary" aria-labelledby="ral-summary-title">
        <h2 id="ral-summary-title" className="ral-summary-title">
          Aujourd’hui
          <small>{todayLabel}</small>
        </h2>

        <div className="ral-summary-grid">
          {SUMMARY_ITEMS.map((item) => {
            const value = summary ? summary[item.key] : null;
            const alert = item.alert && value > 0;

            return (
              <div
                key={item.key}
                className={`ral-stat${alert ? " is-alert" : ""}`}
              >
                <span className="ral-stat-value">{value ?? "—"}</span>
                <span className="ral-stat-label">{item.label}</span>
                {alert && <span className="ral-stat-flag">À vérifier</span>}
              </div>
            );
          })}
        </div>
      </section>

      <section className="cz-panel ral-panel">
        <header className="cz-panel-header cz-panel-header--red">
          <span className="cz-panel-icon" aria-hidden="true">
            <Shield size={23} />
          </span>

          <div className="cz-panel-heading">
            <h2>Filtrer le journal</h2>
            <p>
              Recherchez un utilisateur, un membre ou un projet, puis
              affinez par catégorie et par période.
            </p>
          </div>

          <span className="cz-count-live" aria-live="polite">
            <span className="cz-count">
              {total} entrée{total > 1 ? "s" : ""}
            </span>
          </span>
        </header>

        <div className="cz-panel-toolbar">
          <div className="ral-filters">
            <div className="ral-filter-row ral-filter-row--main">
              <label className="ral-field ral-field--search">
                <span>Rechercher</span>

                <div className="ral-search-box">
                  <Search size={16} aria-hidden="true" />

                  <input
                    type="search"
                    value={search}
                    maxLength={100}
                    onChange={(event) => setSearch(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        setDebouncedSearch(search.trim());
                      }
                    }}
                    placeholder="Utilisateur, membre, projet…"
                    autoComplete="off"
                  />
                </div>
              </label>

              <label className="ral-field ral-field--date">
                <span>Du</span>

                <input
                  type="date"
                  value={dateFrom}
                  max={dateTo || undefined}
                  onChange={(event) => changeDate("from", event.target.value)}
                />
              </label>

              <label className="ral-field ral-field--date">
                <span>Au</span>

                <input
                  type="date"
                  value={dateTo}
                  min={dateFrom || undefined}
                  onChange={(event) => changeDate("to", event.target.value)}
                />
              </label>
            </div>

            <div className="ral-filter-row ral-filter-row--chips">
              <div className="ral-field" role="group" aria-label="Catégories">
                <span>Catégories</span>

                <div className="cz-chips">
                  {CATEGORIES.map((category) => (
                    <button
                      key={category.key}
                      type="button"
                      className="cz-chip"
                      title={category.hint}
                      aria-pressed={categories.includes(category.key)}
                      onClick={() => toggleCategory(category.key)}
                    >
                      {category.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="ral-field" role="group" aria-label="Période">
                <span>Période</span>

                <div className="cz-chips">
                  {PERIODS.map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      className="cz-chip"
                      aria-pressed={period === item.key}
                      onClick={() => choosePeriod(item.key)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="ral-filter-actions">
                <button
                  type="button"
                  className="cz-button"
                  onClick={() => setReloadToken((token) => token + 1)}
                  disabled={loading}
                >
                  <RefreshCw size={16} aria-hidden="true" />
                  Actualiser
                </button>

                <button
                  type="button"
                  className="cz-button"
                  onClick={resetFilters}
                  disabled={!filtersActive}
                >
                  <RotateCcw size={16} aria-hidden="true" />
                  Réinitialiser
                </button>

                <button
                  type="button"
                  className="cz-button"
                  onClick={exportCsv}
                  disabled={items.length === 0}
                  title="Exporte les lignes actuellement chargées"
                >
                  <Download size={16} aria-hidden="true" />
                  Exporter en CSV
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="cz-panel-scroll">
          {loading && items.length === 0 ? (
            <div className="ral-state" role="status">
              <LoaderCircle className="spin" size={24} aria-hidden="true" />
              <p>Chargement du journal…</p>
            </div>
          ) : loadFailed ? (
            <div className="ral-state">
              <FileText size={30} aria-hidden="true" />
              <h2>Impossible de charger le journal.</h2>

              <button
                type="button"
                className="cz-button"
                onClick={() => setReloadToken((token) => token + 1)}
              >
                <RefreshCw size={16} aria-hidden="true" />
                Réessayer
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className="ral-state">
              <FileText size={30} aria-hidden="true" />
              <h2>Aucune activité ne correspond à ces filtres.</h2>
              <p>Élargissez la période ou retirez une catégorie.</p>

              {filtersActive && (
                <button type="button" className="cz-button" onClick={resetFilters}>
                  <RotateCcw size={16} aria-hidden="true" />
                  Réinitialiser les filtres
                </button>
              )}
            </div>
          ) : (
            <div className="ral-table-wrap">
              <table
                className={`ral-table${loading ? " is-refreshing" : ""}`}
                aria-busy={loading}
                aria-label="Journal d’activité"
              >
                <thead>
                  <tr>
                    <th>Quand</th>
                    <th>Événement</th>
                    <th>Activité</th>
                  </tr>
                </thead>

                <tbody>
                  {items.map((log) => (
                    <LogRow key={log.id} log={log} now={now} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {!loadFailed && items.length > 0 && (
          <footer className="ral-pagination">
            <span>
              {items.length} sur {total} entrée{total > 1 ? "s" : ""} affichée
              {items.length > 1 ? "s" : ""}
            </span>

            {hasMore && (
              <div>
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={loadingMore || loading}
                >
                  {loadingMore ? (
                    <LoaderCircle className="spin" size={15} aria-hidden="true" />
                  ) : null}
                  Charger plus
                </button>
              </div>
            )}
          </footer>
        )}
      </section>
    </section>
  );
}
