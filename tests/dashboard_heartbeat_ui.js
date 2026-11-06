/* Never derive operational heartbeat from a cleared admission gate or execution. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync('dashboard/web/heartbeat.js','utf8'),{window});
const state=window.InteractionHeartbeat.state;
const base={schema:'telecodex.heartbeat-control/v1',admission_paused:false,generation:1};
assert.equal(state({...base,operational:true}),'operational');
assert.equal(state(base),'unavailable');
assert.equal(state({...base,executions:[{phase:'running'}]}),'unavailable');
assert.equal(state({...base,admission_paused:true,operational:true}),'paused');
assert.equal(state({...base,producer:{state:'not_configured'},operational:true}),'unconfigured');
assert.equal(state({...base,resources:{state:'unavailable'},operational:true}),'unavailable');
assert.equal(state({...base,producer:{state:'error'}}),'error');
for(const value of [null,{}, {...base,generation:-1},{...base,generation:1.2},{...base,admission_paused:'false'}])assert.equal(state(value),'unavailable');
console.log('Heartbeat: explicit operational evidence, pause/configuration/error and invalid-source states passed.');
