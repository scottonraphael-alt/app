import { Link } from "react-router-dom";
import { BookOpenCheck } from "lucide-react";
import { sheetForReasons } from "./wellbeingApi";

/** Lien en un clic vers la fiche réflexe correspondant aux raisons détectées. */
export default function ReflexLink({ reasons }) {
  const slug = sheetForReasons(reasons);
  return (
    <Link to={`/staff/fiches-reflexes${slug ? `?fiche=${slug}` : ""}`} className="tai-btn" data-testid="reflex-link">
      <BookOpenCheck size={14} aria-hidden="true" /> Fiche réflexe
    </Link>
  );
}
