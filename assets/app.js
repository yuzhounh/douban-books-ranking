const { t, tLabel, isEn, getLang, setLang } = window.I18N;
const labels={all:'全部书籍',tag:'标签',doulist:'豆列',series:'丛书',top250:'Top 250'};
const sourcePrompts={tag:['查找标签','输入标签名'],doulist:['查找豆列','输入豆列名'],series:['查找丛书','输入丛书名']};
let catalog=null,kind='all',source=null,books=[],page=1,totalPages=1,resultCount=0,requestId=0,allWorker=null,pageSize=50;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const pageStore=new BookPageStore();

fetch('data/catalog.json',{cache:'no-cache'})
  .then(response=>{if(!response.ok)throw Error(response.status);return response.json()})
  .then(data=>{
    catalog=data;
    pageStore.version=data.generated_at;
    $('#formula').textContent=t('formula',{formula:data.formula});
    $('#generated-at').textContent=t('updated',{date:new Date(data.generated_at).toLocaleString(isEn()?'en-US':'zh-CN')});
    const allCount = data.all_books.count;
    $('#all-count').textContent = isEn() ? allCount.toLocaleString('en-US') : (allCount >= 10000 ? (allCount / 10000).toFixed(1) + '万' : allCount.toLocaleString());
    const pill = $('#modal-all-count-pill');
    if (pill) pill.textContent = allCount.toLocaleString(isEn()?'en-US':'zh-CN');
    for(const name of ['tag','doulist','series'])$('#'+name+'-count').textContent=data.categories[name].length;
    $('#top250-count').textContent='250';
    activateKind('all');
  })
  .catch(()=>$('#status').textContent=t('catalogFail'));

document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>activateKind(button.dataset.kind)));
$('#source-search').addEventListener('input',renderSources);
$('#apply-all-filters').addEventListener('click',()=>loadAllBooks(1));
$('#reset-all-filters').addEventListener('click',()=>{
  $('#all-book-search').value='';$('#min-rating').value='0.0';$('#min-votes').value='0';loadAllBooks(1);
});
for(const selector of ['#all-book-search','#min-rating','#min-votes']){
  $(selector).addEventListener('keydown',event=>{
    if(event.key==='Enter'){
      event.preventDefault();
      loadAllBooks(1);
      if(window.innerWidth<=800)closeSwitchCategoryModal();
    }
  });
}
$('#first-page').addEventListener('click',()=>loadPage(1));
$('#previous-page').addEventListener('click',()=>loadPage(page-1));
$('#next-page').addEventListener('click',()=>loadPage(page+1));
$('#last-page').addEventListener('click',()=>loadPage(totalPages));
$('#go-page').addEventListener('click',goToInputPage);
$('#page-number').addEventListener('keydown',event=>{if(event.key==='Enter')goToInputPage()});
$('#page-size').addEventListener('change',()=>{pageSize=Number($('#page-size').value)||50;loadPage(1)});

function activateKind(nextKind){
  if(!catalog)return;
  pageStore.cancel();
  kind=nextKind;source=null;books=[];page=1;totalPages=1;resultCount=0;requestId++;
  document.querySelectorAll('.tab').forEach(item=>item.classList.toggle('active',item.dataset.kind===kind));
  $('#kind-label').textContent=tLabel(labels[kind]);
  updateMobileCategoryLabel();
  $('#book-rows').innerHTML='';
  $('#pagination').hidden=true;
  const isAll=kind==='all';
  $('#all-controls').hidden=!isAll;
  $('#all-threshold-controls').hidden=!isAll;
  $('#source-controls').hidden=isAll;
  if(isAll){
    $('#source-title').textContent=tLabel('全部书籍');
    loadAllBooks(1);
    return;
  }
  const hasSourceSearch=kind!=='top250';
  $('#source-search-fields').hidden=!hasSourceSearch;
  if(hasSourceSearch){
    const [label,placeholder]=sourcePrompts[kind];
    $('#source-search-label').textContent=tLabel(label);
    $('#source-search').placeholder=tLabel(placeholder);
  }
  $('#source-search').value='';
  $('#source-title').textContent=t('pickSource');
  $('#status').textContent=t('pickLeftSource');
  renderSources();
  // 仅在桌面端侧边栏模式下自动选第一项；在移动端弹窗内绝不自动触发，让用户在弹窗中自选具体项
  if (window.innerWidth > 800) {
    selectFirstSource();
  }
}

