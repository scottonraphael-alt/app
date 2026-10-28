import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

/** En-tête commun des pages équipe : titre à gauche, « Accueil → » à droite, sans barre latérale. */
export default function TeamHeader({ eyebrow, title, intro }) {
  useEffect(() => {
    document.body.classList.add("team-no-nav");
    return () => document.body.classList.remove("team-no-nav");
  }, []);
  return (
    <header className="tm-header">
      <div className="tm-header-copy">
        <p className="tm-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {intro && <p className="tm-intro">{intro}</p>}
      </div>
      <Link to="/" className="tm-home">
        Accueil
        <ArrowRight size={18} aria-hidden="true" />
      </Link>
    </header>
  );
}
