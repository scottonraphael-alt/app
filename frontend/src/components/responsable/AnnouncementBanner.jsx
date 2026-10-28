import { useCallback, useEffect, useState } from "react";
import { Info, CheckCircle2, TriangleAlert, OctagonAlert, X } from "lucide-react";

import { api } from "../../api/client";
import "./Responsable.css";

const ICONS = { info: Info, succes: CheckCircle2, alerte: TriangleAlert, critique: OctagonAlert };
const REFRESH_MS = 5 * 60 * 1000;

/** Bandeau d'annonces internes : à monter en haut de l'application (aucune prop requise). */
export default function AnnouncementBanner() {
  const [items, setItems] = useState([]);

  const load = useCallback(async () => {
    try {
      const response = await api.get("/staff-announcements/active");
      setItems(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const dismiss = async (id) => {
    setItems((current) => current.filter((item) => item.id !== id));
    try {
      await api.post(`/staff-announcements/${id}/dismiss`);
    } catch {
      load();
    }
  };

  if (items.length === 0) return null;

  return (
    <div className="rs-banners" role="region" aria-label="Annonces internes">
      {items.map((item) => {
        const Icon = ICONS[item.level] || Info;
        const urgent = item.level === "critique" || item.level === "alerte";
        return (
          <div
            key={item.id}
            className={`rs-banner rs-banner-${item.level}`}
            role={urgent ? "alert" : "status"}
            data-testid="announcement-banner"
          >
            <Icon size={18} aria-hidden="true" />
            <span className="rs-banner-text">{item.message}</span>
            <button
              type="button"
              className="rs-banner-close"
              onClick={() => dismiss(item.id)}
              aria-label="Fermer cette annonce"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
