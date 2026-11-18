let regimeResult=null,regimeSerial=0,regimeContext='';
function regimeKey(){return [wbContext(),$('regWindow').value,$('regThreshold').value].join('|');}
function invalidateRegime(){regimeSerial++;regimeResult=null;$('regResults').hidden=true;$('regStatus').textContent='标的、日期或参数已改变，请重新分析';}
function syncRegime(){if(regimeResult&&regimeKey()!==regimeContext)invalidateRegime();}
function regimeCalibration(d){
 const {c,w,h}=canvasSetup('regCalibrationChart'),left=50,right=w-20,top=45,bottom=h-35;
 const x=v=>left+(right-left)*v,y=v=>bottom-(bottom-top)*v;
 c.strokeStyle='#e5e9f0';c.fillStyle='#657389';
 for(let i=0;i<=4;i++){const p=i/4;c.beginPath();c.moveTo(left,y(p));c.lineTo(right,y(p));c.stroke();c.fillText((p*100).toFixed(0)+'%',4,y(p)+3);c.fillText((p*100).toFixed(0)+'%',x(p)-8,bottom+16);}
 c.strokeStyle='#a7b3c8';c.beginPath();c.moveTo(x(0),y(0));c.lineTo(x(1),y(1));c.stroke();
 const colors=['#365ce6','#dc9e37','#299d81'],tips=[];
 Object.keys(d.names).forEach((k,i)=>{c.fillStyle=colors[i];c.fillText(d.names[k],left+i*(right-left)/3,15);for(const r of d.results[k].metrics.calibration){c.beginPath();c.arc(x(r.predicted),y(r.observed),4,0,Math.PI*2);c.fill();tips.push({x:x(r.predicted),y:y(r.observed),text:d.names[k]+' · '+r.count+' 个标签 · 预测 '+pct(r.predicted)+' / 实际 '+pct(r.observed)});}});
 c.fillStyle='#657389';c.fillText('横轴：预测上涨概率；纵轴：实际上涨频率',left,h-2);
 $('regCalibrationChart').onmousemove=e=>{if(!tips.length)return;const p=tips.reduce((a,b)=>Math.hypot(a.x-e.offsetX,a.y-e.offsetY)<Math.hypot(b.x-e.offsetX,b.y-e.offsetY)?a:b);$('regCalibrationChart').title=p.text;};
}
function drawRegime(){
 if(!regimeResult||activeModule!=='state')return;
 const d=regimeResult,keys=Object.keys(d.names),recent=d.results.hmm.observations.slice(-120);
 wbHeat('regTimelineChart',{labels:keys.map(k=>d.names[k]),columns:recent.map(r=>r.date),values:keys.map(k=>d.results[k].observations.slice(-120).map(r=>r.state-1))});
 wbDrawLine('regProbabilityChart',d.states.map((name,i)=>({name,points:recent.map(r=>({date:r.date,value:r.current_probabilities[i]*100}))})));
 wbHeat('regTransitionChart',{labels:d.states,columns:d.states,values:d.latest.hmm.transition.map(row=>row.map(v=>v*100))});
 wbHeat('regFeaturesChart',{labels:keys.flatMap(k=>d.states.map(s=>d.names[k]+' '+s)),columns:['当日收益 %','20 日动量 %','单期波动 %'],values:keys.flatMap(k=>d.latest[k].training_state_features.map(row=>row.map(v=>v==null?null:v*100)))});
 barsChart('regBrierChart',[...keys.map(k=>d.names[k]),'训练无条件基线'],[...keys.map(k=>d.results[k].metrics.brier),d.results.hmm.metrics.baseline_brier],4);
 regimeCalibration(d);
 const groups=keys.flatMap(k=>d.results[k].metrics.by_state.filter(r=>r.count).map(r=>({label:d.names[k]+' '+d.states[r.state],value:r.mean_next_return*100})));
 barsChart('regReturnsChart',groups.map(r=>r.label),groups.map(r=>r.value));
}
function renderRegime(d){
 const h=d.results.hmm.metrics,latest=d.latest.hmm;
 cards('regMetrics',[['已完成样本外标签',h.samples],['滚动训练折数',d.folds.length],['HMM Brier · 越低越好',h.brier.toFixed(4)],['训练基线 Brier',h.baseline_brier.toFixed(4)]]);
 $('regScope').textContent=`${d.code} · 截至 ${d.last_date}${d.demo?' · 合成演示':''}`;
 $('regInsight').textContent=`最近模型训练截至 ${latest.train_end}；当前过滤状态为「${d.states[latest.current_probabilities.indexOf(Math.max(...latest.current_probabilities))]}」。隐状态分布与下一日涨跌概率不是同一个量。HMM 的下一日上涨事件估计为 ${pct(latest.up_probability)}，最新后续标签尚未知，不计入评估。${d.warnings.length?'有 '+d.warnings.length+' 折达到 HMM 迭代上限，请查看训练诊断。':'各折 HMM 均满足训练似然变化容差；这不代表预测有效。'}`;
 tableAt('regComparison',['方法','样本数','Brier','基线 Brier','收益 MAE','基线 MAE','方向准确率','状态切换数'],Object.keys(d.names).map(k=>{const m=d.results[k].metrics;return [d.names[k],m.samples,m.brier.toFixed(4),m.baseline_brier.toFixed(4),pct(m.mae),pct(m.baseline_mae),pct(m.direction_accuracy),m.state_switches];}));
 tableAt('regFoldTable',['折 / 固定锚点','训练区间','测试特征区间','HMM 迭代','训练收敛','初始化种子','训练对数似然'],d.folds.map(f=>[f.fold+' / '+f.anchor,f.train_start+' → '+f.train_end,f.test_start+' → '+f.test_end,f.hmm_iterations,f.hmm_converged?'达到容差':'达到上限',f.hmm_seed,f.hmm_training_log_likelihood.toFixed(2)]));
 tableAt('regRecords',['方法','信号日','训练截止','状态','下一标签日','预测收益','预测上涨概率','实际下一收益'],Object.keys(d.names).flatMap(k=>d.results[k].observations.map(r=>[d.names[k],r.date,r.train_end,d.states[r.state],r.label_end||'尚未知',pct(r.prediction),pct(r.up_probability),r.actual==null?'尚未知':pct(r.actual)])));
 $('regNotes').textContent=d.notes.join('\n')+(d.warnings.length?'\n诊断：'+d.warnings.join('；'):'');drawRegime();
}
async function runRegime(){
 if(!data){$('regStatus').textContent='请先加载行情或合成演示';return;}
 pause();const key=regimeKey(),serial=++regimeSerial;
 regimeResult=null;$('regResults').hidden=true;$('regRun').disabled=true;$('regStatus').textContent='正在滚动训练并逐日过滤 HMM，可能需要数秒…';
 try{
  const d=await postApi('/api/regime-research',{code:loadedCode,end:data.frames[index].date,demo:data.demo,lookback:Number($('regWindow').value),threshold:Number($('regThreshold').value)/100});
  if(serial!==regimeSerial||key!==regimeKey())return;
  regimeResult=d;regimeContext=key;$('regResults').hidden=false;
  $('regStatus').textContent=`${d.demo?'合成演示 · ':''}${d.stale?'过期行情缓存 · ':''}状态对照完成${d.warnings.length?' · 有收敛提示':''}`;
  renderRegime(d);
 }catch(e){if(serial===regimeSerial)$('regStatus').textContent=e.message;}
 finally{$('regRun').disabled=false;}
}
function wireRegime(){
 $('regRun').onclick=runRegime;
 for(const id of ['regWindow','regThreshold']){$(id).addEventListener('input',invalidateRegime);$(id).addEventListener('change',invalidateRegime);}
 $('regExport').onclick=()=>{syncRegime();if(!regimeResult)return;const u=URL.createObjectURL(new Blob([JSON.stringify(regimeResult,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='regime-research-'+regimeResult.code+'-'+regimeResult.asof+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 window.addEventListener('resize',drawRegime);
}
