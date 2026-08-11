let booksPromise=null,cacheKey='',matches=[];

async function loadBooks(file){
  if(!booksPromise){
    booksPromise=fetch(new URL('../'+file,self.location.href)).then(response=>{
      if(!response.ok)throw Error(response.status);
      return response.json();
    }).then(data=>data.books);
  }
  return booksPromise;
}

self.onmessage=async event=>{
  const {requestId,file,page,pageSize,query,minRating,minVotes}=event.data;
  try{
    const books=await loadBooks(file);
    const normalizedQuery=String(query||'').trim().toLocaleLowerCase('zh-CN');
    const key=JSON.stringify([normalizedQuery,minRating,minVotes]);
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
