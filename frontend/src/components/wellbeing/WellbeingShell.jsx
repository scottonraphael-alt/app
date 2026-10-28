import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import "../../Wellbeing.css";

/** En-tête commun des pages bien-être : titre, « Accueil → » à droite, aucune barre latérale. */
export default function WellbeingShell({ eyebrow, title, intro, actions, testId, children }) {
  useEffect(() => {
    document.body.classList.add("wb-no-nav");
    return () => document.body.classList.remove("wb-no-nav");
  }, []);
  return (
    <section className="wb-page" data-testid={testId}>
      <header className="wb-header">
        <div className="wb-header-copy">
          <p className="wb-eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          {intro && <p className="wb-intro">{intro}</p>}
        </div>
        <div className="wb-header-actions">
          {actions}
          <Link to="/" className="wb-home">Accueil<ArrowRight size={18} aria-hidden="true" /></Link>
        </div>
      </header>
      {children}
    </section>
  );
}
