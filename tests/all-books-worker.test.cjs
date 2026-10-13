const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../assets/all-books-worker.js'), 'utf8');
const books = [['1', 'One', 8, 100], ['2', 'Two', 9, 200]];
function worker(fetch, timers = { setTimeout, clearTimeout }) {
  const replies = [];
  const self = { location: { href: 'https://example.invalid/assets/all-books-worker.js' }, postMessage: reply => replies.push(reply) };
  vm.runInNewContext(source, { self, URL, AbortController, fetch, ...timers });
  return { replies, send: (id, extra = {}) => self.onmessage({ data: {
    requestId: id, file: 'data/all.json', page: 1, pageSize: 50, query: '', minRating: 0, minVotes: 0, ...extra,
  } }) };
}
test('failed download and invalid JSON remain retryable within the same worker', async t => {
  for (const failure of ['offline', 'invalid JSON']) await t.test(failure, async () => {
    let calls = 0;
    const fixture = worker(async () => {
      calls++;
      if (calls === 1 && failure === 'offline') throw Error('offline');
      return { ok: true, json: async () => { if (calls === 1) throw Error('invalid JSON'); return { books }; } };
    });
    await fixture.send(1);
    assert.ok(fixture.replies[0].error);
    await fixture.send(2);
    assert.equal(calls, 2);
    assert.equal(fixture.replies[1].count, 2);
  });
});
test('successful concurrent and repeated filtering shares one download and preserves paging', async () => {
  let calls = 0;
  const fixture = worker(async () => { calls++; return { ok: true, json: async () => ({ books }) }; });
  await Promise.all([fixture.send(1), fixture.send(2, { minRating: 9 })]);
  await fixture.send(3, { pageSize: 1, page: 2 });
  assert.equal(calls, 1);
  assert.equal(fixture.replies[2].books[0][0], '2');
});
test('the timeout covers stalled JSON and clears the failed cache for retry', async () => {
  let expire, calls = 0, cleared = 0;
  const fixture = worker(async (_url, { signal }) => {
    calls++;
    return { ok: true, json: () => calls > 1 ? Promise.resolve({ books }) : new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    }) };
  }, { setTimeout: (callback, ms) => { assert.equal(ms, 30000); expire = callback; return 1; }, clearTimeout: () => { cleared++; } });
  const first = fixture.send(1);
  await new Promise(resolve => setImmediate(resolve));
  expire();
  await first;
  assert.ok(fixture.replies[0].error);
  await fixture.send(2);
  assert.equal(fixture.replies[1].count, 2);
  assert.equal(cleared, 2);
});
