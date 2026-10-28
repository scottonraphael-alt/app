import { useEffect, useState } from "react";
import { fetchTagAssignments, fetchTags } from "./extrasApi";

/** Étiquettes et affectations (silencieux en cas d'erreur : la liste reste utilisable). */
export default function useTicketTags() {
  const [tags, setTags] = useState([]);
  const [assignments, setAssignments] = useState({});
  useEffect(() => {
    let active = true;
    Promise.all([fetchTags(), fetchTagAssignments()])
      .then(([t, a]) => { if (active) { setTags(t || []); setAssignments(a || {}); } })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);
  return { tags, assignments };
}
