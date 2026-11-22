import DashboardBoard from "../components/dashboard/DashboardBoard";
import ResponsableToolsModule from "../components/responsable/ResponsableToolsModule";
import CaseworkDashboardLinks from "../components/casework/CaseworkDashboardLinks";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  FileText,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import QuarterlyDashboardModule from "../components/QuarterlyDashboardModule";
import HelperDashboardModule from "../components/HelperDashboardModule";
import AnimateurDashboardModule from "../components/AnimateurDashboardModule";
import HomeGreeting from "../components/home/HomeGreeting";
import MyDayWidget from "../components/home/MyDayWidget";
import TeamOnlineWidget from "../components/home/TeamOnlineWidget";
import useMyDay from "../components/home/useMyDay";
import { summaryFor } from "../components/home/homeUtils";

import "../NewDashboard.css";

function localDateKey() {
  const now = new Date();

  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
}

export default function NewDashboardPage({
  tickets = [],
  helper,
  isAdmin = false,
  isStaff = false,
  isHelper = false,
  isResponsable = false,
  isOperateur = false,
  isAnimateur = false,
  isAdjoint = false,
  isServerAdmin = false,
}) {
  useEffect(() => {
    document.body.classList.add("dashboard-no-nav");

    return () => {
      document.body.classList.remove("dashboard-no-nav");
    };
  }, []);

  const pseudo =
    helper?.global_name ||
    helper?.display_name ||
    helper?.username ||
    "toi";

  const canSeeHelperModule = isHelper || isAdmin;
  const canSeeModeration = isOperateur || isResponsable;
  const canSeeAnimateur = isAnimateur || isResponsable;

  const canSeeStaff =
    isStaff ||
    isResponsable ||
    isAdmin ||
    isHelper ||
    isOperateur;

  const myDay = useMyDay(helper?.id, canSeeStaff);
  const daySummary =
    canSeeStaff && !myDay.isLoading && !myDay.isError ? summaryFor(myDay.counts) : "";

  const absencesQuery = useQuery({
    queryKey: ["dashboard", "absences", helper?.id],
    enabled: Boolean(helper?.id && canSeeStaff),
    queryFn: async ({ signal }) => {
      const response = await api.get("/staff/calendrier", {
        signal,
      });

      if (!Array.isArray(response.data)) {
        throw new Error("Format de réponse inattendu pour les absences.");
      }

      return response.data;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const today = localDateKey();

  const currentAbsence = absencesQuery.data?.find(
    (absence) =>
      String(absence.helper?.id) === String(helper?.id) &&
      absence.start_date <= today &&
      absence.end_date >= today
  );

  let presenceLabel = "Statut indisponible";
  let presenceState = "unknown";

  if (canSeeStaff && absencesQuery.isPending) {
    presenceLabel = "Vérification du statut…";
  } else if (
    canSeeStaff &&
    absencesQuery.isSuccess &&
    !absencesQuery.isError
  ) {
    presenceLabel = currentAbsence
      ? "En absence"
      : "Aucune absence déclarée";

    presenceState = currentAbsence ? "away" : "available";
  }

const pills = [
  isResponsable && {
    label: "Responsable",
    tone: "responsable",
  },
  isAdjoint && {
    label: "Adjoint",
    tone: "adjoint",
  },
  isAdmin && {
    label: "Coordinateur",
    tone: "admin",
  },
  (isOperateur || isStaff) && {
    label: "Opérateur",
    tone: "operateur",
  },
  isHelper && {
    label: "Helper",
    tone: "helper",
  },
  isAnimateur && {
    label: "Animateur",
    tone: "animateur",
  },
].filter(Boolean);

  const quickCards = [
    canSeeModeration && {
      to: "/moderation/casiers",
      title: "Accéder au casier",
      description:
        "Consulter les dossiers et les historiques de modération.",
      tone: "red",
      Icon: ShieldCheck,
    },
    canSeeStaff && {
      to: "/staff/meetings",
      title: "Voir les réunions passées",
      description:
        "Retrouver les comptes-rendus et les documents partagés.",
      tone: "blue",
      Icon: FileText,
    },
    canSeeStaff && {
      to: "/staff/calendrier",
      title: "Calendrier",
      description:
        "Consulter les absences et déclarer une indisponibilité.",
      tone: "white",
      Icon: CalendarDays,
    },
  ].filter(Boolean);

  const widgets = [
    canSeeStaff && {id:'day',label:'Ma journée',width:8,content:<MyDayWidget day={myDay}/>},
    canSeeStaff && {id:'team',label:'Équipe en ligne',width:4,content:<TeamOnlineWidget helperId={helper?.id} enabled={canSeeStaff}/>},
    (isStaff || isResponsable || isServerAdmin) && {id:'casework',label:'Dossiers des membres',width:12,content:<section className="nd-casework-module" aria-labelledby="member-casework-title"><p className="iris-section-kicker">CHAQUE ÉCHANGE À SA PLACE</p><h2 id="member-casework-title">Dossiers des membres</h2><p>Retrouvez les échanges privés et les formulaires, de leur ouverture à leur archivage.</p><CaseworkDashboardLinks isStaff={isStaff} isResponsable={isResponsable} isServerAdmin={isServerAdmin}/></section>},
    {id:'music',label:'Karaoké & blind test',width:12,content:<nav className="nd-helper-v2-shortcuts" aria-label="Animations musicales"><Link to="/karaoke" className="nd-helper-v2-shortcut nd-helper-v2-shortcut--clay"><span className="nd-helper-v2-shortcut-copy"><strong>🎤 Karaoké & blind test</strong><small>Chanter ensemble, réserver une chanson et jouer avec OasisLink.</small></span><ArrowRight size={18}/></Link></nav>},
    isResponsable && {id:'responsable',label:'Outils responsable',width:12,content:<ResponsableToolsModule/>},
    quickCards.length>0 && {id:'shortcuts',label:'Accès principaux',width:12,content:(        <nav
          className="nd-shortcuts"
          aria-label="Accès principaux"
        >
          {quickCards.map(
            ({ to, title, description, tone, Icon }) => (
              <Link
                key={to}
                to={to}
                className={`nd-shortcut nd-shortcut--${tone}`}
              >
                <span className="nd-shortcut-icon">
                  <Icon size={23} aria-hidden="true" />
                </span>

                <h2>{title}</h2>
                <p>{description}</p>

                <span className="nd-shortcut-footer">
                  Ouvrir
                  <ArrowRight size={18} aria-hidden="true" />
                </span>
              </Link>
            )
          )}
        </nav>)},
    canSeeStaff && {id:'quarterly',label:'Engagements trimestriels',width:12,content:<QuarterlyDashboardModule helper={helper}/>},
    canSeeHelperModule && {id:'helper',label:'Mon espace helper',width:12,content:<HelperDashboardModule tickets={tickets} helper={helper} isAdmin={isAdmin}/>},
    canSeeAnimateur && {id:'animateur',label:'Mon espace animateur',width:12,content:<AnimateurDashboardModule helper={helper}/>},
  ].filter(Boolean);

  return (
    <section
      className="nd-page"
      data-testid="new-dashboard-page"
    >
      {/* Titre, accès et compte utilisateur */}
      <header className="nd-header">
        <div className="nd-heading">
          <p className="nd-eyebrow">ESPACE IRIS</p>

          <p className="nd-welcome">Bienvenue {pseudo}</p>
          <h1>On prend <span className="iris-title-accent">le relais.</span></h1>

          <HomeGreeting pseudo={pseudo} summary={daySummary} />

          {pills.length > 0 && (
            <div className="nd-pills" aria-label="Vos accès">
              {pills.map((pill) => (
                <span
                  key={pill.label}
                  className={`nd-pill nd-pill--${pill.tone}`}
                >
                  {pill.label}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="nd-account-actions">
          {canSeeStaff ? (
            <Link
              to="/staff/calendrier"
              className={`nd-presence nd-presence--${presenceState}`}
              title="Ouvrir le calendrier des absences"
            >
              <span
                className="nd-presence-dot"
                aria-hidden="true"
              />

              <span aria-live="polite">
                {presenceLabel}
              </span>

              <CalendarDays size={17} aria-hidden="true" />
            </Link>
          ) : (
            <span className="nd-presence nd-presence--unknown">
              Statut d’absence non accessible
            </span>
          )}

          <Link
            to="/profile"
            className="nd-profile-button"
          >
            Modifier mon profil
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <DashboardBoard key={helper?.id || "anonymous"} userId={helper?.id} widgets={widgets}/>

      
    </section>
  );
}
