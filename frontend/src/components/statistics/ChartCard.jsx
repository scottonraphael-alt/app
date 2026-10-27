import { useId } from "react";
import StatisticsChart from "./StatisticsChart";
import { number } from "./chartOptions";

export default function ChartCard({ title, description, option, rows, columns, onSelect, height=300, wide=false }) {
  const id=useId();
  return <section className={`ss-panel ss-chart-card${wide ? " ss-chart-wide" : ""}`} aria-labelledby={id}>
    <header><h2 id={id}>{title}</h2>{description && <p>{description}</p>}</header>
    <StatisticsChart option={option} label={`${title}. ${description || ""} Une version tableau est disponible ci-dessous.`} onSelect={onSelect} height={height} />
    <details className="ss-chart-data"><summary>Voir les données en tableau</summary><div className="ss-table-scroll"><table><thead><tr>{columns.map(column=><th scope="col" key={column.key}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={row.id ?? index}>{columns.map((column,i)=><td key={column.key}>{i===0 && onSelect ? <button type="button" className="ss-data-button" onClick={()=>onSelect(row)}>{column.format ? column.format(row[column.key],row) : row[column.key]}</button> : column.format ? column.format(row[column.key],row) : typeof row[column.key]==="number" ? number(row[column.key]) : row[column.key] ?? "—"}</td>)}</tr>)}</tbody></table>{!rows.length && <p className="ss-empty">Aucune donnée pour ces filtres.</p>}</div></details>
  </section>;
}