function renderSources(){
  if(!catalog||kind==='all')return;
  const list=$('#source-list');
  if (kind === 'tag') {
    list.classList.add('is-tag-category');
  } else {
    list.classList.remove('is-tag-category');
  }
  const query=$('#source-search').value.trim().toLowerCase();
  const matches=catalog.categories[kind].filter(item=>(item.label+' '+item.key).toLowerCase().includes(query));
  list.innerHTML='';
  for(const item of matches){
    const button=document.createElement('button');
    button.className='source-item'+(source===item?' active':'');
    button.title=item.label;
    button.setAttribute('aria-pressed',source===item?'true':'false');
    button.innerHTML='<span>'+esc(item.label)+'</span><span>'+item.count.toLocaleString()+'</span>';
    button.addEventListener('click',()=>{
      source=item;
      document.querySelectorAll('.source-item').forEach(node=>{node.classList.remove('active');node.setAttribute('aria-pressed','false')});
      button.classList.add('active');button.setAttribute('aria-pressed','true');
      $('#source-title').textContent=item.label;
      updateMobileCategoryLabel(item.label);
      loadSourcePage(1);
      if(window.innerWidth<=800&&typeof closeSwitchCategoryModal==='function'){
        closeSwitchCategoryModal();
      }
    });
    list.appendChild(button);
  }
  if(!matches.length)list.textContent=t('noSourceMatch');
}

function selectFirstSource(){if(window.innerWidth<=800)return;const first=$('#source-list .source-item');if(first)first.click()}

function ensureAllWorker(){
  if(allWorker)return allWorker;
  allWorker=new Worker('assets/all-books-worker.js?v=20261023-1');
  allWorker.onmessage=event=>{
    const data=event.data;
    if(data.requestId!==requestId||kind!=='all')return;
    if(data.error){$('#status').textContent=t('allIndexFail');return}
    showAllPage(data);
  };
  return allWorker;
}

function showAllPage(data){
  books=data.books.map(item=>({id:item[0],title:item[1],rating:item[2],rating_count:item[3],url:'https://book.douban.com/subject/'+item[0]+'/'}));
  page=data.page;totalPages=data.pages;resultCount=data.count;
  renderBookRows(pageSize);
  $('#status').textContent=t('pageStatus',{page:page,total:totalPages,count:books.length,result:resultCount.toLocaleString(isEn()?'en-US':'zh-CN')});
  updatePagination();
}

async function loadAllBooks(target){
  const rating=Math.max(0,Math.min(10,Number($('#min-rating').value)||0));
  const votes=Math.max(0,Math.floor(Number($('#min-votes').value)||0));
  $('#min-rating').value=rating.toFixed(1);$('#min-votes').value=String(votes);
  const currentRequest=++requestId;
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  const query=$('#all-book-search').value.trim();
  if(!query&&rating===0&&votes===0&&catalog.all_books.paged){
    $('#status').textContent=t('loadingPage',{page:target});
    try{
      const data=await pageStore.range(catalog.all_books.paged,target,pageSize);
      if(currentRequest!==requestId||kind!=='all')return;
      showAllPage(data);
    }catch(error){if(currentRequest===requestId)$('#status').textContent=t('pageFailRetry')}
    return;
  }
  pageStore.cancel();
  $('#status').textContent=t('filterAll');
  ensureAllWorker().postMessage({requestId:currentRequest,file:catalog.all_books.file,page:target,pageSize:pageSize,query,minRating:rating,minVotes:votes});
}

