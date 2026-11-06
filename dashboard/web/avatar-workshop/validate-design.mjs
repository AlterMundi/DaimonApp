// Run the pinned workshop validator, never code supplied by an imported model.
import {validate,digest} from './experiments/school-avatar-quest/model.mjs';
process.stdin.setEncoding('utf8');
let input='';
for await (const chunk of process.stdin) {
  input+=chunk;
  if(Buffer.byteLength(input)>1048576)throw Error('Design input exceeds limit');
}
try {
  const design=validate(JSON.parse(input)),canonical=JSON.stringify(design);
  if(Buffer.byteLength(canonical)>524288)throw Error('Design exceeds limit');
  process.stdout.write(JSON.stringify({canonical,sha256:await digest(design)}));
} catch {
  process.stderr.write('Invalid workshop design');process.exitCode=1;
}
