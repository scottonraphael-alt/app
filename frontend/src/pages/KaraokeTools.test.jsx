import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Tools,{karaokeRequest} from './KaraokeTools';
global.IS_REACT_ACT_ENVIRONMENT=true;
const session={videoToken:'signed',instanceId:'room',userId:'123',canControl:false};
const state={mode:'karaoke',theme:'neon',players:[],queue:[]};
beforeEach(()=>{global.fetch=jest.fn().mockResolvedValue({ok:true,json:async()=>({connected:true})});});
test('catalogue only lists Mac-ready full tracks, retains reservations and has no manual import or voice setup',async()=>{
 const host=document.createElement('div'),root=createRoot(host),send=jest.fn();
 const library=[{id:'song',title:'Chanson',artist:'Artiste',prepared:true,preview:false},
 {id:'raw',title:'Non préparée',preview:false},{id:'preview',title:'Deezer',preview:true,prepared:false}];
 try{
 await act(async()=>root.render(<Tools open onClose={jest.fn()} session={session} state={state} library={library} favorites={[]} send={send} plays/>));
 expect(host.textContent).toContain('Chanson');expect(host.textContent).not.toContain('Non préparée');expect(host.textContent).not.toContain('Deezer');
 expect(host.textContent).not.toContain('Importer');expect(host.textContent).not.toContain('Connecter OasisLink');
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Réserver').click());
 expect(send).toHaveBeenCalledWith({type:'queue_add',id:'song'});
 }finally{await act(async()=>root.unmount());}
});
test('site requests use the API URL rather than the Discord proxy',async()=>{
 await karaokeRequest({...session,apiRoot:'https://api.example/api'},'/voice/status',{query:{instance_id:'room'}});
 expect(fetch.mock.calls[0][0]).toContain('https://api.example/api/activity/karaoke/voice/status?');
});