async function loadSourcePage(target){
  if(!source)return;
  totalPages=Math.max(1,Math.ceil(source.count/pageSize));
  target=Math.max(1,Math.min(totalPages,Number(target)||1));
  const currentRequest=++requestId;
  $('#status').textContent=t('loadingPage',{page:target});
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  const selectedSource=source;
  try{
    const data=await pageStore.range(selectedSource,target,pageSize);
    if(currentRequest!==requestId||kind==='all')return;
    books=data.books;
    page=data.page;resultCount=selectedSource.count;
    renderBookRows(pageSize);
    $('#status').textContent=t('pageStatus',{page:page,total:totalPages,count:books.length,result:source.count.toLocaleString(isEn()?'en-US':'zh-CN')});
    updatePagination();
  }catch(error){if(currentRequest===requestId)$('#status').textContent=t('pageFail')}
}

function openBook(url) {
  window.open(url, "_blank", "noopener,noreferrer");
}

function renderBookRows(pageSize){
  if (books.length === 0) {
    $('#book-rows').innerHTML = '<tr><td colspan="6" class="message">' + t('empty') + '</td></tr>';
    return;
  }
  const offset = (page - 1) * pageSize;
  $('#book-rows').innerHTML = books.map((book, index) => {
    const rank = offset + index + 1;
    const ratingStr = book.rating == null ? '—' : Number(book.rating).toFixed(1);
    const votesStr = book.rating_count == null ? '—' : book.rating_count.toLocaleString();
    const url = encodeURI(book.url);
    const safeTitle = esc(book.title);
    return `<tr data-url="${url}" tabindex="0" role="link" aria-label="${esc(t('open.aria',{title:book.title}))}">` +
      `<td class="rank">${rank}</td>` +
      `<td class="id">${book.id}</td>` +
      `<td class="title"><a class="book-title-link" href="${url}" target="_blank" rel="noopener">${safeTitle}</a><span class="inline-id">ID ${book.id}</span></td>` +
      `<td class="rating">${ratingStr}</td>` +
      `<td class="rating-count">${votesStr}</td>` +
      `<td class="book-link-col"><a href="${url}" target="_blank" rel="noopener">${t('douban')}</a></td>` +
    `</tr>`;
  }).join('');
}

function updatePagination(){
  $('#pagination').hidden=totalPages<=1;
  $('#page-number').value=page;$('#page-number').max=totalPages;
  $('#page-total').textContent=t('pagination.total',{pages:totalPages});
  $('#first-page').disabled=page===1;$('#previous-page').disabled=page===1;
  $('#next-page').disabled=page===totalPages;$('#last-page').disabled=page===totalPages;
}

function loadPage(target){if(kind==='all')loadAllBooks(target);else loadSourcePage(target)}
function goToInputPage(){loadPage($('#page-number').value)}


// ---- 主题、抽屉、切类弹窗控制器 ----
const themeToggleBtn = document.getElementById('theme-toggle-btn');
const mobileThemeToggle = document.getElementById('mobile-theme-toggle');
const drawerLayer = document.getElementById('mobile-drawer-layer');
const drawerToggle = document.getElementById('mobile-drawer-toggle');
const drawerClose = document.getElementById('mobile-drawer-close');
const drawerBackdrop = document.getElementById('mobile-drawer-backdrop');

const switchCategoryModal = document.getElementById('switch-category-modal');
const closeSwitchCategoryModalBtn = document.getElementById('closeSwitchCategoryModal');
const openCategoryFromFilter = document.getElementById('openCategoryFromFilter');
const mobileDrawerSwitchCategory = document.getElementById('mobileDrawerSwitchCategory');

const formulaModal = document.getElementById('formula-modal');
const closeFormulaModalBtn = document.getElementById('closeFormulaModal');
const mobileDrawerFormula = document.getElementById('mobileDrawerFormula');
const mobileDrawerSearch = document.getElementById('mobileDrawerSearch');

