import { useId, useState } from "react";
import { BarChart3, Table2 } from "lucide-react";
import StatisticsChart from "./StatisticsChart";
import { number } from "./chartOptions";
import { MetricGuide } from "./StatisticsReading";

export default function ChartCard({title,description,option,rows,columns,onSelect,height=300,wide=false,defaultView="chart",compactColumns}) {
  const id=useId();
  const [view,setView]=useState(defaultView);
  const [expanded,setExpanded]=useState(false);
  const visibleColumns=compactColumns && !expanded ? columns.filter(column=>compactColumns.includes(column.key)) : columns;
  return <section className={`ss-panel ss-chart-card${wide ? " ss-chart-wide" : ""}`} aria-labelledby={id}>
    <header><div className="ss-card-title"><h2 id={id}>{title}</h2><div className="ss-representation" role="group" aria-label={`Présentation : ${title}`}><button type="button" aria-pressed={view==="chart"} onClick={()=>setView("chart")}><BarChart3 size={14} aria-hidden="true" /> Graphique</button><button type="button" aria-pressed={view==="table"} onClick={()=>setView("table")}><Table2 size={14} aria-hidden="true" /> Tableau</button></div></div><MetricGuide title={title} description={description} /></header>
    {view==="chart" ? rows.length ? <StatisticsChart option={option} label={`${title}. ${description || ""} Le bouton Tableau permet une lecture au clavier.`} onSelect={onSelect} height={height} /> : <p className="ss-empty">Aucune donnée disponible pour cette analyse et ces filtres.</p> : <div className="ss-chart-data">{compactColumns && <button className="ss-data-button ss-column-toggle" type="button" onClick={()=>setExpanded(value=>!value)}>{expanded ? "Réduire les colonnes" : "Détailler les colonnes"}</button>}<div className="ss-table-scroll"><table><caption className="cz-sr-only">{title}</caption><thead><tr>{visibleColumns.map(column=><th scope="col" key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={row.id ?? index}>{visibleColumns.map((column,i)=><td key={column.key}>{i===0 && onSelect ? <button type="button" className="ss-data-button" onClick={()=>onSelect(row)}>{column.format ? column.format(row[column.key],row) : row[column.key]}</button> : column.format ? column.format(row[column.key],row) : typeof row[column.key]==="number" ? number(row[column.key]) : row[column.key] ?? "—"}</td>)}</tr>)}</tbody></table>{!rows.length && <p className="ss-empty">Aucune donnée disponible pour ces filtres.</p>}</div></div>}
    {onSelect && <p className="ss-card-action-hint">{view==="chart" ? "Sélectionnez un point, une case ou une barre pour explorer ces données." : "Sélectionnez un libellé souligné pour explorer ces données."}</p>}
  </section>;
}
