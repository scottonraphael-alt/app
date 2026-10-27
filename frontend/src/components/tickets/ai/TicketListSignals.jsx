import CrisisBadge from "./CrisisBadge";
import { presenceLabel } from "./PresenceAvatars";
import "./ai.css";

/** Badge de crise + point de présence pour une ligne de la liste. */
export default function TicketListSignals({ crisis, viewers = [] }) {
  const label = presenceLabel(viewers);
  if (!crisis && !viewers.length) return null;
  return (
    <span className="tai-list-signals">
      {crisis && <CrisisBadge level={crisis.level} acknowledged={crisis.acknowledged} />}
      {viewers.length > 0 && (
        <span className={`tai-dot${viewers.some((v) => v.typing) ? " is-typing" : ""}`} role="img" aria-label={label} title={label} data-testid="presence-dot" />
      )}
    </span>
  );
}
