import {useCallback,useEffect,useRef,useState} from 'react';
export function useKaraokeChrome(paused=false){
 const [visible,setVisible]=useState(true);
 const timer=useRef(null);
 const wake=useCallback(()=>{
  setVisible(true);clearTimeout(timer.current);
  if(!paused)timer.current=setTimeout(()=>setVisible(false),3200);
 },[paused]);
 useEffect(()=>{wake();return()=>clearTimeout(timer.current);},[wake]);
 return {visible,wake};
}
