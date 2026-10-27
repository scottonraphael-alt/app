import { useId, useState } from "react";
import { BookOpenText, ChevronDown, Info, BarChart3, Clock, Layers, Users, FileText, HeartHandshake, RefreshCw, Network, Scale, Activity, MessageCircle, Compass } from "lucide-react";

// Les définitions sont communes aux cartes, aux indicateurs et à leur aide de lecture.
export const reading = {
  "Messages": ["Messages humains envoyés pendant la période dans les espaces affichés.", "Les bots sont exclus. Une pièce jointe sans texte compte aussi comme un message ; masquer une catégorie change le total affiché, pas la collecte."],
  "Membres actifs": ["Personnes différentes ayant envoyé au moins un message dans le périmètre choisi.", "Une personne qui écrit cent messages compte pour un seul membre actif. Ce chiffre mesure la participation, pas l’effectif du serveur."],
  "Salons actifs": ["Salons ayant reçu au moins un message humain sur la période.", "Les fils sont regroupés sous leur salon parent. Un salon masqué par les filtres ne figure pas dans ce total."],
  "Pièces jointes": ["Fichiers joints aux messages comptabilisés, quel que soit leur type.", "Un message avec trois fichiers ajoute un message et trois pièces jointes. Leur contenu n’est pas analysé pour cette statistique."],
  "Évolution des messages": ["Le volume des échanges au fil de la période choisie.", "Une montée indique davantage de messages, pas forcément davantage de personnes. Comparez avec les membres actifs. Une interruption de ligne signale une collecte manquante ; la ligne pointillée compare la période précédente."],
  "Heures de pointe": ["Les jours et heures auxquels les échanges se concentrent.", "Plus la case est verte, plus il y a de messages. Le gris signale un créneau sans données ou hors sélection, pas nécessairement du silence. Toutes les heures sont celles de Paris."],
  "Au fil de la journée": ["La répartition des messages entre les 24 heures de la journée.", "Les messages de tous les jours sélectionnés sont additionnés à la même heure. Sur un mois, la barre de 18 h ne représente donc pas une seule journée."],
  "Salons les plus actifs": ["Les espaces qui concentrent le plus de messages.", "Un salon très actif peut être animé par un petit groupe. Explorez ensuite ses participants. Le tableau donne jusqu’à 20 salons, le graphique en présente 12."],
  "Répartition par catégorie": ["Le poids de chaque ensemble de salons dans l’activité affichée.", "Cliquez sur une catégorie pour resserrer l’analyse. Les catégories masquées ne contribuent ni aux graphiques ni aux compteurs."],
  "Messages par membre": ["Les personnes qui ont écrit le plus de messages.", "Ce classement mesure le volume. Pour voir qui échange avec le plus de personnes différentes, utilisez Interactions → Diversité."],
  "Longueur des messages": ["La place des messages courts et longs dans les échanges.", "La longueur est comptée en caractères. Un fichier sans texte appartient à la première tranche. La moyenne peut être tirée vers le haut par quelques longs messages."],
  "Effectif en fin de période": ["Membres humains présents au dernier instant vérifié de la période.", "Ce nombre comprend aussi les personnes qui ne parlent pas. Pendant une reconnexion, le dernier effectif vérifié reste affiché avec son état de fraîcheur."],
  "Arrivées observées": ["Entrées de membres humains enregistrées pendant la période.", "Une personne qui revient après un départ compte comme une arrivée. Le chargement initial de l’annuaire ne crée pas de fausses arrivées."],
  "Départs observés": ["Sorties de membres effectivement reçues par le bot.", "Une absence découverte à la reconnexion corrige l’effectif mais n’invente pas un départ à une date précise. Arrivées moins départs peuvent donc différer de la croissance nette."],
  "Croissance nette": ["Différence entre les effectifs vérifiés de début et de fin de période.", "Le taux rapporte cette différence à l’effectif initial. Un tiret signifie que l’historique ou la couverture ne permettent pas le calcul ; ce n’est pas un zéro."],
  "Actifs / membres présents": ["Part des membres encore présents qui ont participé pendant la période.", "Le numérateur suit les filtres d’activité ; l’effectif du serveur reste global. Une personne partie avant la fin de période n’entre pas dans ce ratio."],
  "Premiers participants observés": ["Personnes dont la première activité connue apparaît dans cette période.", "Cela ne signifie pas qu’elles viennent d’arriver sur le serveur : elles peuvent simplement prendre la parole pour la première fois depuis le début de la collecte."],
  "Membres revenus après 30 jours": ["Participants qui reprennent la parole après au moins trente jours de silence vérifié.", "Le silence est recherché dans tous les salons, avec une marge liée aux agrégats horaires. Une coupure de collecte ne prouve pas une absence."],
  "Connexion couverte": ["Part du temps pendant lequel une connexion du bot est observée.", "Une faible couverture peut expliquer une baisse apparente. Elle limite les comparaisons et ne garantit pas la réception de chaque événement."],
  "Évolution de la communauté": ["Arrivées, départs et effectif humain au fil des jours.", "Les barres se lisent sur l’axe des mouvements ; la courbe utilise l’axe de l’effectif. Un trou dans la courbe indique une valeur inconnue."],
  "Rétention des nouveaux membres": ["Ce que deviennent les nouveaux membres sept et trente jours après leur arrivée.", "Une cohorte regroupe les personnes arrivées le même jour. Présence signifie encore sur le serveur ; activité signifie au moins un message ce jour-là. Chaque pourcentage indique son dénominateur. Gris : recul ou données insuffisants."],
  "Première participation après l’arrivée": ["La proportion des nouveaux membres qui commencent à écrire rapidement.", "Chaque délai est évalué seulement lorsqu’il est entièrement écoulé. Les envois observés restent des faits de participation même si le message est supprimé ensuite."],
  "Accueil dans les sept premiers jours": ["Nouveaux membres ayant reçu une mention ou une réponse explicite d’une autre personne.", "Les échanges voisins ne suffisent pas. Plusieurs messages d’une même personne ne créent qu’un seul accueillant distinct."],
  "Régularité de participation": ["Le nombre de jours différents où les membres ont participé.", "Deux jours avec un message chacun représentent deux jours actifs, comme deux jours avec cent messages. Les filtres de salons et d’horaires s’appliquent."],
  "Renouvellement des participants": ["Les personnes communes à cette période et à la précédente.", "Nouveau sur la période signifie absent de la précédente, pas nouveau sur le serveur. Le taux est masqué si la comparaison manque de données."],
  "Participants les plus réguliers · Top 20": ["Les personnes présentes dans les échanges sur le plus grand nombre de jours.", "La part des jours se calcule sur la période sélectionnée. Le volume départage les membres ayant le même nombre de jours actifs."],
  "Retours après une absence · 20 derniers": ["Les reprises d’activité après un silence prolongé dans les données du serveur.", "L’absence est vérifiée sur tous les salons et nécessite une collecte suffisante. Le tableau présente les vingt retours les plus récents."],
  "Mentions directes": ["Mentions d’autres utilisateurs humains dans les messages affichés.", "Un destinataire compte une fois par message. Les auto-mentions et les mentions de rôles ne sont pas comptées."],
  "Réponses explicites": ["Réponses Discord dont le destinataire humain est identifié.", "Il s’agit du bouton Répondre de Discord. Une réponse écrite à proximité sans lien explicite n’est pas déduite."],
  "Réciprocité": ["Part des paires de personnes ayant interagi dans les deux sens.", "Une paire est réciproque si chacun a mentionné ou répondu à l’autre au moins une fois. Ce n’est pas un pourcentage de messages."],
  "Contributeurs effectifs": ["Une mesure de la répartition de l’activité entre les contributeurs.", "Si dix personnes écrivent autant, la valeur vaut dix. Si une personne produit presque tout, elle se rapproche de un. Le calcul est l’inverse de la somme des parts au carré."],
  "Cercles restreints estimés": ["Part des signaux situés dans de petits groupes sans liaison extérieure observée.", "Il faut deux à cinq personnes, au moins trois signaux et une seule catégorie connue dans le filtre. C’est une estimation des échanges observés, pas un jugement sur les membres."],
  "Diversité des interlocuteurs": ["Les personnes qui ont le plus de contacts différents, au-delà du nombre de messages.", "Les contacts envoyés et reçus sont réunis sans doublon. Un destinataire de mentions peut apparaître même s’il écrit peu. Le détail distingue les deux sens."],
  "Concentration de l’activité": ["La part des messages portée par les contributeurs les plus actifs.", "La courbe répond à la question : quelle part du total est produite par les N premiers ? Une progression très rapide traduit une forte concentration, sans prédire les effets d’un départ."],
  "Tendance récente": ["Le mouvement de l’activité sur les dernières semaines complètes.", "Une hausse ou baisse commence à 20 %. Reprise signifie hausse après une baisse précédente. Les dates sont explicites et peuvent précéder le début de votre sélection."],
  "Fenêtres hebdomadaires comparées": ["Trois semaines complètes de sept jours, comparées sur les mêmes filtres.", "Les barres grisées ont une collecte insuffisante. La journée en cours est exclue pour éviter de la comparer à une journée complète."],
  "Participation entre catégories": ["Les membres qui participent à plusieurs ensembles de salons.", "Lisez de la ligne vers la colonne : le pourcentage indique quelle part des participants de la ligne est aussi active dans la colonne. Il ne prouve pas une conversation entre ces salons."],
  "Indice descriptif de participation": ["Trois dimensions complémentaires : volume, régularité et diversité des contacts.", "L’indice est leur moyenne sur 100. Il est relatif au filtre choisi et ne se compare pas directement entre deux périmètres. Un tiret signifie qu’il n’est pas calculable."],
  "Comment l’indice est calculé": ["La formule détaillée du score, sans pondération cachée.", "Le logarithme atténue l’effet des très gros volumes. Les autres dimensions mesurent les jours actifs et les interlocuteurs distincts."],
  "Estimation des échanges en cercle restreint": ["Petites composantes dont les échanges restent dans une seule catégorie du périmètre observé.", "Le pourcentage porte sur des signaux de mention et de réponse, pas sur un nombre de discussions réelles. Un filtre plus étroit peut changer les groupes détectés."],
  "Créneaux inhabituellement silencieux": ["Heures ou journées à zéro message alors que le même créneau est habituellement actif.", "La référence utilise les vingt-huit jours précédents, avec au moins trois créneaux couverts. Les nuits habituellement calmes, coupures et heures en cours sont exclues."],
  "Réponses explicites aux messages": ["Les messages qui ont reçu, ou non, une réponse Discord sous vingt-quatre heures.", "Seuls les messages assez anciens et suffisamment suivis sont évalués. Tous les messages ne nécessitent pas de réponse : ce taux ne mesure pas des demandes ignorées."],
  "Délai avant la première réponse observée": ["Le temps écoulé entre un message et la première réponse explicite observée.", "La médiane partage les délais en deux groupes égaux. Cette mesure utilise le registre de trente jours ; les réponses à soi-même et les références disparues sont exclues."],
};

