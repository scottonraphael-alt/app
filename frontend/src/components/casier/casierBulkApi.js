import { api } from "../../api/client";

const BASE = "/moderation/casiers-bulk";

export const bulkKeys = {
  meta: () => ["casier-bulk", "meta"],
  assignees: () => ["casier-bulk", "assignees"],
};

export async function fetchBulkMeta() {
  const response = await api.get(`${BASE}/meta`);
  return response?.data?.items || {};
}

export async function fetchAssignees() {
  const response = await api.get(`${BASE}/assignees`);
  return Array.isArray(response?.data?.items) ? response.data.items : [];
}

export async function bulkTag(casierIds, tag) {
  const response = await api.post(`${BASE}/tag`, { casier_ids: casierIds, tag });
  return response?.data;
}

export async function bulkUntag(casierIds, tag) {
  const response = await api.post(`${BASE}/untag`, { casier_ids: casierIds, tag });
  return response?.data;
}

// assigneeId null = retirer le suivi.
export async function bulkFollowUp(casierIds, { assigneeId, note, dueDate }) {
  const body = { casier_ids: casierIds, assignee_id: assigneeId || null };
  if (note && note.trim()) body.note = note.trim();
  if (dueDate) body.due_date = dueDate;
  const response = await api.post(`${BASE}/follow-up`, body);
  return response?.data;
}

// Télécharge le CSV des casiers sélectionnés.
export async function bulkExport(casierIds) {
  const response = await api.post(`${BASE}/export`, { casier_ids: casierIds }, { responseType: "blob" });
  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `casiers-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fetchModerationStats(params) {
  const response = await api.get("/moderation/stats", { params });
  return response?.data;
}
