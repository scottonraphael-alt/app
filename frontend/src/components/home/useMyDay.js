import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

function localDateKey() {
  const now = new Date();
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
}

function mine(participants, userId) {
  const list = Array.isArray(participants) ? participants : [];
  return list.length === 0 || list.some((p) => String(p?.id) === String(userId));
}

/** Agrège réunions, échéances, tâches et transmissions du jour pour l'utilisateur. */
export default function useMyDay(helperId, enabled) {
  const on = Boolean(helperId && enabled);
  const day = localDateKey();

  const feed = useQuery({
    queryKey: ["home", "feed", helperId, day],
    enabled: on,
    queryFn: async ({ signal }) =>
      (await api.get("/agenda/feed", { params: { start: day, end: day }, signal })).data,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: false,
  });
  const handoffs = useQuery({
    queryKey: ["home", "handoffs", helperId],
    enabled: on,
    queryFn: async ({ signal }) =>
      (await api.get("/handoffs", { params: { status: "open", limit: 30 }, signal })).data,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: false,
  });
  const notifications = useQuery({
    queryKey: ["home", "notifications", helperId],
    enabled: Boolean(helperId),
    queryFn: async ({ signal }) =>
      (await api.get("/notifications", { params: { limit: 5, unread: "1" }, signal })).data,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: false,
  });

  const f = feed.data;
  const meetings = (f?.meetings || [])
    .filter((m) => !m.cancelled && m.is_participant)
    .map((m) => ({ id: m.id, title: m.title, time: m.start_time, to: `/staff/meetings/${m.id}` }));
  const entries = (f?.entries || [])
    .filter((e) => mine(e.participants, helperId))
    .map((e) => ({ id: e.id, title: e.title, time: e.all_day ? null : e.start_time, to: "/staff/calendrier" }));
  const tasks = (f?.tasks || [])
    .filter((t) => String(t.assignee?.id) === String(helperId))
    .map((t) => ({ id: t.id, title: t.title, sub: t.project_title, to: `/animateur/projects/${t.project_id}` }));
  const transmissions = (handoffs.data?.items || [])
    .filter((h) => !h.read && !h.resolved)
    .map((h) => ({ id: h.id, title: String(h.body || "").slice(0, 90), urgent: h.priority === "urgent" }));

  return {
    meetings, entries, tasks, transmissions,
    unreadNotifications: notifications.data?.unread_count || 0,
    isLoading: on && (feed.isPending || handoffs.isPending),
    isError: feed.isError && handoffs.isError,
    counts: {
      meetings: meetings.length, deadlines: entries.length,
      tasks: tasks.length, handoffs: transmissions.length,
    },
  };
}