export function MetricGuide({ title, description }) {
  const help=reading[title];
  return <div className="ss-reading"><p className="ss-definition">{help?.[0] || description}</p>{(help?.[1] || description) && <details><summary><BookOpenText size={14} aria-hidden="true" /> Comment lire ces données</summary><p>{help?.[1]}</p>{description && description!==help?.[0] && <p>{description}</p>}</details>}</div>;
}
export function MetricCollection({items}) {
  const card=([label,value,caption,extra])=><article key={label}><span className="ss-metric-label">{label}</span><strong>{value}</strong>{extra}<small>{reading[label]?.[0] || caption}</small><details className="ss-metric-help"><summary><Info size={13} aria-hidden="true" /> Comprendre</summary><p>{reading[label]?.[1] || caption}</p>{reading[label] && caption && <p>{caption}</p>}</details></article>;
  return <><div className="ss-kpis">{items.slice(0,4).map(card)}</div>{items.length>4 && <details className="ss-more-metrics"><summary>Voir {items.length-4} indicateurs complémentaires <ChevronDown size={14} aria-hidden="true" /></summary><div className="ss-kpis">{items.slice(4).map(card)}</div></details>}</>;
}
export function ExplainedPanel({title,children}) {
  return <section className="ss-panel ss-explained-panel"><header><h2>{title}</h2><MetricGuide title={title} /></header>{children}</section>;
}
const analysisThemes = {
  overview:{tone:"sage",Icon:BarChart3}, population:{tone:"sage",Icon:Users},
  rhythms:{tone:"blue",Icon:Clock}, regularity:{tone:"blue",Icon:Activity}, trend:{tone:"blue",Icon:Activity},
  spaces:{tone:"violet",Icon:Layers}, categories:{tone:"violet",Icon:Layers}, retention:{tone:"violet",Icon:HeartHandshake},
  people:{tone:"teal",Icon:Users}, diversity:{tone:"teal",Icon:Network}, participation:{tone:"teal",Icon:BarChart3},
  format:{tone:"gold",Icon:FileText}, balance:{tone:"gold",Icon:Scale}, responses:{tone:"gold",Icon:MessageCircle},
  welcome:{tone:"clay",Icon:HeartHandshake}, returns:{tone:"blue",Icon:RefreshCw}, quiet:{tone:"clay",Icon:Clock},
};
export function AnalysisDeck({title,items,children}) {
  const [selected,setSelected]=useState(items[0].id);
  const id=useId();
  const item=items.find(item=>item.id===selected) || items[0];
  const theme=analysisThemes[item.id] || analysisThemes.overview;
  const ContextIcon=theme.Icon;
  return <section className="ss-analysis-deck" data-tone={theme.tone} aria-label={title}>
    <div className="ss-analysis-heading"><div><span className="ss-section-eyebrow"><Compass size={13} aria-hidden="true" /> EXPLORER</span><h2>{title}</h2></div><p>Sélectionnez ce que vous souhaitez comprendre.</p></div>
    <div className="ss-analysis-selector" role="tablist" aria-label={title}>{items.map((item,index)=>{
      const {tone,Icon}=analysisThemes[item.id] || analysisThemes.overview;
      return <button type="button" role="tab" data-tone={tone} key={item.id} id={`${id}-tab-${item.id}`} aria-selected={selected===item.id} aria-controls={`${id}-panel`} tabIndex={selected===item.id ? 0 : -1} onClick={()=>setSelected(item.id)} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home' ? 0 : event.key==='End' ? items.length-1 : (index+(event.key==='ArrowRight' ? 1 : -1)+items.length)%items.length;setSelected(items[next].id);event.currentTarget.parentElement.children[next].focus();}}><span className="ss-analysis-tab-icon"><Icon size={17} aria-hidden="true" /></span>{item.label}</button>;
    })}</div>
    <div className="ss-analysis-context"><span className="ss-context-icon"><ContextIcon size={23} aria-hidden="true" /></span><div><strong>{item.question}</strong><p>{item.intro}</p></div></div>
    <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-tab-${item.id}`}>{children(item.id)}</div>
  </section>;
}
