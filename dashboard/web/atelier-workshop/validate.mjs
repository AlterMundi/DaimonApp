// Fixed receiving entry; imports only pinned inert source validators.
import {readRequest,readReply} from './corner-contract.js';
import {createHash} from 'node:crypto';
let bytes=0,chunks=[];for await(const c of process.stdin){bytes+=c.length;if(bytes>34*1024*1024)throw Error('Input bound');chunks.push(c);}const {raw,source}=JSON.parse(Buffer.concat(chunks).toString('utf8'));
if(typeof raw!=='string'||Buffer.byteLength(raw)>8*1024*1024)throw Error('File bound');
const read=source===null?await readRequest(raw):await readReply(raw,source),r=read.request||read.reply;
const metadata={kind:source===null?'request':'reply',id:r.id,createdAt:r.createdAt,sha256:read.envelope.sha256,fileSha256:createHash('sha256').update(raw).digest('hex')};
if(source===null)Object.assign(metadata,{projectId:read.project.id,name:read.project.name,instruction:r.instruction,sourceId:read.revision.id,sourceSha256:read.revision.sha256});else metadata.requestId=r.requestId;
process.stdout.write(JSON.stringify(metadata));
