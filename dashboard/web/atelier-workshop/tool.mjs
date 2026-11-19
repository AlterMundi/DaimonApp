/*
MIT License

Copyright (c) 2026 Sculpt contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

*/

// app/scripts/corner.mjs
import { readFile, writeFile, stat } from "node:fs/promises";

// app/src/project.js
var LIMITS = Object.freeze({ triangles: 25e4, objects: 6, inputBytes: 20 * 1024 * 1024, historyBytes: 64 * 1024 * 1024, historySteps: 64, storageBytes: 200 * 1024 * 1024 });
var uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
function uuid() {
  return crypto.randomUUID();
}
function validId(v) {
  return typeof v === "string" && uuidPattern.test(v);
}
function nameOf(v, fallback = "Sin t\xEDtulo") {
  return typeof v === "string" ? v.trim().slice(0, 80) || fallback : fallback;
}
async function digest(text2) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text2));
  return [...new Uint8Array(b)].map((v) => v.toString(16).padStart(2, "0")).join("");
}
function vector(v, min = -1e4, max = 1e4) {
  return Array.isArray(v) && v.length === 3 && v.every((n) => Number.isFinite(n) && n >= min && n <= max);
}
function validateProject(value) {
  if (!value || value.schema !== "sculpt.project/v1" || value.units !== "mm" || !validId(value.id)) throw Error("Este archivo no es un proyecto editable compatible.");
  if (!Array.isArray(value.objects) || value.objects.length > LIMITS.objects) throw Error("La escena puede tener hasta seis piezas.");
  const seen = /* @__PURE__ */ new Set();
  let triangles = 0;
  const objects = value.objects.map((o) => {
    if (!o || !validId(o.id) || seen.has(o.id)) throw Error("La identidad de una pieza no es v\xE1lida.");
    seen.add(o.id);
    const p = o.positions, i = o.indices;
    if (!Array.isArray(p) || p.length < 9 || p.length % 3 || p.length > 225e4 || !p.every((n) => Number.isFinite(n) && Math.abs(n) <= 1e4)) throw Error("La geometr\xEDa contiene coordenadas fuera de rango.");
    if (!Array.isArray(i) || i.length < 3 || i.length % 3 || !i.every((n) => Number.isSafeInteger(n) && n >= 0 && n < p.length / 3)) throw Error("La geometr\xEDa contiene caras inv\xE1lidas.");
    triangles += i.length / 3;
    if (triangles > LIMITS.triangles) throw Error("Esta escena supera el l\xEDmite de detalle del taller.");
    if (!vector(o.position) || !Number.isFinite(o.scale) || o.scale < 0.01 || o.scale > 100) throw Error("El tama\xF1o o la posici\xF3n de una pieza no es v\xE1lido.");
    if (!p.every((n, j) => Math.abs(n * o.scale + o.position[j % 3]) <= 2e4)) throw Error("La pieza queda fuera del espacio de trabajo.");
    let surface = false;
    for (let f = 0; f < i.length && !surface; f += 3) {
      const a = i[f] * 3, b = i[f + 1] * 3, c = i[f + 2] * 3, ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2], vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2];
      surface = (uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2 + (ux * vy - uy * vx) ** 2 > 1e-16;
    }
    if (!surface) throw Error("La pieza no tiene una superficie editable.");
    if (typeof o.color !== "string" || !/^#[a-f\d]{6}$/i.test(o.color)) throw Error("El color de una pieza no es v\xE1lido.");
    return { id: o.id, name: nameOf(o.name, "Pieza"), color: o.color.toLowerCase(), visible: o.visible !== false, position: [...o.position], scale: o.scale, positions: p.slice(), indices: i.slice() };
  });
  const camera = value.camera && vector(value.camera.position, -1e5, 1e5) && vector(value.camera.target, -1e5, 1e5) ? { position: [...value.camera.position], target: [...value.camera.target] } : null;
  return { schema: "sculpt.project/v1", id: value.id, name: nameOf(value.name), units: "mm", objects, camera };
}
async function makeRevision(project, parentId = null) {
  const normalized = validateProject(project), document = JSON.stringify(normalized);
  if (new TextEncoder().encode(document).length > LIMITS.inputBytes) throw Error("El proyecto es demasiado grande para esta versi\xF3n.");
  const revision = { schema: "sculpt.revision/v1", id: uuid(), projectId: normalized.id, parentId: validId(parentId) ? parentId : null, createdAt: (/* @__PURE__ */ new Date()).toISOString(), sha256: await digest(document), document };
  if (new TextEncoder().encode(JSON.stringify(revision, null, 2)).length > LIMITS.inputBytes) throw Error("El archivo editable supera el l\xEDmite de esta versi\xF3n.");
  return revision;
}
async function readRevision(text2) {
  if (typeof text2 !== "string" || new TextEncoder().encode(text2).length > LIMITS.inputBytes) throw Error("El archivo supera el l\xEDmite de 20 MiB.");
  let r;
  try {
    r = JSON.parse(text2);
  } catch {
    throw Error("No pude leer el proyecto. El archivo no contiene JSON v\xE1lido.");
  }
  if (!r || r.schema !== "sculpt.revision/v1" || !validId(r.id) || !validId(r.projectId) || r.parentId !== null && !validId(r.parentId) || typeof r.document !== "string" || !/^[a-f\d]{64}$/.test(r.sha256) || typeof r.createdAt !== "string" || r.createdAt.length > 40 || !Number.isFinite(Date.parse(r.createdAt))) throw Error("La revisi\xF3n no tiene el formato esperado.");
  if (await digest(r.document) !== r.sha256) throw Error("El contenido no coincide con la huella del archivo. Conserv\xE9 tu trabajo actual.");
  const project = validateProject(JSON.parse(r.document));
  if (project.id !== r.projectId) throw Error("El proyecto y su revisi\xF3n no coinciden.");
  return { revision: { schema: r.schema, id: r.id, projectId: r.projectId, parentId: r.parentId, createdAt: r.createdAt, sha256: r.sha256, document: r.document }, project };
}

