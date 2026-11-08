// Shared inert validator regressions; no providers, account data or browser needed.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateAvatarModel,expressionIds} from '../dashboard/web/avatar-workshop/skills/ascii-avatar-author/scripts/model-runtime.mjs';
const legacy=JSON.parse(readFileSync(new URL('../dashboard/web/avatar-workshop/skills/ascii-avatar-author/assets/example.avatar.json',import.meta.url)));
assert.equal(validateAvatarModel(legacy).schema,'ascii-avatar-model/v1');
const frames=Array(12).fill(0),animations=Object.fromEntries(expressionIds.map(c=>[c,[{node:'head',channel:'rotate',frames}]]));
export const fixture={schema:'ascii-avatar-model/v2',id:'layer-fixture',name:'Layer fixture',atlas:{width:4,height:4,palette:['#00000000','#ff0000ff','#00ff00ff'],pixels:Buffer.from([1,1,2,2,1,1,2,2,2,2,1,1,2,2,1,1]).toString('base64')},nodes:[{id:'head',type:'raster',rect:[0,0,2,2],bounds:[100,100,80,80],pivot:[140,140],poses:{focus:{rect:[2,0,2,2]},sleep:{rect:[0,2,2,2]}}},{id:'finger',parent:'head',type:'raster',rect:[2,2,2,2],bounds:[210,100,20,60],pivot:[220,100]}],animations:{...animations,focus:[{node:'head',channel:'y',frames:[0,2,4,6,8,10,12,10,8,6,4,2]},{node:'finger',channel:'rotate',frames:[0,.1,.2,.3,.4,.5,.6,.5,.4,.3,.2,.1]}],sleep:[{node:'head',channel:'y',frames}]},anchors:{compact:[80,80,180,180]}};
const normalized=validateAvatarModel(fixture);assert.deepEqual(validateAvatarModel(normalized),normalized);
for(const change of [m=>m.atlas.width=257,m=>m.atlas.pixels='https://example.invalid/image',m=>m.atlas.palette[0]='#ffffff',m=>m.atlas.pixels=Buffer.alloc(16,3).toString('base64'),m=>m.nodes[0].rect=[3,0,2,2],m=>m.nodes[0].bounds=[550,0,80,80],m=>m.nodes[0].clip=Array(65).fill([0,0]),m=>m.nodes[0].parent='finger',m=>m.nodes[0].pivot='wrong',m=>m.animations.focus[0].frames=Array(13).fill(0),m=>m.nodes[0].poses.surprise={rect:[0,0,2,2]}]){const m=structuredClone(fixture);change(m);assert.throws(()=>validateAvatarModel(m));}
const wrong=structuredClone(fixture);wrong.schema='ascii-avatar-model/v1';assert.throws(()=>validateAvatarModel(wrong));
console.log('Layer model bounds, inert pixels, hierarchy, cue and roundtrip checks passed.');
