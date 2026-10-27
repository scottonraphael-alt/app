import { useEffect, useRef } from "react";
import { init, use } from "echarts/core";
import { LineChart, BarChart, HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, AriaComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

use([LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, AriaComponent, SVGRenderer]);

export default function StatisticsChart({ option, label, onSelect, height=300 }) {
  const node = useRef(null);
  const chart = useRef(null);
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
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    chart.current?.setOption({ ...option, animation: !reducedMotion, animationDuration:350, animationDurationUpdate:250, aria:{enabled:true,label:{description:label}} }, { notMerge:true });
  }, [option,label]);
  return <div ref={node} className="ss-chart" style={{height}} role="img" aria-label={label} />;
}
