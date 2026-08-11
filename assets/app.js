const labels={all:'全部书籍',tag:'标签',doulist:'豆列',series:'丛书',top250:'Top 250'};
const sourcePrompts={tag:['查找标签','输入标签名'],doulist:['查找豆列','输入豆列名'],series:['查找丛书','输入丛书名']};
let catalog=null,kind='all',source=null,books=[],page=1,totalPages=1,resultCount=0,requestId=0,allWorker=null;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

fetch('data/catalog.json')
  .then(response=>{if(!response.ok)throw Error(response.status);return response.json()})
  .then(data=>{
    catalog=data;
    $('#formula').textContent='综合评分 = '+data.formula;
    $('#generated-at').textContent='数据更新：'+new Date(data.generated_at).toLocaleString('zh-CN');
    $('#all-count').textContent=data.all_books.count.toLocaleString();
    for(const name of ['tag','doulist','series','top250'])$('#'+name+'-count').textContent=data.categories[name].length;
    activateKind('all');
  })
  .catch(()=>$('#status').textContent='目录加载失败，请稍后重试。');

document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>activateKind(button.dataset.kind)));
$('#source-search').addEventListener('input',renderSources);
$('#apply-all-filters').addEventListener('click',()=>loadAllBooks(1));
$('#reset-all-filters').addEventListener('click',()=>{
  $('#all-book-search').value='';$('#min-rating').value='0.0';$('#min-votes').value='0';loadAllBooks(1);
});
for(const selector of ['#all-book-search','#min-rating','#min-votes']){
  $(selector).addEventListener('keydown',event=>{if(event.key==='Enter')loadAllBooks(1)});
}
$('#first-page').addEventListener('click',()=>loadPage(1));
$('#previous-page').addEventListener('click',()=>loadPage(page-1));
$('#next-page').addEventListener('click',()=>loadPage(page+1));
$('#last-page').addEventListener('click',()=>loadPage(totalPages));
$('#go-page').addEventListener('click',goToInputPage);
$('#page-number').addEventListener('keydown',event=>{if(event.key==='Enter')goToInputPage()});

function activateKind(nextKind){
  if(!catalog)return;
  kind=nextKind;source=null;books=[];page=1;totalPages=1;resultCount=0;requestId++;
  document.querySelectorAll('.tab').forEach(item=>item.classList.toggle('active',item.dataset.kind===kind));
  $('#kind-label').textContent=labels[kind];
  $('#book-rows').innerHTML='';
  $('#pagination').hidden=true;
  const isAll=kind==='all';
  $('#all-controls').hidden=!isAll;
  $('#all-threshold-controls').hidden=!isAll;
  $('#source-controls').hidden=isAll;
  if(isAll){
    $('#source-title').textContent='全部书籍';
    loadAllBooks(1);
    return;
  }
  const hasSourceSearch=kind!=='top250';
  $('#source-search-fields').hidden=!hasSourceSearch;
  if(hasSourceSearch){
    const [label,placeholder]=sourcePrompts[kind];
    $('#source-search-label').textContent=label;
    $('#source-search').placeholder=placeholder;
  }
  $('#source-search').value='';
  $('#source-title').textContent='请选择一个来源';
  $('#status').textContent='请选择左侧来源';
  renderSources();
  selectFirstSource();
}

function renderSources(){
  if(!catalog||kind==='all')return;
  const query=$('#source-search').value.trim().toLowerCase();
  const matches=catalog.categories[kind].filter(item=>(item.label+' '+item.key).toLowerCase().includes(query));
  const list=$('#source-list');
  list.innerHTML='';
  for(const item of matches){
    const button=document.createElement('button');
    button.className='source-item'+(source===item?' active':'');
    button.setAttribute('aria-pressed',source===item?'true':'false');
    button.innerHTML='<span>'+esc(item.label)+'</span><span>'+item.count.toLocaleString()+'</span>';
    button.addEventListener('click',()=>{
      source=item;
      document.querySelectorAll('.source-item').forEach(node=>{node.classList.remove('active');node.setAttribute('aria-pressed','false')});
      button.classList.add('active');button.setAttribute('aria-pressed','true');
      $('#source-title').textContent=item.label;
      loadSourcePage(1);
    });
    list.appendChild(button);
  }
  if(!matches.length)list.textContent='没有匹配的来源';
}

