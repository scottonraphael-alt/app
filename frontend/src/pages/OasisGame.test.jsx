import {act} from 'react';
import {createRoot} from 'react-dom/client';
import Menu from './OasisGameMenu';
import Setup from './BlindTestSetup';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());delete global.fetch;});
const session={videoToken:'test',apiRoot:'/api',games:true,channelId:'wrong',karaokeChannelId:'1569069812804751431',guildId:'guild'};
test('main menu disables karaoke outside its channel but permits preparing a blind test',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={session} state={{mode:'menu'}} canControl send={send}/>));
 const buttons=[...host.querySelectorAll('button')];
 expect(buttons.find(b=>b.textContent.includes('Entrer sur scène')).disabled).toBe(true);
 await act(async()=>buttons.find(b=>b.textContent.includes('Préparer une partie')).click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'blindtest_setup'});
 expect(host.querySelector('a').href).toContain('1569069812804751431');
});
test('correct channel enables karaoke and guests wait for the host',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={{...session,channelId:session.karaokeChannelId}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent.includes('Entrer sur scène')).click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'karaoke'});
 await act(async()=>root.render(<Menu session={session} state={{mode:'menu'}} canControl={false} send={send}/>));
 expect([...host.querySelectorAll('button')].every(b=>b.disabled)).toBe(true);
});
test('full blind test setup sends launch with configured settings rather than hiding the lyrics',async()=>{
 const send=jest.fn(),setStarting=jest.fn();
 await act(async()=>root.render(<Setup session={session} settings={{pool:'local',rounds:10,seconds:20,style:'',decade:''}} setSettings={jest.fn()} library={[]} localTracks={[]} plays setPlays={jest.fn()} starting={false} setStarting={setStarting} categoryLoading={false} setCategoryLoading={jest.fn()} connected send={send} setNotice={jest.fn()}/>));
 await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent==='Lancer la partie').click());
 expect(setStarting).toHaveBeenCalledWith(true);expect(send).toHaveBeenCalledWith({type:'bt_start',pool:'local',rounds:10,seconds:20,style:'',decade:''});
 expect(host.querySelector('section').getAttribute('aria-label')).toBe('Préparer un blind test');
});
