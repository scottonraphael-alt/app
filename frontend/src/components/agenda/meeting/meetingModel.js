import { ATTENDANCE, ATTENDANCE_CHOICES, TEXT_LIMITS } from "../agendaConstants";
import { isIsoDate } from "../dateUtils";

// Identifiant d'élément créé par le client (motif ClientId du serveur : lettres, chiffres, _ et -).
export function newClientId() {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  } catch (error) {
    // Contexte non sécurisé : repli ci-dessous.
  }
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

function identityOf(person) {
  if (!person || !person.id) return null;
  return {
    id: String(person.id),
    username: person.username || "",
    display_name: person.display_name ?? null,
    avatar_url: person.avatar_url ?? null,
  };
}

// `lastText` garde le dernier texte non vide : une ligne vidée pendant la frappe n'efface jamais l'élément
// côté serveur (le champ est requis), et une ligne neuve restée vide n'est tout simplement pas envoyée.
function withLast(item, text) {
  return { ...item, lastText: String(text || "") };
}

// État local de l'éditeur à partir du MeetingDetailOut.
export function docFromDetail(detail) {
  const attendance = {};
  for (const person of Array.isArray(detail?.participants) ? detail.participants : []) {
    if (person?.id) attendance[String(person.id)] = person.attendance || "invite";
  }
  return {
    title: detail?.title || "",
    content: typeof detail?.content_markdown === "string" ? detail.content_markdown : "",
    agenda_items: (Array.isArray(detail?.agenda_items) ? detail.agenda_items : []).map((item) =>
      withLast({ id: String(item.id), title: item.title || "", done: Boolean(item.done) }, item.title),
    ),
    decisions: (Array.isArray(detail?.decisions) ? detail.decisions : []).map((item) =>
      withLast({ id: String(item.id), text: item.text || "" }, item.text),
    ),
    action_items: (Array.isArray(detail?.action_items) ? detail.action_items : []).map((item) =>
      withLast(
        {
          id: String(item.id),
          text: item.text || "",
          assignee: identityOf(item.assignee),
          due_date: isIsoDate(item.due_date) ? item.due_date : "",
          done: Boolean(item.done),
          done_at: item.done_at || null,
          done_by: identityOf(item.done_by),
        },
        item.text,
      ),
    ),
    attendance,
  };
}

export function newAgendaItem(title = "") {
  return withLast({ id: newClientId(), title, done: false }, "");
}

export function newDecision(text = "") {
  return withLast({ id: newClientId(), text }, "");
}

export function newAction(text = "") {
  return withLast(
    { id: newClientId(), text, assignee: null, due_date: "", done: false, done_at: null, done_by: null },
    "",
  );
}

// Garde la dernière valeur non vide pour mémoriser le texte lors d'une modification.
export function setItemText(item, field, value) {
  const trimmed = String(value || "").trim();
  return { ...item, [field]: value, lastText: trimmed ? trimmed : item.lastText };
}

// Texte envoyé : le texte saisi, sinon le dernier texte valide, sinon l'élément est ignoré.
function sendableText(value, last, max) {
  const text = String(value || "").trim() || String(last || "").trim();
  return text ? text.slice(0, max) : "";
}

export function agendaPayload(items) {
  const out = [];
  for (const item of items) {
    const title = sendableText(item.title, item.lastText, TEXT_LIMITS.agendaItem);
    if (title) out.push({ id: item.id, title, done: Boolean(item.done) });
  }
  return out;
}

export function decisionsPayload(items) {
  const out = [];
  for (const item of items) {
    const text = sendableText(item.text, item.lastText, TEXT_LIMITS.decision);
    if (text) out.push({ id: item.id, text });
  }
  return out;
}

// `done` n'est envoyé que pour les actions cochées ou décochées ici depuis le dernier enregistrement réussi.
export function actionsPayload(items, doneTouched) {
  const out = [];
  for (const item of items) {
    const text = sendableText(item.text, item.lastText, TEXT_LIMITS.action);
    if (!text) continue;
    const entry = {
      id: item.id,
      text,
      assignee_id: item.assignee?.id ?? null,
      due_date: isIsoDate(item.due_date) ? item.due_date : null,
    };
    if (doneTouched && doneTouched.has(item.id)) entry.done = Boolean(item.done);
    out.push(entry);
  }
  return out;
}

// Corps du PATCH d'enregistrement automatique pour les champs modifiés (hors expected_revision).
export function buildSavePatch(doc, keys, { done, attendance } = {}) {
  const patch = {};
  if (keys.has("title")) {
    const title = doc.title.trim();
    if (title) patch.title = title.slice(0, TEXT_LIMITS.title);
  }
  if (keys.has("content_markdown")) patch.content_markdown = doc.content;
  if (keys.has("agenda_items")) patch.agenda_items = agendaPayload(doc.agenda_items);
  if (keys.has("decisions")) patch.decisions = decisionsPayload(doc.decisions);
  if (keys.has("action_items")) patch.action_items = actionsPayload(doc.action_items, done);
  if (attendance && attendance.size) {
    const map = {};
    for (const [id, value] of attendance) map[id] = value;
    patch.attendance = map;
  }
  return patch;
}

export function isAttendanceValue(value) {
  return Boolean(ATTENDANCE[value]);
}

export { ATTENDANCE_CHOICES };

// Participants du détail, avec la présence locale (la source de vérité pendant la rédaction).
export function participantsWithAttendance(detail, attendance) {
  const list = Array.isArray(detail?.participants) ? detail.participants : [];
  return list
    .filter((person) => person && person.id)
    .map((person) => ({
      ...identityOf(person),
      attendance: attendance?.[String(person.id)] || person.attendance || "invite",
    }));
}

export function pluralize(count, one, many) {
  return `${count} ${count > 1 ? many : one}`;
}
