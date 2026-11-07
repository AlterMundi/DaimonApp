/* Never derive operational heartbeat from a cleared admission gate or execution. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const window={};vm.runInNewContext(fs.readFileSync('dashboard/web/heartbeat.js','utf8'),{window});
const state=window.InteractionHeartbeat.state;
const base={schema:'telecodex.heartbeat-control/v1',admission_paused:false,generation:1};
assert.equal(state({...base,operational:true}),'unavailable');
assert.equal(state(base),'unavailable');
assert.equal(state({...base,executions:[{phase:'running'}]}),'unavailable');
assert.equal(state({...base,admission_paused:true,operational:true}),'paused');
assert.equal(state({...base,producer:{state:'not_configured'},operational:true}),'unconfigured');
assert.equal(state({...base,resources:{state:'unavailable'},operational:true}),'unavailable');
assert.equal(state({...base,producer:{state:'error'}}),'error');
for(const [producer,resources,expected] of [
  ['configured','expired','inference_expired'],
  ['configured','exhausted','inference_exhausted'],
  ['expired','available','observation_expired'],
  ['check_capacity','available','observation_stopped'],
  ['binding_retired','available','observation_stopped'],
  ['configured','unknown','unavailable'],
  ['unknown','available','unavailable'],
])assert.equal(state({...base,producer:{state:producer},resources:{state:resources},operational:true}),expected,'Contradictory dependency state must not pulse');
for(const value of [null,{}, {...base,generation:-1},{...base,generation:1.2},{...base,admission_paused:'false'}])assert.equal(state(value),'unavailable');
console.log('Heartbeat: explicit operational evidence, pause/configuration/error and invalid-source states passed.');
const action=window.InteractionHeartbeat.action;
const conditional={...base,controls:{schema:'telecodex.heartbeat-controls/v1',conditional_global:true,conditional_lane:true,actions:['set_paused','set_lane_paused']},lanes:{messaging:{generation:7,paused:true,supported:true}}};
assert.equal(action(base,'global'),null);
assert.deepEqual(JSON.parse(JSON.stringify(action(conditional,'messaging'))),{action:'set_lane_paused',lane:'messaging',paused:false,generation:7,global_generation:1});
assert.equal(action(conditional,'sensory'),null);
assert.equal(action({...conditional,lanes:{messaging:{generation:7,paused:true,supported:false}}},'messaging'),null);
assert.equal(action({...conditional,generation:true},'global'),null);
const observation=window.InteractionHeartbeat.observation;
const checked={...base,lanes:{messaging:{generation:7}},producer:{last_check:{sequence:2,generation:1,activation:{lane:'messaging',generation:7},outcome:'succeeded',started_at_unix_ms:1700000000000,completed_at_unix_ms:1700000001000},last_success_at_unix_ms:1700000001000}};
assert.equal(observation(checked),'Last source check succeeded at 2023-11-14T22:13:21.000Z.');
assert.match(observation({...checked,generation:2}),/different or unconfirmed control generation/);
assert.match(observation({...checked,lanes:{messaging:{generation:8}}}),/different or unconfirmed control generation/);
const failed={...checked,producer:{...checked.producer,last_check:{...checked.producer.last_check,outcome:'failed',error:'arbitrary private adapter output'}}};
assert.equal(observation(failed),'Last source check failed at 2023-11-14T22:13:21.000Z. Last successful source check: 2023-11-14T22:13:21.000Z.');
assert.match(observation({...failed,producer:{...failed.producer,last_success_at_unix_ms:null}}),/not observed/);
assert.match(observation({...checked,producer:{last_check:{...checked.producer.last_check,outcome:'in_progress',completed_at_unix_ms:null}}}),/completion not observed/);
for(const value of [null,base,{...checked,producer:{last_check:{outcome:'succeeded',completed_at_unix_ms:Infinity}}},{...checked,producer:{last_check:{outcome:'succeeded',completed_at_unix_ms:Number.MAX_SAFE_INTEGER}}}])assert.equal(observation(value),'');
console.log('Heartbeat: expired/exhausted/stopped dependencies cannot pulse; source-check timestamps remain distinct from operational proof.');

const now=1700000000000;
const ready={...base,operational:true,lanes:{messaging:{paused:false,generation:2}},
 producer:{state:'configured',contract:{expires_at_unix_ms:now+60000}},
 resources:{state:'available',contract:{expires_at_unix_ms:now+60000}},
 operational_evidence:{schema:'telecodex.heartbeat-operational/v1',operational:true,generation:1,observed_at_unix_ms:now,valid_for_seconds:15,lanes:{messaging:{operational:true,generation:2}}}};
assert.equal(state(ready,now),'operational');
assert.equal(state(ready,now+14999),'operational');
assert.equal(state(ready,now+15000),'unavailable');
assert.equal(state(ready,now-1),'unavailable');
for(const change of [{generation:2},{valid_for_seconds:16},{observed_at_unix_ms:now-15001},{lanes:{messaging:{operational:true,generation:3}}}])assert.equal(state({...ready,operational_evidence:{...ready.operational_evidence,...change}},now),'unavailable');
assert.equal(state({...ready,resources:{state:'available',contract:{expires_at_unix_ms:now}}},now),'unavailable');
assert.equal(state({...ready,producer:{state:'configured',contract:{expires_at_unix_ms:now}}},now),'unavailable');
console.log('Heartbeat: native operational evidence expires at its actual age/window and rejects changed generations.');
