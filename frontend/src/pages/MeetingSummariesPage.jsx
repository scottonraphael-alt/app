import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarPlus } from "lucide-react";

import "@/Agenda.css";
import "@/components/agenda/meetings/meetings.css";

import AgendaHomeLink from "@/components/agenda/AgendaHomeLink";
import useAgendaNoNav from "@/components/agenda/useAgendaNoNav";
import { agendaQueries } from "@/components/agenda/agendaApi";
import { isForbidden } from "@/components/agenda/agendaErrors";
import { resolveToday } from "@/components/agenda/dateUtils";
import MeetingDialog from "@/components/agenda/meetings/MeetingDialog";
import MeetingsListPanel from "@/components/agenda/meetings/MeetingsListPanel";
import { MeetingsForbidden } from "@/components/agenda/meetings/MeetingsStates";
import NextMeetingCard from "@/components/agenda/meetings/NextMeetingCard";
import OpenActionsPanel from "@/components/agenda/meetings/OpenActionsPanel";
import ToWriteCard from "@/components/agenda/meetings/ToWriteCard";

export default function MeetingSummariesPage({ isResponsable }) {
  useAgendaNoNav();
  const [searchParams, setSearchParams] = useSearchParams();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [phase, setPhase] = useState("");
  const listRef = useRef(null);

  const overviewQuery = useQuery(agendaQueries.meetingsOverview());
  const overview = overviewQuery.data || null;
  const today = resolveToday(overview?.today);
  const canManage = Boolean(isResponsable) || Boolean(overview?.viewer?.is_responsable);
  const overviewLoading = overviewQuery.isPending;
  const overviewError = overviewQuery.isError && !overview ? overviewQuery.error : null;
  const retryOverview = useCallback(() => overviewQuery.refetch(), [overviewQuery]);

  // Ancienne route /staff/meetings/new → ?nouvelle=1 : ouvre la fenêtre (responsables), puis retire le paramètre.
  // On attend la vue d'ensemble pour que la date proposée soit celle du serveur.
  const wantsNew = searchParams.get("nouvelle") === "1";
  useEffect(() => {
    if (!wantsNew || overviewLoading) return;
    if (canManage) setDialogOpen(true);
    setSearchParams(
      (params) => {
        const next = new URLSearchParams(params);
        next.delete("nouvelle");
        return next;
      },
      { replace: true },
    );
  }, [wantsNew, overviewLoading, canManage, setSearchParams]);

  const openDialog = useCallback(() => setDialogOpen(true), []);

  const showToWrite = useCallback(() => {
    setPhase("a_rediger");
    const node = listRef.current;
    if (node) {
      node.scrollIntoView({ behavior: "smooth", block: "start" });
      node.focus({ preventScroll: true });
    }
  }, []);

  if (isForbidden(overviewQuery.error)) {
    return (
      <main className="ag-page ag-meetings" data-testid="meetings-page">
        <header className="ag-header">
          <div>
            <p className="ag-eyebrow">Espace staff</p>
            <h1>Réunions</h1>
          </div>
          <div className="ag-header-actions">
            <AgendaHomeLink />
          </div>
        </header>
        <MeetingsForbidden />
      </main>
    );
  }

  return (
    <main className="ag-page ag-meetings" data-testid="meetings-page">
      <header className="ag-header">
        <div>
          <p className="ag-eyebrow">Espace staff</p>
          <h1>Réunions</h1>
          <p className="ag-intro">
            Préparez l'ordre du jour, rédigez le compte-rendu et suivez les décisions de l'équipe.
          </p>
        </div>
        <div className="ag-header-actions">
          <AgendaHomeLink />
          {canManage ? (
            <button type="button" className="ag-button" onClick={openDialog}>
              <CalendarPlus size={16} aria-hidden="true" />
              Nouvelle réunion
            </button>
          ) : null}
        </div>
      </header>

      <div className="ag-meet-top">
        <NextMeetingCard
          meeting={overview?.next_meeting || null}
          today={today}
          loading={overviewLoading}
          error={overviewError}
          onRetry={retryOverview}
          canManage={canManage}
          onPlan={openDialog}
        />
        <ToWriteCard
          meetings={overview?.to_write}
          count={overview?.counts?.a_rediger}
          today={today}
          loading={overviewLoading}
          error={overviewError}
          onRetry={retryOverview}
          onShowAll={showToWrite}
        />
      </div>

      <div className="ag-meet-stack">
        <OpenActionsPanel
          actions={overview?.open_actions}
          counts={overview?.counts}
          today={today}
          loading={overviewLoading}
          error={overviewError}
          onRetry={retryOverview}
        />
        <MeetingsListPanel
          phase={phase}
          onPhaseChange={setPhase}
          canManage={canManage}
          onPlan={openDialog}
          panelRef={listRef}
        />
      </div>

      {canManage ? <MeetingDialog open={dialogOpen} onOpenChange={setDialogOpen} today={today} /> : null}
    </main>
  );
}
