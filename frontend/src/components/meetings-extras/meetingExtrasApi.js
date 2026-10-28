import { api } from "../../api/client";

const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

function seg(id) {
  const value = String(id ?? "");
  if (!ID_RE.test(value)) {
    const error = new Error("Identifiant invalide.");
    error.response = { status: 404, data: { detail: "Élément introuvable." } };
    throw error;
  }
  return value;
}

const base = (meetingId) => `/meeting-extras/meetings/${seg(meetingId)}`;

export const extrasKeys = {
  proposals: (meetingId) => ["meeting-extras", "proposals", meetingId],
  templates: () => ["meeting-extras", "templates"],
  decisions: (meetingId) => ["meeting-extras", "decisions", meetingId],
  register: (q) => ["meeting-extras", "register", q],
  timer: (meetingId) => ["meeting-extras", "timer", meetingId],
};

// ---- Ordre du jour collaboratif ----
export async function fetchProposals(meetingId) {
  return (await api.get(`${base(meetingId)}/proposals`)).data;
}
export async function addProposal(meetingId, payload) {
  return (await api.post(`${base(meetingId)}/proposals`, payload)).data;
}
export async function editProposal(meetingId, proposalId, patch) {
  return (await api.patch(`${base(meetingId)}/proposals/${seg(proposalId)}`, patch)).data;
}
export async function deleteProposal(meetingId, proposalId) {
  await api.delete(`${base(meetingId)}/proposals/${seg(proposalId)}`);
}
export async function reorderProposals(meetingId, ids) {
  return (await api.put(`${base(meetingId)}/proposals/order`, { ids })).data;
}
export async function proposalsToAgenda(meetingId, expectedRevision) {
  return (await api.post(`${base(meetingId)}/proposals/to-agenda`, { expected_revision: expectedRevision })).data;
}

// ---- Modèles ----
export async function fetchTemplates() {
  return (await api.get("/meeting-extras/templates")).data;
}
export async function createTemplate(payload) {
  return (await api.post("/meeting-extras/templates", payload)).data;
}
export async function deleteTemplate(templateId) {
  await api.delete(`/meeting-extras/templates/${seg(templateId)}`);
}
export async function applyTemplate(meetingId, templateId, expectedRevision) {
  return (
    await api.post(`${base(meetingId)}/apply-template`, { template_id: templateId, expected_revision: expectedRevision })
  ).data;
}

// ---- Décisions ----
export async function fetchMeetingDecisions(meetingId) {
  return (await api.get(`${base(meetingId)}/decisions`)).data;
}
export async function markDecision(meetingId, payload) {
  return (await api.post(`${base(meetingId)}/decisions`, payload)).data;
}
export async function unmarkDecision(decisionId) {
  await api.delete(`/meeting-extras/decisions/${seg(decisionId)}`);
}
export async function fetchDecisionsRegister({ q = "", limit = 50, offset = 0 } = {}) {
  const params = { limit, offset };
  if (q) params.q = q;
  return (await api.get("/meeting-extras/decisions", { params })).data;
}

// ---- Minuteur ----
export async function fetchTimer(meetingId) {
  return (await api.get(`${base(meetingId)}/timer`)).data;
}
export async function initTimer(meetingId, payload = {}) {
  return (await api.post(`${base(meetingId)}/timer/init`, payload)).data;
}
export async function timerAction(meetingId, payload) {
  return (await api.post(`${base(meetingId)}/timer/action`, payload)).data;
}

export function listOf(data) {
  return Array.isArray(data?.items) ? data.items : [];
}

// 12 min 05 s → « 12:05 » ; au-delà d'une heure « 1:02:03 ».
export function formatClock(totalSeconds) {
  const value = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = value % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}
