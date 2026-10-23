// Page-sized reads are shared until selection changes; only completed pages enter LRU.
class BookPageStore {
  constructor(fetcher = (url, options) => fetch(url, options)) {
    this.fetcher = fetcher;
    this.version = '';
    this.cache = new Map();
    this.pending = new Map();
  }

  key(file) {
    return file + (file.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(this.version);
  }

  cancel(keep = []) {
    const wanted = new Set(keep.map(file => this.key(file)));
    for (const [key, request] of this.pending) {
      if (!wanted.has(key)) {
        this.pending.delete(key);
        request.controller.abort();
      }
    }
  }

  read(file) {
    const key = this.key(file);
    if (this.cache.has(key)) {
      const value = this.cache.get(key);
      this.cache.delete(key);
      this.cache.set(key, value);
      return Promise.resolve(value);
    }
    if (this.pending.has(key)) return this.pending.get(key).promise;
    const controller = new AbortController();
    const request = { controller };
    const timer = setTimeout(() => controller.abort(new Error('数据页下载超时')), 30000);
    request.promise = Promise.resolve().then(async () => {
      try {
        controller.signal.throwIfAborted();
        const response = await this.fetcher(key, { signal: controller.signal });
        if (!response.ok) throw Error(response.status);
        const value = await response.json();
        controller.signal.throwIfAborted();
        if (!Array.isArray(value.books)) throw Error('无效的书籍数据页');
        this.cache.set(key, value);
        while (this.cache.size > 8) this.cache.delete(this.cache.keys().next().value);
        return value;
      } finally {
        clearTimeout(timer);
        if (this.pending.get(key) === request) this.pending.delete(key);
      }
    });
    this.pending.set(key, request);
    return request.promise;
  }

  async range(source, target, pageSize) {
    const count = source.count;
    const pages = Math.max(1, Math.ceil(count / pageSize));
    const page = Math.max(1, Math.min(pages, Math.floor(Number(target)) || 1));
    const start = (page - 1) * pageSize;
    const end = Math.min(count, start + pageSize);
    const first = Math.floor(start / source.page_size);
    const last = Math.max(first, Math.floor(Math.max(start, end - 1) / source.page_size));
    const files = Array.from({ length: last - first + 1 }, (_, i) => source.root
      ? source.root + (first + i + 1) + '.json' : source.files[first + i]);
    this.cancel(files);
    const blocks = await Promise.all(files.map(file => this.read(file)));
    const rows = blocks.flatMap(block => block.books);
    const offset = start - first * source.page_size;
    return { books: rows.slice(offset, offset + pageSize), page, pages, count };
  }
}
globalThis.BookPageStore = BookPageStore;
