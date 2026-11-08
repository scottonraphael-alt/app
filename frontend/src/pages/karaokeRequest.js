const ROOT='/.proxy/backend/api';
export async function karaokeRequest(session,path,options={}){
 const query=new URLSearchParams({t:session.videoToken,...options.query});
 const body=options.body;
 const response=await fetch(`${session.apiRoot||ROOT}/activity/karaoke${path}?${query}`,{
 method:options.method||'GET',signal:options.signal,headers:body instanceof FormData?{}:body?{'Content-Type':'application/json'}:{},
 body:body instanceof FormData?body:body?JSON.stringify(body):undefined});
 const data=await response.json();
 if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Action indisponible.');
 return data;
}
