const labels={top250:'Top 250',tag:'标签',doulist:'豆列',series:'丛书'};
let catalog=null,kind='tag',source=null,books=[],page=1,requestId=0;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

fetch('data/catalog.json')
  .then(response=>{if(!response.ok)throw Error(response.status);return response.json()})
  .then(data=>{
    catalog=data;
    $('#formula').textContent='综合评分 = '+data.formula;
    $('#generated-at').textContent='数据更新：'+new Date(data.generated_at).toLocaleString('zh-CN');
    for(const name of Object.keys(labels))$('#'+name+'-count').textContent=data.categories[name].length;
    renderSources();
    selectFirstSource();
  })
  .catch(()=>$('#status').textContent='目录加载失败，请稍后重试。');

document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(item=>item.classList.remove('active'));
  button.classList.add('active');
  kind=button.dataset.kind;
  source=null;books=[];page=1;
  $('#kind-label').textContent=labels[kind];
  $('#source-title').textContent='请选择一个来源';
  $('#source-search').value='';
  $('#book-search').value='';
  $('#book-rows').innerHTML='';
  $('#status').textContent='请选择左侧来源';
  $('#pagination').hidden=true;
  renderSources();
  selectFirstSource();
}));

$('#source-search').addEventListener('input',renderSources);
$('#book-search').addEventListener('input',renderBooks);
$('#first-page').addEventListener('click',()=>loadPage(1));
$('#previous-page').addEventListener('click',()=>loadPage(page-1));
$('#next-page').addEventListener('click',()=>loadPage(page+1));
$('#last-page').addEventListener('click',()=>loadPage(source.files.length));
$('#go-page').addEventListener('click',goToInputPage);
$('#page-number').addEventListener('keydown',event=>{if(event.key==='Enter')goToInputPage()});

function renderSources(){
  if(!catalog)return;
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
      $('#book-search').value='';
      loadPage(1);
    });
    list.appendChild(button);
  }
  if(!matches.length)list.textContent='没有匹配的来源';
}

function selectFirstSource(){
  const first=$('#source-list .source-item');
  if(first)first.click();
}

async function loadPage(target){
  if(!source)return;
  const total=source.files.length;
  target=Math.max(1,Math.min(total,Number(target)||1));
  const currentRequest=++requestId;
  $('#status').textContent='正在加载第 '+target+' 页…';
  $('#book-rows').innerHTML='';
  $('#pagination').hidden=true;
  try{
    const response=await fetch(source.files[target-1]);
    if(!response.ok)throw Error(response.status);
    const data=await response.json();
    if(currentRequest!==requestId)return;
    books=data.books;page=target;
    $('#book-search').value='';
    renderBooks();
    updatePagination();
  }catch(error){
    if(currentRequest===requestId)$('#status').textContent='这一页加载失败，请稍后重试。';
  }
}

function renderBooks(){
  if(!source)return;
  const query=$('#book-search').value.trim().toLowerCase();
  const offset=(page-1)*source.page_size;
  const matches=books.map((book,index)=>({book,index})).filter(item=>!query||item.book.title.toLowerCase().includes(query)||String(item.book.id).includes(query));
  $('#book-rows').innerHTML=matches.map(({book,index})=>'<tr><td>'+(offset+index+1)+'</td><td>'+book.id+'</td><td>'+esc(book.title)+'</td><td>'+(book.rating??'—')+'</td><td>'+(book.rating_count==null?'—':book.rating_count.toLocaleString())+'</td><td><a href="'+encodeURI(book.url)+'" target="_blank" rel="noopener">豆瓣</a></td></tr>').join('');
  const filtered=query?'，当前页匹配 '+matches.length+' 本':'';
  $('#status').textContent='第 '+page+' / '+source.files.length+' 页，本页 '+books.length+' 本'+filtered+'，共 '+source.count.toLocaleString()+' 本，按综合评分排序';
}

function updatePagination(){
  const total=source.files.length;
  $('#pagination').hidden=total<=1;
  $('#page-number').value=page;
  $('#page-number').max=total;
  $('#page-total').textContent='/ '+total+' 页';
  $('#first-page').disabled=page===1;
  $('#previous-page').disabled=page===1;
  $('#next-page').disabled=page===total;
  $('#last-page').disabled=page===total;
}

function goToInputPage(){loadPage($('#page-number').value)}
