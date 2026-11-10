// Real shipped adapter; synthetic CSSOM/event fixture, no native input.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('dashboard/web/interface-appearance.js','utf8');
const provider=new Map(),inline=new Map(),events=new Map();
const root={dataset:{},style:{
 getPropertyValue:k=>inline.get(k)?.value||'',getPropertyPriority:k=>inline.get(k)?.priority||'',
 setProperty:(k,value,priority='')=>inline.set(k,{value,priority}),removeProperty:k=>inline.delete(k),
}};
vm.runInNewContext(source,{document:{documentElement:root},window:{addEventListener:(k,fn)=>events.set(k,fn)},getComputedStyle:()=>({getPropertyValue:k=>provider.get(k)||''})});
assert.equal(inline.size,0,'missing appearance preserves local fallback');
const update=(bg,panel,text,accent)=>{for(const [k,v] of Object.entries({background:bg,surface:panel,text,accent}))provider.set('--dm-'+k,v);events.get('home-style:resolved')();};
update('#090e17','#111925','#f5f0e6','#87d7ee');
assert.equal(inline.get('--dm-ui-warning').value,'#f4c283');
assert.equal(inline.get('--dm-ui-background').value,'#090e17');
const dark=JSON.stringify([...inline]);
update('#090e17','#111925','#f5f0e6','invalid');
assert.equal(JSON.stringify([...inline]),dark,'invalid update retains last valid roles');
update('invalid','#ffffff','#111111','#176241');
assert.equal(JSON.stringify([...inline]),dark,'invalid canvas retains the entire last valid mapping');
update('#ffffff','#ffffff','#111111','#176241');
assert.equal(inline.get('--dm-ui-text').value,'#111111');
assert.equal(inline.get('--dm-ui-positive').value,'#176241');
root.dataset.stylePolicy='authored';events.get('home-style:resolved')();
assert.equal(inline.size,0,'authored transition releases derived overrides');
root.style.setProperty('--dm-ui-warning','#abcdef','important');
root.dataset.stylePolicy='inherit';update('#090e17','#111925','#f5f0e6','#87d7ee');
root.dataset.stylePolicy='authored';events.get('home-style:resolved')();
assert.deepEqual(inline.get('--dm-ui-warning'),{value:'#abcdef',priority:'important'});
console.log('Homemaker adapter: fallback, dark/light updates, invalid recovery, authored opt-out and override restoration passed.');