// app/src/corner-contract.js
var CORNER = Object.freeze({ fileBytes: 24 * 1024 * 1024, instruction: 2e3, summary: 1200, requests: 32 });
var size = (v) => new TextEncoder().encode(v).length;
var exact = (v, keys) => v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).sort().join(",") === keys.split(",").sort().join(",");
function text(v, max) {
  if (typeof v !== "string" || !v.trim() || v.length > max || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v)) throw Error("El texto est\xE1 vac\xEDo o supera el l\xEDmite.");
  return v;
}
function time(v) {
  return typeof v === "string" && v.length <= 40 && Number.isFinite(Date.parse(v));
}
async function envelope(schema, value) {
  const document = JSON.stringify(value), sha256 = await digest(document), result = { schema, sha256, document };
  if (size(JSON.stringify(result)) > CORNER.fileBytes) throw Error("El intercambio supera el l\xEDmite de 24 MiB.");
  return result;
}
async function unwrap(raw, schema) {
  if (typeof raw !== "string" || size(raw) > CORNER.fileBytes) throw Error("El intercambio supera el l\xEDmite de 24 MiB.");
  let v;
  try {
    v = JSON.parse(raw);
  } catch {
    throw Error("No pude leer este archivo de intercambio.");
  }
  if (!exact(v, "schema,sha256,document") || v.schema !== schema || typeof v.document !== "string" || !/^[a-f\d]{64}$/.test(v.sha256)) throw Error("No es un archivo de intercambio compatible.");
  if (await digest(v.document) !== v.sha256) throw Error("La huella del intercambio no coincide.");
  return { envelope: v, value: JSON.parse(v.document) };
}
async function readRequest(raw) {
  const { envelope: envelope2, value: v } = await unwrap(raw, "sculpt.request/v1");
  if (!exact(v, "id,createdAt,instruction,selection,source") || !validId(v.id) || !time(v.createdAt) || !Array.isArray(v.selection) || v.selection.length > 6 || new Set(v.selection).size !== v.selection.length) throw Error("El pedido no tiene el formato esperado.");
  text(v.instruction, CORNER.instruction);
  const source = await readRevision(JSON.stringify(v.source));
  if (envelope2.document !== JSON.stringify({ id: v.id, createdAt: v.createdAt, instruction: v.instruction, selection: v.selection, source: source.revision })) throw Error("El pedido no conserva su representaci\xF3n can\xF3nica.");
  if (!source.project.objects.length || v.selection.some((id) => !source.project.objects.some((o) => o.id === id))) throw Error("El pedido refiere a una pieza que no est\xE1 en su obra.");
  return { envelope: envelope2, request: v, ...source };
}
async function makeReply(requestRaw, revision, summary) {
  const r = await readRequest(requestRaw), v = await readRevision(JSON.stringify(revision));
  if (v.revision.parentId !== r.revision.id || v.project.id !== r.project.id || v.revision.id === r.revision.id) throw Error("La propuesta debe continuar la revisi\xF3n elegida.");
  return envelope("sculpt.reply/v1", { id: uuid(), createdAt: (/* @__PURE__ */ new Date()).toISOString(), requestId: r.request.id, requestSha256: r.envelope.sha256, sourceId: r.revision.id, sourceSha256: r.revision.sha256, summary: text(summary, CORNER.summary), revision: v.revision });
}
async function readReply(raw, requestRaw) {
  const { envelope: envelope2, value: v } = await unwrap(raw, "sculpt.reply/v1");
  if (!exact(v, "id,createdAt,requestId,requestSha256,sourceId,sourceSha256,summary,revision") || !validId(v.id) || !time(v.createdAt)) throw Error("La devoluci\xF3n no tiene el formato esperado.");
  text(v.summary, CORNER.summary);
  const r = await readRequest(requestRaw), result = await readRevision(JSON.stringify(v.revision));
  if (v.requestId !== r.request.id || v.requestSha256 !== r.envelope.sha256 || v.sourceId !== r.revision.id || v.sourceSha256 !== r.revision.sha256 || result.revision.parentId !== r.revision.id || result.project.id !== r.project.id || result.revision.id === r.revision.id) throw Error("Esta propuesta corresponde a otro pedido o momento.");
  return { envelope: envelope2, reply: v, ...result, source: r };
}
async function stretchProposal(requestRaw, { axis = "y", factor = 1.15, piece } = {}) {
  const r = await readRequest(requestRaw);
  if (!["x", "y", "z"].includes(axis) || !Number.isFinite(factor) || factor < 0.5 || factor > 1.5 || factor === 1) throw Error("Choose x/y/z and a factor between0.5 and1.5, different from1.");
  const ids = piece ? [piece] : r.request.selection.length ? r.request.selection : [r.project.objects[0].id];
  for (const id of ids) {
    const o = r.project.objects.find((o2) => o2.id === id);
    if (!o) throw Error("Unknown piece");
    const index = ["x", "y", "z"].indexOf(axis);
    for (let i = index; i < o.positions.length; i += 3) o.positions[i] = Math.fround(o.positions[i] * factor);
  }
  const revision = await makeRevision(r.project, r.revision.id);
  return makeReply(requestRaw, revision, `Estir\xE9 ${ids.length} pieza(s) en su eje ${axis.toUpperCase()} por ${factor}. Transformaci\xF3n geom\xE9trica expl\xEDcita; el texto del pedido no se interpreta autom\xE1ticamente.`);
}

