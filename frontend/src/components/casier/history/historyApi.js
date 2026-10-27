import { api } from "../../../api/client";

const seg = (value) => encodeURIComponent(String(value ?? ""));

export const historyKeys = {
  all: (casierId) => ["casier-history", casierId],
};

export const HISTORY_PAGE_SIZE = 30;

// GET /api/casier/{id}/history → { items: [{ id, entity, entity_id, action, actor_name, at,
//   changes: [{ field, before, after }], revertible, stale, reverted_by?, reverted_at? }] }
export async function getCasierHistory(casierId, { before, limit = HISTORY_PAGE_SIZE, signal } = {}) {
  const params = { limit };
  if (before) params.before = before;
  const { data } = await api.get(`/casier/${seg(casierId)}/history`, { params, signal });
  return Array.isArray(data?.items) ? data.items : [];
}

// POST /api/casier/history/{id}/revert {force} → { revision, reverted_revision_id }
export async function revertRevision(revisionId, { force = false } = {}) {
  const { data } = await api.post(`/casier/history/${seg(revisionId)}/revert`, { force: Boolean(force) });
  return data;
}
