import { api, getErrorMessage } from "../../api/client";

export const errorMessage = getErrorMessage;
const get = async (url, params) => (await api.get(url, { params })).data;

export const weatherStatus = () => get("/team-weather/status");
export const weatherSummary = (weeks = 8) => get("/team-weather/summary", { weeks });
export const sendCheckin = async (payload) => (await api.post("/team-weather/checkin", payload)).data;

export const listSheets = () => get("/reflex-sheets");
export const saveSheet = async (slug, payload) => (await api.put(`/reflex-sheets/${encodeURIComponent(slug)}`, payload)).data;
export const resetSheet = async (slug) => (await api.delete(`/reflex-sheets/${encodeURIComponent(slug)}`)).data;

export const listTrainings = () => get("/trainings");
export const getTraining = (id) => get(`/trainings/${encodeURIComponent(id)}`);
export const trainingProgress = () => get("/trainings/progress");
export const createTraining = async (payload) => (await api.post("/trainings", payload)).data;
export const updateTraining = async (id, payload) => (await api.put(`/trainings/${encodeURIComponent(id)}`, payload)).data;
export const deleteTraining = async (id) => { await api.delete(`/trainings/${encodeURIComponent(id)}`); };
export const submitQuiz = async (id, answers) => (await api.post(`/trainings/${encodeURIComponent(id)}/submit`, { answers })).data;

export const getDebrief = (ticketId) => get(`/debriefs/ticket/${encodeURIComponent(ticketId)}`);
export const sendDebrief = async (ticketId, payload) => (await api.post(`/debriefs/ticket/${encodeURIComponent(ticketId)}`, payload)).data;

export const REASON_TO_SHEET = [
  ["suicid", "crise-suicidaire"], ["automutil", "automutilation"], ["violence", "violences"],
  ["danger", "mineur-en-danger"], ["harcel", "harcelement"],
];
export function sheetForReasons(reasons = []) {
  const text = reasons.join(" ").toLowerCase();
  const hit = REASON_TO_SHEET.find(([key]) => text.includes(key));
  return hit ? hit[1] : "";
}
