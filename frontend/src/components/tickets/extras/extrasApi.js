import { api, getErrorMessage } from "../../../api/client";

export const errorMessage = getErrorMessage;
export const TAG_COLORS = ["sauge", "bleu", "ambre", "rose", "violet", "gris"];
export const FOLLOWUP_PRESETS = [
  { value: "2h", label: "Dans 2 h" },
  { value: "tomorrow", label: "Demain matin" },
  { value: "3d", label: "Dans 3 jours" },
];

export const fetchNotes = (ticketId) => api.get(`/ticket-notes/${encodeURIComponent(ticketId)}`).then((r) => r.data.items);
export const addNote = (ticketId, body) => api.post(`/ticket-notes/${encodeURIComponent(ticketId)}`, { body }).then((r) => r.data);
export const deleteNote = (ticketId, noteId) => api.delete(`/ticket-notes/${encodeURIComponent(ticketId)}/${encodeURIComponent(noteId)}`);

export const fetchTags = () => api.get("/ticket-tags").then((r) => r.data.items);
export const fetchTagAssignments = () => api.get("/ticket-tags/assignments").then((r) => r.data.items);
export const createTag = (name, color) => api.post("/ticket-tags", { name, color }).then((r) => r.data);
export const deleteTag = (id) => api.delete(`/ticket-tags/${encodeURIComponent(id)}`);
export const setTicketTags = (ticketId, tagIds) =>
  api.put(`/ticket-tags/ticket/${encodeURIComponent(ticketId)}`, { tag_ids: tagIds }).then((r) => r.data);

export const fetchFollowups = (ticketId) =>
  api.get("/ticket-followups", { params: { ticket_id: ticketId } }).then((r) => r.data.items);
export const createFollowup = (ticketId, preset, note) =>
  api.post("/ticket-followups", { ticket_id: ticketId, preset, note: note || undefined }).then((r) => r.data);
export const cancelFollowup = (id) => api.delete(`/ticket-followups/${encodeURIComponent(id)}`);
