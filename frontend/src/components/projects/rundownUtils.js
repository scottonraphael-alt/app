import { dateLabel, personName } from './projectUtils';

export function durationLabel(minutes) {
  return minutes >= 60 ? `${Math.floor(minutes/60)} h${minutes%60 ? ` ${minutes%60} min` : ''}` : `${minutes} min`;
}
export function clockLabel(minutes) {
  const day=Math.floor(minutes/1440);
  const local=minutes%1440;
  return `${String(Math.floor(local/60)).padStart(2,'0')}:${String(local%60).padStart(2,'0')}${day?` · J+${day}`:''}`;
}
export function rundownTimeline(startTime,items) {
  const [h,m]=(/^\d{2}:\d{2}$/.test(startTime || '')?startTime:'20:00').split(':').map(Number);
  let cursor=h*60+m;
  return items.map(item=>{
    const start=cursor;
    cursor+=Math.max(0,Number(item.duration_minutes)||0);
    return {...item,start:clockLabel(start),end:clockLabel(cursor)};
  });
}
export function rundownText(project) {
  const plan=project.rundown;
  if (!plan) return '';
  const lines=[project.title,`Déroulé · ${plan.event_date?dateLabel(plan.event_date,true):'Date à préciser'} · heure de Paris`,''];
  rundownTimeline(plan.start_time,plan.items).forEach((item,index)=>{
    lines.push(`${index+1}. ${item.start} → ${item.end} · ${item.title}`,`   ${durationLabel(item.duration_minutes)} · ${item.speaker?personName(item.speaker):'Intervenant à attribuer'}`);
    if(item.notes) lines.push(item.notes.split('\n').map(line=>`   ${line}`).join('\n'));
    lines.push('');
  });
  return lines.join('\n');
}
