import { useEffect, useRef, useState } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, AriaComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

use([LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, AriaComponent, SVGRenderer]);

// Thème sombre : même option ECharts, couleurs adaptées (le thème clair n'est pas touché).
const DARK_TEXT = "#a2b0a9";
const DARK_MAP = {
  "#fff":"#181e1b", "white":"#181e1b", "#dae5dc":"#3a4640", "#365141":"#e7ece9", "#395a42":"#e7ece9",
  "#637a6b":DARK_TEXT, "#748478":DARK_TEXT, "#7a8b7e":DARK_TEXT, "#7b8c80":DARK_TEXT, "#617a67":DARK_TEXT,
  "#edf1ec":"#2c3631", "#e5eee5":"#27302b", "#e9ece8":"#27302b", "#c8cfc3":"#3a4640",
  "#527c66":"#6fa388", "#b4beb1":"#8a9a91", "#a68a6b":"#c4a584", "#839ca7":"#8fb0bd", "#ac8b5e":"#d1ab75", "#b59b7d":"#cfae8c", "#c8b391":"#a68a6b",
  "#edf3e8":"#233228", "#c5dab9":"#3a5e49", "#8cad81":"#5f9a7b", "#4c7956":"#8fbba3",
};
const DARK_RAMPS = { 2:["#27302b","#27302b"], 3:["#1f2a24","#4a7a62","#8fbba3"], 4:["#1f2a24","#3a5e49","#5f9a7b","#8fbba3"] };
function darkValue(value, key) {
  if (Array.isArray(value)) return key === "color" && DARK_RAMPS[value.length] && value.every(v => typeof v === "string" && v.startsWith("#") && !["#527c66","#b4beb1","#a68a6b","#839ca7"].includes(v)) ? DARK_RAMPS[value.length] : value.map(item => darkValue(item, key));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, darkValue(v, k)]));
  return typeof value === "string" ? (DARK_MAP[value.toLowerCase()] || value) : value;
}
function withText(node, extra) { return { ...extra, ...(node || {}), color:(node && node.color) || extra.color }; }
export function darkChartOption(option) {
  const next = darkValue(option);
  const axes = key => next[key] && (Array.isArray(next[key]) ? next[key] : [next[key]]).forEach(axis => {
    axis.axisLabel = withText(axis.axisLabel, { color:DARK_TEXT });
    if (axis.splitLine && axis.splitLine.show !== false) axis.splitLine = { ...axis.splitLine, lineStyle:{ ...(axis.splitLine.lineStyle || {}), color:"#2c3631" } };
    if (axis.nameTextStyle || axis.name) axis.nameTextStyle = withText(axis.nameTextStyle, { color:DARK_TEXT });
  });
  axes("xAxis"); axes("yAxis");
  next.textStyle = withText(next.textStyle, { color:DARK_TEXT });
  if (next.legend) next.legend = { ...next.legend, textStyle:withText(next.legend.textStyle, { color:DARK_TEXT }) };
  if (next.tooltip) next.tooltip = { ...next.tooltip, backgroundColor:"#1f2723", borderColor:"#3a4640", textStyle:withText(next.tooltip.textStyle, { color:"#e7ece9" }) };
  if (next.visualMap) (Array.isArray(next.visualMap) ? next.visualMap : [next.visualMap]).forEach(map => { map.textStyle = withText(map.textStyle, { color:DARK_TEXT }); });
  return next;
}
const isDark = () => typeof document !== "undefined" && document.documentElement.dataset.theme === "dark";

export default function StatisticsChart({ option, label, onSelect, height=300 }) {
  const node = useRef(null);
  const chart = useRef(null);
  const [dark, setDark] = useState(isDark);
  const selection = useRef(onSelect);
  selection.current = onSelect;
  useEffect(() => {
    const instance = init(node.current, null, { renderer:"svg" });
    chart.current = instance;
    instance.on("click", event => { if (event.data?.row) selection.current?.(event.data.row); });
    const resize = () => instance.resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(node.current);
    window.addEventListener("resize", resize);
    return () => { observer?.disconnect(); window.removeEventListener("resize",resize); instance.dispose(); chart.current=null; };
  }, []);
  useEffect(() => {
    const sync = () => setDark(isDark());
    window.addEventListener("iris-theme-change", sync);
    sync();
    return () => window.removeEventListener("iris-theme-change", sync);
  }, []);
  useEffect(() => {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    chart.current?.setOption({ ...(dark ? darkChartOption(option) : option), animation: !reducedMotion, animationDuration:350, animationDurationUpdate:250, aria:{enabled:true,label:{description:label}} }, { notMerge:true });
  }, [option,label,dark]);
  return <div ref={node} className="ss-chart" style={{height}} role="img" aria-label={label} />;
}
