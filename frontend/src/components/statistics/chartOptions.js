export const weekdays = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"];
export const number = value => new Intl.NumberFormat("fr-FR", {maximumFractionDigits:1}).format(value || 0);
export const coverageLabel = value => value == null ? "Non disponible" : `${number(value*100)} %`;
const colors = ["#527c66", "#b4beb1", "#a68a6b", "#839ca7"];
const common = {
  color:colors, textStyle:{fontFamily:"inherit",color:"#637a6b",fontSize:11},
  tooltip:{trigger:"item",renderMode:"richText",confine:true,backgroundColor:"#fff",borderColor:"#dae5dc",textStyle:{color:"#365141",fontSize:12}},
  grid:{left:45,right:24,top:35,bottom:40},
};
const axis = {axisLine:{show:false},axisTick:{show:false},splitLine:{lineStyle:{color:"#edf1ec"}},axisLabel:{color:"#7b8c80"}};
const value = row => row.coverage > 0 || row.messages > 0 ? row.messages : null;
export function timelineOption(rows, comparison, hourly) {
  const series = [{name:"Période sélectionnée",type:"line",smooth:.15,sampling:"lttb",symbolSize:5,connectNulls:false,lineStyle:{width:2.5},areaStyle:{opacity:.08},data:rows.map(row=>({value:value(row),row,itemStyle:{color:row.coverage < .98 ? "#ac8b5e" : colors[0]}}))}];
  if (comparison?.reliable && !hourly) series.push({name:"Période précédente",type:"line",symbol:"none",connectNulls:false,lineStyle:{type:"dashed",width:2},data:rows.map(row=>({value:row.previous_messages,row}))});
  return {...common,grid:{...common.grid,bottom:72},legend:{top:0,textStyle:{color:"#748478",fontSize:10}},
    tooltip:{...common.tooltip,trigger:"axis",formatter:params=>params.map(p=>`${p.seriesName} : ${p.value == null ? "Données manquantes" : number(p.value)}${p.seriesIndex===0 ? `\nCouverture : ${coverageLabel(p.data?.row?.coverage)}` : ""}`).join("\n")},
    xAxis:{...axis,type:"category",boundaryGap:false,data:rows.map(row=>row.label),axisLabel:{hideOverlap:true,fontSize:10}},yAxis:{...axis,type:"value",minInterval:1},
    dataZoom:[{type:"inside",filterMode:"none"},{type:"slider",height:16,bottom:8,borderColor:"transparent",fillerColor:"#e5eee5",handleStyle:{color:colors[0]},showDetail:false}],series};
}
export function rankingOption(rows) {
  return {...common,grid:{left:115,right:40,top:12,bottom:25},xAxis:{...axis,type:"value",minInterval:1},yAxis:{...axis,type:"category",inverse:true,data:rows.map(row=>row.name),axisLabel:{width:98,overflow:"truncate",fontSize:11}},
    tooltip:{...common.tooltip,formatter:params=>`${params.name}\n${number(params.value)} messages`},
    series:[{type:"bar",barMaxWidth:19,itemStyle:{borderRadius:[0,5,5,0]},label:{show:true,position:"right",color:"#617a67",fontSize:10},data:rows.map(row=>({name:row.name,value:row.messages,row}))}]};
}
export function heatmapOption(rows) {
  const known=rows.filter(row=>row.observed_hours>0 || row.messages>0);
  const missing=rows.filter(row=>!row.observed_hours && !row.messages);
  const point = row => ({value:[row.hour,row.weekday,row.messages],row,itemStyle:row.coverage < .98 ? {borderWidth:1,borderColor:"#c8b391"} : {borderWidth:2,borderColor:"#fff"}});
  return {...common,grid:{left:70,right:18,top:12,bottom:72},
    tooltip:{...common.tooltip,formatter:params=>{ const row=params.data.row; return `${weekdays[row.weekday]} · ${row.hour} h\n${!row.possible_hours ? "Hors de la période ou du filtre" : row.observed_hours || row.messages ? `${number(row.messages)} messages` : "Aucune donnée collectée"}\nCouverture : ${coverageLabel(row.coverage)}`; }},
    xAxis:{type:"category",data:Array.from({length:24},(_,i)=>`${i}h`),axisLine:{show:false},axisTick:{show:false},axisLabel:{interval:2,fontSize:10}},
    yAxis:{type:"category",data:weekdays,inverse:true,axisLine:{show:false},axisTick:{show:false},axisLabel:{fontSize:10}},
    visualMap:[{min:0,max:Math.max(1,...known.map(row=>row.messages)),calculable:false,orient:"horizontal",left:"center",bottom:8,itemWidth:12,itemHeight:150,text:["Plus actif","Moins actif"],textStyle:{fontSize:10,color:"#7a8b7e"},inRange:{color:["#eef4ea","#c6dabb","#7da47b","#3e6e50"]},seriesIndex:0},{show:false,min:0,max:1,seriesIndex:1,inRange:{color:["#e9ece8","#e9ece8"]}}],
    series:[{type:"heatmap",data:known.map(point),emphasis:{itemStyle:{borderColor:"#395a42",borderWidth:2}}},{type:"heatmap",data:missing.map(row=>({...point(row),itemStyle:{color:"#e9ece8",borderWidth:2,borderColor:"white"}}))}]};
}
export function profileOption(rows) {
  return {...common,grid:{...common.grid,top:15},xAxis:{...axis,type:"category",data:rows.map(row=>`${row.hour}h`),axisLabel:{interval:2,fontSize:10}},yAxis:{...axis,type:"value",minInterval:1},
    tooltip:{...common.tooltip,formatter:p=>`${p.name}\n${p.value==null ? "Données manquantes" : `${number(p.value)} messages`}\nCouverture : ${coverageLabel(p.data.row.coverage)}`},
    series:[{type:"bar",barMaxWidth:20,itemStyle:{borderRadius:[4,4,0,0]},data:rows.map(row=>({value:value(row),row}))}]};
}
export function lengthOption(rows) {
  return {...common,grid:{left:50,right:25,top:20,bottom:50},xAxis:{...axis,type:"category",data:rows.map(row=>row.label.replace(" caractères"," car.")),axisLabel:{interval:0,fontSize:10}},yAxis:{...axis,type:"value",minInterval:1},
    tooltip:{...common.tooltip,formatter:p=>`${p.name}\n${number(p.value)} messages · ${number(p.data.row.share)} %`},
    series:[{type:"bar",barMaxWidth:55,itemStyle:{borderRadius:[6,6,0,0]},data:rows.map((row,index)=>({value:row.messages,row,itemStyle:{color:colors[index]}}))}]};
}
