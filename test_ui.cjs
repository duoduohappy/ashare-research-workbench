// DOM-free controller tests; not a substitute for browser visual QA.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements={};
function element(id='') {return {id,value:'',style:{},dataset:{},children:[],className:'',textContent:'',disabled:false,checked:true,classList:{toggle(){}},setAttribute(){},removeAttribute(){},
  append(x){this.children.push(x)},replaceChildren(){this.children=[]},reportValidity(){return true},addEventListener(){},
  getBoundingClientRect(){return {width:900,height:290,left:0}},getContext(){return new Proxy({},{get:()=>()=>{}})}};}
for(const id of ['window','threshold','code','speed','slider','start','end'])elements[id]=element(id);
elements.window.value='20';elements.threshold.value='5';elements.code.value='600519';elements.speed.value='500';
const nav=['trend','state','portfolio','factors','ml','execution','text','market','rotation','watch','finance','events','lab','paper','quality','operations'].map(k=>{const e=element(k);e.dataset.module=k;return e});
const views=['trend','state','portfolio','factors ml execution text'].map(k=>{const e=element(k);e.dataset.view=k;return e});
const context=vm.createContext({document:{getElementById:id=>elements[id]??=(element(id)),querySelector:()=>null,querySelectorAll:q=>q==='[data-module]'?nav:q==='[data-view]'?views:[],createElement:()=>element(),hidden:false},devicePixelRatio:1,
 window:{addEventListener(){}},crypto:require('node:crypto').webcrypto,setInterval:()=>1,clearInterval(){},setTimeout,console,Blob,URL,URLSearchParams,AbortSignal,Date,fetch:(path,opt)=>fetch('http://127.0.0.1:8876'+path,opt)});
vm.runInContext(fs.readFileSync('modules.js','utf8'),context);
vm.runInContext(fs.readFileSync('advanced.js','utf8'),context);
vm.runInContext(fs.readFileSync('workbench.js','utf8'),context);
vm.runInContext(fs.readFileSync('operations.js','utf8'),context);
vm.runInContext(fs.readFileSync('app.js','utf8'),context);
(async()=>{
 const r=await fetch('http://127.0.0.1:8876/api/history?demo=1');assert.equal(r.status,200);context.fixture=await r.json();
 vm.runInContext('data=fixture; index=data.frames.length-1; $("slider").min=20; $("slider").max=index; $("start").value=data.frames[20].date; $("end").value=data.frames.at(-1).date;render();seek(100);',context);
 assert.match(elements.mode.textContent,/回放/);assert.equal(elements.date.value,context.fixture.frames[100].date);
 assert.match(elements.chartCaption.textContent,new RegExp(context.fixture.frames[100].date));
 assert.equal(elements.matrix.children.length,16);assert.equal(elements.probabilities.children.length,3);
 vm.runInContext('seek(-1)',context);assert.equal(elements.date.value,context.fixture.frames[20].date);
 vm.runInContext('seek(999999)',context);assert.equal(elements.date.value,context.fixture.frames.at(-1).date);
 vm.runInContext('seek(80);$("start").value=data.frames[50].date;$("end").value=data.frames[60].date;play()',context);
 assert.equal(elements.date.value,context.fixture.frames[50].date);assert.equal(elements.play.textContent,'暂停');
 vm.runInContext('pause()',context);assert.equal(elements.play.textContent,'播放');
 for(const [id,value] of Object.entries({capital:'100000',commission:'3',minFee:'5',slippage:'1',limit:'0.1'}))elements[id].value=value;
 vm.runInContext('loadedCode="600519";seek(data.frames.length-1);$("btStart").value=data.frames[273].date;',context);
 await vm.runInContext('runBacktest()',context);
 assert.equal(elements.btResults.hidden,false);assert.equal(elements.btTable.children.length,3);
 assert.match(elements.btStatus.textContent,/2023/);
 assert.notEqual(elements.maValue.textContent,'— / —');
 vm.runInContext('seek(300)',context);assert.equal(elements.btResults.hidden,true);
 const selected=elements.date.value;
 vm.runInContext('switchModule("trend")',context);assert.equal(elements.moduleTitle.textContent,'趋势与反转');assert.equal(views[0].hidden,false);assert.equal(views[1].hidden,true);assert.equal(elements.date.value,selected);
 vm.runInContext('switchModule("ml")',context);assert.match(elements.moduleTitle.textContent,/机器学习/);assert.equal(views[3].hidden,false);
 vm.runInContext('switchModule("portfolio");seek(data.frames.length-1)',context);
 elements.portfolioInput.value='600519,30\n000001,30\n300750,30';elements.portfolioStart.value='2023-01-01';
 await vm.runInContext('runPortfolio()',context);
 assert.equal(elements.portfolioResults.hidden,false);assert.equal(elements.portfolioTable.children.length,3);assert.equal(elements.correlationTable.children.length,4);
 vm.runInContext('seek(300)',context);assert.equal(elements.portfolioResults.hidden,true);
 vm.runInContext('seek(data.frames.length-1)',context);
 const inputs={candidatePool:'600519,000001,300750',factorWeights:'1,1,1,1,1,1',financialCsv:'',mlMethod:'ridge',execMethod:'twap',execSide:'buy',execQuantity:'10000',execParticipation:'10',execSlippage:'1',minuteCsv:'',analysisText:'公司营业收入增长 20%，净利润改善，同时提示市场风险，拟回购股份 100 万股。',localModel:''};
 for(const [id,value] of Object.entries(inputs))(elements[id]??=element(id)).value=value;
 for(const kind of ['factors','ml','execution','text']){await vm.runInContext(`runAdvanced('${kind}')`,context);assert.equal(elements[kind+'Result'].hidden,false,elements[kind+'Status'].textContent);}
 vm.runInContext('seek(300)',context);for(const kind of ['factors','ml','execution','text'])assert.equal(elements[kind+'Result'].hidden,true);
 vm.runInContext('seek(data.frames.length-1)',context);
 const wbInputs={wbCodes:'600519,000001,300750',wbMomentum:'-100',wbVolatility:'100',wbDrawdown:'100',wbEventCsv:'',wbPeriods:'20,60',wbMomenta:'20',wbLabCapital:'300000'};
 for(const [id,value] of Object.entries(wbInputs))(elements[id]??=element(id)).value=value;
 for(const kind of ['market','rotation','watch','finance','events','lab','paper','quality']){
   vm.runInContext(`switchModule('${kind}')`,context);
   await vm.runInContext('runWorkbench()',context);
   assert.equal(elements.wbResults.hidden,false,kind+': '+elements.wbStatus.textContent);
   assert.ok(elements.wbCharts.children.length>=2,kind+' must have charts');
 }
 console.log('PASS: eight workbench modules, chart generation, shared context and demo API');
 vm.runInContext('switchModule("operations")',context);await vm.runInContext('refreshOperations(true)',context);
 assert.ok(elements.opsCharts.children.length>=4);assert.match(elements.moduleTitle.textContent,/持续模拟/);
 console.log('PASS: operations monitoring, lifecycle and PnL chart rendering');
 console.log('PASS: demo API, past-date render, probability/matrix rendering, seek bounds, playback restart/pause');
 console.log('PASS: risk indicators, three-strategy backtest render, future-result invalidation');
 console.log('PASS: module navigation, shared replay date, portfolio and four advanced modules, chart rendering, result invalidation');
})().catch(e=>{console.error(e);process.exitCode=1});
