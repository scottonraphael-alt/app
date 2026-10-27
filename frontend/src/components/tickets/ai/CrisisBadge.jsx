import { TriangleAlert } from "lucide-react";
import { CRISIS_LABELS, isCrisis } from "./crisis";
import "./ai.css";

export default function CrisisBadge({ level, acknowledged = false }) {
  if (!isCrisis(level)) return null;
  return (
    <span className={`tai-badge tai-level-${level}`} data-testid="crisis-badge">
      <TriangleAlert size={12} aria-hidden="true" />
      {CRISIS_LABELS[level]}
      {acknowledged && <span className="tai-badge-ack"> · pris en charge</span>}
    </span>
  );
}
