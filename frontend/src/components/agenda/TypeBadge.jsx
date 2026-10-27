import { Ban, CalendarClock, CircleCheck, Clock, History, PenLine } from "lucide-react";

import "@/Agenda.css";

import { ABSENCE_PHASES, MEETING_PHASES, typeLabel, typeMeta } from "./agendaConstants";

const PHASE_ICONS = {
  meeting: { a_venir: CalendarClock, a_rediger: PenLine, redige: CircleCheck, annulee: Ban },
  absence: { en_cours: Clock, a_venir: CalendarClock, passee: History },
};

function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

function iconSize(size) {
  return size === "sm" ? 12 : 14;
}

// Classe de couleur d'un type (ag-type--<type>) : pose les variables --ag-type-bg / -line / -ink.
export function typeClass(type) {
  return `ag-type--${typeMeta(type).slug}`;
}

// Icône lucide d'un type (repli sur « autre »).
export function TypeIcon({ type, size = 14, className }) {
  const Icon = typeMeta(type).icon;
  return <Icon size={size} className={className} aria-hidden="true" focusable="false" />;
}

// Puce de couleur d'un type (filtres, légendes). Décorative : le libellé est toujours écrit à côté.
export function TypeDot({ type, className = "" }) {
  return <span className={joinClasses("ag-chip-dot", typeClass(type), className)} aria-hidden="true" />;
}

// Pastille générique (.ag-pill) : `tone` = neutral | white | danger, ou une classe de type/phase via className.
export function Pill({ icon: Icon = null, tone = "", size = "md", title, className = "", children }) {
  return (
    <span
      className={joinClasses("ag-pill", tone ? `ag-pill--${tone}` : "", size === "sm" ? "ag-pill--sm" : "", className)}
      title={title}
    >
      {Icon ? <Icon size={iconSize(size)} aria-hidden="true" focusable="false" /> : null}
      <span className="ag-pill-text">{children}</span>
    </span>
  );
}

// Pastille de type : icône + texte (la couleur n'est jamais le seul signe).
export default function TypeBadge({
  type,
  customLabel = null,
  label = null,
  size = "md",
  showIcon = true,
  strike = false,
  title,
  className = "",
}) {
  const meta = typeMeta(type);
  const text = label || typeLabel(type, customLabel);
  return (
    <Pill
      icon={showIcon ? meta.icon : null}
      size={size}
      title={title}
      className={joinClasses(meta.pillClass, strike ? "ag-strike" : "", className)}
    >
      {text}
    </Pill>
  );
}

// Pastille de phase : réunion (a_venir, a_rediger, redige, annulee) ou absence (en_cours, a_venir, passee).
export function PhaseBadge({ phase, kind = "meeting", label = null, size = "md", showIcon = true, title, className = "" }) {
  const phases = kind === "absence" ? ABSENCE_PHASES : MEETING_PHASES;
  const meta = phases[phase];
  if (!meta) return null;
  const Icon = showIcon ? PHASE_ICONS[kind === "absence" ? "absence" : "meeting"][phase] || null : null;
  return (
    <Pill icon={Icon} size={size} title={title} className={joinClasses(`ag-pill--${meta.slug}`, className)}>
      {label || meta.label}
    </Pill>
  );
}

export { TypeBadge };
