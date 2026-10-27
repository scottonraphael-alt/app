// Vérifie les configurations avec le vrai moteur ECharts, sans navigateur ni image enregistrée.
import { readFile } from 'node:fs/promises';
import { init, use } from 'echarts/core.js';
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts.js';
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, AriaComponent } from 'echarts/components.js';
import { SVGRenderer } from 'echarts/renderers.js';

use([LineChart,BarChart,HeatmapChart,GridComponent,TooltipComponent,LegendComponent,DataZoomComponent,VisualMapComponent,AriaComponent,SVGRenderer]);
const source = await readFile(new URL('../src/components/statistics/chartOptions.js',import.meta.url),'utf8');
const {timelineOption,rankingOption,heatmapOption,profileOption,lengthOption,memberEvolutionOption,cohortOption,memberRegularityOption} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const rows=[{id:'x',name:'Salon',label:'27/10/2026',messages:3,previous_messages:1,coverage:1,weekday:1,hour:12,observed_hours:1,possible_hours:1,share:100}];
const gap={...rows[0],id:'missing',messages:0,coverage:0,hour:13,observed_hours:0};
const options=[timelineOption(rows,{reliable:true},false),rankingOption(rows),heatmapOption([...rows,gap]),profileOption(rows),lengthOption(rows),heatmapOption([]),
  memberEvolutionOption([{day:'2026-10-27',joins:2,departures:1,new_members:1,population:10},{day:'2026-10-28',joins:0,departures:0,new_members:0,population:null}]),
  cohortOption([{day:'2026-10-01',label:'01/10/2026',members:2,p7:50,a7:0,p30:null,a30:null}]),
  memberRegularityOption([{label:'1 jour actif',members:2}]),cohortOption([])];
for (const option of options) {
  const chart=init(null,null,{renderer:'svg',ssr:true,width:800,height:350});
  try {
    chart.setOption({...option,animation:false});
    const svg=chart.renderToSVGString();
    if (!svg.startsWith('<svg') || svg.includes('NaN')) throw new Error('Configuration graphique invalide');
  } finally { chart.dispose(); }
}
console.log('10 configurations ECharts validées (dont cohortes en attente et vides).');
