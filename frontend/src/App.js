import { useEffect, useState } from "react";
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

function AuthenticatedApp({ helper, isAdmin, isStaff, isHelper, isResponsable, isAnimateur }) {
  const [tickets, setTickets] = useState([]);
  const [stats, setStats] = useState({ active_count: 0, archived_count: 0, total_messages: 0 });

  const canSeeHelper = isResponsable || isAdmin || isHelper;
  const canSeeAdmin = isResponsable || isAdmin;
  const canSeeStaff = isResponsable || isAdmin || isHelper || isStaff;
  const canSeeAnimateur = isAnimateur || isResponsable;

  const refreshDashboard = async () => {
    const [ticketsResponse, statsResponse] = await Promise.all([api.get("/tickets"), api.get("/tickets/stats")]);
    setTickets(ticketsResponse.data);
    setStats(statsResponse.data);
  };

  useEffect(() => {
    if (canSeeHelper) {
      refreshDashboard().catch(() => undefined);
    }
  }, [canSeeHelper]);

  const updateTicket = (ticket) => {
    setTickets((current) => [ticket, ...current.filter((item) => item.id !== ticket.id)]);
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

  const defaultRoute = canSeeHelper ? "/" : "/staff/calendrier";

  return (
    <AppShell
      helper={helper}
      tickets={tickets}
      onLogout={logout}
      isResponsable={isResponsable}
      isAdmin={isAdmin}
      isHelper={isHelper}
      isStaff={isStaff}
      isAnimateur={isAnimateur}
    >
      <Routes>
        <Route
          path="/"
          element={canSeeHelper ? <DashboardPage stats={stats} tickets={tickets} /> : <Navigate to="/staff/calendrier" replace />}
        />
        <Route
          path="/new"
          element={canSeeHelper ? <NewTicketPage onCreated={updateTicket} /> : <Navigate to="/staff/calendrier" replace />}
        />
        <Route
          path="/staff/taches"
          element={isStaff ? <QuarterlyTasksPage isResponsable={isResponsable} /> : <Navigate to="/" replace />}
        />
        <Route
          path="/tickets/:ticketId"
          element={
            canSeeHelper ? (
              <TicketWorkspacePage onTicketUpdate={updateTicket} onTicketDeleted={deleteTicket} isAdmin={isAdmin} helper={helper} />
            ) : (
              <Navigate to="/staff/calendrier" replace />
            )
          }
        />
        <Route
          path="/archives"
          element={
            canSeeHelper ? (
              <DashboardPage stats={stats} tickets={tickets.filter((ticket) => ticket.status === "archived")} />
            ) : (
              <Navigate to="/staff/calendrier" replace />
            )
          }
        />
        <Route path="/admin" element={canSeeAdmin ? <AdminDashboardPage /> : <Navigate to={defaultRoute} replace />} />
        <Route path="/profile" element={<HelperProfilePage helper={helper} />} />
        <Route
          path="/resources"
          element={canSeeHelper ? <ResourcesPage isAdmin={isAdmin} /> : <Navigate to="/staff/calendrier" replace />}
        />
        <Route
          path="/staff/calendrier"
          element={canSeeStaff ? <AbsenceCalendarPage isResponsable={isResponsable} /> : <Navigate to={defaultRoute} replace />}
        />
        <Route
          path="/staff/meetings"
          element={canSeeStaff ? <MeetingSummariesPage isResponsable={isResponsable} /> : <Navigate to={defaultRoute} replace />}
        />
        <Route
          path="/staff/meetings/new"
          element={canSeeStaff && isResponsable ? <MeetingSummaryEditorPage /> : <Navigate to="/staff/meetings" replace />}
        />
        <Route
          path="/staff/meetings/:meetingId"
          element={canSeeStaff ? <MeetingSummaryEditorPage isResponsable={isResponsable} /> : <Navigate to={defaultRoute} replace />}
        />
<Route path="/responsable/auth-logs" element={<ResponsableAuthLogsPage />} />
            

            <Route path="/moderation/casiers" element={<ModerationCasierPage />} />
      <Route path="/animateur/projects" element={canSeeAnimateur ? <ProjectsListPage isResponsable={isResponsable} helper={helper} /> : <Navigate to="/" replace />} />
        <Route path="/animateur/projects/:projectId" element={canSeeAnimateur ? (<ProjectDetailPage isResponsable={isResponsable} helper={helper} isResponsableGlobal={isResponsable} />) : (<Navigate to="/" replace />)}/>
        <Route
          path="/animateur/calendrier"
          element={
            canSeeAnimateur ? (
              <ProjectCalendarPage isResponsable={isResponsable} helper={helper} isResponsableGlobal={isResponsable} />
            ) : (
              <Navigate to="/" replace />
            )
          }
        />

            
      </Routes>
    </AppShell>
  );
}

function App() {
  const [session, setSession] = useState(null);

  useEffect(() => {
    document.documentElement.removeAttribute("data-theme");
    localStorage.removeItem("iris-theme");
  }, []);

  useEffect(() => {
    api
      .get("/auth/session")
      .then((response) => setSession(response.data))
      .catch(() => setSession({ authenticated: false }));
  }, []);

  if (!session) {
    return <div className="app-loading" data-testid="application-loading">Initialisation d'Iris</div>;
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
            isAnimateur={session.is_animateur}
          />
        ) : (
          <LoginPage />
        )}
        <Toaster theme="light" position="bottom-right" />
      </BrowserRouter>
    </div>
  );
}

export default App;
