const $=id=>document.getElementById(id), names=['熊市','震荡','牛市'], colors=['#209d7b','#8e9bad','#d84f58'];
let data=null,index=0,timer=null,live=true,busy=false,token=0,loadedCode='',plot=[],loadedWindow=20,loadedThreshold=5,lastHistoryRefresh=0;
let btResult=null,btSerial=0;
const pct=v=>(v*100).toFixed(1)+'%';
function message(text,kind=''){ $('message').textContent=text; $('message').className='message '+kind; }
function pause(){clearInterval(timer);timer=null;$('play').textContent='播放';}
function at(day){let k=data.frames.findIndex(f=>f.date>day);return k===-1?data.frames.length-1:Math.max(0,k-1);}
async function api(url){const res=await fetch(url,{signal:AbortSignal.timeout(120000)});const result=await res.json();if(!res.ok)throw Error(result.error||'请求失败');return result;}
async function load(demo=false,force=false,background=false){
 if(busy)return; if(!$('form').reportValidity())return;
 busy=true;pause();const seq=++token;const code=$('code').value;
 $('load').disabled=true;
 if(!background)message(demo?'正在生成演示数据…':'正在获取历史行情，首次加载可能需要几十秒…');
 try{
  const result=await api(`/api/history?code=${encodeURIComponent(code)}&window=${$('window').value}&threshold=${Number($('threshold').value)/100}&demo=${demo?1:0}&refresh=${force?1:0}`);
  if(seq!==token)return;
  data=result;loadedCode=code;loadedWindow=Number($('window').value);loadedThreshold=Number($('threshold').value);lastHistoryRefresh=Date.now();live=true;index=data.frames.length-1;
  btResult=null;btSerial++;$('btResults').hidden=true;invalidatePortfolio();
  const btFirst=data.frames[Math.min(loadedWindow+253,data.frames.length-1)].date;
  $('btStart').min=btFirst;$('btStart').max=data.frames.at(-1).date;$('btStart').value=btFirst;
  $('limit').value=/^(300|301|688)/.test(code)?'0.2':'0.1';
  const first=data.frames[Math.min(Number($('window').value),data.frames.length-1)].date,last=data.frames.at(-1).date;
  for(const id of ['date','start','end']){$(id).min=first;$(id).max=last;}
  $('start').value=first;$('end').value=last;$('slider').min=Math.min(Number($('window').value),data.frames.length-1);$('slider').max=index;
  $('stock').textContent=demo?'合成数据 · 演示标的':code+' · 沪深 A 股';
  $('quote').textContent='—';$('quoteInfo').textContent=demo?'演示模式没有实时行情':'正在更新实时报价…';
  message(demo?'演示模式：价格为合成数据，不是真实股票行情。':data.stale?data.warning:'历史行情已加载。盘中更新报价；确认状态仅使用已收盘日线。',demo||data.stale?'warning':'');
  render();if(!demo)updateQuote(seq);
 }catch(err){message(err.message,'error');}
 finally{busy=false;$('load').disabled=false;}
}
async function updateQuote(seq=token){
 if(!data||data.demo||!live)return;
 try{const q=await api('/api/quote?code='+encodeURIComponent(loadedCode));if(seq!==token||!live)return;
  $('stock').textContent=q.name+' · '+loadedCode;
  $('quote').textContent='¥ '+q.price.toFixed(2);$('quote').className=q.change>=0?'bull':'bear';
  $('quoteInfo').textContent=`${q.change>=0?'+':''}${q.change.toFixed(2)}% · ${q.timestamp.replace('T',' ').slice(0,19)}${q.stale?' · 非最新/非交易时段报价':''}`;
 }catch(err){if(seq!==token||!live)return;$('quote').textContent='—';$('quoteInfo').textContent='报价不可用：'+err.message;}
}
function render(){
 if(!data)return;
 const f=data.frames[index];$('date').value=f.date;$('slider').value=index;
 $('mode').textContent=data.demo?(live?'演示数据':'演示回放'):(live?'最新行情':'历史回放');
 $('regime').textContent=f.state===null?'样本不足':names[f.state];$('regime').style.color=colors[f.state]||'#8e9bad';
 $('asof').textContent='截至 '+f.date+' 收盘';$('signal').textContent=f.signal===null?'—':(f.signal>=0?'+':'')+f.signal.toFixed(3);
 $('samples').textContent=f.samples;$('lookbackInfo').textContent=f.samples<252?'样本较少，概率估计不稳定':'仅统计截至当前日的转移';
 $('rangeStart').textContent=data.frames[Number($('slider').min)].date;$('rangeEnd').textContent=data.frames.at(-1).date;$('progress').textContent=`${f.date} · 第 ${index+1} 个观测日`;
 $('source').textContent='数据源：'+data.source;
 $('fetched').textContent=data.fetched_at?'历史获取时间：'+data.fetched_at.replace('T',' ')+(data.stale?' · 缓存已过期':''):'演示数据仅供体验交互';
 if(!live){$('quote').textContent=f.close.toFixed(2);$('quote').className='';$('quoteInfo').textContent='所选日后复权收盘价 · 非当时成交价格';}
 $('matrix').replaceChildren();
 ['',...names].forEach(s=>cell(s,'heading'));
 f.matrix.forEach((row,r)=>{cell(names[r],'heading');row.forEach(v=>{const el=cell(pct(v),r===f.state?'current':'');el.style.background=`rgba(54,92,230,${.035+v*.32})`;});});
 $('probabilities').replaceChildren();
 names.forEach((name,r)=>{const row=document.createElement('div');row.className='prob-row';const v=f.probs?f.probs[r]:0;row.innerHTML=`<span>${name}</span><div class="track"><div class="fill" style="background:${colors[r]};width:${v*100}%"></div></div><span>${f.probs?pct(v):'—'}</span>`;$('probabilities').append(row);});
 $('mix').replaceChildren();f.stationary.forEach((v,r)=>{const el=document.createElement('span');el.style.width=(v*100)+'%';el.style.background=colors[r];el.textContent=names[r]+' '+pct(v);el.title=el.textContent;$('mix').append(el);});
 draw();
 renderResearch(f);
 syncModules(f);
 syncAdvanced();
 syncWorkbench();
}
function cell(text,cls){const el=document.createElement('div');el.className='cell '+cls;el.textContent=text;$('matrix').append(el);return el;}
function draw(){
 const canvas=$('chart'),rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;
 canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);const w=rect.width,h=rect.height;
 c.clearRect(0,0,w,h);if(!data)return;
 const rows=data.frames.slice(Math.max(0,index-179),index+1),left=62,right=w-14,top=12,bottom=h-30;
 const visibleValues=rows.flatMap(f=>[f.close,f.ma20,f.ma60].filter(v=>v!=null));let lo=Math.min(...visibleValues),hi=Math.max(...visibleValues);const pad=(hi-lo)*.1||1;lo-=pad;hi+=pad;
 const x=i=>left+(right-left)*i/Math.max(rows.length-1,1),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top),step=(right-left)/Math.max(rows.length-1,1);
 rows.forEach((f,i)=>{c.fillStyle=f.state===null?'#f5f6f8':colors[f.state]+'13';c.fillRect(Math.max(left,x(i)-step/2),top,step+1,bottom-top);});
 c.font='10px Segoe UI';c.fillStyle='#8793a5';c.textAlign='right';
 for(let i=0;i<5;i++){let yy=top+(bottom-top)*i/4;c.strokeStyle='#e9edf2';c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillText((hi-(hi-lo)*i/4).toFixed(2),left-9,yy+4);}
 c.strokeStyle='#365ce6';c.lineWidth=2;c.beginPath();rows.forEach((f,i)=>i?c.lineTo(x(i),y(f.close)):c.moveTo(x(i),y(f.close)));c.stroke();
 for(const [field,color] of [['ma20','#d79d37'],['ma60','#9b77cc']]){c.strokeStyle=color;c.lineWidth=1.2;c.beginPath();let began=false;rows.forEach((f,i)=>{if(f[field]!=null){if(!began){c.moveTo(x(i),y(f[field]));began=true;}else c.lineTo(x(i),y(f[field]));}});c.stroke();}
 c.fillStyle='#365ce6';c.beginPath();c.arc(x(rows.length-1),y(rows.at(-1).close),4,0,Math.PI*2);c.fill();
 c.fillStyle='#8793a5';c.textAlign='left';c.fillText(rows[0].date,left,h-8);c.textAlign='right';c.fillText(rows.at(-1).date,right,h-8);
 plot=rows.map((f,i)=>({...f,x:x(i)}));
 $('chartCaption').textContent=`${data.demo?'合成':'后复权'}收盘价 · MA20 金 / MA60 紫 · 截至 ${rows.at(-1).date}`;
}
function seek(i){if(!data)return;live=false;index=Math.max(Number($('slider').min),Math.min(data.frames.length-1,i));render();}
function bounds(){return [Math.max(Number($('slider').min),at($('start').value)),at($('end').value)];}
function play(){
 if(!data)return;if(timer){pause();return;}
 const [a,b]=bounds();if(a>b){message('回放起点不能晚于终点','error');return;}
 if(index<a||index>=b)seek(a);live=false;render();$('play').textContent='暂停';
 timer=setInterval(()=>{if(index>=b){pause();return;}seek(index+1);if(index>=b)pause();},Number($('speed').value));
}
async function autoUpdate(){
 if(activeModule==='operations')return;
 if(!data||data.demo||!live||!$('auto').checked||busy||document.hidden)return;
 // Pending form edits are applied only by an explicit submit.
 await updateQuote();
 if(Date.now()-lastHistoryRefresh>=900000 && $('code').value===loadedCode && Number($('window').value)===loadedWindow && Number($('threshold').value)===loadedThreshold)await load(false,true,true);
}
let refreshClock=setInterval(autoUpdate,60000);
function wire(){
 $('form').onsubmit=e=>{e.preventDefault();load(false,true);};$('demo').onclick=()=>load(true);
 document.querySelectorAll('[data-code]').forEach(b=>b.onclick=()=>{$('code').value=b.dataset.code;load(false);});
 $('date').onchange=()=>{if(!data||!$('date').value)return;pause();seek(at($('date').value));};
 $('slider').oninput=()=>{pause();seek(Number($('slider').value));};
 $('prev').onclick=()=>{pause();seek(index-1);};$('next').onclick=()=>{pause();seek(index+1);};$('play').onclick=play;
 $('speed').onchange=()=>{if(timer){pause();play();}};
 for(const id of ['start','end'])$(id).onchange=pause;
 $('latest').onclick=()=>{if(!data)return;pause();live=true;index=data.frames.length-1;render();if(data.demo){$('quote').textContent='—';$('quoteInfo').textContent='演示模式没有实时行情';}else{ $('quote').textContent='—';$('quoteInfo').textContent='正在更新实时报价…';updateQuote();}};
 $('export').onclick=()=>{if(!data)return;const rows=data.frames.slice(0,index+1);let csv='\uFEFFdate,adjusted_close,regime,signal\n'+rows.map(f=>[f.date,f.close,names[f.state]||'',f.signal??''].join(',')).join('\n');let u=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));let a=document.createElement('a');a.href=u;a.download=`${data.demo?'demo':loadedCode}-${rows.at(-1).date}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 $('chart').onmousemove=e=>{if(!plot.length)return;let x=e.clientX-$('chart').getBoundingClientRect().left;let f=plot.reduce((a,b)=>Math.abs(a.x-x)<Math.abs(b.x-x)?a:b);$('hover').textContent=`${f.date} · 收盘 ${f.close.toFixed(2)} · ${names[f.state]||'预热期'}`;};
 window.addEventListener('resize',draw);
 window.addEventListener('resize',drawEquity);
 $('runBacktest').onclick=runBacktest;
 for(const id of ['btStart','capital','commission','minFee','slippage','limit'])$(id).onchange=()=>{btResult=null;btSerial++;$('btResults').hidden=true;$('btStatus').textContent='参数已修改，请重新运行回测';};
 $('exportBt').onclick=()=>{if(!btResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(btResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=`research-${loadedCode}-${btResult.end}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
}
function renderResearch(f){
 const number=v=>v==null?'—':v.toFixed(2);
 $('maValue').textContent=number(f.ma20)+' / '+number(f.ma60);
 $('trendValue').textContent=f.ma60==null?'历史不足 60 日':f.close>f.ma60&&f.momentum20>0?'趋势条件：允许做多':'趋势条件：空仓';
 $('momentumValue').textContent=f.momentum20==null?'—':pct(f.momentum20);
 $('volatilityValue').textContent=f.volatility20==null?'—':pct(f.volatility20);
 $('drawdownValue').textContent=f.drawdown==null?'—':pct(f.drawdown);
 $('volumeValue').textContent=f.volume_ratio==null?'—':f.volume_ratio.toFixed(2)+' 倍';
 $('turnoverValue').textContent=f.turnover==null?'成交量 / 前 20 日均量':`收盘估算成交额 ${(f.turnover/1e8).toFixed(2)} 亿元`;
 if(btResult&&btResult.end>f.date){btResult=null;btSerial++;$('btResults').hidden=true;}
 if(!btResult)$('btStatus').textContent=`截至 ${f.date} · 点击运行回测`;
}
async function runBacktest(){
 if(!data||busy)return;pause();
 const f=data.frames[index],seq=++btSerial,loadToken=token;
 const fields=['capital','commission','minFee','slippage'];
 if(fields.some(id=>!$(id).reportValidity()))return;
 const params=new URLSearchParams({code:loadedCode,window:loadedWindow,threshold:loadedThreshold/100,demo:data.demo?1:0,
  start:$('btStart').value,end:f.date,capital:$('capital').value,commission:Number($('commission').value)/10000,
  min_fee:$('minFee').value,slippage:Number($('slippage').value)/1000,limit:$('limit').value});
 btResult=null;$('btResults').hidden=true;$('runBacktest').disabled=true;$('btStatus').textContent='正在模拟成交与计算净值…';
 try{const result=await api('/api/backtest?'+params);if(seq!==btSerial||token!==loadToken||data.frames[index].date!==f.date)return;
  btResult=result;$('btResults').hidden=false;
  $('btStatus').textContent=`${result.demo?'演示数据 · ':''}${result.start} 至 ${result.end}${result.stale?' · 使用过期缓存':''}`;
  const labels={hold:'买入持有',trend:'趋势策略',filtered:'趋势＋状态过滤'};const cs={hold:'#8e9bad',trend:'#d79d37',filtered:'#365ce6'};
  $('btTable').replaceChildren();$('tradeLog').replaceChildren();
  for(const [key,r] of Object.entries(result.results)){
   const tr=document.createElement('tr'),m=r.metrics;
   [labels[key],pct(m.return),m.annual_return==null?'—':pct(m.annual_return),pct(m.max_drawdown),m.sharpe==null?'—':m.sharpe.toFixed(2),r.trades.length,r.blocked.length,r.fees.toFixed(2)].forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(!i)td.style.color=cs[key];tr.append(td);});$('btTable').append(tr);
   const heading=document.createElement('strong');heading.textContent=labels[key]+(r.open_position?' · 期末仍持仓':' · 期末空仓');$('tradeLog').append(heading);
   const records=[...r.trades.map(t=>({...t,text:`${t.side} ${t.quantity.toFixed(2)}股 @ ${t.price.toFixed(2)}，费用 ${t.fees.toFixed(2)}，信号 ${t.signal_date}`})),...r.blocked.map(t=>({...t,text:'未成交：'+t.reason}))].sort((a,b)=>b.date.localeCompare(a.date)).slice(0,30);
   for(const rec of records){const line=document.createElement('div');line.textContent=rec.date+' '+rec.text;$('tradeLog').append(line);}
  }
  $('btCaveat').textContent=result.caveat;drawEquity();
 }catch(err){$('btStatus').textContent=err.message;}finally{$('runBacktest').disabled=false;}
}
function drawEquity(){
 if(!btResult)return;
 const canvas=$('equityChart'),rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;
 canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);const w=rect.width,h=rect.height,left=55,right=w-12,top=30,bottom=h-25;
 const capital=btResult.params.capital,series=Object.values(btResult.results).map(r=>[{date:btResult.start,value:capital},...r.equity]);
 const vals=series.flat().map(p=>p.value/capital);let lo=Math.min(...vals),hi=Math.max(...vals);const pad=(hi-lo)*.1||.02;lo-=pad;hi+=pad;
 const x=i=>left+(right-left)*i/(series[0].length-1),y=v=>bottom-(v/capital-lo)/(hi-lo)*(bottom-top);
 c.font='10px Segoe UI';c.fillStyle='#8793a5';
 for(let i=0;i<4;i++){const yy=top+(bottom-top)*i/3;c.strokeStyle='#e9edf2';c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillText((hi-(hi-lo)*i/3).toFixed(2),4,yy+3);}
 const colors=['#8e9bad','#d79d37','#365ce6'];const labels=['买入持有','趋势策略','趋势＋状态过滤'];
 series.forEach((s,k)=>{c.strokeStyle=colors[k];c.lineWidth=k===2?2:1.3;c.beginPath();s.forEach((p,i)=>i?c.lineTo(x(i),y(p.value)):c.moveTo(x(i),y(p.value)));c.stroke();c.fillStyle=colors[k];c.fillText(labels[k],left+k*115,14);});
 c.fillStyle='#8793a5';c.fillText(btResult.start,left,h-5);c.textAlign='right';c.fillText(btResult.end,right,h-5);
}
async function verifyServerCompatibility(){
 const banner=$('serviceCompatibility');if(!banner)return false;
 try{
  const r=await fetch('/api/version',{cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!r.ok)throw Error('旧版服务');
  const version=await r.json();
  if(!Number.isInteger(version.api_revision)||version.api_revision<2||!['factor-validation','portfolio-experiment','regime-research','strategy-validation'].every(name=>version.features?.includes(name)))throw Error('接口版本不匹配');
  banner.hidden=true;return true;
 }catch(e){
  banner.textContent='页面代码已更新，但后台版本尚未确认匹配。基础页面仍可使用；新增分析功能需要在原终端按 Ctrl+C 停止旧服务，重新运行 python server.py，然后刷新页面。';
  banner.hidden=false;return false;
 }
}
wire();
wireModules();
wireAdvanced();
wireFactorValidation();
wireOptimization();
wireRegime();
wireStrategyValidation();
wireWorkbench();
wireOperations();
if(typeof location!=='undefined'){const selectedModule=new URLSearchParams(location.search).get('module');if(selectedModule&&moduleInfo[selectedModule])switchModule(selectedModule);}
verifyServerCompatibility();
