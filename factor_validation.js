// Research diagnostics share the selected as-of date, never an execution account.
let factorValidationResult=null,factorValidationSerial=0,factorValidationContext='';
function factorValidationKey(){return [wbContext(),$('candidatePool').value,$('fvFactor').value,$('fvHorizon').value].join('|');}
function invalidateFactorValidation(){factorValidationSerial++;factorValidationResult=null;$('fvResults').hidden=true;$('fvStatus').textContent='输入或查看日期已改变，请重新验证';}
function syncFactorValidation(){if(factorValidationResult&&factorValidationContext!==factorValidationKey())invalidateFactorValidation();}
const fvNumber=v=>v==null?'—':v.toFixed(3);
function drawFactorValidation(){
 if(!factorValidationResult||activeModule!=='factors')return;
 const d=factorValidationResult;
 wbDrawLine('fvIcChart',[{name:'20 日均值 IC',points:d.rolling.map(r=>({date:r.date,value:r.ic}))},{name:'20 日均值 Rank IC',points:d.rolling.map(r=>({date:r.date,value:r.rank_ic}))}]);
 wbDrawLine('fvDecayChart',[{name:'平均 IC',points:d.decay.map(r=>({date:String(r.horizon),value:r.mean_ic}))},{name:'平均 Rank IC',points:d.decay.map(r=>({date:String(r.horizon),value:r.mean_rank_ic}))}]);
 const groupValues=d.summary.group_returns;
 if(groupValues.some(v=>v!=null))barsChart('fvGroupsChart',['低分组','中分组','高分组'],groupValues.map(v=>v==null?0:v*100));
 else{const {c}=canvasSetup('fvGroupsChart');c.fillText('无可定义分组：请检查因子并列值',20,55);}
 wbDrawLine('fvGroupTimeChart',[0,1,2].map((j)=>({name:['低分组','中分组','高分组'][j]+'远期收益 %',points:d.observations.map(r=>({date:r.date,value:r.groups==null?null:r.groups[j]*100}))})));
 wbDrawLine('fvWalkChart',[{name:'训练定向 Rank IC',points:d.folds.map(r=>({date:r.test_start,value:r.train_mean_rank_ic}))},{name:'样本外定向 Rank IC',points:d.folds.map(r=>({date:r.test_start,value:r.test.mean_rank_ic}))}]);
}
function renderFactorValidation(d){
 const s=d.summary;
 cards('fvMetrics',[['平均 IC',fvNumber(s.mean_ic)],['平均 Rank IC',fvNumber(s.mean_rank_ic)],['Rank ICIR · 不年化',fvNumber(s.rank_ic_ir)],['有效 Rank IC 日期',s.valid_rank_ic+' / '+s.dates]]);
 $('fvScope').textContent=`${d.factor_name} · ${d.horizon} 个共同观测日 · ${d.codes.length} 只股票`;
 $('fvSummary').textContent=`共同日线 ${d.common_start} 至 ${d.common_end}（${d.common_rows} 日）；信号区间 ${d.signal_start} 至 ${d.signal_end}；已完成标签截止 ${d.label_end}。高低组平均远期收益差 ${s.mean_spread==null?'—':pct(s.mean_spread)}；有效分组 ${s.valid_groups} 日。${d.folds.length?'滚动验证 '+d.folds.length+' 折。':'没有足够有效训练截面形成滚动验证。'}这些是小股票池的描述性证据，不能据此判定策略有效。`;
 tableAt('fvFolds',['折','训练信号区间','训练标签截止','测试信号区间','测试标签截止','训练所选因子 / 方向','训练 Rank IC','测试 Rank IC','测试抽样数','高低组差'],d.folds.map(r=>[r.fold,r.train_start+' → '+r.train_end,r.train_label_end,r.test_start+' → '+r.test_end,r.test_label_end,r.factor_name+(r.direction>0?' 正向':' 反向'),fvNumber(r.train_mean_rank_ic),fvNumber(r.test.mean_rank_ic),r.test.dates,r.test.mean_spread==null?'—':pct(r.test.mean_spread)]));
 tableAt('fvObservations',['信号日','标签截止','IC','Rank IC','低分组','中分组','高分组'],d.observations.map(r=>[r.date,r.label_end,fvNumber(r.ic),fvNumber(r.rank_ic),...[0,1,2].map(j=>r.groups==null?'—':pct(r.groups[j]))]));
 $('fvNotes').textContent=d.notes.join('\n');drawFactorValidation();
}
async function runFactorValidation(){
 if(!data){$('fvStatus').textContent='请先加载行情或演示数据';return;}
 pause();const key=factorValidationKey(),serial=++factorValidationSerial;
 factorValidationResult=null;$('fvResults').hidden=true;$('fvRun').disabled=true;$('fvStatus').textContent='正在对齐历史、计算 IC 与滚动样本外验证…';
 try{
  const codes=$('candidatePool').value.trim().split(/[,，\s]+/);
  if(codes.length<5||codes.length>8||new Set(codes).size!==codes.length)throw Error('因子验证需 5–8 只不重复股票，请修改上方候选池');
  const d=await postApi('/api/factor-validation',{codes,end:data.frames[index].date,demo:data.demo,factor:$('fvFactor').value,horizon:Number($('fvHorizon').value)});
  if(serial!==factorValidationSerial||key!==factorValidationKey())return;
  factorValidationContext=key;factorValidationResult=d;$('fvResults').hidden=false;
  $('fvStatus').textContent=`${d.demo?'合成演示 · ':''}${d.stale?'过期行情缓存 · ':''}验证完成，截至 ${d.asof}`;
  renderFactorValidation(d);
 }catch(e){if(serial===factorValidationSerial)$('fvStatus').textContent=e.message;}
 finally{$('fvRun').disabled=false;}
}
function drawMlDiagnostics(d){
 if(activeModule!=='ml'||!d.folds)return;
 wbDrawLine('mlFoldChart',[{name:'模型 MAE %',points:d.folds.map(r=>({date:String(r.fold),value:r.mae*100}))},{name:'均值基线 MAE %',points:d.folds.map(r=>({date:String(r.fold),value:r.baseline_mae*100}))}]);
 wbDrawLine('mlIcChart',[{name:'逐日横截面 Rank IC',points:d.folds.flatMap(r=>r.daily_rank_ic.map(p=>({date:p.date,value:p.rank_ic})))}]);
 tableAt('mlFolds',['折','训练区间','训练标签截止','测试区间','测试标签截止','训练/测试样本','模型 MAE','基线 MAE','平均 Rank IC'],d.folds.map(r=>[r.fold,r.train_start+' → '+r.train_end,r.train_label_end,r.test_start+' → '+r.test_end,r.test_label_end,r.train_samples+' / '+r.test_samples,pct(r.mae),pct(r.baseline_mae),fvNumber(r.mean_rank_ic)]));
}
function wireFactorValidation(){
 $('fvRun').onclick=runFactorValidation;
 $('fvFactor').onchange=invalidateFactorValidation;$('fvHorizon').onchange=invalidateFactorValidation;
 $('candidatePool').addEventListener('input',invalidateFactorValidation);
 $('fvExport').onclick=()=>{syncFactorValidation();if(!factorValidationResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(factorValidationResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='factor-validation-'+factorValidationResult.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 window.addEventListener('resize',drawFactorValidation);
}
