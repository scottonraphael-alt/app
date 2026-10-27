import { Navigate, useParams } from "react-router-dom";

import MeetingEditor from "../components/agenda/meeting/MeetingEditor";

// Page d'une réunion (/staff/meetings/:meetingId). La création passe par la fenêtre « Nouvelle réunion » de la
// page Réunions : /staff/meetings/new (route statique, sans paramètre) y redirige.
export default function MeetingSummaryEditorPage({ isResponsable }) {
  const { meetingId } = useParams();
  if (!meetingId || meetingId === "new") {
    return <Navigate to="/staff/meetings?nouvelle=1" replace />;
  }
  return <MeetingEditor key={meetingId} meetingId={meetingId} isResponsable={isResponsable} />;
}
