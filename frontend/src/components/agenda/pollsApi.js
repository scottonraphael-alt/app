import { api } from "../../api/client";

export const pollKeys = {
  all: ["agenda", "polls"],
};

export async function fetchPolls({ signal } = {}) {
  const response = await api.get("/agenda/polls", { signal });
  return response.data;
}

export async function createPoll(payload) {
  const response = await api.post("/agenda/polls", payload);
  return response.data;
}

export async function votePoll(pollId, votes) {
  const response = await api.put(`/agenda/polls/${encodeURIComponent(pollId)}/vote`, { votes });
  return response.data;
}

export async function closePoll(pollId, slotId, includeMaybe = true) {
  const response = await api.post(`/agenda/polls/${encodeURIComponent(pollId)}/close`, {
    slot_id: slotId,
    include_maybe: includeMaybe,
  });
  return response.data;
}

export async function deletePoll(pollId) {
  await api.delete(`/agenda/polls/${encodeURIComponent(pollId)}`);
  return null;
}
