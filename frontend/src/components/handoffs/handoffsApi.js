import { api, getErrorMessage } from "@/api/client";

export const PRIORITIES = [
  { value: "info", label: "Info" },
  { value: "important", label: "Important" },
  { value: "urgent", label: "Urgent" },
];
export const STATUS_FILTERS = [
  { value: "open", label: "Ouvertes" },
  { value: "resolved", label: "Résolues" },
  { value: "all", label: "Toutes" },
];
export const MAX_BODY = 4000;
export const MAX_TAGS = 5;
export const MAX_TAG = 24;
export const PAGE_SIZE = 30;

export const handoffKeys = {
  all: ["handoffs"],
  list: (status) => ["handoffs", "list", status],
};

export const errorMessage = getErrorMessage;

export async function fetchHandoffs({ status, before }) {
  const params = { status, limit: PAGE_SIZE };
  if (before) params.before = before;
  const { data } = await api.get("/handoffs", { params });
  return data;
}

export async function createHandoff(payload) {
  const { data } = await api.post("/handoffs", payload);
  return data;
}

export async function updateHandoff(id, payload) {
  const { data } = await api.patch(`/handoffs/${encodeURIComponent(id)}`, payload);
  return data;
}

export async function markHandoffRead(id) {
  const { data } = await api.post(`/handoffs/${encodeURIComponent(id)}/read`);
  return data;
}

export async function resolveHandoff(id, resolved) {
  const { data } = await api.post(`/handoffs/${encodeURIComponent(id)}/${resolved ? "resolve" : "reopen"}`);
  return data;
}

export async function deleteHandoff(id) {
  await api.delete(`/handoffs/${encodeURIComponent(id)}`);
}

export function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
