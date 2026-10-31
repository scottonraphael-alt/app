import { Link } from 'react-router-dom';
import { ArrowRight, ClipboardList, FileCheck2, MessagesSquare, ShieldCheck, Sparkles } from 'lucide-react';

export default function CaseworkDashboardLinks({ isStaff = false, isResponsable = false, isServerAdmin = false }) {
  if (!(isStaff || isResponsable || isServerAdmin)) return null;
  const links = [
    ['/staff/messages-anonymes','Messages anonymes','Consulter les propositions, les décisions et les publications.',MessagesSquare,'blue'],
    ['/staff/dossiers/verification','Tickets de vérification','Retrouver les échanges complémentaires aux formulaires.',FileCheck2,'sage'],
    ['/staff/dossiers/summons','Convocations','Suivre les échanges demandés par l’équipe de modération.',ShieldCheck,'clay'],
    ['/staff/dossiers/contact_staff','Contacts Staff','Lire les questions, signalements et demandes des membres.',MessagesSquare,'sage'],
    ['/staff/dossiers/bubble','Bulles d’échange','Retrouver les discussions privées sans motif disciplinaire.',Sparkles,'blue'],
    ['/staff/verifications','Formulaires d’admission','Prendre en charge les candidatures et consulter leurs archives.',ClipboardList,'clay'],
  ];
  return <nav aria-label="Dossiers des membres" className="nd-helper-v2-shortcuts nd-casework-shortcuts">
    {links.map(([to,title,description,Icon,tone])=><Link key={to} to={to} className={'nd-helper-v2-shortcut nd-helper-v2-shortcut--'+tone}>
      <span className="nd-helper-v2-shortcut-icon"><Icon size={22} aria-hidden="true"/></span>
      <span className="nd-helper-v2-shortcut-copy"><strong>{title}</strong><small>{description}</small></span>
      <ArrowRight size={18} aria-hidden="true"/>
    </Link>)}
  </nav>;
}
