import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Tools,{karaokeRequest} from './KaraokeTools';
global.IS_REACT_ACT_ENVIRONMENT=true;
const session={videoToken:'signed',instanceId:'room',userId:'123',canControl:false};
const state={mode:'karaoke',theme:'neon',players:[],queue:[]};
beforeEach(()=>{global.fetch=jest.fn().mockResolvedValue({ok:true,json:async()=>({connected:true,consented:false,scores:[]})});});
test('players see reservations, explicit voice opt-in and cannot connect the bot',async()=>{
 const host=document.createElement('div'),root=createRoot(host),send=jest.fn();
 const library=[{id:'song',title:'Chanson',artist:'Artiste',preview:false}];
 try{
 await act(async()=>root.render(<Tools session={session} state={state} library={library} favorites={[]} send={send} setLibrary={jest.fn()} plays setPlays={jest.fn()}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent.includes('Catalogue')).click());
 expect(host.textContent).toContain('Aucun enregistrement');
 expect(host.textContent).not.toContain('Connecter OasisLink');
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Réserver').click());
 expect(send).toHaveBeenCalledWith({type:'queue_add',id:'song'});
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='J’accepte l’analyse de ma voix').click());
 expect(fetch.mock.calls.some(([url,options])=>url.includes('/voice/consent')&&JSON.parse(options.body).enabled===true)).toBe(true);
 }finally{await act(async()=>root.unmount());}
});
test('site requests use the API URL rather than the Discord proxy',async()=>{
 await karaokeRequest({...session,apiRoot:'https://api.example/api'},'/voice/status',{query:{instance_id:'room'}});
 expect(fetch.mock.calls[0][0]).toContain('https://api.example/api/activity/karaoke/voice/status?');
});
