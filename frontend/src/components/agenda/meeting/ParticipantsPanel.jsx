import { Settings2, Users } from "lucide-react";

import "./meeting.css";

import HelperAvatar from "../HelperAvatar";
import { ATTENDANCE, ATTENDANCE_CHOICES } from "../agendaConstants";
import { helperName } from "../calendarModel";

// Participants : avatar, nom et présence (Présent · Absent · Excusé), modifiable tant que la réunion n'est pas
// verrouillée. `absentIds` : personnes dont une absence couvre le jour de la réunion.
export default function ParticipantsPanel({ participants, absentIds, readOnly, canManage, onChange, onManage }) {
  const away = new Set(absentIds || []);
  return (
    <section className="ag-panel ag-meeting-side-panel" aria-labelledby="ag-meeting-participants-title">
      <div className="ag-panel-header">
        <span className="ag-panel-icon">
          <Users size={20} aria-hidden="true" />
        </span>
        <div className="ag-panel-heading">
          <h2 id="ag-meeting-participants-title">Participants</h2>
        </div>
        <span className="ag-count">{participants.length}</span>
      </div>
      <div className="ag-panel-body ag-meeting-participants">
        {participants.length ? (
          <ul className="ag-meeting-people">
            {participants.map((person) => {
              const name = helperName(person);
              return (
                <li key={person.id} className="ag-meeting-person">
                  <HelperAvatar person={person} size={32} decorative />
                  <span className="ag-meeting-person-name">
                    {name}
                    {away.has(person.id) ? <small>Absent(e) ce jour-là</small> : null}
                  </span>
                  <div
                    className="ag-segmented ag-segmented--small"
                    role="radiogroup"
                    aria-label={`Présence de ${name}`}
                  >
                    {ATTENDANCE_CHOICES.map((choice) => (
                      <button
                        key={choice}
                        type="button"
                        role="radio"
                        aria-checked={person.attendance === choice}
                        disabled={readOnly}
                        onClick={() => onChange(person.id, person.attendance === choice ? "invite" : choice)}
                      >
                        {ATTENDANCE[choice].label}
                      </button>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="ag-meeting-empty">Aucun participant pour l'instant.</p>
        )}
        {canManage ? (
          <button type="button" className="ag-button ag-button--secondary ag-button--small" onClick={onManage}>
            <Settings2 size={14} aria-hidden="true" />
            Gérer
          </button>
        ) : null}
      </div>
    </section>
  );
}

export { ParticipantsPanel };
