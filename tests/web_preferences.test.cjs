const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const template = readFileSync(resolve(__dirname, '../app/templates/courses.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace('{% include "download_status.js" %}', () =>
    readFileSync(resolve(__dirname, '../app/templates/download_status.js'), 'utf8'))
  .replace(/{% if error %}[\s\S]*?{% endif %}/g, '');
const optionNames = ['skip_videos', 'convert_word', 'convert_powerpoint', 'replace_originals'];

// A DOM boundary harness: execute the actual page script and interact via controls/events.
function page(storage = new Map()) {
  function element(tagName = '') {
    const listeners = {};
    const classes = new Set();
    return {
      tagName, checked: false, disabled: false, hidden: false, value: '', children: [], dataset: {},
      classList: {
        add: (name) => classes.add(name), remove: (name) => classes.delete(name),
        contains: (name) => classes.has(name),
        toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
      },
      addEventListener(name, handler) { (listeners[name] ??= []).push(handler); },
      dispatch(name, event = {}) { for (const handler of listeners[name] || []) handler(event); },
      remove() {},
      append(...items) { for (const item of items) { item.parentElement = this; this.children.push(item); } },
      appendChild(item) { this.append(item); },
      add(item) { this.append(item); },
      replaceChildren(...items) {
        this.children = []; this.append(...items);
        if (this.tagName === 'select') this.value = items[0]?.value || '';
      },
      setAttribute(name, value) {
        this[name] = value;
        if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
      },
      focus() { document.activeElement = this; },
      closest(selector) {
        for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node;
        return null;
      },
      querySelectorAll(selector) { return descendants(this).filter((node) => matches(node, selector)); },
      querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    };
  }
  function descendants(node) {
    return (node.children || []).flatMap((child) => [child, ...descendants(child)]);
  }
  function matches(node, selector) {
    if (selector === 'input:checked') return node.tagName === 'input' && node.checked;
    if (selector === '[data-post-group]') return 'postGroup' in (node.dataset || {});
    if (selector === '[data-file-row]') return 'fileRow' in (node.dataset || {});
    if (selector === '[data-file-row]:not([hidden])') return matches(node, '[data-file-row]') && !node.hidden;
    if (selector === '[data-file-row]:not([hidden]) input') return node.tagName === 'input' && !node.parentElement.hidden;
    return false;
  }
  const ids = Object.fromEntries([...template.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], element()]));
  ids.fileTypeFilter.tagName = 'select';
  const options = Object.fromEntries(optionNames.map((name) => {
    const tag = template.match(new RegExp(`<input[^>]*name="${name}"[^>]*>`))[0];
    const id = tag.match(/id="([^"]+)"/)?.[1];
    const control = id ? ids[id] : element();
    control.checked = /\schecked(?:\s|>)/.test(tag);
    control.disabled = /\sdisabled(?:\s|>)/.test(tag);
    return [name, control];
  }));
  const files = () => descendants(ids.fileList)
    .filter((control) => control.name === 'file_ids');
  const form = element();
  const main = element(), header = element();
  form.querySelectorAll = () => files().filter((control) => control.checked);
  const submitButton = element();
  form.querySelector = () => submitButton;
  const document = {
    cookie: '', body: element(),
    getElementById: (id) => ids[id],
    querySelector: (selector) => selector === "form[action='/download']" ? form
      : selector === 'main' ? main : selector === 'header' ? header
      : options[selector.match(/name=['"]([^'"]+)/)?.[1]],
    querySelectorAll: (selector) => selector.startsWith('#fileList') ? files() : [],
    createElement: element, createTextNode: (text) => ({ textContent: text }),
    addEventListener() {},
  };
  const requests = [];
  const context = vm.createContext({
    document,
    window: { addEventListener() {} },
    crypto: require('node:crypto').webcrypto,
    setInterval: () => 1, clearInterval() {},
    Option: function(text, value) { return { textContent: text, value }; },
    get localStorage() {
      if (storage instanceof Error) throw storage;
      return { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
    },
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => [{ id: 'file-1', name: 'Notes.docx' }] };
    },
  });
  vm.runInContext(script, context);
  return {
    options, ids, form, requests, files,
    change(name, checked) { options[name].checked = checked; options[name].dispatch('change'); },
    open: (id) => context.openDrawer(id, `Course ${id}`),
    close: () => context.closeDrawer(),
    clear: () => context.toggleAllFiles(false),
  };
}

test('download options survive a reload without storing file selections or course data', async () => {
  const storage = new Map();
  const first = page(storage);
  for (const name of optionNames) first.change(name, true);
  await first.open('course-a');
  first.clear();
  const reloaded = page(storage);
  for (const name of optionNames) assert.equal(reloaded.options[name].checked, true, name);
  assert.equal(storage.size, 1);
  assert.deepEqual(JSON.parse([...storage.values()][0]), Object.fromEntries(optionNames.map((name) => [name, true])));
  assert.deepEqual(reloaded.requests, []);
  await reloaded.open('course-b');
  assert.equal(reloaded.files()[0].checked, true);
  let prevented = false;
  reloaded.form.dispatch('submit', { preventDefault() { prevented = true; } });
  assert.equal(prevented, false);
  assert.match(reloaded.form.target, /^download_[a-f0-9]{32}$/);
  assert.deepEqual(reloaded.requests, ['/api/courses/course-b/files']);
});

test('missing, malformed and non-boolean preferences preserve default options', () => {
  for (const saved of [null, '{broken', 'null', 'false', '42', '"text"', '[]',
    JSON.stringify({ skip_videos: 'true', convert_word: 1, convert_powerpoint: {}, replace_originals: [] })]) {
    const storage = new Map(saved === null ? [] : [['gcr-downloader.download-options', saved]]);
    const current = page(storage);
    for (const name of optionNames) assert.equal(current.options[name].checked, false, `${saved}: ${name}`);
    assert.equal(current.options.replace_originals.disabled, true);
  }
});

test('partial preferences restore only known boolean options', () => {
  const current = page(new Map([['gcr-downloader.download-options', JSON.stringify({
    skip_videos: true, convert_word: 'false', token: 'not-a-preference', file_ids: ['old-file'],
  })]]));
  assert.equal(current.options.skip_videos.checked, true);
  assert.equal(current.options.convert_word.checked, false);
  assert.equal(current.options.replace_originals.disabled, true);
});

test('unavailable or failing storage never blocks drawer changes or downloads', async () => {
  const readFailure = new Map();
  readFailure.get = () => { throw new Error('read blocked'); };
  const writeFailure = new Map();
  writeFailure.set = () => { throw new Error('quota exceeded'); };
  for (const storage of [new Error('storage access denied'), readFailure, writeFailure]) {
    const current = page(storage);
    assert.equal(current.options.replace_originals.disabled, true);
    current.change('convert_word', true);
    current.change('replace_originals', true);
    current.change('skip_videos', true);
    assert.equal(current.options.replace_originals.disabled, false);
    assert.equal(current.options.replace_originals.checked, true);
    await current.open('course-a');
    current.form.dispatch('submit', { preventDefault() { assert.fail('download should work'); } });
    assert.match(current.form.target, /^download_[a-f0-9]{32}$/);
  }
});

test('restore disables and clears replace originals unless a conversion is enabled', () => {
  for (const conversion of [null, 'convert_word', 'convert_powerpoint']) {
    const preferences = { replace_originals: true };
    if (conversion) preferences[conversion] = true;
    const current = page(new Map([['gcr-downloader.download-options', JSON.stringify(preferences)]]));
    assert.equal(current.options.replace_originals.disabled, conversion === null);
    assert.equal(current.options.replace_originals.checked, conversion !== null);
  }
});

test('turning off the last conversion clears replace originals on this visit and reload', () => {
  const storage = new Map();
  const current = page(storage);
  current.change('convert_word', true);
  current.change('convert_powerpoint', true);
  current.change('replace_originals', true);
  current.change('convert_word', false);
  assert.equal(current.options.replace_originals.checked, true);
  assert.equal(current.options.replace_originals.disabled, false);
  current.change('convert_powerpoint', false);
  for (const visit of [current, page(storage)]) {
    assert.equal(visit.options.replace_originals.checked, false);
    assert.equal(visit.options.replace_originals.disabled, true);
  }
  current.change('convert_word', true);
  assert.equal(current.options.replace_originals.disabled, false);
  assert.equal(current.options.replace_originals.checked, false);
});

test('preferences apply across courses while file selections remain course-local', async () => {
  const current = page();
  await current.open('course-a');
  current.change('skip_videos', true);
  current.change('convert_powerpoint', true);
  current.change('replace_originals', true);
  current.clear();
  current.close();
  await current.open('course-b');
  for (const name of ['skip_videos', 'convert_powerpoint', 'replace_originals']) {
    assert.equal(current.options[name].checked, true, name);
  }
  assert.equal(current.options.convert_word.checked, false);
  assert.equal(current.ids.activeCourseId.value, 'course-b');
  assert.equal(current.files()[0].checked, true);
  current.change('skip_videos', false);
  current.close();
  await current.open('course-a');
  assert.equal(current.options.skip_videos.checked, false);
  assert.equal(current.options.replace_originals.checked, true);
});
