import { useState } from "react";
import { AnalysisDeck } from "./StatisticsReading";
import ChartCard from "./ChartCard";
import { timelineOption, rankingOption, heatmapOption, profileOption, lengthOption, weekdays, coverageLabel } from "./chartOptions";

const counts=[{key:"name",label:"Nom"},{key:"messages",label:"Messages"}];
export default function StatisticsCharts({data, granularity, onPeriod, onCategory, onChannel, onMember, onPeak, onHour}) {
  const [rhythm,setRhythm]=useState("week");
  const [space,setSpace]=useState("channels");
  const charts=data.charts;
  if (!charts) return null;
  const ranks = (title,rows,select) => <ChartCard title={title} description="Cliquez sur une barre pour filtrer tous les graphiques. Classement limité aux 20 premiers ; 12 affichés dans le graphique." defaultView="table" option={rankingOption(rows.slice(0,12))} rows={rows} columns={counts} onSelect={select} height={320} />;
  return <AnalysisDeck title="Comprendre l’activité" items={[
    {id:"overview",label:"Vue d’ensemble",question:"Comment évoluent les échanges ?",intro:"Commencez par le volume, puis explorez les rythmes, les espaces ou les personnes qui l’expliquent."},
    {id:"rhythms",label:"Rythmes",question:"Quand les membres échangent-ils ?",intro:"Choisissez une lecture par jour et heure, ou un profil sur les vingt-quatre heures de la journée."},
    {id:"spaces",label:"Salons et catégories",question:"Où se concentre l’activité ?",intro:"Repérez les espaces les plus fréquentés. Les classements s’ouvrent en tableau pour lire les noms facilement."},
    {id:"people",label:"Participants",question:"Qui prend le plus la parole ?",intro:"Le nombre de messages décrit le volume ; la diversité des contacts se consulte dans Interactions et équilibre."},
    {id:"format",label:"Format des messages",question:"Les échanges sont-ils plutôt courts ou longs ?",intro:"La longueur apporte une autre lecture du volume, sans analyser ni conserver le texte des messages."},
  ]}>{topic=><div className="ss-analysis-panels">
    {topic==="rhythms" && <div className="ss-local-switch" role="group" aria-label="Lecture des rythmes"><button aria-pressed={rhythm==="week"} onClick={()=>setRhythm("week")}>Jours et heures</button><button aria-pressed={rhythm==="day"} onClick={()=>setRhythm("day")}>Profil de la journée</button></div>}
    {topic==="spaces" && <div className="ss-local-switch" role="group" aria-label="Lecture des espaces"><button aria-pressed={space==="channels"} onClick={()=>setSpace("channels")}>Salons</button><button aria-pressed={space==="categories"} onClick={()=>setSpace("categories")}>Catégories</button></div>}
    {topic==="overview" && <ChartCard wide title="Évolution des messages" description={granularity === "hour" ? "Détail horaire en heure de Paris, décalage UTC indiqué. La comparaison reste disponible dans les indicateurs. Glissez pour zoomer." : "Glissez pour zoomer. Cliquez sur un point pour explorer sa période. La ligne pointillée représente la période précédente lorsqu’elle est suffisamment couverte."} option={timelineOption(charts.timeline,charts.comparison,granularity==="hour")} rows={charts.timeline} columns={[{key:"label",label:"Période"},{key:"messages",label:"Messages"},{key:"previous_messages",label:"Période précédente"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onPeriod} height={330} />}
    {topic==="rhythms" && rhythm==="week" && <ChartCard wide title="Heures de pointe" description="Messages par jour de semaine et heure de Paris. Gris : collecte absente ; contour ocre : couverture partielle. Cliquez sur une case pour filtrer ce créneau." option={heatmapOption(charts.heatmap)} rows={charts.heatmap.map(row=>({...row,id:`${row.weekday}-${row.hour}`,label:`${weekdays[row.weekday]} · ${row.hour} h`}))} columns={[{key:"label",label:"Créneau"},{key:"messages",label:"Messages"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onPeak} height={350} />}
    {topic==="rhythms" && rhythm==="day" && <ChartCard title="Au fil de la journée" description="Messages par heure de Paris, additionnés sur les jours de la période. Cliquez pour isoler une heure." option={profileOption(charts.hour_profile)} rows={charts.hour_profile.map(row=>({...row,id:row.hour,label:`${row.hour} h`}))} columns={[{key:"label",label:"Heure"},{key:"messages",label:"Messages"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onHour} />}
    {topic==="format" && <ChartCard title="Longueur des messages" description={`Distribution en caractères, pièces jointes sans texte comprises dans la première tranche. Moyenne : ${data.totals.messages ? Math.round(data.totals.characters/data.totals.messages) : 0} caractères par message.`} option={lengthOption(charts.lengths)} rows={charts.lengths} columns={[{key:"label",label:"Longueur"},{key:"messages",label:"Messages"},{key:"share",label:"Part (%)"}]} />}
    {topic==="spaces" && space==="channels" && ranks("Salons les plus actifs",data.channels,row=>onChannel(row.id))}
    {topic==="people" && ranks("Messages par membre",data.members,row=>onMember(row.id))}
    {topic==="spaces" && space==="categories" && <ChartCard wide defaultView="table" title="Répartition par catégorie" description="Cliquez sur une catégorie pour explorer ses salons. Les catégories masquées ne figurent pas dans ces chiffres." option={rankingOption(data.category_totals.slice(0,15))} rows={data.category_totals} columns={counts} onSelect={row=>onCategory(row.id || "uncategorized")} height={Math.min(480,Math.max(200,data.category_totals.slice(0,15).length*28+45))} />}
  </div>}</AnalysisDeck>;
}
