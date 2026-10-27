import { TriangleAlert } from "lucide-react";

import "./meeting.css";

import { helperName } from "../calendarModel";
import { formatInstantTime } from "../dateUtils";

function conflictText(conflict) {
  const who = conflict?.updatedBy ? helperName(conflict.updatedBy) : "";
  const time = conflict?.updatedAt ? formatInstantTime(conflict.updatedAt) : "";
  const by = who ? ` par ${who}` : " par quelqu'un d'autre";
  const when = time ? ` à ${time}` : "";
  return { text: `Ce compte-rendu a été modifié${by}${when}.` };
}

// Conflit de révision (409) : l'enregistrement est arrêté tant que la personne n'a pas choisi.
export default function ConflictBanner({ conflict, busy = false, onReload, onKeep }) {
  const { text } = conflictText(conflict);
  return (
    <div className="ag-callout ag-callout--warning ag-meeting-banner ag-meeting-conflict" role="alert">
      <TriangleAlert size={17} aria-hidden="true" />
      <div className="ag-meeting-banner-body">
        <p>
          <strong>{text}</strong>
        </p>
        <p>
          Vos modifications ne sont pas encore enregistrées. Rechargez leur version (votre brouillon reste dans ce
          navigateur) ou gardez la vôtre pour écraser les changements de l'autre personne.
        </p>
      </div>
      <div className="ag-meeting-banner-actions">
        <button type="button" className="ag-button ag-button--secondary ag-button--small" onClick={onReload} disabled={busy}>
          Recharger leur version
        </button>
        <button type="button" className="ag-button ag-button--small" onClick={onKeep} disabled={busy}>
          Garder ma version
        </button>
      </div>
    </div>
  );
}

export { ConflictBanner };
