// Imported historical sample research; independent of the shared quote/replay.
let pitView=null,pitRun=null,pitSequence=0;
function pitDownload(value,name){const u=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function pitConfig(){return {lookback:Number($('pitLookback').value),interval:Number($('pitInterval').value),top_k:Number($('pitTop').value),factor:$('pitFactor').value,capital:Number($('pitCapital').value),participation:Number($('pitParticipation').value)/100,slippage:Number($('pitSlippage').value)/1000};}
function pitClearRun(){pitSequence++;pitRun=null;$('pitTradeResults').hidden=true;$('pitReplay').disabled=true;$('pitExportRun').disabled=true;}
async function pitInventory(){try{const d=await postApi('/api/point-in-time',{action:'list'});$('pitSaved').replaceChildren();for(const r of d.datasets){const o=document.createElement('option');o.value=r.dataset_id;o.textContent=(r.mode==='demo'?'演示':'导入')+' · '+r.start+'—'+r.end+' · '+r.securities+'只 · '+r.dataset_id.slice(0,8);$('pitSaved').append(o);}if(pitView)$('pitSaved').value=pitView.dataset_id;}catch(e){$('pitStatus').textContent=e.message;}}
function pitApply(d){
 pitView=d;$('pitResults').hidden=false;$('pitEnd').value=d.asof;
 const last=d.timeline.at(-1),mode=d.provenance.mode==='demo'?'合成演示':'导入样本';
 cards('pitCards',[['数据模式',mode],['截止日存续股票',String(last.members)],['已退出交易样本',String(last.historical_delisted)],['可用财报 / 存续股票',last.financial_available+' / '+last.members]]);
 $('pitSource').textContent=d.provenance.source+'；数据包 '+d.dataset_id.slice(0,12)+'；全市场完整性为来源自述：'+(d.provenance.universe_complete?'声称完整，未核验':'未声称完整');
 $('pitNote').textContent=d.notice;tableAt('pitVersions',['代码','当前存续','报告期','披露时间','可用时间','采用版本'],d.financial_versions.map(r=>[r.code,r.member?'是':'否',r.report_date||'—',r.published_at||'—',r.available_at||'—',r.version||'无可用版本']));
 drawPIT();
}
function drawPIT(){
 if(!pitView||!['quality','lab'].includes(activeModule)||$('pitResults').hidden)return;
 const rows=pitView.timeline;
 wbDrawLine('pitPoolChart',[{name:'历史存续池',points:rows.map(r=>({date:r.date,value:r.members}))},{name:'截至当日已退出',points:rows.map(r=>({date:r.date,value:r.historical_delisted}))},{name:'当日 ST',points:rows.map(r=>({date:r.date,value:r.st}))}],true);
 wbDrawLine('pitFinancialChart',[{name:'可用财报股票数',points:rows.map(r=>({date:r.date,value:r.financial_available}))},{name:'暂停交易股票数',points:rows.map(r=>({date:r.date,value:r.suspended}))}],true);
 wbHeat('pitCoverageChart',{labels:pitView.codes,columns:pitView.coverage_dates,values:pitView.coverage});
 if(!pitRun)return;const b=pitRun.backtest;
 wbDrawLine('pitNavChart',[{name:'费用后研究净值',points:b.equity.map(r=>({date:r.date,value:r.value/b.capital}))}]);
 wbDrawLine('pitDrawdownChart',[{name:'回撤 %',points:b.drawdown.map(r=>({date:r.date,value:r.value*100}))}]);
 wbDrawLine('pitCostChart',[{name:'累计费用 元',points:b.equity.map(r=>({date:r.date,value:r.fees}))}],true);
 const counts={};for(const r of b.orders){const key=r.filled===0?r.reason:r.filled<r.requested?'部分成交':'全部成交';counts[key]=(counts[key]||0)+1;}
 barsChart('pitOrderChart',Object.keys(counts),Object.values(counts),0);
}
async function pitAction(action,overrideId=null){
 const buttons=['pitDemo','pitImport','pitAudit','pitRun','pitReplay','pitOpen'];for(const id of buttons)$(id).disabled=true;
 const seq=++pitSequence;$('pitStatus').textContent='正在核验历史样本与时间边界…';
 try{
  let body={action};if(!['demo','import'].includes(action)){if(!pitView&&!overrideId)throw Error('请先载入演示或导入历史数据包');body.dataset_id=overrideId||pitView.dataset_id;body.end=$('pitEnd').value;}
  if(action==='import'){const file=$('pitFile').files[0];if(!file)throw Error('请选择历史数据包 JSON');if(file.size>1400000)throw Error('数据包须小于 1.4 MB，请缩小样本或分段导入');body.dataset=JSON.parse(await file.text());}
  if(action==='run')body.config=pitConfig();
  if(action==='replay'){if(!pitRun)throw Error('先运行研究');body.config=pitRun.config;body.end=pitRun.asof;body.expected_hash=pitRun.result_hash;}
  const d=await postApi('/api/point-in-time',body);if(seq!==pitSequence)return;
  if(['demo','import','audit'].includes(action)){pitRun=null;$('pitTradeResults').hidden=true;pitApply(d);$('pitStatus').textContent='历史样本已核验；此数据包独立于上方共享行情与回放日期。';if(action!=='audit')await pitInventory();}
  if(['run','replay'].includes(action)){
   if(action==='run')pitRun={...d,config:body.config};pitApply(d);$('pitTradeResults').hidden=false;
   const b=d.backtest;cards('pitTradeCards',[['费用后收益',pct(b.metrics.return)],['最大回撤',pct(b.metrics.max_drawdown)],['累计费用',b.fees.toFixed(2)+' 元'],['有成交 / 委托',b.orders.filter(r=>r.filled>0).length+' / '+b.orders.length]]);
   tableAt('pitOrders',['日期','信号日','代码','方向','申请股数','成交股数','成交价','费用','结果'],b.orders.map(r=>[r.date,r.signal_date,r.code,r.side,r.requested,r.filled,r.price?.toFixed(2)||'—',r.fees?.toFixed(2)||'—',r.reason]));
   tableAt('pitSelections',['信号日','执行日','历史池数量','目标股票','因子排序与版本'],b.selections.map(r=>[r.signal_date,r.execution_date,r.pool.length,r.target.join('、')||'空仓',r.ranked.map(x=>x.code+': '+x.score.toFixed(4)+(x.financial_version?' ('+x.financial_version+')':'')).join('；')]));
   tableAt('pitSettlements',['代码','处置日期','性质','每股现金','账户现金增加','来源'],b.settlements.map(r=>[r.code,r.date,r.kind,r.cash_per_share,r.amount.toFixed(2),r.source]));
   $('pitAssumptions').textContent=b.assumptions+' 规则版本：'+b.rule_version+'。发生复权因子变化而没有逐笔公司行动账本时阻断研究；退市现金处置情景会明确列示。';
   $('pitStatus').textContent=action==='replay'?(d.matched?'复算结果哈希一致':'复算结果有差异，请核对引擎版本与输入'):'研究完成；保存结果可导出并再次离线复算。';drawPIT();
  }
 }catch(e){if(seq===pitSequence){pitRun=null;$('pitTradeResults').hidden=true;$('pitStatus').textContent='研究未通过：'+e.message;}}
 finally{for(const id of buttons)$(id).disabled=false;$('pitReplay').disabled=!pitRun;$('pitExportRun').disabled=!pitRun;}
}
function wirePIT(){
 $('pitRefresh').onclick=pitInventory;
 $('pitOpen').onclick=()=>{const id=$('pitSaved').value;if(!id){$('pitStatus').textContent='请选择已保存的数据包';return;}pitClearRun();$('pitResults').hidden=true;$('pitEnd').value='';pitAction('audit',id);};
 for(const [id,action] of [['pitDemo','demo'],['pitImport','import'],['pitAudit','audit'],['pitRun','run'],['pitReplay','replay']])$(id).onclick=()=>pitAction(action);
 for(const id of ['pitEnd','pitLookback','pitInterval','pitTop','pitFactor','pitCapital','pitParticipation','pitSlippage'])$(id).onchange=()=>{pitClearRun();$('pitStatus').textContent='日期或参数已改变，请重新核验 / 运行';};
 $('pitFile').onchange=()=>{pitClearRun();pitView=null;$('pitResults').hidden=true;$('pitStatus').textContent='数据包已改变，请点击导入并核验';};
 $('pitExportData').onclick=async()=>{try{if(!pitView)throw Error('先载入数据包');const d=await postApi('/api/point-in-time',{action:'export',dataset_id:pitView.dataset_id});pitDownload(d.dataset,'historical-sample-'+pitView.dataset_id.slice(0,12)+'.json');}catch(e){$('pitStatus').textContent=e.message;}};
 $('pitExportRun').onclick=()=>{if(pitRun)pitDownload(pitRun,'pit-research-'+pitRun.asof+'.json');};
 window.addEventListener('resize',drawPIT);
}

