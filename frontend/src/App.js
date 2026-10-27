import { useCallback, useEffect, useState, Suspense, lazy } from "react";
import "@/App.css";
import "@/MentalHealth.css";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api/client";
import AppShell from "./components/AppShell";
import ActivityPage from "./pages/ActivityPage";
const NewDashboardPage = lazy(() => import("./pages/NewDashboardPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const AdminDashboardPage = lazy(() => import("./pages/AdminDashboardPage"));
const HelperProfilePage = lazy(() => import("./pages/HelperProfilePage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const NewTicketPage = lazy(() => import("./pages/NewTicketPage"));
const ResourcesPage = lazy(() => import("./pages/ResourcesPage"));
const TicketWorkspacePage = lazy(() => import("./pages/TicketWorkspacePage"));
const AbsenceCalendarPage = lazy(() => import("./pages/AbsenceCalendarPage"));
const MeetingSummariesPage = lazy(() => import("./pages/MeetingSummariesPage"));
const MeetingSummaryEditorPage = lazy(() => import("./pages/MeetingSummaryEditorPage"));
const QuarterlyTasksPage = lazy(() => import("./pages/QuarterlyTasksPage"));
const ProjectsListPage = lazy(() => import("./pages/ProjectsListPage"));
const ProjectDetailPage = lazy(() => import("./pages/ProjectDetailPage"));
const ServerStatisticsPage = lazy(() => import("./pages/ServerStatisticsPage"));
const SanctionAccessPage = lazy(() => import("./pages/SanctionAccessPage"));
const DiscordAnnouncementsPage = lazy(() => import("./pages/DiscordAnnouncementsPage"));
const ResponsableAuthLogsPage = lazy(() => import("./pages/ResponsableAuthLogsPage"));
const ResponsableChannelArchivesPage = lazy(() => import("./pages/ResponsableChannelArchivesPage"));
const ChannelArchiveWorkspacePage = lazy(() => import("./pages/ChannelArchiveWorkspacePage"));
const ModerationCasierPage = lazy(() => import("./pages/ModerationCasierPage"));
const TicketArchivesPage = lazy(() => import("./pages/TicketArchivesPage"));

function Loading() {
  return <div className="app-loading">Chargement…</div>;
}

function AuthenticatedApp({
  helper,
  isAdmin,
  isStaff,
  isHelper,
  isResponsable,
  isOperateur,
  isAnimateur,
  isAdjoint,
  onSessionRefresh,
}) {
  const queryClient = useQueryClient();

  const canSeeHelper = isResponsable || isAdmin || isHelper;
  const canSeeAdmin = isResponsable || isAdmin;
  const canSeeStaff = isResponsable || isAdmin || isHelper || isStaff || isOperateur;
  const canSeeAnimateur = isAnimateur || isResponsable;
  const canSeeOperateur = isOperateur || isResponsable;

  const ticketsQuery = useQuery({
    queryKey: ["tickets"],
    queryFn: async () => {
      const response = await api.get("/tickets");
      return response.data;
    },
    enabled: canSeeHelper,
    refetchInterval: 30 * 1000,
  });

  const statsQuery = useQuery({
    queryKey: ["tickets", "stats"],
    queryFn: async () => {
      const response = await api.get("/tickets/stats");
      return response.data;
    },
    enabled: canSeeHelper,
    refetchInterval: 30 * 1000,
  });

  const tickets = ticketsQuery.data || [];
  const stats = statsQuery.data || {
    active_count: 0,
    archived_count: 0,
    total_messages: 0,
  };

  const updateTicket = (ticket) => {
    queryClient.setQueryData(["tickets"], (current) => [
      ticket,
      ...(current || []).filter((item) => item.id !== ticket.id),
    ]);
    queryClient.invalidateQueries({ queryKey: ["tickets", "stats"] });
  };

  const deleteTicket = (ticketId) => {
    queryClient.setQueryData(["tickets"], (current) =>
      (current || []).filter((ticket) => ticket.id !== ticketId)
    );
    queryClient.invalidateQueries({ queryKey: ["tickets", "stats"] });
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
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route
  path="/"
  element={
    canSeeHelper ? (
      <NewDashboardPage
        stats={stats}
        tickets={tickets}
        helper={helper}
        isAdmin={isAdmin}
        isStaff={isStaff}
        isHelper={isHelper}
        isResponsable={isResponsable}
        isOperateur={isOperateur}
        isAnimateur={isAnimateur}
        isAdjoint={isAdjoint}
      />
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
  path="/suivis"
  element={
    canSeeHelper ? (
      <DashboardPage stats={stats} tickets={tickets} />
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
      <TicketArchivesPage
        tickets={tickets}
        helper={helper}
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
                <AbsenceCalendarPage isResponsable={isResponsable} currentHelperId={helper?.id} />
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
                <QuarterlyTasksPage isResponsable={isResponsable} helper={helper} />
              ) : (
                <Navigate to={defaultRoute} replace />
              )
            }
          />

          <Route path="/responsable/acces-sanctions" element={isResponsable ? <SanctionAccessPage /> : <Navigate to={defaultRoute} replace />} />
          <Route path="/responsable/annonces" element={isResponsable ? <DiscordAnnouncementsPage helper={helper} /> : <Navigate to={defaultRoute} replace />} />
          <Route path="/responsable/statistiques" element={isResponsable ? <ServerStatisticsPage /> : <Navigate to={defaultRoute} replace />} />

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
            path="/responsable/archives-salons"
            element={
              isResponsable ? (
                <ResponsableChannelArchivesPage />
              ) : (
                <Navigate to={defaultRoute} replace />
              )
            }
          />

          <Route
            path="/responsable/archives-salons/:archiveId"
            element={
              isResponsable ? (
                <ChannelArchiveWorkspacePage />
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
                <Navigate to="/staff/calendrier?categorie=taches" replace />
              ) : (
                <Navigate to={defaultRoute} replace />
              )
            }
          />

          <Route path="*" element={<Navigate to={defaultRoute} replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

// Discord ajoute ces paramètres à l'URL de l'iframe d'une Activity.
const isDiscordActivity = (() => {
  const params = new URLSearchParams(window.location.search);
  return params.has("frame_id") && params.has("instance_id");
})();

export default function App() {
  // L'Activity ne passe pas par la session IRIS : elle a sa propre vérification (serveur Discord).
  return isDiscordActivity ? <ActivityPage /> : <MainApp />;
}

function MainApp() {
  const sessionQuery = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      const response = await api.get("/auth/session", {
        params: { refresh: Date.now() },
      });
      return response.data;
    },
    retry: false,
  });

  const session = sessionQuery.data;

  useEffect(() => {
    if (!session?.authenticated) return undefined;

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        sessionQuery.refetch();
      }
    };

    const refreshInterval = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        sessionQuery.refetch();
      }
    }, 5 * 60 * 1000);

    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);

    return () => {
      window.clearInterval(refreshInterval);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [session?.authenticated, sessionQuery]);

  if (sessionQuery.isLoading || !session) {
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
            isAdjoint={session.is_adjoint}
            onSessionRefresh={() => sessionQuery.refetch()}
          />
        ) : (
          <Suspense fallback={<Loading />}>
            <LoginPage />
          </Suspense>
        )}
      </BrowserRouter>
      <Toaster theme="light" position="bottom-right" />
    </div>
  );
}