function getStoredTheme() {
  const saved = localStorage.getItem('douban_books_theme');
  if (saved === 'dark' || saved === 'light') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  const isDark = theme === 'dark';
  document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');
  try {
    localStorage.setItem('douban_books_theme', theme);
  } catch (_) {}

  const navSun = document.getElementById('theme-icon-sun');
  const navMoon = document.getElementById('theme-icon-moon');
  if (navSun) navSun.style.display = isDark ? 'inline-block' : 'none';
  if (navMoon) navMoon.style.display = isDark ? 'none' : 'inline-block';

  const drawerSun = document.getElementById('drawer-theme-icon-sun');
  const drawerMoon = document.getElementById('drawer-theme-icon-moon');
  if (drawerSun) drawerSun.style.display = isDark ? 'none' : 'inline-block';
  if (drawerMoon) drawerMoon.style.display = isDark ? 'inline-block' : 'none';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || getStoredTheme();
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

applyTheme(getStoredTheme());

if (themeToggleBtn) themeToggleBtn.addEventListener('click', toggleTheme);
if (mobileThemeToggle) mobileThemeToggle.addEventListener('click', toggleTheme);

function openDrawer() {
  if (drawerLayer) {
    drawerLayer.removeAttribute('hidden');
    drawerLayer.hidden = false;
    document.body.style.overflow = 'hidden';
  }
}

function closeDrawer() {
  if (drawerLayer) {
    drawerLayer.setAttribute('hidden', '');
    drawerLayer.hidden = true;
    document.body.style.overflow = '';
  }
}

if (drawerToggle) drawerToggle.addEventListener('click', openDrawer);
if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
if (drawerBackdrop) drawerBackdrop.addEventListener('click', closeDrawer);

function openSwitchCategoryModal() {
  if (switchCategoryModal) {
    switchCategoryModal.removeAttribute('hidden');
    switchCategoryModal.hidden = false;
    document.body.style.overflow = 'hidden';
  }
}

function closeSwitchCategoryModal() {
  if (switchCategoryModal) {
    switchCategoryModal.setAttribute('hidden', '');
    switchCategoryModal.hidden = true;
    document.body.style.overflow = '';
  }
}

if (closeSwitchCategoryModalBtn) closeSwitchCategoryModalBtn.addEventListener('click', closeSwitchCategoryModal);
if (switchCategoryModal) {
  switchCategoryModal.addEventListener('click', (e) => {
    if (e.target === switchCategoryModal) closeSwitchCategoryModal();
  });
}
if (openCategoryFromFilter) {
  openCategoryFromFilter.addEventListener('click', openSwitchCategoryModal);
}
if (mobileDrawerSwitchCategory) {
  mobileDrawerSwitchCategory.addEventListener('click', () => {
    closeDrawer();
    openSwitchCategoryModal();
  });
}

function openFormulaModal() {
  if (formulaModal) {
    formulaModal.removeAttribute('hidden');
    formulaModal.hidden = false;
    document.body.style.overflow = 'hidden';
  }
}

function closeFormulaModal() {
  if (formulaModal) {
    formulaModal.setAttribute('hidden', '');
    formulaModal.hidden = true;
    document.body.style.overflow = '';
  }
}

if (closeFormulaModalBtn) closeFormulaModalBtn.addEventListener('click', closeFormulaModal);
if (formulaModal) {
  formulaModal.addEventListener('click', (e) => {
    if (e.target === formulaModal) closeFormulaModal();
  });
}
if (mobileDrawerFormula) {
  mobileDrawerFormula.addEventListener('click', () => {
    closeDrawer();
    openFormulaModal();
  });
}

if (mobileDrawerSearch) {
  mobileDrawerSearch.addEventListener('click', () => {
    closeDrawer();
    if(window.innerWidth<=800)openSwitchCategoryModal();
    const searchInput = kind==='all' ? $('#all-book-search') : kind==='top250' ? null : $('#source-search');
    if (searchInput) {
      searchInput.focus();
      searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
}

window.addEventListener('keydown', (e) => {
  const isInputActive = ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  if ((e.key === 'd' || e.key === 'D') && !isInputActive) {
    e.preventDefault();
    toggleTheme();
  } else if (e.key === 'Escape') {
    if (switchCategoryModal && !switchCategoryModal.hidden) {
      closeSwitchCategoryModal();
    } else if (formulaModal && !formulaModal.hidden) {
      closeFormulaModal();
    } else if (drawerLayer && !drawerLayer.hidden) {
      closeDrawer();
    }
  }
});

function updateMobileCategoryLabel(subLabel) {
  const mobileVal = document.getElementById('mobileCurrentCategory');
  if (!mobileVal) return;
  const mainLabel = tLabel(labels[kind] || '全部书籍');
  if (subLabel) {
    mobileVal.textContent = `${mainLabel} / ${subLabel}`;
  } else if (kind === 'all') {
    mobileVal.textContent = tLabel('全部书籍');
  } else if (source && source.label) {
    mobileVal.textContent = `${mainLabel} / ${source.label}`;
  } else {
    mobileVal.textContent = mainLabel;
  }
}

// 动态响应式转移 Tabs 和 Source-Panel（桌面端在顶部和侧边，移动端在切类弹窗中）
function syncCategoryPlacement() {
  const isMobile = window.innerWidth <= 800;
  const desktopCatSlot = document.getElementById('desktop-category-slot');
  const desktopSrcSlot = document.getElementById('desktop-source-slot');
  const modalCatSlot = document.getElementById('modal-category-slot');
  const tabsNav = document.getElementById('category-tabs-nav');
  const srcPanel = document.getElementById('source-panel');

  if (!tabsNav || !srcPanel || !desktopCatSlot || !desktopSrcSlot || !modalCatSlot) return;

  if (isMobile) {
    if (modalCatSlot.firstElementChild !== tabsNav) {
      modalCatSlot.appendChild(tabsNav);
      modalCatSlot.appendChild(srcPanel);
    }
  } else {
    if (desktopCatSlot.firstElementChild !== tabsNav) {
      desktopCatSlot.appendChild(tabsNav);
    }
    if (desktopSrcSlot.firstElementChild !== srcPanel) {
      desktopSrcSlot.appendChild(srcPanel);
    }
  }
}

window.addEventListener('resize', syncCategoryPlacement);
syncCategoryPlacement();


// 移动端切类弹窗中的“全部书籍”快捷选择按钮
const modalAllBooksChoiceBtn = document.getElementById('modalAllBooksChoiceBtn');
if (modalAllBooksChoiceBtn) {
  modalAllBooksChoiceBtn.addEventListener('click', () => {
    activateKind('all');
    updateMobileCategoryLabel();
    if (window.innerWidth <= 800 && typeof closeSwitchCategoryModal === 'function') {
      closeSwitchCategoryModal();
    }
  });
}

// 书籍卡片点击整行跳转与键盘回车交互
const bookRowsTable = document.getElementById('book-rows');
if (bookRowsTable) {
  bookRowsTable.addEventListener('click', (e) => {
    const row = e.target.closest('tr[data-url]');
    if (!row) return;
    if (e.target.closest('a')) return;
    const url = row.dataset.url;
    if (url) openBook(url);
  });
  bookRowsTable.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      const row = e.target.closest('tr[data-url]');
      if (row && e.target === row) {
        e.preventDefault();
        const url = row.dataset.url;
        if (url) openBook(url);
      }
    }
  });
}

// 语言切换后重渲染当前视图（静态文案由 assets/i18n.js 处理）
document.addEventListener('i18n:change', () => {
  if (!catalog) return;
  if (catalog.formula) $('#formula').textContent = t('formula', { formula: catalog.formula });
  $('#generated-at').textContent = t('updated', { date: new Date(catalog.generated_at).toLocaleString(isEn() ? 'en-US' : 'zh-CN') });
  if (catalog.all_books) {
    const allCount = catalog.all_books.count;
    $('#all-count').textContent = isEn() ? allCount.toLocaleString('en-US') : (allCount >= 10000 ? (allCount / 10000).toFixed(1) + '万' : allCount.toLocaleString());
    const pill = $('#modal-all-count-pill');
    if (pill) pill.textContent = allCount.toLocaleString(isEn() ? 'en-US' : 'zh-CN');
  }
  $('#kind-label').textContent = tLabel(labels[kind]);
  $('#source-title').textContent = kind === 'all' ? tLabel('全部书籍') : (source ? source.label : t('pickSource'));
  updateMobileCategoryLabel(source && source.label ? source.label : undefined);
  loadPage(page || 1);
});
