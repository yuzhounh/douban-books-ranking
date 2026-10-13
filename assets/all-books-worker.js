let booksPromise=null,booksFile='',cacheKey='',matches=[];

async function loadBooks(file){
  if(!booksPromise||booksFile!==file){
    booksFile=file;cacheKey='';
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(new Error('索引下载超时')),30000);
    const loading=(async()=>{
      try{
        const response=await fetch(new URL('../'+file,self.location.href),{signal:controller.signal});
        if(!response.ok)throw Error(response.status);
        const data=await response.json();
        if(!Array.isArray(data.books))throw Error('无效的书籍索引');
        return data.books;
      }catch(error){
        if(booksPromise===loading){booksPromise=null;cacheKey=''}
        throw error;
      }finally{clearTimeout(timer)}
    })();
    booksPromise=loading;
  }
  return booksPromise;
}

self.onmessage=async event=>{
  const {requestId,file,page,pageSize,query,minRating,minVotes}=event.data;
  try{
    const books=await loadBooks(file);
    const normalizedQuery=String(query||'').trim().toLocaleLowerCase('zh-CN');
    const key=JSON.stringify([file,normalizedQuery,minRating,minVotes]);
    if(key!==cacheKey){
      matches=[];
      for(let index=0;index<books.length;index++){
        const book=books[index],rating=book[2],votes=book[3]??0;
        const ratingMatches=minRating<=0?true:rating!==null&&rating>=minRating;
        const textMatches=!normalizedQuery||String(book[0]).includes(normalizedQuery)||String(book[1]).toLocaleLowerCase('zh-CN').includes(normalizedQuery);
        if(ratingMatches&&votes>=minVotes&&textMatches)matches.push(index);
      }
      cacheKey=key;
    }
    const pages=Math.max(1,Math.ceil(matches.length/pageSize));
    const selectedPage=Math.max(1,Math.min(pages,Number(page)||1));
    const start=(selectedPage-1)*pageSize;
    const result=matches.slice(start,start+pageSize).map(index=>books[index]);
    self.postMessage({requestId,page:selectedPage,pages,count:matches.length,books:result});
  }catch(error){self.postMessage({requestId,error:String(error)})}
};
