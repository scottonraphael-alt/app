import { dateLabel, personName } from './projectUtils';

export function durationParts(minutes) {
  const total=Math.max(0,Math.floor(Number(minutes)||0));
  return {duration_days:Math.floor(total/1440),duration_hours:Math.floor(total%1440/60),duration_remainder:total%60};
}
export function durationMinutes(parts) {
  return Number(parts.duration_days || 0)*1440+Number(parts.duration_hours || 0)*60+Number(parts.duration_remainder || 0);
}
export function durationLabel(minutes) {
  const parts=durationParts(minutes);
  return [parts.duration_days?`${parts.duration_days} j`:null,parts.duration_hours?`${parts.duration_hours} h`:null,parts.duration_remainder?`${parts.duration_remainder} min`:null].filter(Boolean).join(' ') || '0 min';
}
export function clockLabel(minutes) {
  const day=Math.floor(minutes/1440);
  const local=minutes%1440;
  return `${String(Math.floor(local/60)).padStart(2,'0')}:${String(local%60).padStart(2,'0')}${day?` · J+${day}`:''}`;
}
function dateAtOffset(eventDate,minutes) {
  if (!eventDate) return null;
  const date=new Date(`${eventDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate()+Math.floor(minutes/1440));
  if (Number.isNaN(date.getTime()) || date.getUTCFullYear()>9999) return null;
  return date.toISOString().slice(0,10);
}
export function rundownTimeline(startTime,items,eventDate=null) {
  const [h,m]=(/^\d{2}:\d{2}$/.test(startTime || '')?startTime:'20:00').split(':').map(Number);
  let cursor=h*60+m;
  return items.map(item=>{
    const start=cursor;
    cursor+=Math.max(0,Math.floor(Number(item.duration_minutes)||0));
    return {...item,start:clockLabel(start),end:clockLabel(cursor),startClock:clockLabel(start%1440),endClock:clockLabel(cursor%1440),startDate:dateAtOffset(eventDate,start),endDate:dateAtOffset(eventDate,cursor)};
  });
}
export function rundownPoint(item,edge) {
  return item[`${edge}Date`]?`${dateLabel(item[`${edge}Date`])} · ${item[`${edge}Clock`]}`:item[edge];
}
export function rundownText(project) {
  const plan=project.rundown;
  if (!plan) return '';
  const lines=[project.title,`Déroulé · ${plan.event_date?dateLabel(plan.event_date,true):'Date à préciser'} · heure de Paris`,''];
  rundownTimeline(plan.start_time,plan.items,plan.event_date).forEach((item,index)=>{
    lines.push(`${index+1}. ${rundownPoint(item,'start')} → ${rundownPoint(item,'end')} · ${item.title}`,`   ${durationLabel(item.duration_minutes)} · ${item.speaker?personName(item.speaker):'Intervenant à attribuer'}`);
    if(item.notes) lines.push(item.notes.split('\n').map(line=>`   ${line}`).join('\n'));
    lines.push('');
  });
  return lines.join('\n');
}
