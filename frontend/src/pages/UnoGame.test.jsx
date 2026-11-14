import {act} from 'react';
import {createRoot} from 'react-dom/client';
import UnoGame from './UnoGame';
import Menu from './OasisGameMenu';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');document.body.appendChild(host);root=createRoot(host);jest.useFakeTimers();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();jest.useRealTimers();});
const red={id:'red-3-0',color:'red',value:'3'},blue={id:'blue-2-0',color:'blue',value:'2'},wild={id:'wild-0',color:null,value:'wild'};
function state(phase='playing'){
 return {mode:'uno',at:performance.now(),uno:{phase,settings:{seconds:60},round:1,round_id:'round',revision:5,turn:1,direction:1,
  top:{id:'red-5-0',color:'red',value:'5'},color:'red',deck_count:70,remaining:42,paused:false,pending:null,vulnerable:null,
  seats:[{id:'a',name:'Alice',cards:3,connected:true,score:0},{id:'b',name:'Bob',cards:7,connected:true,score:20}],
  history:[],spectators:0,result:null,hand:[red,blue,wild],playable_ids:[red.id,wild.id],can_draw:true,can_pass:false,can_uno:false,can_catch:false,can_challenge:false}};
}
function button(text){return [...host.querySelectorAll('button')].find(b=>b.textContent.trim()===text.trim());}

test('menu offers UNO to the host',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={{}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>button('Rejoindre la table →').click());expect(send).toHaveBeenCalledWith({type:'choose_game',game:'uno'});
});

test('playable cards commit their private server ID and unplayable cards stay disabled',async()=>{
 const send=jest.fn();await act(async()=>root.render(<UnoGame state={state()} userId="a" connected send={send}/>));
 expect(host.querySelector('[aria-label="Jouer Bleu 2"]').disabled).toBe(true);
 await act(async()=>host.querySelector('[aria-label="Jouer Rouge 3"]').click());
 expect(send).toHaveBeenLastCalledWith({type:'uno_play',round_id:'round',revision:5,card_id:red.id});
});

test('wild color selector sends chosen color and closes with Escape',async()=>{
 const send=jest.fn();await act(async()=>root.render(<UnoGame state={state()} userId="a" connected send={send}/>));
 await act(async()=>host.querySelector('[aria-label="Jouer Joker"]').click());
 expect(host.querySelector('[role="dialog"]')).not.toBeNull();
 await act(async()=>button('◆ Bleu').click());
 expect(send).toHaveBeenLastCalledWith({type:'uno_play',round_id:'round',revision:5,card_id:wild.id,color:'blue'});
 await act(async()=>host.querySelector('[aria-label="Jouer Joker"]').click());
 await act(async()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 expect(host.querySelector('[role="dialog"]')).toBeNull();
});

test('draw and keep actions use the latest authoritative revision',async()=>{
 const send=jest.fn(),data=state();await act(async()=>root.render(<UnoGame state={data} userId="a" connected send={send}/>));
 await act(async()=>button('Piocher une carte').click());expect(send).toHaveBeenLastCalledWith({type:'uno_draw',round_id:'round',revision:5});
 data.uno={...data.uno,can_draw:false,can_pass:true,revision:6};
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected send={send}/>));
 await act(async()=>button('Garder la carte et passer').click());expect(send).toHaveBeenLastCalledWith({type:'uno_pass',round_id:'round',revision:6});
});

test('UNO declaration and catch signals require private server permission',async()=>{
 const send=jest.fn(),data=state();data.uno={...data.uno,can_uno:true,hand:[red,wild]};
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected send={send}/>));
 await act(async()=>button('UNO !').click());expect(send).toHaveBeenLastCalledWith({type:'uno_uno',round_id:'round',revision:5});
 data.uno={...data.uno,can_uno:false,can_catch:true,vulnerable:'b'};
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected send={send}/>));
 await act(async()=>button('UNO oublié ! (+2)').click());expect(send).toHaveBeenLastCalledWith({type:'uno_catch',round_id:'round',revision:5});
});

test('pending draw four offers acceptance and challenge without showing the opponents hand',async()=>{
 const send=jest.fn(),data=state();data.uno={...data.uno,pending:{from:'b',target:'a'},can_challenge:true,can_draw:false,playable_ids:[]};
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected send={send}/>));
 expect(button('Piocher 4 et passer')).toBeDefined();
 await act(async()=>button('Contester le +4').click());expect(send).toHaveBeenLastCalledWith({type:'uno_challenge',round_id:'round',revision:5});
 expect(host.querySelectorAll('.un-hand-card')).toHaveLength(3);
});

test('spectators have no cards and disconnected players cannot play',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected={false} send={send}/>));
 await act(async()=>host.querySelector('[aria-label="Jouer Rouge 3"]').click());expect(send).not.toHaveBeenCalled();
 data.uno={...data.uno,hand:[],playable_ids:[],can_draw:false};
 await act(async()=>root.render(<UnoGame state={data} userId="spectator" connected send={send}/>));
 expect(host.querySelectorAll('.un-hand-card')).toHaveLength(0);expect(host.textContent).toContain('Mode spectateur');
});

test('host seating and restart controls follow the round protocol',async()=>{
 const send=jest.fn(),data=state('lobby');
 await act(async()=>root.render(<UnoGame state={data} userId="new" connected canControl send={send}/>));
 await act(async()=>button('Prendre une place').click());expect(send).toHaveBeenLastCalledWith({type:'uno_join',round_id:'round',revision:5});
 await act(async()=>button('Distribuer les cartes').click());expect(send).toHaveBeenLastCalledWith({type:'uno_start',round_id:'round',revision:5});
 data.uno={...data.uno,phase:'finished',result:{winner_id:'a',points:38}};
 await act(async()=>root.render(<UnoGame state={data} userId="a" connected canControl send={send}/>));
 expect(host.textContent).toContain('Alice remporte la manche');
 await act(async()=>button('Rejouer ensemble').click());expect(send).toHaveBeenLastCalledWith({type:'uno_restart',round_id:'round',revision:5});
});
