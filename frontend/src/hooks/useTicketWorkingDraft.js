import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from '../api/client';
const fields=value=>({vocal_summary:value?.vocal_summary||'',person_triggers:value?.person_triggers||'',follow_up_status:value?.follow_up_status||'en attente de réponse'});
export const draftSignature=value=>JSON.stringify(fields(value));

export default function useTicketWorkingDraft({ticketId,userId,ticket,values,onRestore}){
 const [recovery,setRecovery]=useState(null),[loaded,setLoaded]=useState(false),[status,setStatus]=useState('idle'),[retry,setRetry]=useState(0);
 const contexts=useRef(new Map()),queue=useRef(Promise.resolve()),timer=useRef(null),saved=useRef(''),latest=useRef(null),restore=useRef(onRestore),generation=useRef(0),mounted=useRef(true),firstDirty=useRef(0);
 const signature=draftSignature(values),baseline=draftSignature(ticket),endpoint=`/tickets/${ticketId}/working-draft`;
 latest.current={values:fields(values),signature,baseline,base_updated_at:ticket?.updated_at,endpoint,loaded,recovery,userId,ticketId};contexts.current.set(`${userId}:${endpoint}`,latest.current);restore.current=onRestore;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const enqueue=useCallback((context)=>{
  const token=generation.current;
  queue.current=queue.current.catch(()=>{}).then(()=>api.put(context.endpoint,{...context.values,owner_id:String(context.userId),base_updated_at:context.base_updated_at||null})).then(()=>{
   if(mounted.current&&token===generation.current){saved.current=context.signature;if(latest.current.signature===context.signature)setStatus('saved');}
  }).catch(()=>{if(mounted.current&&token===generation.current)setStatus('error');});
  return queue.current;
 },[]);
 useEffect(()=>{
  if(!ticket?.id||!userId)return undefined;
  let active=true;const token=++generation.current;const registry=contexts.current;const stillCurrent=()=>token===generation.current;saved.current='';firstDirty.current=0;setLoaded(false);setRecovery(null);setStatus('loading');
  api.get(endpoint).then(r=>{if(!active)return;const draft=r.data.draft;if(draft&&draftSignature(draft)!==latest.current.baseline){setRecovery(draft);setStatus('recovery');}else{setStatus('idle');}setLoaded(true);}).catch(()=>{if(active){setStatus('load-error');setLoaded(false);}});
  return()=>{active=false;clearTimeout(timer.current);const context=registry.get(`${userId}:${endpoint}`);if(context&&latest.current.userId===userId&&context.loaded&&!context.recovery&&context.signature!==context.baseline&&context.signature!==saved.current&&context.endpoint===endpoint&&context.userId&&stillCurrent())enqueue(context);registry.delete(`${userId}:${endpoint}`);};
 },[ticket?.id,ticketId,userId,endpoint,enqueue,retry]);
 useEffect(()=>{
  if(!loaded||recovery||!userId||!ticket?.id)return undefined;
  if(signature===baseline||signature===saved.current){firstDirty.current=0;return undefined;}
  if(!firstDirty.current)firstDirty.current=Date.now();setStatus('pending');
  timer.current=setTimeout(()=>{firstDirty.current=0;setStatus('saving');enqueue({...latest.current});},Math.min(1000,Math.max(0,5000-(Date.now()-firstDirty.current))));
  return()=>clearTimeout(timer.current);
 },[signature,baseline,loaded,recovery,userId,ticket?.id,enqueue,retry]);
 useEffect(()=>{const warn=e=>{const c=latest.current;if(c.signature!==c.baseline&&c.signature!==saved.current){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 const clear=useCallback(async(snapshot)=>{
  clearTimeout(timer.current);const context={...latest.current};if(!context.userId)return; saved.current=draftSignature(snapshot||context.values);
  const token=generation.current;
  queue.current=queue.current.catch(()=>{}).then(async()=>{await api.delete(context.endpoint);const current=latest.current;if(current.userId===context.userId&&current.endpoint===context.endpoint&&current.signature!==saved.current&&current.signature!==current.baseline){await api.put(current.endpoint,{...current.values,owner_id:String(current.userId),base_updated_at:current.base_updated_at||null});saved.current=current.signature;}}).then(()=>{if(mounted.current&&token===generation.current){setRecovery(null);setStatus('idle');}}).catch(()=>{if(mounted.current&&token===generation.current)setStatus('error');});
  return queue.current;
 },[]);
 function recover(){if(signature!==baseline&&!window.confirm('Remplacer les modifications présentes dans l’éditeur par le brouillon récupéré ?'))return;restore.current(fields(recovery));saved.current=draftSignature(recovery);setRecovery(null);setStatus('saved');}
 return {recovery,status,recover,discard:()=>clear(ticket),clear,retry:()=>setRetry(n=>n+1)};
}
