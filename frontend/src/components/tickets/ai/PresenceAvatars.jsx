import { resolveAvatarUrl } from "../../../utils/avatar";
import "./ai.css";

export function presenceLabel(viewers) {
  const writing = viewers.filter((v) => v.typing).map((v) => v.name || "Quelqu’un");
  const reading = viewers.filter((v) => !v.typing).map((v) => v.name || "Quelqu’un");
  const parts = [];
  if (writing.length) parts.push(`${writing.join(", ")} écrit…`);
  if (reading.length) parts.push(`${reading.join(", ")} consulte`);
  return parts.join(" · ");
}

export default function PresenceAvatars({ viewers = [] }) {
  if (!viewers.length) return null;
  return (
    <div className="tai-presence" role="status" aria-live="polite" data-testid="presence-avatars">
      <span className="tai-avatars">
        {viewers.slice(0, 4).map((viewer) => (
          <span key={viewer.user_id} className={`tai-avatar${viewer.typing ? " is-typing" : ""}`} title={viewer.name}>
            {viewer.avatar_url
              ? <img src={resolveAvatarUrl(viewer.avatar_url)} alt="" />
              : (viewer.name || "?").slice(0, 1).toUpperCase()}
          </span>
        ))}
      </span>
      <span>{presenceLabel(viewers)}</span>
    </div>
  );
}
