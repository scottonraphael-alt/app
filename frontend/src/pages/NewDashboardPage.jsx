import CaseworkDashboardLinks from "../components/casework/CaseworkDashboardLinks";
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  Megaphone,
  KeyRound,
  Archive,
  CalendarDays,
  FileText,
  ShieldCheck,
  Users,
  Gauge,
  ClipboardList,
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

  return (
    <section
      className="nd-page"
      data-testid="new-dashboard-page"
    >
      {/* Titre, accès et compte utilisateur */}
      <header className="nd-header">
        <div className="nd-heading">
          <p className="nd-eyebrow">ESPACE IRIS</p>

          <h1>Bienvenue {pseudo}</h1>

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

      {canSeeStaff && (
        <div className="hm-widgets">
          <MyDayWidget day={myDay} />
          <TeamOnlineWidget helperId={helper?.id} enabled={canSeeStaff} />
        </div>
      )}

      {(isStaff || isResponsable || isServerAdmin) && <section className="nd-casework-module" aria-labelledby="member-casework-title"><h2 id="member-casework-title">Dossiers des membres</h2><p>Retrouvez les échanges privés et les formulaires, de leur ouverture à leur archivage.</p><CaseworkDashboardLinks isStaff={isStaff} isResponsable={isResponsable} isServerAdmin={isServerAdmin}/><Link className="nd-responsable-link" to="/staff/verifications">Formulaires d’admission <ArrowRight size={18}/></Link></section>}
      {/* Espace réservé aux responsables */}
      {isResponsable && (
        <section
          className="nd-responsable-banner"
          aria-labelledby="nd-responsable-title"
        >
          <div className="nd-responsable-content">
            <p className="nd-responsable-eyebrow">
              ESPACE RESPONSABLE
            </p>

            <h2 id="nd-responsable-title">
              Veiller au bon fonctionnement d’Iris.
            </h2>

            <p className="nd-responsable-description">
              Consultez les journaux d’accès et retrouvez les
              sauvegardes des salons Discord.
            </p>
          </div>

          <nav
            className="nd-responsable-actions"
            aria-label="Outils du responsable"
          >
            <Link to="/responsable/commandes-discord" className="nd-responsable-link"><KeyRound size={18}/><span>Descriptions des commandes Discord</span><ArrowRight size={18}/></Link>
            <Link to="/responsable/moderation-ia" className="nd-responsable-link"><KeyRound size={18}/><span>Prompt de modération IA</span><ArrowRight size={18}/></Link>
            <Link to="/responsable/parcours-discord" className="nd-responsable-link"><KeyRound size={18}/><span>Parcours Discord et rôles</span><ArrowRight size={18}/></Link>
            <Link to="/responsable/acces-sanctions" className="nd-responsable-link">
              <KeyRound size={18} aria-hidden="true" />
              <span>Codes d’accès modération</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
            <Link to="/responsable/annonces" className="nd-responsable-link">
              <Megaphone size={18} aria-hidden="true" />
              <span>Composer une annonce Discord</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>

            <Link to="/responsable/statistiques" className="nd-responsable-link">
              <BarChart3 size={18} aria-hidden="true" />
              <span>Statistiques du serveur</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>

            <Link
              to="/responsable/auth-logs"
              className="nd-responsable-link"
            >
              <FileText size={18} aria-hidden="true" />
              <span>Logs d’authentification</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>

            <Link to="/responsable/charge" className="nd-responsable-link">
              <Gauge size={18} aria-hidden="true" />
              <span>Charge du staff</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>

            <Link to="/responsable/rapports" className="nd-responsable-link">
              <ClipboardList size={18} aria-hidden="true" />
              <span>Rapport mensuel</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>

            <Link
              to="/responsable/archives-salons"
              className="nd-responsable-link"
            >
              <Archive size={18} aria-hidden="true" />
              <span>Sauvegardes de salons</span>
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          </nav>
        </section>
      )}

      {/* Accès principaux selon les rôles */}
      {quickCards.length > 0 && (
        <nav
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
        </nav>
      )}

      {/* Mes engagements trimestriels */}
      {canSeeStaff && (
        <QuarterlyDashboardModule helper={helper} />
      )}

      {/* Suivis et outils d’accompagnement */}
      {canSeeHelperModule && (
        <HelperDashboardModule
          tickets={tickets}
          helper={helper}
          isAdmin={isAdmin}
        />
      )}

      {/* Projets animateur et tâches personnelles */}
      {canSeeAnimateur && (
        <AnimateurDashboardModule helper={helper} />
      )}

      
    </section>
  );
}
