// HTTP script-loading regression; this is not browser visual QA.
const assert=require('node:assert/strict'),vm=require('node:vm'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
let base=process.env.BOOTSTRAP_BASE_URL||process.env.TEST_BASE_URL||'http://127.0.0.1:8876';
let legacy=process.argv.includes('--legacy'),fixture=null;
const staticPaths=new Set(['/','/index.html','/modules.js','/advanced.js','/workbench.js','/operations.js','/app.js','/style.css']);
function element(id=''){return {id,value:'',hidden:false,style:{},dataset:{},children:[],textContent:'',classList:{toggle(){}},setAttribute(){},removeAttribute(){},addEventListener(){},append(v){this.children.push(v);},replaceChildren(){this.children=[];},reportValidity(){return true;},getBoundingClientRect(){return {width:900,height:290,left:0};},getContext(){return new Proxy({},{get:()=>()=>{}});}};}
(async()=>{
 try{
  if(process.argv.includes('--legacy-fixture')){
   legacy=true;const upstream=base;
   fixture=http.createServer(async(req,res)=>{
    try{
     const name=new URL(req.url,'http://127.0.0.1').pathname;
     if(req.method==='GET'&&staticPaths.has(name)){
      const filename=name==='/'?'index.html':name.slice(1);
      res.setHeader('Content-Type',filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(__dirname,filename)));return;
     }
     if(req.method==='GET'&&req.url==='/api/history?demo=1'){
      const response=await fetch(upstream+req.url);res.writeHead(response.status,{'Content-Type':'application/json'});res.end(await response.text());return;
     }
     req.resume();res.writeHead(404,{'Content-Type':'text/html'});res.end('<h1>Legacy route: not found</h1>');
    }catch(e){res.writeHead(500);res.end(String(e));}
   });
   await new Promise(resolve=>fixture.listen(0,'127.0.0.1',resolve));base='http://127.0.0.1:'+fixture.address().port;
  }
  const page=await fetch(base+'/');assert.equal(page.status,200);const html=await page.text();
  const sources=[...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map(m=>m[1]);
  assert.equal(sources.length,5);assert.ok(sources.every(s=>staticPaths.has(s)),'new scripts must use legacy-supported entry points');
  const elements={};const get=id=>elements[id]??=(element(id));
  for(const [id,value] of Object.entries({window:'20',threshold:'5',code:'600519',speed:'500'}))get(id).value=value;
  const context=vm.createContext({document:{getElementById:get,querySelectorAll:()=>[],querySelector:()=>null,createElement:()=>element(),hidden:false},window:{addEventListener(){}},location:{search:'?module=market'},devicePixelRatio:1,crypto:require('node:crypto').webcrypto,Blob,URL,URLSearchParams,AbortSignal,Date,console,setTimeout,setInterval:()=>1,clearInterval(){},fetch:(p,o)=>fetch(base+p,o)});
  for(const source of sources){const r=await fetch(base+source);assert.equal(r.status,200,source);vm.runInContext(await r.text(),context,{filename:source});}
  assert.equal(await vm.runInContext('verifyServerCompatibility()',context),!legacy);
  assert.equal(get('serviceCompatibility').hidden,!legacy);
  const response=await fetch(base+'/api/history?demo=1');assert.equal(response.status,200);context.fixture=await response.json();
  vm.runInContext('data=fixture;index=data.frames.length-1;loadedCode="600519";$("slider").min=20;$("start").value=data.frames[20].date;$("end").value=data.frames.at(-1).date;render();switchModule("market");syncModules(data.frames[index]);',context);
  assert.equal(get('moduleTitle').textContent,'市场全景');
  for(const name of ['syncStrategyValidation','wireStrategyValidation','syncRegime','syncOptimization','syncFactorValidation'])assert.equal(vm.runInContext('typeof '+name,context),'function',name);
  if(legacy){
   assert.match(get('serviceCompatibility').textContent,/停止旧服务/);
   await assert.rejects(()=>vm.runInContext("postApi('/api/strategy-validation',{end:'2025-02-25',demo:true,code:'600519'})",context),/重新运行 python server.py/);
  }
  console.log('PASS: HTTP bootstrap, market render and '+(legacy?'legacy routes with restart guidance':'current backend compatibility'));
 }finally{if(fixture){const stopped=new Promise(resolve=>fixture.close(resolve));fixture.closeAllConnections();await stopped;}}
})().catch(e=>{console.error(e);process.exitCode=1;});
