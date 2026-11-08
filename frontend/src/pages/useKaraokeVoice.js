import {useCallback,useEffect,useRef,useState} from 'react';
import {karaokeRequest} from './karaokeRequest';

export function useKaraokeVoice(session,active){
 const [voice,setVoice]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const attempts=useRef(0),pending=useRef(false),alive=useRef(true);
 const {videoToken,apiRoot,instanceId,channelId}=session;
 const connect=useCallback(async()=>{
  const result=await karaokeRequest({videoToken,apiRoot},'/voice/ensure',{method:'POST',body:{instance_id:instanceId,...(channelId?{channel_id:channelId}:{})}});
  return result;
 },[videoToken,apiRoot,instanceId,channelId]);
 useEffect(()=>{
  alive.current=true;let stopped=false,timer;
  attempts.current=0;
  const refresh=async()=>{
   try{
    const status=await karaokeRequest({videoToken,apiRoot},'/voice/status',{query:{instance_id:instanceId}});
    if(stopped)return;
    setVoice(status);
    if(status.busy){attempts.current=0;setError(status.message||'OasisLink attend qu’une autre salle soit libre.');}
    else if(status.connected){attempts.current=0;setError('');}
    else if(active&&!status.connecting&&!pending.current&&attempts.current<5){
     attempts.current++;pending.current=true;
     try{await connect();if(!stopped)setError('');}finally{pending.current=false;}
    }
   }catch(e){if(!stopped)setError(e.message);}
   finally{if(!stopped)timer=setTimeout(refresh,3000);}
  };
  if(active)refresh();
  return()=>{stopped=true;alive.current=false;clearTimeout(timer);};
 },[videoToken,apiRoot,instanceId,active,connect]);
 const toggle=useCallback(async()=>{
  if(busy)return;
  setBusy(true);setError('');
  try{
   const enabled=!voice?.consented;
   if(enabled&&!voice?.connected)await connect();
   const result=await karaokeRequest({videoToken,apiRoot},'/voice/consent',{method:'POST',query:{instance_id:instanceId},body:{enabled,latency_ms:0}});
   if(alive.current)setVoice(v=>({...v,consented:result.enabled}));
  }catch(e){if(alive.current)setError(e.message);}
  finally{if(alive.current)setBusy(false);}
 },[busy,voice?.consented,voice?.connected,videoToken,apiRoot,instanceId,connect]);
 return {voice,busy,error,toggle};
}