function selectFirstSource(){const first=$('#source-list .source-item');if(first)first.click()}

function ensureAllWorker(){
  if(allWorker)return allWorker;
  allWorker=new Worker('assets/all-books-worker.js');
  allWorker.onmessage=event=>{
    const data=event.data;
    if(data.requestId!==requestId||kind!=='all')return;
    if(data.error){$('#status').textContent='全部书籍索引加载失败，请稍后重试。';return}
    books=data.books.map(item=>({id:item[0],title:item[1],rating:item[2],rating_count:item[3],url:'https://book.douban.com/subject/'+item[0]+'/'}));
    page=data.page;totalPages=data.pages;resultCount=data.count;
    renderBookRows(catalog.all_books.page_size);
    $('#status').textContent='第 '+page+' / '+totalPages+' 页，本页 '+books.length+' 本，共 '+resultCount.toLocaleString()+' 本，按综合评分排序';
    updatePagination();
  };
  return allWorker;
}

function loadAllBooks(target){
  const rating=Math.max(0,Math.min(10,Number($('#min-rating').value)||0));
  const votes=Math.max(0,Math.floor(Number($('#min-votes').value)||0));
  $('#min-rating').value=rating.toFixed(1);$('#min-votes').value=String(votes);
  const currentRequest=++requestId;
  $('#status').textContent='正在筛选全部书籍，首次使用需要加载索引…';
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  ensureAllWorker().postMessage({requestId:currentRequest,file:catalog.all_books.file,page:target,pageSize:catalog.all_books.page_size,query:$('#all-book-search').value.trim(),minRating:rating,minVotes:votes});
}

async function loadSourcePage(target){
  if(!source)return;
  totalPages=source.files.length;
  target=Math.max(1,Math.min(totalPages,Number(target)||1));
  const currentRequest=++requestId;
  $('#status').textContent='正在加载第 '+target+' 页…';
  $('#book-rows').innerHTML='';$('#pagination').hidden=true;
  try{
    const response=await fetch(source.files[target-1]);
    if(!response.ok)throw Error(response.status);
    const data=await response.json();
    if(currentRequest!==requestId||kind==='all')return;
    books=data.books;page=target;resultCount=source.count;
    renderBookRows(source.page_size);
    $('#status').textContent='第 '+page+' / '+totalPages+' 页，本页 '+books.length+' 本，共 '+source.count.toLocaleString()+' 本，按综合评分排序';
    updatePagination();
  }catch(error){if(currentRequest===requestId)$('#status').textContent='这一页加载失败，请稍后重试。'}
}

function renderBookRows(pageSize){
  const offset=(page-1)*pageSize;
  $('#book-rows').innerHTML=books.map((book,index)=>'<tr><td>'+(offset+index+1)+'</td><td>'+book.id+'</td><td>'+esc(book.title)+'</td><td>'+(book.rating??'—')+'</td><td>'+(book.rating_count==null?'—':book.rating_count.toLocaleString())+'</td><td><a href="'+encodeURI(book.url)+'" target="_blank" rel="noopener">豆瓣</a></td></tr>').join('');
}

function updatePagination(){
  $('#pagination').hidden=totalPages<=1;
  $('#page-number').value=page;$('#page-number').max=totalPages;
  $('#page-total').textContent='/ '+totalPages+' 页';
  $('#first-page').disabled=page===1;$('#previous-page').disabled=page===1;
  $('#next-page').disabled=page===totalPages;$('#last-page').disabled=page===totalPages;
}

function loadPage(target){if(kind==='all')loadAllBooks(target);else loadSourcePage(target)}
function goToInputPage(){loadPage($('#page-number').value)}
