import ChartCard from "./ChartCard";
import { timelineOption, rankingOption, heatmapOption, profileOption, lengthOption, weekdays, coverageLabel } from "./chartOptions";

const counts=[{key:"name",label:"Nom"},{key:"messages",label:"Messages"}];
export default function StatisticsCharts({data, granularity, onPeriod, onCategory, onChannel, onMember, onPeak, onHour}) {
  const charts=data.charts;
  if (!charts) return null;
  const ranks = (title,rows,select) => <ChartCard title={title} description="Cliquez sur une barre pour filtrer tous les graphiques. Classement limité aux 20 premiers ; 12 affichés dans le graphique." option={rankingOption(rows.slice(0,12))} rows={rows} columns={counts} onSelect={select} height={320} />;
  return <div className="ss-grid ss-charts-grid">
    <ChartCard wide title="Évolution des messages" description={granularity === "hour" ? "Détail horaire en heure de Paris, décalage UTC indiqué. La comparaison reste disponible dans les indicateurs. Glissez pour zoomer." : "Glissez pour zoomer. Cliquez sur un point pour explorer sa période. La ligne pointillée représente la période précédente lorsqu’elle est suffisamment couverte."} option={timelineOption(charts.timeline,charts.comparison,granularity==="hour")} rows={charts.timeline} columns={[{key:"label",label:"Période"},{key:"messages",label:"Messages"},{key:"previous_messages",label:"Période précédente"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onPeriod} height={330} />
    <ChartCard wide title="Heures de pointe" description="Messages par jour de semaine et heure de Paris. Gris : collecte absente ; contour ocre : couverture partielle. Cliquez sur une case pour filtrer ce créneau." option={heatmapOption(charts.heatmap)} rows={charts.heatmap.map(row=>({...row,id:`${row.weekday}-${row.hour}`,label:`${weekdays[row.weekday]} · ${row.hour} h`}))} columns={[{key:"label",label:"Créneau"},{key:"messages",label:"Messages"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onPeak} height={350} />
    <ChartCard title="Au fil de la journée" description="Messages par heure de Paris, additionnés sur les jours de la période. Cliquez pour isoler une heure." option={profileOption(charts.hour_profile)} rows={charts.hour_profile.map(row=>({...row,id:row.hour,label:`${row.hour} h`}))} columns={[{key:"label",label:"Heure"},{key:"messages",label:"Messages"},{key:"coverage",label:"Collecte couverte",format:coverageLabel}]} onSelect={onHour} />
    <ChartCard title="Longueur des messages" description={`Distribution en caractères, pièces jointes sans texte comprises dans la première tranche. Moyenne : ${data.totals.messages ? Math.round(data.totals.characters/data.totals.messages) : 0} caractères par message.`} option={lengthOption(charts.lengths)} rows={charts.lengths} columns={[{key:"label",label:"Longueur"},{key:"messages",label:"Messages"},{key:"share",label:"Part (%)"}]} />
    {ranks("Salons les plus actifs",data.channels,row=>onChannel(row.id))}
    {ranks("Messages par membre",data.members,row=>onMember(row.id))}
    <ChartCard wide title="Répartition par catégorie" description="Cliquez sur une catégorie pour explorer ses salons. Les catégories masquées ne figurent pas dans ces chiffres." option={rankingOption(data.category_totals.slice(0,15))} rows={data.category_totals} columns={counts} onSelect={row=>onCategory(row.id || "uncategorized")} height={Math.min(480,Math.max(200,data.category_totals.slice(0,15).length*28+45))} />
  </div>;
}
