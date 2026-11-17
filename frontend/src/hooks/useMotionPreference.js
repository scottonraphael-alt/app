import {useCallback,useEffect,useState} from 'react';

export const MOTION_EVENT='iris-motion-change';
const KEY='iris.motion';
function read(){try{return localStorage.getItem(KEY)==='reduced'?'reduced':'auto';}catch{return 'auto';}}
function apply(value){document.documentElement.dataset.motion=value;window.dispatchEvent(new Event(MOTION_EVENT));}

export default function useMotionPreference(){
  const [preference,setPreference]=useState(read);
  useEffect(()=>{
    document.documentElement.dataset.motion=preference;
    window.dispatchEvent(new Event(MOTION_EVENT));
  },[preference]);
  useEffect(()=>{
    const sync=()=>setPreference(document.documentElement.dataset.motion==='reduced'?'reduced':'auto');
    const storage=e=>{if(e.key===KEY||e.key===null){const value=read();setPreference(value);apply(value);}};
    window.addEventListener(MOTION_EVENT,sync);window.addEventListener('storage',storage);
    return()=>{window.removeEventListener(MOTION_EVENT,sync);window.removeEventListener('storage',storage);};
  },[]);
  const toggle=useCallback(()=>{
    const value=document.documentElement.dataset.motion==='reduced'?'auto':'reduced';
    try{localStorage.setItem(KEY,value);}catch{}
    setPreference(value);apply(value);
  },[]);
  return {reduced:preference==='reduced',toggle};
}
