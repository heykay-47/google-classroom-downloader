// Behavior checks for the browser controller with a deterministic clock and DOM boundary.
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function browser() {
  let now = 0, sequence = 0, selected = 2;
  const timers = new Map(), cookies = new Map(), errors = [], logs = [], frames = [];
  const button = {disabled: false};
  const form = {
    action: '/download', listeners: {},
    querySelectorAll: () => Array(selected).fill({}),
    querySelector: () => button,
    setAttribute(k, v) { this[k] = v; },
    addEventListener(k, fn) { this.listeners[k] = fn; },
  };
  const status = {textContent: '', classList: {add() {}}};
  const document = {
    getElementById: () => status,
    createElement: () => {
      const frame = {listeners: {}, contentDocument: {querySelector: () => null, body: {textContent: ''}},
        addEventListener(k, fn) { this.listeners[k] = fn; }, remove() {this.removed = true;}};
      frames.push(frame); return frame;
    },
    body: {append() {}},
    get cookie() { return [...cookies].map(([k,v]) => `${k}=${v}`).join('; '); },
    set cookie(value) {
      const [pair] = value.split(';'), [k,v] = pair.split('=');
      if (value.includes('Max-Age=0')) cookies.delete(k); else cookies.set(k,v);
    },
  };
  const window = {addEventListener() {}};
  vm.runInNewContext(readFileSync('app/templates/download_status.js', 'utf8'), {
    downloadForm: form, document, window, showError: m => errors.push(m), logToTerminal: m => logs.push(m),
    crypto: {getRandomValues: a => { a.fill(++sequence); return a; }},
    Date: {now: () => now},
    setInterval: fn => {timers.set(1,fn); return 1;}, clearInterval: id => timers.delete(id),
  });
  return {form, button, status, cookies, errors, logs, frames, timers,
    submit() {let prevented = false; form.listeners.submit({preventDefault() {prevented = true;}}); return prevented;},
    tick(ms) {now += ms; for (const fn of [...timers.values()]) fn();},
    select(n) {selected = n;},
  };
}

const b = browser();
assert.equal(b.submit(), false);
assert.match(b.status.textContent, /Preparing 2 files.*0s/);
assert.equal(b.button.disabled, true);
assert.equal(b.submit(), true, 'duplicate submit must not create another attempt');
assert.equal(b.frames.length, 1);
b.cookies.set('download_status_stale', 'ready');
b.tick(2000);
assert.match(b.status.textContent, /2s/);
assert.equal(b.button.disabled, true, 'unrelated cookie cannot finish this attempt');
const firstQuery = new URL(b.form.action, 'http://localhost').searchParams;
assert.equal(firstQuery.get('download_deadline'), '300', 'deadline must use the original five-minute timer');
let token = firstQuery.get('download_token');
b.cookies.set(`download_status_${token}`, 'ready');
b.tick(250);
assert.equal(b.button.disabled, false);
assert.match(b.status.textContent, /response is ready/i);
assert.equal(b.timers.size, 0);
assert.equal(b.cookies.has(`download_status_${token}`), false);
assert.equal(b.submit(), false);
const secondQuery = new URL(b.form.action, 'http://localhost').searchParams;
const secondToken = secondQuery.get('download_token');
assert.equal(secondQuery.get('download_deadline'), '302', 'a repeat gets its own deadline');
assert.notEqual(token, secondToken);
b.cookies.set(`download_status_${token}`, 'ready');
b.tick(250);
assert.equal(b.button.disabled, true, 'late prior response cannot finish a repeat');
b.frames.at(-1).contentDocument.querySelector = () => ({dataset: {downloadToken: token}, textContent: 'Stale error'});
b.frames.at(-1).contentDocument.body.textContent = 'Stale error';
b.frames.at(-1).listeners.load();
assert.equal(b.button.disabled, true, 'a mismatched error envelope cannot finish this attempt');
b.frames.at(-1).contentDocument.querySelector = () => ({dataset: {downloadToken: secondToken}, textContent: 'Preparation unavailable. Retry.'});
b.frames.at(-1).listeners.load();
assert.match(b.errors.at(-1), /Preparation unavailable/);
assert.equal(b.button.disabled, false);
assert.equal(b.timers.size, 0);
b.submit(); b.tick(300000);
assert.match(b.errors.at(-1), /may still be running/i);
assert.equal(b.button.disabled, false);
assert.equal(b.timers.size, 0);
b.select(0); assert.equal(b.submit(), true);
assert.match(b.errors.at(-1), /Select at least one/);
const http = browser(); http.submit();
http.frames[0].contentDocument.body.textContent = '{"detail":[{"msg":"Invalid boolean"}]}';
http.frames[0].listeners.load();
assert.match(http.errors.at(-1), /rejected/i);
assert.equal(http.button.disabled, false);
console.log('download status behavior checks passed');
