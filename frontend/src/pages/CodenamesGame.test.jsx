import {act} from 'react';
import {createRoot} from 'react-dom/client';
import CodenamesGame from './CodenamesGame';
import Menu from './OasisGameMenu';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');document.body.appendChild(host);root=createRoot(host);jest.useFakeTimers();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();jest.useRealTimers();});
function state(phase='playing'){
 return {mode:'codenames',at:performance.now(),codenames:{phase,settings:{seconds:0,starting:'random'},round:1,round_id:'round',revision:2,
  turn:'red',stage:'guess',first_team:'red',board:Array.from({length:25},(_,i)=>({word:'MOT'+i,revealed:false,color:null})),
  votes:Array(25).fill(0),clue:{word:'Cosmos',count:2,team:'red',by:'a'},guesses_left:3,guesses_made:0,
  remaining_agents:{red:9,blue:8},total_agents:{red:9,blue:8},remaining_time:null,paused:false,result:null,scores:{red:0,blue:0},history:[],ready:true,
  seats:[{id:'a',name:'Alice',team:'red',role:'spymaster',connected:true},{id:'b',name:'Bob',team:'red',role:'agent',connected:true},
   {id:'c',name:'Camille',team:'blue',role:'spymaster',connected:true},{id:'d',name:'David',team:'blue',role:'agent',connected:true}],
  spectators:0,key:null,own_team:'red',own_role:'agent',can_clue:false,can_guess:true,can_end:false,selected:null}};
}
function button(label){return [...host.querySelectorAll('button')].find(b=>b.textContent.trim()===label.trim());}
function inputValue(input,value){Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));}

test('menu opens Codenames in OasisGame',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={{}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>button('Entrer en mission →').click());expect(send).toHaveBeenCalledWith({type:'choose_game',game:'codenames'});
});

test('agent cannot see hidden affiliations and must confirm a reveal',async()=>{
 const send=jest.fn();await act(async()=>root.render(<CodenamesGame state={state()} userId="b" connected send={send}/>));
 expect(host.querySelectorAll('.cn-cell')).toHaveLength(25);expect(host.querySelectorAll('.cn-card-hidden')).toHaveLength(25);
 expect(button('Afficher la clé')).toBeUndefined();
 await act(async()=>host.querySelector('[data-cell="0"]').click());
 expect(send).not.toHaveBeenCalled();expect(host.querySelector('[role="dialog"]')).not.toBeNull();
 await act(async()=>button('Révéler pour l’équipe').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_guess',round_id:'round',revision:2,cell:0});
});

test('proposal sends a vote instead of revealing and can be removed',async()=>{
 const send=jest.fn(),data=state();await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected send={send}/>));
 await act(async()=>host.querySelector('[data-cell="3"]').click());
 await act(async()=>button('Proposer à l’équipe').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_vote',round_id:'round',revision:2,cell:3});
 data.codenames={...data.codenames,selected:3,votes:data.codenames.votes.map((_,i)=>i===3?1:0)};
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected send={send}/>));
 expect(host.querySelector('[data-cell="3"]').className).toContain('cn-selected');
 await act(async()=>button('Retirer ma proposition').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_vote',round_id:'round',revision:2,cell:null});
});

test('spymaster receives a private key and can mask it without enabling guesses',async()=>{
 const send=jest.fn(),data=state();data.codenames={...data.codenames,key:Array.from({length:25},(_,i)=>i===0?'assassin':i<10?'red':'blue'),own_role:'spymaster',can_guess:false};
 await act(async()=>root.render(<CodenamesGame state={data} userId="a" connected send={send}/>));
 expect(host.querySelectorAll('.cn-card-assassin')).toHaveLength(1);
 expect(host.querySelector('[data-cell="1"]').disabled).toBe(true);
 await act(async()=>button('Masquer la clé').click());
 expect(host.querySelectorAll('.cn-card-hidden')).toHaveLength(25);expect(button('Afficher la clé')).toBeDefined();
});

test('only a permitted spymaster sees and submits the clue form',async()=>{
 const send=jest.fn(),data=state();data.codenames={...data.codenames,stage:'clue',clue:null,can_clue:true,can_guess:false,own_role:'spymaster',key:Array(25).fill('red')};
 await act(async()=>root.render(<CodenamesGame state={data} userId="a" connected send={send}/>));
 await act(async()=>inputValue(host.querySelector('input'),'Forêt'));
 await act(async()=>host.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(send).toHaveBeenLastCalledWith({type:'cn_clue',round_id:'round',revision:2,word:'Forêt',count:2});
 data.codenames={...data.codenames,can_clue:false,own_role:'agent',key:null};
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected send={send}/>));
 expect(host.querySelector('input')).toBeNull();
});

test('lobby role controls preserve team and role in the command',async()=>{
 const send=jest.fn(),data=state('lobby');data.codenames.seats=[];data.codenames.ready=false;
 await act(async()=>root.render(<CodenamesGame state={data} userId="new" connected canControl send={send}/>));
 await act(async()=>button('Devenir maître-espion rouge').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_join',round_id:'round',revision:2,team:'red',role:'spymaster'});
 await act(async()=>button('Rejoindre les agents bleus').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_join',round_id:'round',revision:2,team:'blue',role:'agent'});
 expect(button('Lancer la mission').disabled).toBe(true);
});

test('turn ending is confirmed and not available before a first guess',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected send={send}/>));
 expect(button('Terminer le tour').disabled).toBe(true);
 data.codenames={...data.codenames,can_end:true,guesses_made:1};
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected send={send}/>));
 await act(async()=>button('Terminer le tour').click());await act(async()=>button('Confirmer').click());
 expect(send).toHaveBeenLastCalledWith({type:'cn_end',round_id:'round',revision:2});
});

test('spectators and disconnected agents cannot guess',async()=>{
 const send=jest.fn(),data=state();data.codenames={...data.codenames,own_team:null,own_role:null,can_guess:false};
 await act(async()=>root.render(<CodenamesGame state={data} userId="spectator" connected send={send}/>));
 expect(host.querySelector('[data-cell="0"]').disabled).toBe(true);
 data.codenames={...data.codenames,own_team:'red',own_role:'agent',can_guess:true};
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected={false} send={send}/>));
 expect(host.querySelector('[data-cell="0"]').disabled).toBe(true);expect(send).not.toHaveBeenCalled();
});

test('finished round exposes known colors and permits the host to restart',async()=>{
 const send=jest.fn(),data=state('finished');data.codenames={...data.codenames,result:{winner:'blue',reason:'assassin'},can_guess:false,
  board:data.codenames.board.map((c,i)=>({...c,color:i===0?'assassin':'blue'}))};
 await act(async()=>root.render(<CodenamesGame state={data} userId="b" connected canControl send={send}/>));
 expect(host.textContent).toContain('Victoire de l’équipe bleue');expect(host.querySelectorAll('.cn-card-assassin')).toHaveLength(1);
 await act(async()=>button('Nouvelle mission').click());expect(send).toHaveBeenLastCalledWith({type:'cn_restart',round_id:'round',revision:2});
});
