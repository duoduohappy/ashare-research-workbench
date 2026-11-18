let svResult=null,svSerial=0,svContext='';
const svPct=v=>(v*100).toFixed(3)+'%';
function svKey(){return [wbContext(),loadedWindow,loadedThreshold,$('wbPeriods').value,$('wbMomenta').value,$('wbLabCapital').value,$('wbLabFilter').checked,$('svWindow').value,$('svLimit').value].join('|');}
function invalidateStrategyValidation(){svSerial++;svResult=null;$('svResults').hidden=true;$('svStatus').textContent='日期、标的或参数已改变，请重新验收';}
function syncStrategyValidation(){if(svResult&&svContext!==svKey())invalidateStrategyValidation();}
function drawStrategyValidation(){
 if(!svResult||activeModule!=='lab')return;
 const d=svResult;
 wbDrawLine('svFoldChart',[{name:'所选策略 · 63 日收益 %',points:d.folds.map(f=>({date:f.test_start,value:f.test.results[d.strategy].metrics.return*100}))},{name:'买入持有 · 63 日收益 %',points:d.folds.map(f=>({date:f.test_start,value:f.test.results.hold.metrics.return*100}))}]);
 wbDrawLine('svEquityChart',d.folds.flatMap(f=>[d.strategy,'hold'].map(k=>({name:'折'+f.fold+(k==='hold'?'持有':'策略'),points:[{date:'0',value:1},...f.test.results[k].equity.map((r,i)=>({date:String(i+1),value:r.value/d.capital}))]}))));
 const choices=d.summary.selection_counts;
 wbHeat('svStabilityChart',{labels:choices.map(r=>'MA'+r.ma+'/M'+r.momentum),columns:d.folds.map(f=>'折'+f.fold),values:choices.map(r=>d.folds.map(f=>f.cells.find(c=>c.ma===r.ma&&c.momentum===r.momentum).score*100))});
 wbHeat('svChoiceChart',{labels:d.periods.map(v=>'MA'+v),columns:d.momenta.map(v=>'动量'+v),values:d.periods.map(ma=>d.momenta.map(m=>choices.find(r=>r.ma===ma&&r.momentum===m).count))});
 wbHeat('svCostChart',{labels:[3,6].map(c=>'佣金 '+c+' bp'),columns:[0,10,30].map(s=>'滑点 '+s+' bp'),values:[3,6].map(c=>[0,10,30].map(s=>d.stress_summary.find(r=>r.commission_bps===c&&r.slippage_bps===s).mean_fold_return*100))});
 const hist=d.bootstrap.histogram;
 barsChart('svBootstrapChart',hist.counts.map((_,i)=>svPct(hist.edges[i])+'～'+svPct(hist.edges[i+1])),hist.counts,0);
 wbDrawLine('svDelayChart',[{name:'前一日信号收益 %',points:d.folds.map(f=>({date:f.test_start,value:f.test.results[d.strategy].metrics.return*100}))},{name:'前两日信号收益 %',points:d.folds.map(f=>({date:f.test_start,value:f.delayed.results[d.strategy].metrics.return*100}))}]);
}
function renderStrategyValidation(d){
 const s=d.summary,b=d.bootstrap;
 cards('svMetrics',[['独立测试窗 / 总观测',s.folds+' / '+s.test_observations],['平均单折收益 · 非复合',pct(s.mean_fold_return)],['最差单折收益',pct(s.worst_fold_return)],['平均每日配对超额',svPct(b.mean_daily_excess)]]);
 $('svScope').textContent=`${d.code} · ${d.evaluated_start} → ${d.evaluated_end}${d.demo?' · 合成演示':''}`;
 $('svInsight').textContent=`各测试窗从 ${d.capital.toLocaleString('zh-CN')} 元独立开始，图中相对步数不是连续账户时间轴。尾部 ${d.tail_observations} 个观测日不足完整测试窗，未纳入评分。平均每日配对超额的 95% 区块重采样区间为 ${svPct(b.interval[0])} 至 ${svPct(b.interval[2])}；该区间不修正参数选择、多重检验或数据偏差，不能据此认定稳定有效。`;
 tableAt('svFoldTable',['折','训练区间','测试区间','训练所选 MA/动量','训练评分','测试收益','持有收益','测试回撤','成交 / 受阻'],d.folds.map(f=>{const r=f.test.results[d.strategy];return [f.fold,f.train_start+' → '+f.train_end,f.test_start+' → '+f.test_end,f.selected.ma+' / '+f.selected.momentum,f.selected.score.toFixed(4),pct(r.metrics.return),pct(f.test.results.hold.metrics.return),pct(r.metrics.max_drawdown),r.trades.length+' / '+r.blocked.length];}));
 tableAt('svStressTable',['佣金每侧 bp','滑点每侧 bp','平均单折收益','同成本下平均单折超额'],d.stress_summary.map(r=>[r.commission_bps,r.slippage_bps,pct(r.mean_fold_return),pct(r.mean_fold_excess)]));
 tableAt('svTrades',['折','信号日','执行日','方向','数量','执行价','费用'],d.folds.flatMap(f=>f.test.results[d.strategy].trades.map(r=>[f.fold,r.signal_date,r.date,r.side,r.quantity,r.price.toFixed(3),r.fees.toFixed(2)])));
 $('svNotes').textContent=d.notes.join('\n');drawStrategyValidation();
}
async function runStrategyValidation(){
 if(!data){$('svStatus').textContent='请先加载行情或合成演示';return;}
 pause();const key=svKey(),serial=++svSerial;svResult=null;$('svResults').hidden=true;$('svRun').disabled=true;$('svStatus').textContent='正在滚动选参、复算成本情景和配对区块重采样…';
 try{
  const body={code:loadedCode,end:data.frames[index].date,demo:data.demo,window:loadedWindow,threshold:loadedThreshold/100,lookback:Number($('svWindow').value),periods:$('wbPeriods').value.split(/[,，\s]+/).map(Number),momenta:$('wbMomenta').value.split(/[,，\s]+/).map(Number),capital:Number($('wbLabCapital').value),filtered:$('wbLabFilter').checked,limit:$('svLimit').value};
  const d=await postApi('/api/strategy-validation',body);if(serial!==svSerial||key!==svKey())return;
  svResult=d;svContext=key;$('svResults').hidden=false;$('svStatus').textContent=`${d.demo?'合成演示 · ':''}${d.stale?'过期行情缓存 · ':''}独立测试窗验收完成`;
  renderStrategyValidation(d);
 }catch(e){if(serial===svSerial)$('svStatus').textContent=e.message;}
 finally{$('svRun').disabled=false;}
}
function wireStrategyValidation(){
 $('svRun').onclick=runStrategyValidation;
 for(const id of ['svWindow','svLimit','wbPeriods','wbMomenta','wbLabCapital','wbLabFilter']){$(id).addEventListener('input',invalidateStrategyValidation);$(id).addEventListener('change',invalidateStrategyValidation);}
 $('svExport').onclick=()=>{syncStrategyValidation();if(!svResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(svResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='strategy-validation-'+svResult.code+'-'+svResult.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 window.addEventListener('resize',drawStrategyValidation);
}
