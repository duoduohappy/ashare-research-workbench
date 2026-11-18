let evInventory=null,evView=null,evRun=null,evCheck=null,evComparison=null,evBusy=false,evRefreshSerial=0;
const evNames={factor:'因子验证',portfolio:'组合算法实验',regime:'状态算法对照',strategy:'策略稳健性验收'};
const evidenceApi=body=>postApi('/api/research-evidence',body);
function evOptions(id,rows,label){const el=$(id),old=el.value;el.replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='请选择';el.append(empty);for(const r of rows){const option=document.createElement('option');option.value=r.id;option.textContent=label(r);el.append(option);}el.value=rows.some(r=>r.id===old)?old:'';}
function evRunOptions(){if(!evInventory)return;evOptions('evRunSelect',evInventory.runs.filter(r=>r.snapshot_id===$('evSnapshot').value),r=>evNames[r.kind]+' · '+r.created_at+' · '+r.id.slice(0,8));}
async function refreshEvidence(selectId=''){
 const serial=++evRefreshSerial;
 try{
  const inventory=await evidenceApi({action:'list'});if(serial!==evRefreshSerial)return;
  evInventory=inventory;
  for(const id of ['evSnapshot','evCompareLeft','evCompareRight'])evOptions(id,evInventory.snapshots,r=>`${r.demo?'演示':'真实'} · ${r.asof} · ${r.rows.length} 只 · ${r.id.slice(0,8)}`);
  if(selectId)$('evSnapshot').value=selectId;
  evRunOptions();renderEvidence();
  if(evInventory.warnings.length)$('evStatus').textContent=evInventory.warnings.join('；');
 }catch(e){$('evStatus').textContent=e.message;}
}
function evConfig(){
 const kind=$('evKind').value;
 if(kind==='factor')return {factor:$('fvFactor').value,horizon:Number($('fvHorizon').value)};
 if(kind==='portfolio')return {start:$('optStart').value,lookback:Number($('optWindow').value),interval:Number($('optInterval').value),cap:Number($('optCap').value)/100,cost_bps:Number($('optCost').value),capital:Number($('optCapital').value),estimator:$('optEstimator').value};
 const code=$('evTarget').value;
 if(kind==='regime')return {code,lookback:Number($('regWindow').value),threshold:Number($('regThreshold').value)/100};
 const scenario=$('svLimit').value;
 return {code,window:loadedWindow,threshold:loadedThreshold/100,lookback:Number($('svWindow').value),periods:$('wbPeriods').value.split(/[,，\s]+/).map(Number),momenta:$('wbMomenta').value.split(/[,，\s]+/).map(Number),capital:Number($('wbLabCapital').value),filtered:$('wbLabFilter').checked,limit:scenario==='auto'?(/^(300|301|688)/.test(code)?.2:.1):Number(scenario)};
}
function previewEvidence(){
 $('evTargetLabel').hidden=!['regime','strategy'].includes($('evKind').value);
 const names={code:'分析标的',factor:'价格因子',horizon:'远期观测步数',start:'起点',lookback:'训练窗口',interval:'调仓间隔',cap:'单股目标上限比例',cost_bps:'每侧成本 bp',capital:'初始研究资金',estimator:'协方差方法',window:'状态窗口',threshold:'状态阈值比例',periods:'均线候选',momenta:'动量候选',filtered:'附加状态过滤',limit:'涨跌停场景比例'};
 tableAt('evConfigTable',['本次参数','值'],Object.entries(evConfig()).map(([key,value])=>[names[key]||key,Array.isArray(value)?value.join('、'):String(value)||'自动起点']));
}
async function viewEvidence(){
 const id=$('evSnapshot').value;evRun=null;evCheck=null;evView=null;evRunOptions();renderEvidence();
 if(!id){evView=null;renderEvidence();return;}
 try{const d=await evidenceApi({action:'view',snapshot_id:id});if(id!==$('evSnapshot').value)return;evView=d;evOptions('evTarget',d.rows.map(r=>({id:r.code})),r=>r.id);if(!$('evTarget').value)$('evTarget').value=d.rows[0].code;previewEvidence();renderEvidence();}
 catch(e){$('evStatus').textContent=e.message;}
}
function renderEvidence(){
 const inventory=evInventory||{snapshots:[],runs:[],checks:[]};
 cards('evMetrics',[['已存日线版本',inventory.snapshots.length],['已存研究记录',inventory.runs.length],['所选快照截止',evView?.asof||'未选择'],['当前复现核对',evCheck?({matched:'完整哈希一致',mismatch:'结果不一致',engine_changed:'环境已变化'}[evCheck.status]):'尚未复算']]);
 $('evSnapshotInfo').textContent=evView?`${evView.demo?'合成演示':'真实模式'} · 截止 ${evView.asof} · ${evView.id}。该日期独立于上方共享回放日。`:'先冻结一版日线，或选择已有快照。';
 tableAt('evSnapshotTable',['代码','日线数','起点','截止','源缓存状态','来源'],(evView?.rows||[]).map(r=>[r.code,r.rows,r.first,r.last,r.stale?'冻结时为过期缓存':'冻结时未标过期',r.source]));
 tableAt('evRunTable',['类型','快照截止','创建时间','结果指纹'],inventory.runs.map(r=>[evNames[r.kind],r.asof,r.created_at,r.result_sha.slice(0,16)]));
 tableAt('evChecks',['核对项目','结论'],(evCheck?.checks||[]).map(r=>[r.label,r.passed===null?'未执行':r.passed?'通过':'未通过']));
 $('evReplayInfo').textContent=evCheck?(evCheck.status==='engine_changed'?'计算环境与原记录不同，已停止重算。原始结果仍可查看；不会运行保存的历史源码。':`原始结果 ${evCheck.expected_sha}；复算结果 ${evCheck.actual_sha}。完整 JSON 采用严格哈希比较；不一致需检查环境及浮点差异。`):evRun?`所选记录：${evNames[evRun.kind]}，数据截止 ${evRun.asof}。结果 ${evRun.result_sha}；可离线复算或导出原始结果。`:'选择已保存的研究记录后再进行复现核对。';
 if(evComparison){tableAt('evDiffTable',['代码','新增日期','删除日期','共同日期字段变化'],evComparison.rows.map(r=>[r.code,r.added,r.removed,r.changed]));$('evDiffInfo').textContent=`左版截止 ${evComparison.left_asof}；右版截止 ${evComparison.right_asof}。${evComparison.note}`;}
 drawEvidence();
}
function drawEvidence(){
 if(activeModule!=='quality')return;
 const v=evView;
 wbHeat('evCoverageChart',{labels:(v?.rows||[]).map(r=>r.code),columns:v?.dates||[],values:(v?.rows||[]).map(r=>r.presence),binary:true});
 barsChart('evRowsChart',(v?.rows||[]).map(r=>r.code),(v?.rows||[]).map(r=>r.rows),0);
 const diff=evComparison;
 wbHeat('evDiffChart',{labels:(diff?.rows||[]).map(r=>r.code),columns:['新增','删除','字段变化'],values:(diff?.rows||[]).map(r=>[r.added,r.removed,r.changed])});
 wbDrawLine('evRevisionChart',(diff?.rows||[]).map(r=>({name:r.code,points:diff.changes.filter(c=>c.code===r.code&&c.close_revision!==0).map(c=>({date:c.date,value:c.close_revision*100}))})));
 const original=evCheck?.original_summary||evRun?.summary,replayed=evCheck?.replayed_summary;
 wbHeat('evReplayChart',{labels:original?.labels||[],columns:['原始记录','离线复算'],values:(original?.values||[]).map((v,i)=>[v,replayed?.values[i]??null])});
 $('evReplayUnit').textContent=original?'数值单位：'+original.unit:'选择记录后显示单位';
 barsChart('evHistoryChart',Object.values(evNames),Object.keys(evNames).map(k=>(evInventory?.runs||[]).filter(r=>r.kind===k).length),0);
}
async function captureEvidence(){
 if(!data){$('evStatus').textContent='请先加载行情或合成演示，选择共享截止日';return;}
 if(evBusy)return;evBusy=true;$('evCapture').disabled=true;const end=data.frames[index].date;
 try{const d=await evidenceApi({action:'capture',codes:$('evCodes').value.trim().split(/[,，\s]+/),end,demo:data.demo});await refreshEvidence(d.snapshot_id);await viewEvidence();$('evStatus').textContent=`${d.reused?'复用已有相同数据版本':'已冻结数据版本'} · 截至 ${end} · ${d.snapshot_id.slice(0,12)}`;}
 catch(e){$('evStatus').textContent=e.message;}
 finally{evBusy=false;$('evCapture').disabled=false;}
}
async function runEvidence(){
 if(evBusy)return;const id=$('evSnapshot').value;if(!id){$('evStatus').textContent='请先选择冻结快照';return;}
 const kind=$('evKind').value,config=evConfig(),key=JSON.stringify([id,kind,config]);previewEvidence();evBusy=true;$('evAnalyze').disabled=true;$('evStatus').textContent='正在使用冻结日线计算并保存研究证据…';
 try{const d=await evidenceApi({action:'run',snapshot_id:id,kind,config});await refreshEvidence();if(key===JSON.stringify([$('evSnapshot').value,$('evKind').value,evConfig()])){evRun=d;evCheck=null;$('evRunSelect').value=d.run_id;renderEvidence();}$('evStatus').textContent='研究记录已保存 · '+d.run_id.slice(0,12);}
 catch(e){$('evStatus').textContent=e.message;}
 finally{evBusy=false;$('evAnalyze').disabled=false;}
}
async function loadEvidenceRun(){
 const id=$('evRunSelect').value;evCheck=null;evRun=null;
 if(!id){renderEvidence();return;}
 try{const d=await evidenceApi({action:'run_detail',run_id:id});if(id!==$('evRunSelect').value)return;evRun=d;renderEvidence();}catch(e){$('evStatus').textContent=e.message;}
}
async function replayEvidence(){
 const id=$('evRunSelect').value;if(!id||evBusy){if(!id)$('evStatus').textContent='请选择研究记录';return;}
 evBusy=true;$('evReplay').disabled=true;
 try{const d=await evidenceApi({action:'replay',run_id:id});if(id===$('evRunSelect').value){evCheck=d;renderEvidence();}$('evStatus').textContent=d.status==='matched'?'离线复算的完整结果哈希一致':d.status==='engine_changed'?'环境变化，已阻止复算':'复算结果不一致';await refreshEvidence();}
 catch(e){$('evStatus').textContent=e.message;}
 finally{evBusy=false;$('evReplay').disabled=false;}
}
async function compareEvidence(){
 const left=$('evCompareLeft').value,right=$('evCompareRight').value;
 if(!left||!right){$('evStatus').textContent='请选择左右两个数据版本';return;}
 try{const d=await evidenceApi({action:'compare',left_id:left,right_id:right});if(left!==$('evCompareLeft').value||right!==$('evCompareRight').value)return;evComparison=d;renderEvidence();}catch(e){$('evStatus').textContent=e.message;}
}
function downloadEvidence(value,name){const u=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=name+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function wireEvidence(){
 $('evCapture').onclick=captureEvidence;$('evRefresh').onclick=()=>refreshEvidence();$('evSnapshot').onchange=viewEvidence;$('evKind').onchange=previewEvidence;$('evTarget').onchange=previewEvidence;$('evPreview').onclick=previewEvidence;$('evAnalyze').onclick=runEvidence;$('evRunSelect').onchange=loadEvidenceRun;$('evReplay').onclick=replayEvidence;$('evCompare').onclick=compareEvidence;
 for(const id of ['evCompareLeft','evCompareRight'])$(id).onchange=()=>{evComparison=null;$('evDiffTable').replaceChildren();$('evDiffInfo').textContent='版本已改变，请重新比较';drawEvidence();};
 $('evExportSnapshot').onclick=async()=>{try{const id=$('evSnapshot').value;if(!id)throw Error('请选择快照');downloadEvidence(await evidenceApi({action:'export_snapshot',snapshot_id:id}),'snapshot-'+id.slice(0,12));}catch(e){$('evStatus').textContent=e.message;}};
 $('evExportRun').onclick=()=>{if(evRun)downloadEvidence(evRun,'research-'+evRun.run_id.slice(0,12));else $('evStatus').textContent='请先选择研究记录';};
 window.addEventListener('resize',drawEvidence);
}
function switchEvidence(){if(activeModule==='quality')refreshEvidence();}