// app/scripts/corner.mjs
var [command, input, ...args] = process.argv.slice(2);
async function file(p) {
  if ((await stat(p)).size > CORNER.fileBytes) throw Error("File exceeds24MiB");
  return readFile(p, "utf8");
}
async function output(p, v) {
  if (!p) throw Error("Missing output path");
  await writeFile(p, JSON.stringify(v) + "\n", { flag: "wx" });
}
if (command === "inspect") {
  const r = await readRequest(await file(input));
  console.log(JSON.stringify({ requestId: r.request.id, requestSha256: r.envelope.sha256, instruction: r.request.instruction, selection: r.request.selection, source: { id: r.revision.id, sha256: r.revision.sha256, projectId: r.project.id, units: r.project.units }, pieces: r.project.objects.map((o) => ({ id: o.id, name: o.name, triangles: o.indices.length / 3, scale: o.scale, position: o.position })) }, null, 2));
} else if (command === "stretch") {
  const [out, axis, factor, piece] = args;
  const raw = await file(input), reply = await stretchProposal(raw, { axis: axis || "y", factor: factor === void 0 ? 1.15 : Number(factor), piece });
  await readReply(JSON.stringify(reply), raw);
  await output(out, reply);
  console.log(JSON.stringify({ output: out, sha256: reply.sha256, kind: "Explicit CPU geometry operation; not automatic natural-language generation" }));
} else if (command === "wrap") {
  const [candidate, out, summary] = args;
  const r = await readRevision(await file(candidate)), reply = await makeReply(await file(input), r.revision, summary);
  await output(out, reply);
  console.log(JSON.stringify({ output: out, sha256: reply.sha256 }));
} else throw Error("Usage: node scripts/corner.mjs inspect REQUEST | stretch REQUEST REPLY [x|y|z] [0.5..1.5] [PIECE_UUID] | wrap REQUEST CHILD.sculpt REPLY SUMMARY");
