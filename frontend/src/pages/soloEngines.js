// Local solo games: independent boards, no multiplayer score or hidden information.
export const SUITS=['♠','♥','♣','♦'];
export const rank=card=>card%13+1;
export const suit=card=>Math.floor(card/13);
export const red=card=>suit(card)%2===1;
export const cardName=card=>`${['','As','2','3','4','5','6','7','8','9','10','Valet','Dame','Roi'][rank(card)]} de ${['pique','cœur','trèfle','carreau'][suit(card)]}`;
const shuffle=values=>{const array=[...values];for(let i=array.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[array[i],array[j]]=[array[j],array[i]];}return array;};
export function newSolitaire(draw=1){const deck=shuffle(Array.from({length:52},(_,i)=>i));return {version:1,draw,stock:deck.slice(28),waste:[],foundations:[[],[],[],[]],columns:Array.from({length:7},(_,i)=>deck.slice(i*(i+1)/2,(i+1)*(i+2)/2).map((card,j)=>({card,up:j===i}))),moves:0,elapsed:0,won:false};}
function sourceCards(game,source){
 if(!source)return null;
 if(source.pile==='waste')return game.waste.length?[game.waste.at(-1)]:null;
 if(source.pile==='foundation'&&Number.isInteger(source.column)&&source.column>=0&&source.column<4)return game.foundations[source.column].length?[game.foundations[source.column].at(-1)]:null;
 if(source.pile==='column'&&Number.isInteger(source.column)&&source.column>=0&&source.column<7&&Number.isInteger(source.index)){
  const cards=game.columns[source.column].slice(source.index);
  if(source.index<0||!cards.length||cards.some(c=>!c.up))return null;
  if(cards.some((c,i)=>i>0&&(rank(cards[i-1].card)!==rank(c.card)+1||red(cards[i-1].card)===red(c.card))))return null;
  return cards.map(c=>c.card);
 }
 return null;
}
export function canMove(game,source,target){
 if(game.won||!target)return false;
 const cards=sourceCards(game,source);if(!cards)return false;
 if(source.pile===target.pile&&source.column===target.column)return false;
 if(target.pile==='foundation'&&Number.isInteger(target.column)&&target.column>=0&&target.column<4){const foundation=game.foundations[target.column];return cards.length===1&&suit(cards[0])===target.column&&rank(cards[0])===foundation.length+1;}
 if(target.pile==='column'&&Number.isInteger(target.column)&&target.column>=0&&target.column<7){const last=game.columns[target.column].at(-1);return last?last.up&&rank(last.card)===rank(cards[0])+1&&red(last.card)!==red(cards[0]):rank(cards[0])===13;}
 return false;
}
export function solitaireMove(game,source,target){
 if(!canMove(game,source,target))return null;
 const next=JSON.parse(JSON.stringify(game)),cards=sourceCards(game,source);
 if(source.pile==='waste')next.waste.pop();
 else if(source.pile==='foundation')next.foundations[source.column].pop();
 else {next.columns[source.column].splice(source.index);const last=next.columns[source.column].at(-1);if(last)last.up=true;}
 if(target.pile==='column')next.columns[target.column].push(...cards.map(card=>({card,up:true})));
 else next.foundations[target.column].push(cards[0]);
 next.moves++;next.won=next.foundations.every(f=>f.length===13);return next;
}
export function drawCards(game){
 if(game.won||(!game.stock.length&&!game.waste.length))return null;
 const next=JSON.parse(JSON.stringify(game));
 if(next.stock.length)for(let i=0;i<game.draw&&next.stock.length;i++)next.waste.push(next.stock.pop());
 else {next.stock=next.waste.reverse();next.waste=[];}
 next.moves++;return next;
}
export function solitaireHint(game){
 const sources=[{pile:'waste'},...game.columns.flatMap((col,column)=>col.flatMap((c,index)=>c.up?[{pile:'column',column,index}]:[]))];
 for(const source of sources)for(let column=0;column<4;column++)if(canMove(game,source,{pile:'foundation',column}))return {source,target:{pile:'foundation',column}};
 for(const source of sources)for(let column=0;column<7;column++)if(canMove(game,source,{pile:'column',column})&&!(source.pile==='column'&&source.index===0&&!game.columns[column].length))return {source,target:{pile:'column',column}};
 return null;
}
export function peers(a,b){return a!==b&&(Math.floor(a/9)===Math.floor(b/9)||a%9===b%9||(Math.floor(a/27)===Math.floor(b/27)&&Math.floor(a%9/3)===Math.floor(b%9/3)));}
export function candidates(board,index){if(board[index])return [];return [1,2,3,4,5,6,7,8,9].filter(n=>!board.some((v,i)=>v===n&&peers(i,index)));}
export function countSolutions(input,limit=2){
 const board=[...input];let count=0;
 function visit(){let index=-1,options=null;for(let i=0;i<81;i++)if(!board[i]){const values=candidates(board,i);if(!values.length)return;if(!options||values.length<options.length){index=i;options=values;if(values.length===1)break;}}
  if(index===-1){count++;return;}
  for(const value of options){board[index]=value;visit();if(count>=limit)break;}board[index]=0;
 }
 visit();return count;
}
export function newSudoku(difficulty='easy'){
 const groups=()=>shuffle([0,1,2]).flatMap(g=>shuffle([0,1,2]).map(i=>g*3+i)),rows=groups(),cols=groups(),digits=shuffle([1,2,3,4,5,6,7,8,9]);
 const solution=rows.flatMap(r=>cols.map(c=>digits[(r*3+Math.floor(r/3)+c)%9])),givens=[...solution];let removed=0;
 const target={easy:36,medium:45,hard:50}[difficulty]||36;
 for(const i of shuffle(Array.from({length:81},(_,i)=>i))){const old=givens[i];givens[i]=0;if(countSolutions(givens)===1)removed++;else givens[i]=old;if(removed===target)break;}
 return {version:1,difficulty,solution,givens,board:[...givens],notes:Array.from({length:81},()=>[]),elapsed:0,hints:0,checks:0,won:false};
}
export function sudokuEntry(game,index,value,note=false){
 if(game.won||!Number.isInteger(index)||index<0||index>80||game.givens[index]||!Number.isInteger(value)||value<0||value>9)return null;
 const next={...game,board:[...game.board],notes:game.notes.map(n=>[...n])};
 if(note&&value){if(next.board[index])return null;const notes=next.notes[index];next.notes[index]=notes.includes(value)?notes.filter(n=>n!==value):[...notes,value].sort();}
 else {next.board[index]=value;next.notes[index]=[];if(value)next.notes=next.notes.map((n,i)=>peers(i,index)?n.filter(v=>v!==value):n);}
 next.won=next.board.every((v,i)=>v===next.solution[i]);return next;
}
export function sudokuConflicts(board){return board.map((v,i)=>Boolean(v&&board.some((w,j)=>w===v&&peers(i,j))));}
