const moduleInfo={
 trend:{title:'趋势与反转',description:'均线、动量、区间突破与均值偏离，比较策略在历史中的表现。'},
 state:{title:'市场状态识别',description:'马尔可夫状态回放，以及 HMM、聚类和阈值模型的滚动样本外对照。'},
 portfolio:{title:'组合配置与风控',description:'持有组合、风险贡献与滚动样本外配置；比较等权、风险平价与最小方差。'},
 factors:{title:'多因子选股',description:'需要接入可追溯的财务数据、历史股票池与行业分类。',methods:['价值：估值比较','质量：盈利与现金流','成长：收入及利润增长','红利：股息与分红','动量：相对强弱','低波：收益波动']},
 ml:{title:'机器学习选股',description:'需要补充特征库、滚动训练、样本外检验与数据版本管理。',methods:['线性模型','LightGBM','XGBoost']},
 execution:{title:'交易执行',description:'后续先开发拆单与成交成本模拟；当前不连接券商，不发送委托。',methods:['TWAP：按时间拆单','VWAP：参考成交量分布','POV：控制成交参与率','冰山：分批暴露订单']},
 text:{title:'文本分析',description:'需要接入公告、财报及新闻原文，并保留发布时间与来源。',methods:['NLP 信息提取','情绪分析','大语言模型摘要']}
};
let activeModule='state',portfolioResult=null,portfolioSerial=0,portfolioAsOf='';
function switchModule(name){
 if(!moduleInfo[name])return;
 activeModule=name;const info=moduleInfo[name];
 if(document.body)document.body.dataset.module=name;
 $('moduleTitle').textContent=info.title;$('moduleDescription').textContent=info.description;
 document.querySelectorAll('[data-module]').forEach(el=>{const selected=el.dataset.module===name;el.classList.toggle('active',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 document.querySelectorAll('[data-view]').forEach(el=>{el.hidden=!el.dataset.view.split(' ').includes(name);});
 if(info.methods){$('plannedTitle').textContent=info.title;$('plannedDescription').textContent=info.description;$('plannedMethods').replaceChildren();for(const method of info.methods){const el=document.createElement('div');el.textContent=method+' · 待接入';$('plannedMethods').append(el);}}
 // Navigation preserves shared symbol, date, replay progress and parameters.
 if(data){draw();if(activeModule==='trend')drawEquity();if(activeModule==='portfolio')drawPortfolio();}
 drawAdvanced();
 syncFactorValidation();drawFactorValidation();
 syncOptimization();drawOptimization();
 syncRegime();drawRegime();
 switchWorkbench();
 switchOperations();
}
function invalidatePortfolio(){portfolioSerial++;portfolioResult=null;portfolioAsOf='';$('portfolioResults').hidden=true;$('portfolioStatus').textContent='组合配置或共享数据已变化，请重新分析';}
function syncModules(frame){
 syncRegime();
 syncOptimization();
 $('breakoutValue').textContent=frame.breakout20==null?'历史不足 20 日':frame.breakout20===1?'向上突破':frame.breakout20===-1?'跌破区间':'仍在区间内';
 $('reversionValue').textContent=frame.zscore20==null?'—':frame.zscore20.toFixed(2)+' σ';
 if(portfolioAsOf&&portfolioAsOf!==frame.date)invalidatePortfolio();
}
function wireModules(){
 document.querySelectorAll('[data-module]').forEach(el=>el.onclick=()=>switchModule(el.dataset.module));
 $('runPortfolio').onclick=runPortfolio;
 $('portfolioInput').oninput=invalidatePortfolio;$('portfolioStart').onchange=invalidatePortfolio;
 $('exportPortfolio').onclick=()=>{if(!portfolioResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(portfolioResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='portfolio-'+portfolioResult.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 window.addEventListener('resize',drawPortfolio);switchModule('state');
}
async function runPortfolio(){
 if(!data){$('portfolioStatus').textContent='请先加载行情或演示数据，再选择查看日期';return;}
 pause();const end=data.frames[index].date,loadToken=token,seq=++portfolioSerial;
 let codes=[],weights=[];
 try{
  const rows=$('portfolioInput').value.trim().split(/\n/).filter(s=>s.trim());
  for(const row of rows){const pair=row.trim().split(/[,，\s]+/);if(pair.length!==2||!/^\d{6}$/.test(pair[0])||!Number.isFinite(Number(pair[1])))throw Error('每行请输入六位代码和权重，例如 600519,30');codes.push(pair[0]);weights.push(Number(pair[1]));}
  if(codes.length<2||codes.length>8||new Set(codes).size!==codes.length)throw Error('请输入 2–8 只不重复股票');
  if(weights.some(w=>w<=0||w>100)||weights.reduce((a,b)=>a+b,0)>100.000001)throw Error('权重须大于零，合计不超过 100%');
  if(!$('portfolioStart').value||$('portfolioStart').value>end)throw Error('组合起点不能为空，也不能晚于查看日期');
  portfolioResult=null;portfolioAsOf=end;$('portfolioResults').hidden=true;$('runPortfolio').disabled=true;
  $('portfolioStatus').textContent='正在获取组合历史日线并计算共同区间…';
  const params=new URLSearchParams({codes:codes.join(','),weights:weights.join(','),start:$('portfolioStart').value,end,demo:data.demo?1:0});
  const result=await api('/api/portfolio?'+params);
  if(seq!==portfolioSerial||token!==loadToken||data.frames[index].date!==end)return;
  portfolioResult=result;$('portfolioResults').hidden=false;
  $('portfolioStatus').textContent=`${result.demo?'合成演示 · ':''}${result.start} 至 ${result.end} · ${result.rows} 个共同日线${result.stale?' · 使用过期缓存':''}`;
  $('portfolioReturn').textContent=pct(result.metrics.return);$('portfolioDrawdown').textContent=pct(result.metrics.max_drawdown);$('portfolioVolatility').textContent=pct(result.volatility);$('portfolioCash').textContent=pct(result.cash_weight);
  $('portfolioTable').replaceChildren();
  codes.forEach((code,i)=>{const tr=document.createElement('tr');[code,pct(result.target_weights[i]),pct(result.current_weights[i]),pct(result.asset_returns[i]),pct(result.asset_volatility[i]),result.risk_contributions[i]==null?'—':pct(result.risk_contributions[i]),result.inverse_volatility_weights[i]==null?'—':pct(result.inverse_volatility_weights[i])].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td);});$('portfolioTable').append(tr);});
  $('correlationTable').replaceChildren();const heading=document.createElement('tr');['',...codes].forEach(v=>{const th=document.createElement('th');th.textContent=v;heading.append(th);});$('correlationTable').append(heading);
  codes.forEach((code,i)=>{const tr=document.createElement('tr');const th=document.createElement('th');th.textContent=code;tr.append(th);result.correlation[i].forEach(v=>{const td=document.createElement('td');td.textContent=v==null?'—':v.toFixed(2);if(v!=null)td.style.background=v>=0?`rgba(54,92,230,${Math.abs(v)*.15})`:`rgba(32,157,123,${Math.abs(v)*.15})`;tr.append(td);});$('correlationTable').append(tr);});
  $('portfolioCaveat').textContent=result.caveat;drawPortfolio();
 }catch(err){if(seq===portfolioSerial)$('portfolioStatus').textContent=err.message;}
 finally{$('runPortfolio').disabled=false;}
}
function drawPortfolio(){
 if(!portfolioResult||activeModule!=='portfolio')return;
 barsChart('weightsChart',[...portfolioResult.codes,'现金'],[...portfolioResult.current_weights,portfolioResult.cash_weight].map(v=>v*100));
 barsChart('riskChart',portfolioResult.codes,portfolioResult.risk_contributions.map(v=>v==null?0:v*100));
 const canvas=$('portfolioChart'),rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;canvas.width=rect.width*dpr;canvas.height=rect.height*dpr;
 const c=canvas.getContext('2d');c.scale(dpr,dpr);const rows=portfolioResult.equity,w=rect.width,h=rect.height,left=55,right=w-15,top=20,bottom=h-25;
 let lo=Math.min(...rows.map(r=>r.value)),hi=Math.max(...rows.map(r=>r.value));const pad=(hi-lo)*.1||.01;lo-=pad;hi+=pad;
 c.font='10px Segoe UI';for(let i=0;i<4;i++){const y=top+(bottom-top)*i/3;c.strokeStyle='#e9edf2';c.beginPath();c.moveTo(left,y);c.lineTo(right,y);c.stroke();c.fillStyle='#8793a5';c.fillText((hi-(hi-lo)*i/3).toFixed(2),5,y+3);}
 c.strokeStyle='#365ce6';c.lineWidth=2;c.beginPath();rows.forEach((r,i)=>{const x=left+(right-left)*i/(rows.length-1),y=bottom-(r.value-lo)/(hi-lo)*(bottom-top);i?c.lineTo(x,y):c.moveTo(x,y);});c.stroke();c.fillStyle='#8793a5';c.fillText(rows[0].date,left,h-5);c.textAlign='right';c.fillText(rows.at(-1).date,right,h-5);
}
