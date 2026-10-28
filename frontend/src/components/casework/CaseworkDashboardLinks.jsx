import '../../Casework.css';
import { Link } from 'react-router-dom';
import { FileCheck2, MessagesSquare, ShieldCheck, Sparkles } from 'lucide-react';

// Drop into the existing Staff dashboard module during integration. These booleans
// control visibility only; every endpoint independently checks fresh Discord roles.
export default function CaseworkDashboardLinks({ isStaff = false, isResponsable = false, isServerAdmin = false }) {
  if (!(isStaff || isResponsable || isServerAdmin)) return null;
  const links = [
    ['verification', 'Tickets de vérification', FileCheck2],
    ['summons', 'Convocations', ShieldCheck],
    ['contact_staff', 'Contacts Staff', MessagesSquare],
    ['bubble', 'Bulles d’échange', Sparkles],
  ];
  return <nav aria-label="Dossiers des membres" className="cw-dashboard-links">{links.map(([kind, title, Icon]) =>
    <Link key={kind} to={`/staff/dossiers/${kind}`}><Icon size={18} aria-hidden="true" /><span>{title}</span></Link>)}</nav>;
}
