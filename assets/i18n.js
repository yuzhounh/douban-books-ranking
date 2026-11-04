// Lightweight bilingual (Simplified Chinese / English) runtime for the Douban
// Books ranking site. Loaded as a classic script before assets/app.js.
// Default language is Simplified Chinese; the choice is stored in localStorage
// and switched from the site's settings drawer or the top-bar selector.
(function () {
  const STORAGE_KEY = "douban_books_lang";
  const SUPPORTED = ["zh", "en"];

  const EN = {
    "豆瓣读书排行榜": "Douban Books Ranking",
    "豆瓣读书": "Douban Books",
    "功能导航": "Navigation",
    "切换类别与来源": "Switch category & source",
    "搜索书籍 / 来源": "Search books / sources",
    "评分规则说明": "Scoring rules",
    "外观主题": "Theme",
    "开源项目": "Open source",
    "切换来源与类别": "Switch source & category",
    "📐 综合评分公式与规则": "📐 Composite score formula & rules",
    "综合评分": "Composite score",
    "评分": "Rating",
    "评价人数": "Votes",
    "计算原理与设计初衷：": "How it works and why:",
    "质量基准": "Quality baseline",
    "：将评分基准设为 2.5 分，凸显有效好评的书籍价值。":
      ": Sets the rating baseline at 2.5 to emphasise genuinely well-rated books.",
    "对数热度": "Logarithmic popularity",
    "：通过评价人数的自然对数（ln）收敛热门书籍的数量权重，防止唯人数论。":
      ": Uses the natural log (ln) of vote counts to dampen runaway popularity and avoid ranking purely by vote count.",
    "兼顾小众与经典": "Balances niche and classic",
    "：使高质量冷门好书与大样本经典神作在同一坐标系下合理排列。":
      ": Places high-quality hidden gems and massively popular classics on one comparable scale.",
    "从标签、豆列、丛书与 Top 250 重新发现值得读的书。":
      "Rediscover books worth reading through tags, doulists, series and the Top 250.",
    "综合评分加载中…": "Loading composite score…",
    "全部书籍": "All books",
    "标签": "Tags",
    "豆列": "Doulists",
    "丛书": "Series",
    "全部书籍（浏览 33.8 万本全部数据）": "All books (browse all 338,820 titles)",
    "搜索全部书籍": "Search all books",
    "查找来源": "Find source",
    "当前类别：": "Current category:",
    "切换类别": "Switch category",
    "最低评分": "Min rating",
    "最低评价人数": "Min votes",
    "筛选": "Filter",
    "重置": "Reset",
    "正在加载当前页…": "Loading current page…",
    "每页显示": "Show",
    "条": "per page",
    "书名": "Title",
    "链接": "Link",
    "首页": "First",
    "上一页": "Prev",
    "第": "Page",
    "页": "",
    "跳转": "Go",
    "下一页": "Next",
    "末页": "Last",
    "/ 1 页": "/ 1",
    "数据来自豆瓣公开的标签筛选页、豆列、丛书与 Top 250 页面，仅供学习、研究与索引。评分及评价人数可能随时间变化。":
      "Data comes from public Douban tag pages, doulists, series and Top 250 pages, for study, research and indexing only. Ratings and vote counts may change over time.",
    "查看源代码": "View source code",
    "语言 / Language": "Language",
  };

  const ATTR = {
    "全局导航": "Global navigation",
    "豆瓣读书排行榜首页": "Douban Books Ranking home",
    "切换外观主题": "Toggle theme",
    "切换外观主题 (D)": "Toggle theme (D)",
    "GitHub 源代码": "GitHub source code",
    "打开导航与设置菜单": "Open navigation and settings menu",
    "快捷设置与导航": "Quick settings and navigation",
    "关闭菜单": "Close menu",
    "关闭切换类别": "Close category switcher",
    "关闭": "Close",
    "关闭公式说明": "Close formula explanation",
    "来源类别": "Source categories",
    "切换类别与来源": "Switch category & source",
    "书籍分页": "Book pagination",
    "第一页": "First page",
    "上一页": "Previous page",
    "下一页": "Next page",
    "最后一页": "Last page",
    "输入书名或豆瓣 ID": "Enter a book title or Douban ID",
    "输入来源名": "Enter a source name",
    "语言 / Language": "Language",
  };

  const LABELS = {
    "全部书籍": "All books",
    "标签": "Tags",
    "豆列": "Doulists",
    "丛书": "Series",
    "Top 250": "Top 250",
    "全部": "All",
    "查找标签": "Find tag",
    "输入标签名": "Enter a tag name",
    "查找豆列": "Find doulist",
    "输入豆列名": "Enter a doulist name",
    "查找丛书": "Find series",
    "输入丛书名": "Enter a series name",
    "更早": "Earlier",
  };

  const MESSAGES = {
    "formula": { zh: "综合评分 = {formula}", en: "Composite score = {formula}" },
    "updated": { zh: "数据更新：{date}", en: "Data updated: {date}" },
    "catalogFail": { zh: "目录加载失败，请稍后重试。", en: "Failed to load the catalog. Please try again later." },
    "pickSource": { zh: "请选择一个来源", en: "Select a source" },
    "pickLeftSource": { zh: "请选择左侧来源", en: "Choose a source on the left" },
    "noSourceMatch": { zh: "没有匹配的来源", en: "No matching sources" },
    "allIndexFail": { zh: "全部书籍索引加载失败，联网后点击“筛选”重试。", en: "Failed to load the full index. Go online and tap “Filter” to retry." },
    "pageFailRetry": { zh: "这一页加载失败，联网后点击“筛选”重试。", en: "Failed to load this page. Go online and tap “Filter” to retry." },
    "filterAll": { zh: "正在筛选全部书籍，首次使用需要加载索引…", en: "Filtering all books. The index loads on first use…" },
    "loadingPage": { zh: "正在加载第 {page} 页…", en: "Loading page {page}…" },
    "pageFail": { zh: "这一页加载失败，请稍后重试。", en: "Failed to load this page. Please try again later." },
    "empty": { zh: "没有找到匹配的书籍条目", en: "No matching books found" },
    "open.aria": { zh: "在豆瓣打开《{title}》", en: "Open “{title}” on Douban" },
    "douban": { zh: "豆瓣", en: "Douban" },
    "pagination.total": { zh: "/ {pages} 页", en: "/ {pages}" },
    "pageStatus": { zh: "第 {page} / {total} 页，本页 {count} 本，共 {result} 本，按综合评分排序", en: "Page {page} / {total} · {count} on this page · {result} total · sorted by composite score" },
  };

  const DOC = {
    title: { zh: "豆瓣读书排行榜", en: "Douban Books Ranking" },
    description: {
      zh: "浏览和筛选豆瓣读书公开列表中的全部书籍、标签、豆列、丛书与 Top 250 排行",
      en: "Browse and filter all books, tags, doulists, series and the Top 250 from public Douban Books lists.",
    },
  };

  const originalText = new WeakMap();
  const originalAttrs = new WeakMap();

  function normalize(lang) {
    return SUPPORTED.includes(lang) ? lang : "zh";
  }
  function getLang() {
    try {
      return normalize(localStorage.getItem(STORAGE_KEY) || "zh");
    } catch (e) {
      return "zh";
    }
  }
  function isEn() {
    return getLang() === "en";
  }
  function pad(original, replacement) {
    const lead = (original.match(/^\s*/) || [""])[0];
    const trail = (original.match(/\s*$/) || [""])[0];
    return lead + replacement + trail;
  }
  function applyTextNode(node, en) {
    if (originalText.has(node)) {
      const original = originalText.get(node);
      if (en) {
        const key = original.trim();
        node.nodeValue = Object.prototype.hasOwnProperty.call(EN, key) ? pad(original, EN[key]) : original;
      } else {
        node.nodeValue = original;
        originalText.delete(node);
      }
      return;
    }
    if (!en) return;
    const current = node.nodeValue;
    const key = current.trim();
    if (!key || !Object.prototype.hasOwnProperty.call(EN, key)) return;
    originalText.set(node, current);
    node.nodeValue = pad(current, EN[key]);
  }
  function applyAttr(el, attr, en) {
    if (!el.hasAttribute(attr)) return;
    let map = originalAttrs.get(el);
    if (!map) {
      map = new Map();
      originalAttrs.set(el, map);
    }
    if (!map.has(attr)) map.set(attr, el.getAttribute(attr));
    const original = map.get(attr);
    const key = (original || "").trim();
    if (en && Object.prototype.hasOwnProperty.call(ATTR, key)) el.setAttribute(attr, ATTR[key]);
    else el.setAttribute(attr, original);
  }
  function applyStatic() {
    const en = isEn();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const tag = node.parentNode && node.parentNode.nodeName;
        if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let node;
    while ((node = walker.nextNode())) applyTextNode(node, en);
    document.querySelectorAll("[placeholder],[title],[aria-label],[alt]").forEach(function (el) {
      ["placeholder", "title", "aria-label", "alt"].forEach(function (attr) {
        applyAttr(el, attr, en);
      });
    });
    document.documentElement.lang = en ? "en" : "zh-CN";
    document.title = DOC.title[en ? "en" : "zh"];
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute("content", DOC.description[en ? "en" : "zh"]);
  }
  function tFormula(formula) {
    if (!formula || typeof formula !== "string") return formula;
    if (!isEn()) return formula;
    return formula
      .replace(/评分/g, EN["评分"] || "Rating")
      .replace(/评价人数/g, EN["评价人数"] || "Votes");
  }
  function t(key, vars) {
    const entry = MESSAGES[key];
    let text = entry ? entry[isEn() ? "en" : "zh"] : key;
    if (vars) {
      Object.keys(vars).forEach(function (name) {
        let val = vars[name];
        if (isEn() && key === "formula" && name === "formula") {
          val = tFormula(val);
        }
        text = text.split("{" + name + "}").join(String(val));
      });
    }
    return text;
  }
  function tLabel(text) {
    if (!isEn() || text == null) return text;
    if (Object.prototype.hasOwnProperty.call(LABELS, text)) return LABELS[text];
    const decade = /^(\d{4})年代$/.exec(text);
    if (decade) return decade[1] + "s";
    return text;
  }
  function syncButtons() {
    const lang = getLang();
    const isChinese = lang === "zh";
    const label = isChinese ? "Switch to English" : "切换为中文";
    const text = isChinese ? "EN" : "中";
    [document.getElementById("lang-toggle-btn"), document.getElementById("mobile-lang-toggle")].forEach((btn) => {
      if (!btn) return;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
      const span = btn.querySelector(".lang-toggle-text");
      if (span) span.textContent = text;
    });
  }
  function setLang(lang) {
    const next = normalize(lang);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (e) {
      /* ignore */
    }
    applyStatic();
    syncButtons();
    document.dispatchEvent(new CustomEvent("i18n:change", { detail: next }));
    return next;
  }
  function init() {
    applyStatic();
    syncButtons();
    function toggle() { setLang(isEn() ? "zh" : "en"); }
    const a = document.getElementById("lang-toggle-btn");
    const b = document.getElementById("mobile-lang-toggle");
    if (a) a.addEventListener("click", toggle);
    if (b) b.addEventListener("click", toggle);
  }

  window.I18N = { getLang, isEn, t, tLabel, tFormula, applyStatic, setLang, changeLang: setLang };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
