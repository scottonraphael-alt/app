import { api, getErrorMessage } from "../../api/client";

export const errorMessage = getErrorMessage;

export const STATES = [
  { value: "disponible", label: "Disponible" },
  { value: "occupe", label: "Occupé" },
  { value: "en_pause", label: "En pause" },
  { value: "absent", label: "Absent" },
];
export const DURATIONS = [
  { value: "", label: "Sans expiration" },
  { value: "30", label: "30 minutes" },
  { value: "60", label: "1 heure" },
  { value: "240", label: "4 heures" },
  { value: "1440", label: "24 heures" },
  { value: "10080", label: "7 jours" },
];
export const DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

export const teamKeys = {
  directory: (params) => ["team", "directory", params],
  card: ["team", "card"],
  myStatus: ["team", "status", "me"],
  kudos: (scope) => ["team", "kudos", scope],
  kudosSummary: ["team", "kudos", "summary"],
  onboarding: ["team", "onboarding", "me"],
  overview: ["team", "onboarding", "overview"],
  templates: ["team", "onboarding", "templates"],
};

const get = async (url, params) => (await api.get(url, { params })).data;

export const fetchDirectory = (params) => get("/staff-directory", params);
export const fetchMyCard = () => get("/staff-directory/me");
export const saveMyCard = async (payload) => (await api.put("/staff-directory/me", payload)).data;

export const fetchMyStatus = () => get("/staff-status/me");
export const saveMyStatus = async (payload) => (await api.put("/staff-status/me", payload)).data;
export const clearMyStatus = async () => { await api.delete("/staff-status/me"); };

export const fetchKudos = (scope, before) => get("/kudos", { scope, limit: 20, ...(before ? { before } : {}) });
export const fetchKudosMeta = () => get("/kudos/categories");
export const fetchKudosSummary = () => get("/kudos/summary");
export const sendKudos = async (payload) => (await api.post("/kudos", payload)).data;
export const deleteKudos = async (id) => { await api.delete(`/kudos/${encodeURIComponent(id)}`); };

export const fetchChecklist = () => get("/onboarding/me");
export const setChecklistItem = async (id, done) =>
  (await api.post(`/onboarding/me/items/${encodeURIComponent(id)}`, { done })).data;
export const fetchOverview = () => get("/onboarding/overview");
export const fetchTemplates = () => get("/onboarding/templates");
export const saveTemplate = async (role, items) =>
  (await api.put(`/onboarding/templates/${encodeURIComponent(role)}`, { items })).data;
export const resetTemplate = async (role) => { await api.delete(`/onboarding/templates/${encodeURIComponent(role)}`); };
export const nudgeMember = async (id) => (await api.post(`/onboarding/${encodeURIComponent(id)}/nudge`)).data;

export function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}
