import { ArrowRight, HeartHandshake, NotebookPen, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";

import NewTicketForm from "../components/NewTicketForm";
import "../NewTicket.css";

export default function NewTicketPage({ onCreated }) {
  const navigate = useNavigate();

  useEffect(() => {
    document.body.classList.add("new-ticket-no-nav");
    return () => document.body.classList.remove("new-ticket-no-nav");
  }, []);

  const created = (ticket) => {
    onCreated?.(ticket);
    navigate(`/tickets/${ticket.id}`);
  };

  const steps = [
    { Icon: HeartHandshake, title: "Identifier la personne", text: "Renseignez l’identifiant Discord du membre concerné." },
    { Icon: NotebookPen, title: "Retrouver les échanges", text: "Indiquez l’identifiant du salon à importer." },
    { Icon: ShieldCheck, title: "Préparer l’accompagnement", text: "Retrouvez ensuite le dossier, sa transcription et les outils de suivi dans Iris." },
  ];

  return (
    <section className="nt-page" data-testid="new-ticket-page">
      <header className="nt-header">
        <div>
          <p className="nt-eyebrow">ACCOMPAGNEMENT · IMPORT DISCORD</p>
          <h1>Créer un nouveau suivi</h1>
          <p className="nt-intro">Rassemblez les échanges d’un salon Discord pour démarrer un accompagnement dans Iris.</p>
        </div>
        <Link to="/" className="nt-home" data-testid="new-ticket-back-link">Accueil <ArrowRight size={18} aria-hidden="true" /></Link>
      </header>
      <div className="nt-layout">
        <aside className="nt-guide">
          <p className="nt-eyebrow">UN DOSSIER, TROIS ÉTAPES</p>
          <h2>Les bons repères pour commencer.</h2>
          <div className="nt-steps">
            {steps.map(({ Icon, title, text }, index) => (
              <div className="nt-step" key={title}>
                <span className="nt-step-icon"><Icon size={21} aria-hidden="true" /></span>
                <div><small>0{index + 1}</small><h3>{title}</h3><p>{text}</p></div>
              </div>
            ))}
          </div>
          <p className="nt-tip">Pour récupérer un identifiant Discord, activez le mode développeur dans Discord, puis utilisez « Copier l’identifiant » sur le membre ou le salon.</p>
        </aside>
        <section className="nt-form-card" aria-labelledby="nt-form-title">
          <header><span className="nt-form-icon"><NotebookPen size={23} aria-hidden="true" /></span><div><p className="nt-eyebrow">IMPORTER UN SALON</p><h2 id="nt-form-title">Informations du suivi</h2></div></header>
          <div className="nt-form-wrap"><NewTicketForm onCreated={created} /></div>
        </section>
      </div>
    </section>
  );
}
