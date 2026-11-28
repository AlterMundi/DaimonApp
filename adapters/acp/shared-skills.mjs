import { constants } from 'node:fs';
import { open, readdir, realpath, stat } from 'node:fs/promises';
import { join } from 'node:path';

const SKILL_NAME = /^[a-z0-9][a-z0-9_-]{0,79}$/;
const MAX_FILES = 128;
const MAX_SKILL_BYTES = 32 * 1024;

async function installedSkills(root) {
  const directory = await stat(root);
  if (!directory.isDirectory() || directory.uid !== process.getuid() || (directory.mode & 0o022)) {
    throw new Error('Invalid shared skills directory');
  }
  const names = (await readdir(root)).filter(name => SKILL_NAME.test(name)).sort();
  if (names.length > MAX_FILES) throw new Error('Shared skill catalog exceeds its bound');
  const entries = new Map();
  for (const name of names) {
    const directory = await realpath(join(root, name)).catch(error => {
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
      throw error;
    });
    if (!directory) continue;
    const path = join(directory, 'SKILL.md');
    const entry = await stat(path).catch(error => {
      if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
      throw error;
    });
    if (entry?.isFile()) entries.set(name, path);
  }
  return entries;
}

async function readSkill(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o002) || ((info.mode & 0o020) && info.gid !== process.getgid())) {
      throw new Error('Skill file is outside the installed catalog');
    }
    const buffer = Buffer.alloc(MAX_SKILL_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await file.read(buffer, length, buffer.length - length, null);
      if (!bytesRead) break;
      length += bytesRead;
    }
    if (length > MAX_SKILL_BYTES) throw new Error('Skill file exceeds its bound');
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, length));
  } finally {
    await file.close();
  }
}

export async function sharedSkill(root, name) {
  const catalog = await installedSkills(root);
  if (name !== undefined) {
    const path = catalog.get(name);
    if (!path) throw new Error('Unknown shared skill');
    return { name, markdown: await readSkill(path) };
  }
  const skills = [];
  for (const [name, path] of catalog) {
    const markdown = await readSkill(path);
    const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/.exec(markdown)?.[1];
    const description = /^description:\s*([^\r\n]+)/m.exec(frontmatter ?? '')?.[1]?.trim() ?? '';
    skills.push({ name, description: description.slice(0, 200) });
  }
  return { skills };
}
