import { useState } from "react";

import "@/Agenda.css";

import { helperName } from "./calendarModel";

const MIN_SIZE = 18;
const MAX_SIZE = 40;

// Teintes de la charte pour les initiales (fond, texte), choisies d'après l'identifiant.
const INITIAL_TONES = [
  ["#e8efea", "#4a675c"],
  ["#e9eff9", "#49658d"],
  ["#ebdff5", "#765094"],
  ["#fbefd9", "#88672e"],
  ["#f7e9e2", "#945b46"],
  ["#f0f1ee", "#64706a"],
];

function clampSize(size) {
  const value = Number(size);
  if (!Number.isFinite(value)) return 30;
  return Math.min(MAX_SIZE, Math.max(MIN_SIZE, Math.round(value)));
}

function toneFor(person) {
  const key = String(person?.id || person?.username || helperName(person));
  let hash = 0;
  for (const char of key) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
  return INITIAL_TONES[hash % INITIAL_TONES.length];
}

function safeImageUrl(url) {
  if (typeof url !== "string") return "";
  const value = url.trim();
  return /^(https?:)?\/\//i.test(value) || value.startsWith("/") ? value : "";
}

// Première lettre (ou chiffre) du nom affiché, en majuscule.
export function avatarInitial(person) {
  const match = /[\p{L}\p{N}]/u.exec(helperName(person));
  return match ? match[0].toUpperCase() : "?";
}

// « Inès », « Inès et Lou », « Inès, Lou et Sacha », « Inès, Lou, Sacha, Noé et 2 autres »
export function peopleSummary(people, max = 4) {
  const list = Array.isArray(people) ? people.filter(Boolean) : [];
  if (!list.length) return "";
  const names = list.map((person) => helperName(person));
  if (names.length <= max) {
    if (names.length === 1) return names[0];
    return `${names.slice(0, -1).join(", ")} et ${names[names.length - 1]}`;
  }
  const rest = names.length - max;
  return `${names.slice(0, max).join(", ")} et ${rest} ${rest > 1 ? "autres" : "autre"}`;
}

// Avatar rond : image Discord, ou initiale si l'image manque ou ne se charge pas.
export default function HelperAvatar({ person, size = 30, decorative = false, title, className = "" }) {
  const [failedUrl, setFailedUrl] = useState("");
  const pixels = clampSize(size);
  const name = helperName(person);
  const url = safeImageUrl(person?.avatar_url);
  const showImage = Boolean(url) && url !== failedUrl;
  const [background, ink] = toneFor(person);
  const style = {
    width: pixels,
    height: pixels,
    fontSize: Math.max(9, Math.round(pixels * 0.42)),
    "--ag-avatar-bg": background,
    "--ag-avatar-ink": ink,
  };
  const classes = ["ag-avatar", className].filter(Boolean).join(" ");

  if (showImage) {
    return (
      <span className={classes} style={style} title={title} aria-hidden={decorative ? "true" : undefined}>
        <img
          src={url}
          alt={decorative ? "" : name}
          width={pixels}
          height={pixels}
          loading="lazy"
          decoding="async"
          draggable={false}
          referrerPolicy="no-referrer"
          onError={() => setFailedUrl(url)}
        />
      </span>
    );
  }

  return (
    <span
      className={classes}
      style={style}
      title={title}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : name}
      aria-hidden={decorative ? "true" : undefined}
    >
      {avatarInitial(person)}
    </span>
  );
}

// Pile d'avatars : `max` visibles puis « +N ». Un seul libellé pour le lecteur d'écran.
export function AvatarStack({ people, max = 4, size = 26, label, className = "" }) {
  const list = Array.isArray(people) ? people.filter(Boolean) : [];
  if (!list.length) return null;
  const visible = list.slice(0, Math.max(1, max));
  const hidden = list.length - visible.length;
  const summary = peopleSummary(list, Math.max(1, max));
  const pixels = clampSize(size);
  return (
    <span
      className={["ag-avatar-stack", className].filter(Boolean).join(" ")}
      role="img"
      aria-label={label || summary}
      title={summary}
    >
      {visible.map((person, index) => (
        <HelperAvatar key={person.id || `${helperName(person)}-${index}`} person={person} size={pixels} decorative />
      ))}
      {hidden > 0 ? (
        <span className="ag-avatar-more" style={{ height: pixels, minWidth: pixels }} aria-hidden="true">
          +{hidden}
        </span>
      ) : null}
    </span>
  );
}

// Avatar + nom sur une ligne (.ag-person). `suffix` s'affiche après le nom (pastille, mention…).
export function PersonLabel({ person, size = 24, suffix = null, className = "" }) {
  return (
    <span className={["ag-person", className].filter(Boolean).join(" ")}>
      <HelperAvatar person={person} size={size} decorative />
      <span className="ag-person-name">{helperName(person)}</span>
      {suffix}
    </span>
  );
}

export { HelperAvatar };
