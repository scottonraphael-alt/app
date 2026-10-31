import {Link} from 'react-router-dom';
import {ArrowRight,Terminal,BrainCircuit,Settings2,KeyRound,Megaphone,BarChart3,FileText,Gauge,ClipboardList,Archive} from 'lucide-react';
const GROUPS=[
 {title:'Discord et IA',intro:'Configurer le bot et préparer les messages.',tone:'violet',links:[
  ['/responsable/commandes-discord','Descriptions des commandes',Terminal],
  ['/responsable/parcours-discord','Parcours, rôles et panneaux',Settings2],
  ['/responsable/moderation-ia','Prompt de modération IA',BrainCircuit],
  ['/responsable/annonces','Composer une annonce',Megaphone],
 ]},
 {title:'Sécurité et archives',intro:'Contrôler les accès et retrouver les traces.',tone:'clay',links:[
  ['/responsable/acces-sanctions','Codes d’accès modération',KeyRound],
  ['/responsable/auth-logs','Logs d’authentification',FileText],
  ['/responsable/archives-salons','Sauvegardes des salons',Archive],
 ]},
 {title:'Pilotage',intro:'Suivre l’activité et la charge de l’équipe.',tone:'sage',links:[
  ['/responsable/statistiques','Statistiques du serveur',BarChart3],
  ['/responsable/charge','Charge du staff',Gauge],
  ['/responsable/rapports','Rapport mensuel',ClipboardList],
 ]},
];
export default function ResponsableToolsModule(){
 return <section className="nd-responsable-hub" aria-labelledby="nd-responsable-title">
  <header className="nd-responsable-hub-heading"><div><p className="nd-responsable-eyebrow">ESPACE RESPONSABLE</p><h2 id="nd-responsable-title">Les outils pour piloter Iris</h2><p>Retrouvez chaque réglage et chaque suivi à sa place.</p></div></header>
  <div className="nd-responsable-hub-grid">{GROUPS.map(group=><section className={'nd-responsable-group nd-responsable-group--'+group.tone} key={group.title}>
   <header><h3>{group.title}</h3><p>{group.intro}</p></header>
   <nav aria-label={group.title}>{group.links.map(([to,label,Icon])=><Link className="nd-responsable-link" to={to} key={to}>
    <span className="nd-responsable-tool-icon"><Icon size={19} aria-hidden="true"/></span><span>{label}</span><ArrowRight size={17} aria-hidden="true"/>
   </Link>)}</nav>
  </section>)}</div>
 </section>;
}
