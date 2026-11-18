let optResult=null,optSerial=0,optContext='';
const optNames={equal:'等权基线',inverse_vol:'波动倒数',risk_parity:'风险平价（约束近似）',min_variance:'受约束最小方差'};
function optKey(){return [wbContext(),...['optCodes','optStart','optWindow','optInterval','optCap','optCost','optCapital','optEstimator'].map(id=>$(id).value)].join('|');}
function invalidateOptimization(){optSerial++;optResult=null;$('optResults').hidden=true;$('optStatus').textContent='日期、股票池或参数已改变，请重新运行';}
function syncOptimization(){if(optResult&&optKey()!==optContext)invalidateOptimization();}
function drawOptimization(){
 if(!optResult||activeModule!=='portfolio')return;
 const d=optResult,methods=Object.keys(d.results);
 wbDrawLine('optEquityChart',methods.map(m=>({name:optNames[m],points:d.results[m].equity})));
 wbDrawLine('optDrawdownChart',methods.map(m=>({name:optNames[m],points:d.results[m].drawdown.map(p=>({date:p.date,value:p.value*100}))})));
 wbHeat('optWeightsChart',{labels:methods.map(m=>optNames[m]),columns:d.codes,values:methods.map(m=>d.latest.allocations[m].weights.map(v=>v*100))});
 wbHeat('optRiskChart',{labels:methods.map(m=>optNames[m]),columns:d.codes,values:methods.map(m=>d.latest.allocations[m].risk_contributions.map(v=>v*100))});
 wbDrawLine('optTurnoverChart',methods.map(m=>({name:optNames[m],points:d.results[m].trades.map(p=>({date:p.date,value:p.gross_turnover*100}))})));
 wbDrawLine('optCostChart',methods.map(m=>({name:optNames[m],points:d.results[m].trades.map(p=>({date:p.date,value:p.cumulative_cost/d.config.capital*100}))})));
 wbHeat('optCorrelationChart',{labels:d.codes,columns:d.codes,values:d.latest.correlation});
}
function renderOptimization(d){
 const methods=Object.keys(d.results),base=d.results.equal.metrics;
 cards('optMetrics',[['样本外共同观测日',d.observations],['调仓次数 / 方法',d.schedule.length],['最新收缩系数',d.latest.covariance.shrinkage==null?'样本协方差':d.latest.covariance.shrinkage.toFixed(3)],['等权基线收益',pct(base.return)]]);
 $('optScope').textContent=`${d.start} → ${d.end}${d.demo?' · 合成演示':''}`;
 const erc=d.latest.allocations.risk_parity;
 $('optInsight').textContent=`共同历史 ${d.common_start} → ${d.common_end}（${d.common_rows} 日）。最新研究目标截至 ${d.latest.signal_date} 收盘，尚未执行；与历史账户当前权重分开展示。风险平价最大等分偏差 ${(erc.risk_parity_residual*100).toFixed(2)} 个百分点，${erc.equal_risk_achieved?'达到 0.01 个百分点容差':'未精确均分风险，请核查仓位约束和相关性'}。结果可能不及等权基线，不自动选出“最佳策略”。`;
 tableAt('optPerformance',['算法','区间收益','年化收益（近似）','最大回撤','年化波动（近似）','累计成本 · 元','累计双向换手'],methods.map(m=>{const r=d.results[m];return [optNames[m],pct(r.metrics.return),pct(r.metrics.annual_return),pct(r.metrics.max_drawdown),r.metrics.volatility==null?'—':pct(r.metrics.volatility),r.total_cost.toFixed(2),pct(r.gross_turnover)];}));
 tableAt('optTargets',['最新研究目标','估计年化波动','最大等风险偏差（百分点）','触及上限股票','求解状态'],methods.map(m=>{const r=d.latest.allocations[m];return [optNames[m],pct(r.forecast_volatility),(r.risk_parity_residual*100).toFixed(3),d.codes.filter((_,i)=>r.at_cap[i]).join('、')||'无',r.solver_status];}));
 tableAt('optHoldings',['算法 / 代码',...d.codes,'现金'],methods.map(m=>[optNames[m],...d.results[m].current_weights.map(pct),pct(d.results[m].cash_weight)]));
 tableAt('optSchedule',['信号收盘日','假设执行开盘日','训练价格起点','训练收益截止','训练收益条数','收缩系数','对角正则','条件数'],d.schedule.map(r=>[r.signal_date,r.execution_date,r.train_start,r.train_end,r.training_returns,r.covariance.shrinkage==null?'—':r.covariance.shrinkage.toFixed(4),r.covariance.diagonal_jitter.toExponential(2),r.covariance.condition_number.toFixed(2)]));
 tableAt('optTrades',['算法','日期','调仓前资产','成本 · 元','调仓后资产','双向换手'],methods.flatMap(m=>d.results[m].trades.map(r=>[optNames[m],r.date,r.nav_before.toFixed(2),r.cost.toFixed(2),r.nav_after.toFixed(2),pct(r.gross_turnover)])));
 $('optNotes').textContent=d.notes.join('\n');drawOptimization();
}
async function runOptimization(){
 if(!data){$('optStatus').textContent='请先加载行情或合成演示';return;}
 pause();const key=optKey(),serial=++optSerial;
 optResult=null;$('optResults').hidden=true;$('optRun').disabled=true;$('optStatus').textContent='正在估计协方差、优化权重并计算样本外对照…';
 try{
  const codes=$('optCodes').value.trim().split(/[,，\s]+/);
  if(codes.length<2||codes.length>8||new Set(codes).size!==codes.length)throw Error('请输入 2–8 只不重复股票');
  const body={codes,end:data.frames[index].date,demo:data.demo,start:$('optStart').value,lookback:Number($('optWindow').value),interval:Number($('optInterval').value),cap:Number($('optCap').value)/100,cost_bps:Number($('optCost').value),capital:Number($('optCapital').value),estimator:$('optEstimator').value};
  const d=await postApi('/api/portfolio-experiment',body);
  if(serial!==optSerial||key!==optKey())return;
  optResult=d;optContext=key;$('optResults').hidden=false;
  $('optStatus').textContent=`${d.demo?'合成演示 · ':''}${d.stale?'过期行情缓存 · ':''}研究对照完成`;
  renderOptimization(d);
 }catch(e){if(serial===optSerial)$('optStatus').textContent=e.message;}
 finally{$('optRun').disabled=false;}
}
function wireOptimization(){
 $('optRun').onclick=runOptimization;
 $('optUsePortfolio').onclick=()=>{$('optCodes').value=$('portfolioInput').value.trim().split(/\n/).filter(s=>s.trim()).map(s=>s.trim().split(/[,，\s]+/)[0]).join(',');invalidateOptimization();};
 for(const id of ['optCodes','optStart','optWindow','optInterval','optCap','optCost','optCapital','optEstimator']){$(id).addEventListener('input',invalidateOptimization);$(id).addEventListener('change',invalidateOptimization);}
 $('optExport').onclick=()=>{syncOptimization();if(!optResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(optResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='portfolio-experiment-'+optResult.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 window.addEventListener('resize',drawOptimization);
}
