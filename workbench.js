const workspaceModules={
 market:{title:'市场全景',description:'最新行情广度、涨跌分布与成交活跃热力图。'},
 rotation:{title:'行业与板块轮动',description:'行业 ETF 代理的相对强弱、历史轨迹与收益比较。'},
 watch:{title:'股票筛选与自选池',description:'设置条件，比较候选股票，并在本地保存自选池。'},
 finance:{title:'财务与估值研究',description:'营收、利润、每股现金流及历史估值位置。'},
 events:{title:'事件与公告日历',description:'公告发布日期、已披露未来事件与事件窗口走势。'},
 lab:{title:'策略实验室',description:'组合均线、动量和状态条件，分开检验训练与样本外表现。'},
 paper:{title:'模拟持仓与交易复盘',description:'本地模拟账本、资金净值与已实现盈亏归因。'},
 quality:{title:'数据质量与来源',description:'日线覆盖、异常记录、更新时间与来源核验。'}
};
Object.assign(moduleInfo,workspaceModules);
let wbResult=null,wbKind='',wbSerial=0,wbKey='',wbPlots=[],wbBusy=false,paperInputSymbol='';
function wbContext(){return [token,data?.frames[index]?.date||'',data?.demo||false,loadedCode].join('|');}
function syncWorkbench(){
 const key=wbContext();if(key!==wbKey){wbKey=key;wbSerial++;if(wbKind!=='market'){wbResult=null;$('wbResults').hidden=true;}$('wbStatus').textContent='共享数据已改变，请重新加载分析';}
 if(data&&!$('wbTradeDay').value)$('wbTradeDay').value=data.frames[index].date;
}
function switchWorkbench(){
 if(!workspaceModules[activeModule])return;
 $('wbHeading').textContent=workspaceModules[activeModule].title;
 document.querySelectorAll('[data-tool]').forEach(el=>el.hidden=!el.dataset.tool.split(' ').includes(activeModule));
 $('wbScope').textContent=activeModule==='market'?'最新快照 · 独立于回放日':'共享查看日期';
 $('wbResults').hidden=!wbResult||wbKind!==activeModule;
 $('wbStatus').textContent=wbResult&&wbKind===activeModule?'已加载结果':'点击加载分析';
 $('wbRun').textContent=activeModule==='market'?'获取最新市场快照':'加载分析';
 if(activeModule==='paper'&&data&&paperInputSymbol!==loadedCode){$('wbTradeDay').value=data.frames[index].date;$('wbTradePrice').value=data.bars[index].raw_close;paperInputSymbol=loadedCode;}
 if(wbResult&&wbKind===activeModule)drawWorkbench();
}
const wbFmt=v=>v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
function wbPanel(title,plot,wide=false){const box=document.createElement('section');box.className='wb-chart-card'+(wide?' wide':'');const h=document.createElement('h3');h.textContent=title;box.append(h);const canvas=document.createElement('canvas');canvas.id='wbPlot'+wbPlots.length;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',title);box.append(canvas);$('wbCharts').append(box);wbPlots.push({id:canvas.id,...plot});}
function wbTable(headers,rows){tableAt('wbTable',headers,rows);}
function wbCards(rows){cards('wbCards',rows);}
function wbEquity(result,capital=300000){return Object.entries(result.results).map(([key,r])=>({name:{hold:'买入持有',trend:'趋势策略',filtered:'趋势＋状态过滤'}[key],points:[{date:r.equity[0]?.date||'',value:1},...r.equity.map(p=>({date:p.date,value:p.value/capital}))]}));}
function wbRender(d,kind){
 wbPlots=[];$('wbCharts').replaceChildren();$('wbResults').hidden=false;
 $('wbNote').textContent=(d.note||'')+' '+(d.warnings||[]).join('；');
 $('wbScope').textContent=kind==='market'?'行情时间：'+d.timestamp:'分析截止：'+(d.asof||'—');
 let insight='图表展示描述性结果，点击“精确数据与记录”可核对数值。';
 if(kind==='market'){
  wbCards([['有效行情 / 总证券',d.valid+' / '+d.total],['上涨 / 下跌',d.breadth[0]+' / '+d.breadth[2]],['样本成交额',wbFmt(d.turnover/1e8)+' 亿元'],['数据覆盖率',pct(d.valid/d.total)]]);
  wbPanel('市场涨跌广度',{type:'donut',labels:['上涨','平盘','下跌'],values:d.breadth});
  wbPanel('个股涨跌幅分布',{type:'bar',labels:d.bins,values:d.distribution,unit:'家'});
  wbPanel('成交额前 80 个股 · 等面积涨跌热力图',{type:'tiles',rows:d.rows},true);
  wbTable(['代码','名称','涨跌幅 %','成交额（亿元）'],d.rows.map(r=>[r.code,r.name,wbFmt(r.change),wbFmt(r.amount/1e8)]));
  insight=(d.valid<d.total?'行情覆盖不完整，当前广度仅代表已获取样本。':'已获取完整有效样本。')+'快照使用独立行情时间，不跟随历史回放。';
 }else if(kind==='rotation'){
  wbCards([['行业代理数量',d.matrix.length],['共同截止日',d.asof],['观察窗口','5 / 20 / 60 日'],['轨迹窗口','最近 40 个观测日']]);
  wbPanel('相对强弱轮动轨迹（%）',{type:'paths',paths:d.paths});
  wbPanel('行业代理收益热力图（%）',{type:'heat',labels:d.matrix.map(r=>r.name),columns:['5 日','20 日','60 日'],values:d.matrix.map(r=>r.returns.map(v=>v*100))});
  wbPanel('近期行业代理归一化走势',{type:'lines',series:d.lines},true);
  wbTable(['代理','代码','5 日','20 日','60 日'],d.matrix.map(r=>[r.name,r.code,...r.returns.map(pct)]));
  insight='不同颜色对应固定行业 ETF 代理；右上方表示相对较强，轨迹仅供比较，不代表未来轮动方向。';
 }else if(kind==='watch'){
  wbCards([['候选数量',d.stages[0]],['通过条件',d.rows.length],['筛选截止',d.asof],['本地自选池',d.watchlists.length]]);
  wbPanel('筛选漏斗',{type:'bar',labels:['输入股票','历史足够','动量通过','风险通过','趋势通过'],values:d.stages,unit:'只'});
  wbPanel('通过股票：动量与波动（%）',{type:'scatter',points:d.rows.map(r=>({x:r.volatility*100,y:r.momentum*100,label:r.code})),xLabel:'年化波动',yLabel:'20 日动量'});
  wbPanel('通过股票 · 动量及回撤（%）',{type:'heat',labels:d.rows.map(r=>r.code),columns:['20 日动量','区间回撤'],values:d.rows.map(r=>[r.momentum*100,r.drawdown*100])},true);
  wbTable(['代码','日线日期','20 日动量','年化波动','区间回撤'],d.rows.map(r=>[r.code,r.date,pct(r.momentum),pct(r.volatility),pct(r.drawdown)]));wbUpdateLists(d.watchlists);
  insight=d.rows.length?'可将通过条件的股票保存到自选池，并用于其他模块。':'当前没有股票满足全部条件。可调整阈值后重新筛选。';
 }else if(kind==='finance'){
  wbCards([['当前 PB',wbFmt(d.current.pb)],['历史 PB 分位',d.percentiles.pb==null?'—':pct(d.percentiles.pb)],['当前 PE(TTM)',wbFmt(d.current.pe)],['历史 PE 分位',d.percentiles.pe==null?'—':pct(d.percentiles.pe)]]);
  wbPanel('累计营收与净利润（亿元）',{type:'lines',series:['营收（亿元）','净利润（亿元）'].map(name=>({name,points:d.series[name]}))},true);
  wbPanel('每股收益与经营现金流（元）',{type:'lines',series:['每股收益','每股经营现金流'].map(name=>({name,points:d.series[name]}))});
  wbPanel('已披露累计 ROE（%）',{type:'bar',labels:d.series['ROE（%）'].map(r=>r.date),values:d.series['ROE（%）'].map(r=>r.value),unit:'%'});
  for(const key of ['pb','pe'])wbPanel(key==='pb'?'历史 PB':'历史 PE(TTM)',{type:'lines',series:[{name:key.toUpperCase(),points:d.valuations.filter(r=>r[key]!=null).map(r=>({date:r.date,value:r[key]}))}]});
  wbTable(['估值日期','PB','PE(TTM)'],d.valuations.slice(-30).map(r=>[r.date,wbFmt(r.pb),wbFmt(r.pe)]));
  insight='财报柱线按报告期展示；估值逐日只采用当时已披露的报告。分位低不等于必然低估。';
 }else if(kind==='events'){
  wbCards([['已知事件',d.events.length],['事件类型',Object.keys(d.counts).length],['可展示完整事件窗口',d.windows.length],['查看日期',d.asof]]);
  wbPanel('已披露事件时间轴 · 最近 30 条',{type:'timeline',events:d.events.slice(-30)},true);
  const startDate=new Date(d.asof+'T00:00:00Z');startDate.setUTCDate(startDate.getUTCDate()-60);startDate.setUTCDate(startDate.getUTCDate()-((startDate.getUTCDay()+6)%7));const finalDate=new Date(d.asof+'T00:00:00Z');finalDate.setUTCDate(finalDate.getUTCDate()+30);
  const calendarDays=[],columns=[];for(let cursor=new Date(startDate);cursor<=finalDate;cursor.setUTCDate(cursor.getUTCDate()+1))calendarDays.push(cursor.toISOString().slice(0,10));
  for(let i=0;i<calendarDays.length;i+=7)columns.push(calendarDays[i]);const eventCounts={};for(const e of d.events)eventCounts[e.date]=(eventCounts[e.date]||0)+1;
  wbPanel('事件日历 · 前 60 日至后 30 日（已知记录数）',{type:'heat',labels:['周一','周二','周三','周四','周五','周六','周日'],columns,values:Array.from({length:7},(_,day)=>columns.map((_,week)=>eventCounts[calendarDays[week*7+day]]||0)),cellDates:Array.from({length:7},(_,day)=>columns.map((_,week)=>calendarDays[week*7+day]||''))},true);
  wbPanel('事件类型分布',{type:'donut',labels:Object.keys(d.counts),values:Object.values(d.counts)});
  wbPanel('事件前后各 5 个观测日走势',{type:'lines',series:d.windows.map(e=>({name:e.date,points:e.points}))});
  wbTable(['日期','披露日期','类型','标题','来源'],d.events.map(e=>[e.date,e.published_at,e.kind,e.title,e.source]));
  insight='自动事件点代表公告发布日期。未来事件只显示当时已经披露的用户补充记录；事件窗口不表示因果关系。';
 }else if(kind==='lab'){
  const r=d.test.results[d.strategy],rows=[...new Set(d.cells.map(r=>r.ma))],cols=[...new Set(d.cells.map(r=>r.momentum))];
  wbCards([['训练选择 MA / 动量',d.best.ma+' / '+d.best.momentum],['样本外累计收益',pct(r.metrics.return)],['样本外最大回撤',pct(r.metrics.max_drawdown)],['样本外起点',d.split]]);
  wbPanel('训练区间参数热力图 · 累计收益 %',{type:'heat',labels:rows.map(v=>'MA'+v),columns:cols.map(v=>'动量'+v),values:rows.map(p=>cols.map(m=>d.cells.find(r=>r.ma===p&&r.momentum===m).train_return*100))});
  let peak=d.test.params.capital;const dd=r.equity.map(p=>{peak=Math.max(peak,p.value);return {date:p.date,value:(p.value/peak-1)*100};});
  wbPanel('所选参数 · 样本外回撤（%）',{type:'lines',series:[{name:'回撤',points:dd}]});
  wbPanel('所选参数 · 样本外净值对比',{type:'lines',series:wbEquity(d.test,d.test.params.capital)},true);
  wbTable(['MA','动量周期','训练收益','训练回撤','选择分数'],d.cells.map(r=>[r.ma,r.momentum,pct(r.train_return),pct(r.train_drawdown),wbFmt(r.score)]));
  insight='先按训练区间选择参数，再单独评估样本外；样本外亏损会如实显示，不再按验证结果挑参数。';
 }else if(kind==='paper'){
  const sold=d.realized,net=d.equity.at(-1)?.value||300000;
  wbCards([['模拟净资产',wbFmt(net)+' 元'],['可用现金',wbFmt(d.cash)+' 元'],['已实现盈亏',wbFmt(sold.reduce((a,r)=>a+r.profit,0))+' 元'],['已卖出委托',sold.length]]);
  wbPanel('模拟资金净值',{type:'lines',series:[{name:'净资产（元）',points:d.equity}]},true);
  wbPanel('已卖出委托盈亏（元）',{type:'bar',labels:sold.slice(-20).map(r=>r.date+' '+r.code),values:sold.slice(-20).map(r=>r.profit),unit:'元'});
  wbPanel('持有天数与已实现盈亏',{type:'scatter',points:sold.map(r=>({x:r.holding_days,y:r.profit,label:r.code})),xLabel:'日历持有天数',yLabel:'盈亏（元）'});
  wbTable(['成交日','代码','方向','股数','价格','费用','备注'],d.trades.map(r=>[r.day,r.code,r.side==='buy'?'买入':'卖出',r.quantity,r.price,r.fee,r.note]));
  insight=d.trades.length?'复盘仅反映已录入的模拟成交；遇分红送转等公司行动，需核对账本。':'暂无成交记录。可在真实模式录入手工模拟成交，或切换演示模式体验。';
 }else if(kind==='quality'){
  wbCards([['已检查股票',d.rows.length],['无效价格',d.rows.reduce((a,r)=>a+r.invalid,0)],['OHLC 异常',d.rows.reduce((a,r)=>a+r.ohlc_errors,0)],['过期缓存',d.rows.filter(r=>r.stale).length]]);
  wbPanel('共同日期并集 · 数据覆盖日历',{type:'heat',labels:d.rows.map(r=>r.code),columns:d.dates,values:d.rows.map(r=>r.presence),binary:true},true);
  wbPanel('观测样本数量',{type:'bar',labels:d.rows.map(r=>r.code),values:d.rows.map(r=>r.rows),unit:'日'});
  wbPanel('待核查记录数量',{type:'bar',labels:['重复日期','无效价格','OHLC 异常','零成交量'],values:['duplicates','invalid','ohlc_errors','zero_volume'].map(k=>d.rows.reduce((a,r)=>a+r[k],0)),unit:'条'});
  wbTable(['代码','最近日线','记录数','数据源','获取时间','缓存状态'],d.rows.map(r=>[r.code,r.last,r.rows,r.source,r.fetched_at||'演示',r.stale?'已过期':'当前获取/有效缓存']));
  insight='覆盖缺口不直接判为错误，可能是停牌或上市时间差异；查看来源和最近日线日期，再判断是否可用。';
 }
 $('wbInsight').textContent=insight+(d.warnings?.length?' 数据提示：'+d.warnings.join('；'):'');$('wbInsight').className='message'+(d.warnings?.length?' warning':'');drawWorkbench();
}

function wbDrawLine(id,series){
 const {c,w,h}=canvasSetup(id),pts=series.flatMap(s=>s.points).filter(p=>Number.isFinite(p.value));if(!pts.length){c.fillStyle='#8793a5';c.fillText('没有可用观测',25,55);return;}
 const legendCols=w<500?2:4,left=65,right=w-20,top=28+Math.ceil(series.length/legendCols)*14,bottom=h-30;let lo=Math.min(...pts.map(p=>p.value)),hi=Math.max(...pts.map(p=>p.value));const pad=(hi-lo)*.12||1;lo-=pad;hi+=pad;
 const numeric=pts.every(p=>/^[-+]?\d+$/.test(p.date)),dates=[...new Set(pts.map(p=>p.date))].sort((a,b)=>numeric?Number(a)-Number(b):a.localeCompare(b));const map=new Map(dates.map((d,i)=>[d,i]));
 c.font='10px Segoe UI';for(let i=0;i<4;i++){const y=top+(bottom-top)*i/3;c.strokeStyle='#e9edf2';c.beginPath();c.moveTo(left,y);c.lineTo(right,y);c.stroke();c.fillStyle='#8793a5';c.fillText(wbFmt(hi-(hi-lo)*i/3),2,y+4);}
 const palette=['#365ce6','#dc9e37','#299d81','#ac74cb','#d25764','#2babc1','#8793a5','#8c9444'];
 const tips=[];series.forEach((s,k)=>{c.strokeStyle=palette[k%8];c.lineWidth=1.8;c.beginPath();let began=false;s.points.forEach(p=>{if(!Number.isFinite(p.value)){began=false;return;}const x=left+(right-left)*map.get(p.date)/Math.max(1,dates.length-1),y=bottom-(p.value-lo)/(hi-lo)*(bottom-top);if(!began){c.moveTo(x,y);began=true;}else c.lineTo(x,y);tips.push({x,y,text:s.name+' · '+p.date+' · '+wbFmt(p.value)});});c.stroke();c.fillStyle=palette[k%8];c.fillText(s.name.slice(0,w<500?9:14),left+(k%legendCols)*(right-left)/legendCols,12+Math.floor(k/legendCols)*14);});
 c.fillStyle='#8793a5';c.fillText(dates[0],left,h-8);c.textAlign='right';c.fillText(dates.at(-1),right,h-8);$(id).onmousemove=e=>{const x=e.offsetX,y=e.offsetY;const t=tips.reduce((a,b)=>Math.hypot(a.x-x,a.y-y)<Math.hypot(b.x-x,b.y-y)?a:b);$(id).title=t.text;};
}
function wbHeat(id,p){
 const {c,w,h}=canvasSetup(id),left=120,top=34,columns=p.columns,values=p.values;if(!p.labels.length||!columns.length){c.fillText('暂无可用数据',20,50);return;}
 const cellW=(w-left-10)/columns.length,cellH=Math.min(36,(h-top-20)/p.labels.length);const max=Math.max(.001,...values.flat().map(v=>Math.abs(v||0)));
 c.font='10px Segoe UI';c.fillStyle='#8793a5';c.textAlign='center';columns.forEach((v,j)=>{if(columns.length<=12||j===0||j===columns.length-1)c.fillText(v,left+(j+.5)*cellW,20);});
 p.labels.forEach((v,i)=>{c.fillStyle='#657389';c.textAlign='right';c.fillText(v.slice(0,10)+(v.length>10?'…':''),left-10,top+i*cellH+cellH*.65);values[i].forEach((v,j)=>{c.fillStyle=p.binary?(v?'#486ae0':'#f0d7d9'):v==null?'#eef0f5':v>=0?`rgba(216,79,88,${.07+Math.abs(v)/max*.8})`:`rgba(32,157,123,${.07+Math.abs(v)/max*.8})`;c.fillRect(left+j*cellW,top+i*cellH,Math.max(1,cellW-2),cellH-3);if(cellW>42&&!p.binary){c.fillStyle=Math.abs(v)/max>.6?'#fff':'#32445f';c.textAlign='center';c.fillText(v==null?'—':v.toFixed(1),left+(j+.5)*cellW,top+i*cellH+cellH*.65);}});});
 $(id).onmousemove=e=>{const i=Math.floor((e.offsetY-top)/cellH),j=Math.floor((e.offsetX-left)/cellW);if(i>=0&&i<values.length&&j>=0&&j<columns.length)$(id).title=p.labels[i]+' · '+(p.cellDates?p.cellDates[i][j]:columns[j])+' · '+(p.binary?(values[i][j]?'有日线':'无日线'):wbFmt(values[i][j]));};
}
function wbScatter(id,p){
 const {c,w,h}=canvasSetup(id),left=60,right=w-25,top=30,bottom=h-40;const points=p.points||[];if(!points.length){c.fillStyle='#8793a5';c.fillText('暂无符合条件的点',20,55);return;}
 let xmin=Math.min(0,...points.map(p=>p.x)),xmax=Math.max(.1,...points.map(p=>p.x)),ymin=Math.min(0,...points.map(p=>p.y)),ymax=Math.max(.1,...points.map(p=>p.y));const xp=(xmax-xmin)*.12||1,yp=(ymax-ymin)*.12||1;xmin-=xp;xmax+=xp;ymin-=yp;ymax+=yp;
 const x=v=>left+(right-left)*(v-xmin)/(xmax-xmin),y=v=>bottom-(bottom-top)*(v-ymin)/(ymax-ymin);c.strokeStyle='#e1e6ef';c.beginPath();c.moveTo(left,y(0));c.lineTo(right,y(0));c.moveTo(x(0),top);c.lineTo(x(0),bottom);c.stroke();c.fillStyle='#8793a5';c.fillText(p.xLabel+' →',left,h-10);c.fillText(p.yLabel,8,15);
 points.forEach(q=>{c.fillStyle=q.y>=0?'#365ce6':'#249a7a';c.beginPath();c.arc(x(q.x),y(q.y),5,0,Math.PI*2);c.fill();c.fillText(q.label,x(q.x)+7,y(q.y)-5);});
 $(id).onmousemove=e=>{const q=points.reduce((a,b)=>Math.hypot(x(a.x)-e.offsetX,y(a.y)-e.offsetY)<Math.hypot(x(b.x)-e.offsetX,y(b.y)-e.offsetY)?a:b);$(id).title=q.label+' · '+wbFmt(q.x)+' / '+wbFmt(q.y);};
}
function drawWorkbench(){
 if(!wbResult||wbKind!==activeModule)return;
 for(const p of wbPlots){
  if(p.type==='bar')barsChart(p.id,p.labels,p.values);
  if(p.type==='lines')wbDrawLine(p.id,p.series);
  if(p.type==='heat')wbHeat(p.id,p);
  if(p.type==='scatter')wbScatter(p.id,p);
  if(p.type==='paths'){
   const {c,w,h}=canvasSetup(p.id),all=p.paths.flatMap(r=>r.points),max=Math.max(1,...all.flatMap(p=>[Math.abs(p.x),Math.abs(p.y)]));const cx=w/2,cy=h/2,scale=Math.min(w-80,h-80)/(2*max);c.strokeStyle='#e0e5ef';c.beginPath();c.moveTo(25,cy);c.lineTo(w-20,cy);c.moveTo(cx,25);c.lineTo(cx,h-20);c.stroke();c.fillStyle='#8793a5';c.fillText('横：相对 20 日收益；纵：相对 5 日收益',20,16);const colors=['#365ce6','#d49a31','#299e81','#a174c5','#cc5664','#279fb5','#868e9e','#899048'];p.paths.forEach((s,k)=>{c.strokeStyle=colors[k%8];c.beginPath();s.points.forEach((q,i)=>i?c.lineTo(cx+q.x*scale,cy-q.y*scale):c.moveTo(cx+q.x*scale,cy-q.y*scale));c.stroke();const q=s.points.at(-1);c.fillStyle=colors[k%8];c.beginPath();c.arc(cx+q.x*scale,cy-q.y*scale,4,0,Math.PI*2);c.fill();c.textAlign=q.x>0?'right':'left';c.fillText(s.name.slice(0,12),cx+q.x*scale+(q.x>0?-7:7),cy-q.y*scale-4);});
  }
  if(p.type==='donut'){
   const {c,w,h}=canvasSetup(p.id),total=p.values.reduce((a,b)=>a+b,0);if(!total){c.fillText('暂无可用数据',20,55);continue;}const radius=Math.min(w*.23,h*.35),cx=w*.32,cy=h*.5;let angle=-Math.PI/2;const colors=['#d84f58','#a1aabc','#209d7b','#365ce6','#bd91d1'];p.values.forEach((v,i)=>{const next=angle+v/total*Math.PI*2;c.fillStyle=colors[i%5];c.beginPath();c.moveTo(cx,cy);c.arc(cx,cy,radius,angle,next);c.closePath();c.fill();angle=next;c.fillRect(w*.63,40+i*30,9,9);c.fillStyle='#657389';c.fillText(p.labels[i]+' '+v+' ('+pct(v/total)+')',w*.63+15,49+i*30);});c.fillStyle='#fff';c.beginPath();c.arc(cx,cy,radius*.68,0,Math.PI*2);c.fill();c.fillStyle='#18283b';c.font='22px Segoe UI';c.textAlign='center';c.fillText(wbFmt(total),cx,cy+8);
  }
  if(p.type==='tiles'){
   const tileCanvas=$(p.id),tileWidth=tileCanvas.getBoundingClientRect().width,tileCols=Math.max(3,Math.floor(tileWidth/105));tileCanvas.style.height=Math.max(200,Math.ceil(p.rows.length/tileCols)*48)+'px';
   const {c,w,h}=canvasSetup(p.id),cols=Math.max(3,Math.floor(w/105)),cw=w/cols,rh=(h-10)/Math.ceil(p.rows.length/cols);p.rows.forEach((r,i)=>{const x=(i%cols)*cw,y=Math.floor(i/cols)*rh;c.fillStyle=r.change>=0?`rgba(216,79,88,${Math.min(.9,.12+Math.abs(r.change)/12)})`:`rgba(32,157,123,${Math.min(.9,.12+Math.abs(r.change)/12)})`;c.fillRect(x,y,cw-3,rh-3);c.fillStyle=Math.abs(r.change)>5?'#fff':'#34465f';c.font='10px Segoe UI';c.fillText(r.name.slice(0,9),x+7,y+17);c.fillText(r.change.toFixed(2)+'%',x+7,y+33);});
  }
  if(p.type==='timeline'){
   const {c,w,h}=canvasSetup(p.id),n=p.events.length;if(!n){c.fillText('当前日期范围内无已知事件',20,55);continue;}const left=95,right=w-20,row=Math.min(23,(h-30)/n);c.strokeStyle='#e2e7ef';c.beginPath();c.moveTo(left,10);c.lineTo(left,h-15);c.stroke();p.events.forEach((e,i)=>{const y=18+i*row;c.fillStyle='#8793a5';c.fillText(e.date,0,y+4);c.fillStyle=e.date>(wbResult.asof||'')?'#d39a32':'#365ce6';c.beginPath();c.arc(left,y,4,0,Math.PI*2);c.fill();c.fillStyle='#34465f';c.fillText('['+e.kind+'] '+e.title.slice(0,Math.max(10,Math.floor((right-left)/12))),left+15,y+4);});
  }
 }
}
function wbBody(){
 const end=data?.frames[index]?.date;if(!end)throw Error('请先加载股票行情或演示数据，设置共享查看日期');
 return {kind:activeModule,end,demo:data.demo,code:loadedCode,codes:['watch','quality'].includes(activeModule)?$('wbCodes').value.trim().split(/[,，\s]+/):[loadedCode],window:loadedWindow,threshold:loadedThreshold/100,
 min_momentum:Number($('wbMomentum').value)/100,max_volatility:Number($('wbVolatility').value)/100,max_drawdown:-Number($('wbDrawdown').value)/100,trend_only:$('wbTrend').checked,
 event_csv:$('wbEventCsv').value,periods:$('wbPeriods').value.split(/[,，\s]+/).map(Number),momenta:$('wbMomenta').value.split(/[,，\s]+/).map(Number),capital:Number($('wbLabCapital').value),filtered:$('wbLabFilter').checked,limit:Number($('limit').value)};
}
async function runWorkbench(action='analyze'){
 if(wbBusy)return;wbBusy=true;$('wbAddTrade').disabled=true;
 const kind=activeModule,key=wbContext(),serial=++wbSerial;$('wbStatus').textContent='正在获取并分析数据…';$('wbRun').disabled=true;
 wbResult=null;$('wbResults').hidden=true;
 try{const body=wbBody();if(action==='add'){
  if(data.demo)throw Error('演示模式不保存交易；切回真实行情后录入');
  Object.assign(body,{action:'add',trade:{code:loadedCode,day:$('wbTradeDay').value,side:$('wbTradeSide').value,quantity:Number($('wbTradeQty').value),price:Number($('wbTradePrice').value),fee:Number($('wbTradeFee').value),note:$('wbTradeNote').value}});
 }
 const d=await postApi('/api/workbench',body);if(serial!==wbSerial||key!==wbContext())return;
 wbResult=d;wbKind=kind;
 if(activeModule===kind){$('wbStatus').textContent=(d.demo?'合成演示 · ':'')+'分析完成'+(d.warnings?.length?' · 有数据提示':'');wbRender(d,kind);}
 else{$('wbStatus').textContent=workspaceModules[kind].title+'结果已完成，切回该模块查看';$('wbResults').hidden=true;}
 }catch(e){if(serial===wbSerial)$('wbStatus').textContent=e.message;}finally{$('wbRun').disabled=false;$('wbAddTrade').disabled=false;wbBusy=false;}
}
function wbUpdateLists(lists){$('wbWatchList').replaceChildren();const first=document.createElement('option');first.value='';first.textContent='选择已保存自选池';$('wbWatchList').append(first);for(const r of lists){const op=document.createElement('option');op.value=r.codes.join(',');op.textContent=r.name+' ('+r.codes.length+')';$('wbWatchList').append(op);}}
function wireWorkbench(){
 $('wbTradeDay').onchange=()=>{if(!data)return;const b=data.bars.find(r=>r.date===$('wbTradeDay').value);if(b)$('wbTradePrice').value=b.raw_close;};
 $('wbRun').onclick=()=>runWorkbench();$('wbAddTrade').onclick=()=>runWorkbench('add');
 $('wbExport').onclick=()=>{if(!wbResult||wbKind!==activeModule)return;const u=URL.createObjectURL(new Blob([JSON.stringify(wbResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=wbKind+'-'+(wbResult.asof||'latest')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 $('wbSaveWatch').onclick=async()=>{try{if(wbKind!=='watch'||!wbResult?.rows.length)throw Error('请先筛选出至少一只股票');const body=wbBody();body.action='save';body.name=$('wbWatchName').value;body.codes=wbResult.rows.map(r=>r.code);const d=await postApi('/api/workbench',body);wbUpdateLists(d.watchlists);$('wbStatus').textContent='已保存本地自选池';}catch(e){$('wbStatus').textContent=e.message;}};
 $('wbLoadWatch').onclick=()=>{const value=$('wbWatchList').value;if(!value)return;$('wbCodes').value=value;$('candidatePool').value=value;$('portfolioInput').value=value.split(',').map(c=>c+','+(Math.floor(100/value.split(',').length))).join('\n');invalidatePortfolio();advancedSerial.factors=(advancedSerial.factors||0)+1;advancedSerial.ml=(advancedSerial.ml||0)+1;advancedResults.factors=null;advancedResults.ml=null;$('factorsResult').hidden=true;$('mlResult').hidden=true;wbResult=null;wbSerial++;$('wbResults').hidden=true;$('wbStatus').textContent='已读取自选池，可重新筛选或切换到多因子、机器学习、组合模块';};
 const panel=$('wbPanel');panel.addEventListener('input',e=>{if(['wbWatchName','wbWatchList'].includes(e.target?.id))return;wbResult=null;wbSerial++;$('wbResults').hidden=true;$('wbStatus').textContent='输入已变化，请重新分析';});
 window.addEventListener('resize',drawWorkbench);
}
