import { useCallback, useEffect, useState } from "react";
import "@/App.css";
import "@/MentalHealth.css";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";

import { api } from "./api/client";
import AppShell from "./components/AppShell";
import AdminDashboardPage from "./pages/AdminDashboardPage";
import DashboardPage from "./pages/DashboardPage";
import HelperProfilePage from "./pages/HelperProfilePage";
import LoginPage from "./pages/LoginPage";
import NewTicketPage from "./pages/NewTicketPage";
import ResourcesPage from "./pages/ResourcesPage";
import TicketWorkspacePage from "./pages/TicketWorkspacePage";
import AbsenceCalendarPage from "./pages/AbsenceCalendarPage";
import MeetingSummariesPage from "./pages/MeetingSummariesPage";
import MeetingSummaryEditorPage from "./pages/MeetingSummaryEditorPage";
import QuarterlyTasksPage from "./pages/QuarterlyTasksPage";
import ProjectsListPage from "./pages/ProjectsListPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectCalendarPage from "./pages/ProjectCalendarPage";
import ResponsableAuthLogsPage from "./pages/ResponsableAuthLogsPage";
import ModerationCasierPage from "./pages/ModerationCasierPage";

function AuthenticatedApp({
  helper,
  isAdmin,
  isStaff,
  isHelper,
  isResponsable,
  isOperateur,
  isAnimateur,
  onSessionRefresh,
}) {
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState({
    active_count: 0,
    archived_count: 0,
    total_messages: 0,
  });

  const canSeeHelper = isResponsable || isAdmin || isHelper;
  const canSeeAdmin = isResponsable || isAdmin;
  const canSeeStaff = isResponsable || isAdmin || isHelper || isStaff || isOperateur;
  const canSeeAnimateur = isAnimateur || isResponsable;
  const canSeeOperateur = isOperateur || isResponsable;

  const refreshDashboard = useCallback(async () => {
    const [ticketsResponse, statsResponse] = await Promise.all([
      api.get("/tickets"),
      api.get("/tickets/stats"),
    ]);
    setTickets(ticketsResponse.data);
    setStats(statsResponse.data);
  }, []);

  useEffect(() => {
    if (!canSeeHelper) return;
    refreshDashboard().catch(() => undefined);
  }, [canSeeHelper, refreshDashboard]);

  const updateTicket = (ticket) => {
    setTickets((current) => [
      ticket,
      ...current.filter((item) => item.id !== ticket.id),
    ]);
    api
      .get("/tickets/stats")
      .then((response) => setStats(response.data))
      .catch(() => undefined);
  };

  const deleteTicket = (ticketId) => {
    setTickets((current) => current.filter((ticket) => ticket.id !== ticketId));
    api
      .get("/tickets/stats")
      .then((response) => setStats(response.data))
      .catch(() => undefined);
  };

  const logout = async () => {
    await api.post("/auth/logout");
    window.location.assign("/");
  };

  const defaultRoute = isResponsable
    ? "/responsable/auth-logs"
    : isHelper
      ? "/"
      : "/staff/calendrier";

  return (
    <AppShell
      helper={helper}
      tickets={tickets}
      onLogout={logout}
      isAdmin={isAdmin}
      isStaff={isStaff}
      isResponsable={isResponsable}
      isAnimateur={isAnimateur}
      isOperateur={isOperateur}
      isHelper={isHelper}
    >
      <Routes>
        <Route
          path="/"
          element={
            canSeeHelper ? (
              <DashboardPage stats={stats} tickets={tickets} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/new"
          element={
            canSeeHelper ? (
              <NewTicketPage onCreated={updateTicket} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/tickets/:ticketId"
          element={
            canSeeHelper ? (
              <TicketWorkspacePage
                onTicketUpdate={updateTicket}
                onTicketDeleted={deleteTicket}
                isAdmin={isAdmin}
                helper={helper}
              />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/archives"
          element={
            canSeeHelper ? (
              <DashboardPage
                stats={stats}
                tickets={tickets.filter((ticket) => ticket.status === "archived")}
              />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/admin"
          element={
            canSeeAdmin ? (
              <AdminDashboardPage />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route path="/profile" element={<HelperProfilePage helper={helper} />} />

        <Route
          path="/resources"
          element={
            canSeeHelper ? (
              <ResourcesPage isAdmin={isAdmin} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/staff/calendrier"
          element={
            canSeeStaff ? (
              <AbsenceCalendarPage isResponsable={isResponsable} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/staff/meetings"
          element={
            canSeeStaff ? (
              <MeetingSummariesPage isResponsable={isResponsable} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/staff/meetings/new"
          element={
            canSeeStaff && isResponsable ? (
              <MeetingSummaryEditorPage />
            ) : (
              <Navigate to="/staff/meetings" replace />
            )
          }
        />

        <Route
          path="/staff/meetings/:meetingId"
          element={
            canSeeStaff ? (
              <MeetingSummaryEditorPage isResponsable={isResponsable} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/staff/taches"
          element={
            canSeeStaff ? (
              <QuarterlyTasksPage isResponsable={isResponsable} />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/responsable/auth-logs"
          element={
            isResponsable ? (
              <ResponsableAuthLogsPage />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/moderation/casiers"
          element={
            canSeeOperateur ? (
              <ModerationCasierPage />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/animateur/projects"
          element={
            canSeeAnimateur ? (
              <ProjectsListPage
                helper={helper}
                isResponsable={isResponsable}
                isResponsableGlobal={isResponsable}
              />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/animateur/projects/:projectId"
          element={
            canSeeAnimateur ? (
              <ProjectDetailPage
                helper={helper}
                isResponsable={isResponsable}
                isResponsableGlobal={isResponsable}
              />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route
          path="/animateur/calendrier"
          element={
            canSeeAnimateur ? (
              <ProjectCalendarPage
                helper={helper}
                isResponsable={isResponsable}
                isResponsableGlobal={isResponsable}
              />
            ) : (
              <Navigate to={defaultRoute} replace />
            )
          }
        />

        <Route path="*" element={<Navigate to={defaultRoute} replace />} />
      </Routes>
    </AppShell>
  );
}

export default function App() {
  const [session, setSession] = useState(null);

  const loadSession = useCallback(async () => {
    const response = await api.get("/auth/session", {
      params: { refresh: Date.now() },
    });
    setSession(response.data);
    return response.data;
  }, []);

  useEffect(() => {
    loadSession().catch(() => {
      setSession({ authenticated: false });
    });
  }, [loadSession]);

  useEffect(() => {
    if (!session?.authenticated) return undefined;

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        loadSession().catch(() => undefined);
      }
    };

    const refreshInterval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        loadSession().catch(() => undefined);
      }
    }, 5 * 60 * 1000);

    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);

    return () => {
      window.clearInterval(refreshInterval);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [session?.authenticated, loadSession]);

  if (!session) {
    return <div className="app-loading">Initialisation d’Iris</div>;
  }

  return (
    <div className="App" data-testid="iris-app">
      <BrowserRouter>
        {session.authenticated ? (
          <AuthenticatedApp
            helper={session.helper}
            isAdmin={session.is_admin}
            isStaff={session.is_staff}
            isHelper={session.is_helper}
            isResponsable={session.is_responsable}
            isOperateur={session.is_operateur}
            isAnimateur={session.is_animateur}
            onSessionRefresh={loadSession}
          />
        ) : (
          <LoginPage />
        )}
      </BrowserRouter>
      <Toaster theme="light" position="bottom-right" />
    </div>
  );
}
