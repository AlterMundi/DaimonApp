// Session-local trial history. Saved versions remain an explicit separate action.
export function editHistory(initial){
 let current=JSON.stringify(initial),past=[],future=[],group=null,last=0;
 const bound=stack=>{while(stack.length>30||stack.reduce((n,s)=>n+s.length,0)>4*1024*1024)stack.shift();};
 return {reset(value){current=JSON.stringify(value);past=[];future=[];group=null;},
 record(value,key=null,now=Date.now()){const next=JSON.stringify(value);if(next===current)return;if(!key||key!==group||now-last>600)past.push(current);bound(past);current=next;future=[];group=key;last=now;},
 undo(){if(!past.length)return null;future.push(current);bound(future);current=past.pop();group=null;return JSON.parse(current);},
 redo(){if(!future.length)return null;past.push(current);bound(past);current=future.pop();group=null;return JSON.parse(current);},
 get canUndo(){return past.length>0;},get canRedo(){return future.length>0;}};
}
