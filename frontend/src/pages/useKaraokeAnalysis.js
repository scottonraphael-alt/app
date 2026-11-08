import {useCallback, useEffect, useState} from 'react';

const RETRIES = [2000, 5000, 10000];

export function useKaraokeAnalysis({trackId, apiRoot, token, revision}) {
  const [value, setValue] = useState({data:null, status:'idle', error:''});
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt(v=>v+1), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    setValue({data:null,status:trackId?'loading':'idle',error:''});
    if (!trackId) return () => controller.abort();
    const request = async (index=0) => {
      let error = 'Les données du morceau ne sont pas encore disponibles sur le serveur.';
      let terminal = false;
      try {
        const response = await fetch(`${apiRoot}/activity/karaoke/analysis?t=${encodeURIComponent(token)}&id=${encodeURIComponent(trackId)}`,
          {signal:controller.signal, cache:'no-store'});
        terminal = [401,403,404].includes(response.status);
        if (response.ok) {
          const data = await response.json();
          if (controller.signal.aborted) return;
          if (data?.available) {setValue({data,status:'ready',error:''});return;}
          if (typeof data?.error === 'string') error = data.error;
        } else {
          error = response.status===403 ? 'Guide masqué pendant le blind test.' : response.status===401 ? 'Session expirée : rouvre le karaoké.' : 'Impossible de charger les données du morceau.';
        }
      } catch {
        if (controller.signal.aborted) return;
        error = 'Connexion au serveur interrompue pendant le chargement du guide.';
      }
      if (controller.signal.aborted) return;
      if (!terminal && index<RETRIES.length) {
        timer = window.setTimeout(()=>request(index+1), RETRIES[index]);
      } else setValue({data:null,status:'unavailable',error});
    };
    request();
    return () => {controller.abort();window.clearTimeout(timer);};
  }, [trackId,apiRoot,token,revision,attempt]);
  return {...value,reload};
}
