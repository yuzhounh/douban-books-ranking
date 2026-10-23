const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../assets/pages-data.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
function store(fetcher, timers = { setTimeout, clearTimeout }) {
  const context = { fetch: fetcher, AbortController, ...timers };
  vm.runInNewContext(code, context);
  return new context.BookPageStore();
}
const source = { count: 205, page_size: 100, root: 'data/version/' };
function payload(url) {
  const number = Number(url.match(/\/(\d+)\.json/)[1]);
  return { books: Array.from({ length: Math.min(100, 205 - (number - 1) * 100) }, (_, i) => (number - 1) * 100 + i) };
}

test('25/50/100 pages, last page and clamping preserve every row while sharing decoded blocks', async () => {
  const calls = [];
  const cache = store(async url => { calls.push(url); return { ok: true, json: async () => payload(url) }; });
  const first = await cache.range(source, 1, 50);
  assert.deepEqual(plain(first.books), Array.from({length:50}, (_, i) => i));
  assert.deepEqual(plain((await cache.range(source, 2, 50)).books), Array.from({length:50}, (_, i) => i + 50));
  assert.equal(calls.length, 1);
  assert.deepEqual(plain((await cache.range(source, 3, 25)).books), Array.from({length:25}, (_, i) => i + 50));
  const last = await cache.range(source, 9999, 100);
  assert.deepEqual(plain(last), {books:[200,201,202,203,204],page:3,pages:3,count:205});
  cache.version = 'new snapshot';
  await cache.range(source, 1, 50);
  assert.equal(calls.length, 3);
  assert.ok(calls[2].endsWith('v=new%20snapshot'));
});

test('pending reads are shared; leaving a page aborts unused work; returning immediately starts a clean request', async () => {
  const requests = [];
  const cache = store((url, { signal }) => new Promise((resolve, reject) => {
    requests.push({url,signal,resolve});
    signal.addEventListener('abort', () => reject(signal.reason), {once:true});
  }));
  const first = cache.range(source, 1, 50);
  const shared = cache.range(source, 2, 50);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, 1);
  const failedFirst = assert.rejects(first);
  const failedShared = assert.rejects(shared);
  const next = cache.range(source, 3, 50);
  const failedNext = assert.rejects(next);
  const returned = cache.range(source, 1, 50);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(requests[0].signal.aborted);
  const current = requests.at(-1);
  current.resolve({ok:true,json:async()=>payload(current.url)});
  await Promise.all([failedFirst, failedShared, failedNext]);
  assert.equal((await returned).books[0], 0);
  assert.equal(cache.pending.size, 0);
});

test('sync fetch failures and JSON errors never poison the cache; completed cache stays bounded', async () => {
  let calls = 0;
  const cache = store(url => {
    if (++calls === 1) throw Error('offline');
    return {ok:true,json:async()=>{if(calls===2)throw Error('bad JSON');return payload(url)}};
  });
  await assert.rejects(cache.range(source, 1, 50), /offline/);
  await assert.rejects(cache.range(source, 1, 50), /bad JSON/);
  assert.equal((await cache.range(source, 1, 50)).books.length, 50);
  for (let i=0;i<12;i++) await cache.read(`data/different-${i}/1.json`);
  assert.equal(cache.cache.size, 8);
});

test('30-second timeout includes JSON parsing and allows retry', async () => {
  let expire, calls=0, cleared=0;
  const cache = store(async (_url,{signal}) => ({ok:true,json:()=>++calls>1
    ? Promise.resolve({books:[1]}) : new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}))}), {
    setTimeout(callback,ms){assert.equal(ms,30000);expire=callback;return 1},clearTimeout(){cleared++},
  });
  const first=cache.read('data/1.json');
  await new Promise(resolve=>setImmediate(resolve));
  expire();
  await assert.rejects(first,/超时/);
  assert.deepEqual(plain((await cache.read('data/1.json')).books),[1]);
  assert.equal(cleared,2);
});
