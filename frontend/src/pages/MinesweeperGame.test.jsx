import {act} from 'react';
import {createRoot} from 'react-dom/client';
import MinesweeperGame from './MinesweeperGame';
import Menu from './OasisGameMenu';
global.IS_REACT_ACT_ENVIRONMENT=true;
let host,root;
beforeEach(()=>{host=document.createElement('div');document.body.appendChild(host);root=createRoot(host);jest.useFakeTimers();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();jest.useRealTimers();});
function state(phase='playing'){
 return {mode:'minesweeper',host_id:'a',at:performance.now(),minesweeper:{phase,round_id:'round',round:1,revision:4,
  settings:{difficulty:'easy',mode:'coop'},rows:9,columns:9,mine_count:10,flag_count:0,opened:0,safe_total:71,
  board:Array.from({length:9},()=>Array(9).fill('hidden')),seats:[{id:'a',name:'Alice',connected:true,opened:0}],
  spectators:0,elapsed:0,started:false,paused:false,result:null}};
}
function button(text){return [...host.querySelectorAll('button')].find(b=>b.textContent.trim()===text.trim());}

test('menu offers the minefield in OasisGame',async()=>{
 const send=jest.fn();await act(async()=>root.render(<Menu session={{}} state={{mode:'menu'}} canControl send={send}/>));
 await act(async()=>button('Explorer la grille →').click());
 expect(send).toHaveBeenCalledWith({type:'choose_game',game:'minesweeper'});
});

test('reveal and right-click flag use the authoritative revision',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected send={send}/>));
 await act(async()=>host.querySelector('[data-cell="0"]').click());
 expect(send).toHaveBeenLastCalledWith({type:'ms_reveal',round_id:'round',revision:4,cell:0});
 await act(async()=>host.querySelector('[data-cell="1"]').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true})));
 expect(send).toHaveBeenLastCalledWith({type:'ms_flag',round_id:'round',revision:4,cell:1});
});

test('touch flag mode toggles a marker and never sends a reveal',async()=>{
 const send=jest.fn();await act(async()=>root.render(<MinesweeperGame state={state()} userId="a" connected send={send}/>));
 await act(async()=>button('Drapeau').click());
 await act(async()=>host.querySelector('[data-cell="2"]').click());
 expect(send).toHaveBeenLastCalledWith({type:'ms_flag',round_id:'round',revision:4,cell:2});
 expect(send.mock.calls.some(([p])=>p.type==='ms_reveal')).toBe(false);
});

test('number click requests a chord while revealed empty cells do nothing',async()=>{
 const send=jest.fn(),data=state();data.minesweeper.board[0][0]=2;data.minesweeper.board[0][1]=0;
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected send={send}/>));
 await act(async()=>host.querySelector('[data-cell="0"]').click());
 expect(send).toHaveBeenLastCalledWith({type:'ms_chord',round_id:'round',revision:4,cell:0});
 send.mockClear();await act(async()=>host.querySelector('[data-cell="1"]').click());expect(send).not.toHaveBeenCalled();
});

test('spectators can join coop but cannot reveal cells',async()=>{
 const send=jest.fn();await act(async()=>root.render(<MinesweeperGame state={state()} userId="b" connected send={send}/>));
 await act(async()=>host.querySelector('[data-cell="0"]').click());expect(send).not.toHaveBeenCalled();
 await act(async()=>button('Rejoindre l’équipe').click());expect(send).toHaveBeenLastCalledWith({type:'ms_join',round_id:'round',revision:4});
});

test('lobby settings and start are reserved for the host',async()=>{
 const send=jest.fn(),data=state('lobby');
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected canControl send={send}/>));
 expect(host.querySelectorAll('select')).toHaveLength(2);
 await act(async()=>button('Lancer la partie ').click());expect(send).toHaveBeenLastCalledWith({type:'ms_start',round_id:'round',revision:4});
 await act(async()=>root.render(<MinesweeperGame state={data} userId="b" connected send={send}/>));
 expect(host.querySelector('select')).toBeNull();expect(button('Lancer la partie ')).toBeUndefined();
});

test('victory allows a fresh grid and confirms quitting an active game',async()=>{
 const send=jest.fn(),data=state('finished');data.minesweeper.result={reason:'cleared'};data.minesweeper.opened=71;
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected canControl send={send}/>));
 expect(host.textContent).toContain('La grille est libérée');
 await act(async()=>button('Nouvelle grille').click());expect(send).toHaveBeenLastCalledWith({type:'ms_restart',round_id:'round',revision:4});
 data.minesweeper.phase='playing';data.minesweeper.result=null;
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected canControl send={send}/>));
 await act(async()=>button('Tous les jeux').click());expect(host.querySelector('[role="dialog"]')).not.toBeNull();
 await act(async()=>button('Retour au menu').click());expect(send).toHaveBeenLastCalledWith({type:'choose_game',game:'menu'});
});

test('keyboard flagging works and disconnection disables all moves',async()=>{
 const send=jest.fn(),data=state();
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected send={send}/>));
 await act(async()=>host.querySelector('[data-cell="0"]').dispatchEvent(new KeyboardEvent('keydown',{key:'f',bubbles:true,cancelable:true})));
 expect(send).toHaveBeenLastCalledWith({type:'ms_flag',round_id:'round',revision:4,cell:0});
 send.mockClear();
 await act(async()=>root.render(<MinesweeperGame state={data} userId="a" connected={false} send={send}/>));
 await act(async()=>host.querySelector('[data-cell="1"]').click());expect(send).not.toHaveBeenCalled();
 expect(host.textContent).toContain('Reconnexion à OasisGame');
});
