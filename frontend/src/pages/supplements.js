import{store}from'../stores/business.js';import{esc,num}from'../utils/format.js';import{table}from'../components/common/table.js';import{notice}from'../components/common/notice.js';import{GROUPS}from'../constants/enums.js';
export const DRAW_STATUS={pending:'待抽取',drawn:'待发出',issued:'已发出'};
export const OUTCOMES={awaiting:'未回应',responded:'愿意返校',refused:'拒绝',unreachable:'失联'};
const pct=v=>v==null?'—':(v*100).toFixed(1)+'%';
function drawFor(planId){return store.supplements.find(d=>d.plan_id===planId);}
function diffPanel(a){
 if(!a)return notice('尚未抽取名单。发起补测后，入选概率与抽样依据会随名单一起封存。');
 const d=a.difference,groups=a.groups;
 const low=d.low,high=d.high;
 const verdict=d.identified?'两个缺考层都有回应，点估计在假设成立时可识别。':(d.sign_identified?'0–100 分范围内方向已可识别：两组全体均差不会跨过 0。':'0–100 分范围内的组均差区间包含 0，辅导效果无法识别。');
 return `<div class=result-sheet><div class=result-heading><div><span class=eyebrow>补测聚合 · 分层概率加权</span><h2>两组全体均差 <em>${low==null?'—':`[${num(low)}, ${num(high)}]`}</em></h2><p>${esc(verdict)}</p></div><span class=report-no>抽样 № ${String(a.draw_id).padStart(3,'0')}<br>π 设计校验 ${esc(a.checksum.slice(0,12))}</span></div><div class=stats-strip><div><label>加权点估计</label><strong>${d.estimate==null?'不可识别':num(d.estimate)}</strong></div><div><label>仅回应者（有偏）</label><strong>${d.naive==null?'—':num(d.naive)}</strong></div><div><label>回应 / 样本</label><strong>${a.response_summary.responded} / ${a.response_summary.sampled}</strong></div><div><label>未回应</label><strong>${a.response_summary.awaiting}</strong></div></div><p class=method>${esc(a.method)}　样本校验 ${esc(a.checksum.slice(0,12))}</p></div>`;
}
function groupRows(a){return ['control','intervention'].map(g=>{const v=a.groups[g];return [`<b>${GROUPS[g]}</b>`,`${v.observed_n} / ${v.absent_n}`,`${v.responded_n} / ${v.sampled_n}`,v.mean_estimate==null?'—':num(v.mean_estimate),`[${num(v.mean_low)}, ${num(v.mean_high)}]`,v.naive_mean==null?'—':num(v.naive_mean)];});}
function stratumRows(a){
 const rows=[];
 for(const g of ['control','intervention']){
  for(const s of (a.groups?.[g]?.strata||[]))rows.push(s);
 }
 return rows.sort((x,y)=>x.campus===y.campus?x.group.localeCompare(y.group):x.campus.localeCompare(y.campus)).map(s=>[`<b>${esc(s.campus)}</b><small>${GROUPS[s.group]}</small>`,`${s.N}`,s.empty?'空层':`${s.quota}（π=${pct(s.pi)}）`,s.sampled,s.responded,s.refused,s.unreachable,s.awaiting,s.response_rate==null?'—':pct(s.response_rate)]);
}
function sampleTable(draw,canEdit){
 const rows=draw.samples.map(s=>[`<b>${esc(s.code)}</b><small>${esc(s.name)}</small>`,`${esc(s.campus)} / ${GROUPS[s.group]}`,pct(s.inclusion_probability),`${esc(s.stratum)} · #${s.selection_rank}`,draw.status==='issued'&&canEdit?`<span class=badge>${OUTCOMES[s.outcome]}</span>`:`<span class=badge>${OUTCOMES[s.outcome]}</span>`,s.retest_score==null?'—':num(s.retest_score,1),`<button class=text-btn data-sample=${s.id}>去向与依据</button>${draw.status==='issued'&&canEdit?`<button class=text-btn data-respond=${s.id} data-version=${s.response_version}>登记回应</button>`:''}`]);
 return table(['学号 / 姓名','教学点 / 分组','入选概率 π','层 · 抽取序号','回应','补测分','操作'],rows);
}
export function supplementsPage(){
 const canEdit=store.user.role!=='viewer';
 const plans=store.plans.map(p=>{const d=drawFor(p.id);return {p,d};});
 return `<header class=page-head><div><span class=eyebrow>05 / SUPPLEMENT SAMPLING</span><h1>补测抽样</h1><p>只补测愿意返校的缺考者会高估辅导效果。这里按教学点和原分组随机抽取，并封存入选概率与抽样依据。</p></div></header><div class=split><section>${plans.map(({p,d})=>{
  const a=d?.analysis;
  return `<article class=plan-entry><span class=eyebrow>PLAN ${String(p.id).padStart(3,'0')}</span><h2>${esc(p.title)}</h2><div class=meta>教学点 ${esc(p.campus)}　／　${d?`抽样 № ${d.id} · <span class=badge>${DRAW_STATUS[d.status]||d.status}</span>`:'尚未发起补测'}　／　${d?`冻结名册 ${d.frame_size} 条`:''}</div>
  <div class=filter-row style="margin-bottom:14px">${canEdit&&!d?`<form class="supplement-form inline-form" data-plan=${p.id}><label>每层名额<input name=per_stratum type=number min=1 max=50 value=2 required></label><button class=primary>封存设计并抽取名单</button></form>`:''}${canEdit&&d&&d.status==='pending'?`<button class=primary data-execute=${d.id}>抽取名单（沿用封存设计）</button>`:''}${canEdit&&d&&d.status==='drawn'?`<button class=primary data-issue=${d.id}>发出名单</button>`:''}${d?`<button class=quiet data-sample-draw=${d.id}>查看抽样依据</button>`:''}</div>
  ${d?.roster_drift?.changed?notice('抽样后应考名册已修订：冻结名册保持不变，入选概率不动；新修订只进入之后受理的检验报告。'):''}
  ${d?diffPanel(a):notice('发起补测会冻结当时的应考名册与缺考名册，之后的名册修订和重复提交都不会改变入选概率。')}
  ${d?`<div class=section-title><h2>分层样本</h2><span>空层保留，π 记为 0</span></div>${a?table(['层','缺考 N','名额 / π','已抽','回应','拒绝','失联','未回应','回应率'],stratumRows(a)):table(['层','缺考 N','名额 / π'],d.strata.map(s=>[`<b>${esc(s.campus)}</b><small>${GROUPS[s.group]}</small>`,s.N,s.empty?'空层':`${s.quota}（π=${pct(s.pi)}）`]))}`:''}
  ${d?`<div class=section-title><h2>补测名单</h2><span>${d.samples.length} 名 · ${DRAW_STATUS[d.status]}</span></div>${d.samples.length?sampleTable(d,canEdit):notice('该方案没有缺考者，所有层为空层，名单为空。')}`:''}
  ${d&&a?`<div class=section-title><h2>组均分估计</h2><span>只聚合冻结应考名册与补测样本</span></div>${table(['组','已观测 / 缺考','回应 / 样本','加权均分','0–100 识别区间','仅回应者（有偏）'],groupRows(a))}`:''}
  ${d&&a?`<aside class=notice>${a.assumptions.map(x=>esc(x)).join('<br>')}</aside>${a.warnings.length?`<aside class=notice>${a.warnings.map(x=>esc(x)).join('<br>')}</aside>`:''}`:''}
  </article>`;}).join('')||notice('还没有方案。先到辅导分组登记研究范围。')}</section><aside class=side-sheet><span class=eyebrow>SAMPLE PROVENANCE</span><h2>样本去向与依据</h2><div id=sample-detail>${sampleDetail(null)}</div></aside></div>`;
}
export function responseForm(info){
 const s=info.sample;
 return `<form id=response-form data-sample=${s.id} data-version=${s.response_version}><input type=hidden name=sample_id value=${s.id}><span class=eyebrow>登记回应 · ${esc(s.code)}</span><h2 style="font-size:19px">${esc(s.name)}</h2><label>回应<select name=outcome><option value=responded>愿意返校补测</option><option value=refused>拒绝</option><option value=unreachable>失联</option></select></label><label>补测分（愿意返校时必填，0–100）<input name=retest_score type=number min=0 max=100 step=.1></label><label>备注<input name=note maxlength=1000></label><button class=primary>保存回应</button><button type=button class=quiet data-cancel-response=1>取消</button></form>`;
}
export function drawBasis(draw){
 const design={method:'按教学点×原分组分层，从缺考名册无放回随机抽取固定名额；入选概率在抽取前封存。',strata:draw.strata};
 return `<div class=result-sheet style="padding:18px"><span class=eyebrow>SAMPLING BASIS</span><h2 style="font-size:19px">抽样设计 № ${draw.id}</h2><div class=stats-strip style="flex-wrap:wrap;gap:16px"><div><label>每层名额</label><strong>${draw.per_stratum}</strong></div><div><label>冻结名册</label><strong>${draw.frame_size}</strong></div><div><label>名单状态</label><strong>${DRAW_STATUS[draw.status]||draw.status}</strong></div></div><p class=checksum>设计校验 SHA-256 ${esc(draw.checksum)}<br>冻结名册 SHA-256 ${esc(draw.frame_sha256)}<br>随机种子 ${esc(draw.seed)}</p><p class=method>${esc(design.method)}</p>${table(['层','缺考 N','名额','π'],design.strata.map(s=>[`${esc(s.campus)} / ${GROUPS[s.group]}`,s.N,s.quota,pct(s.pi)]))}</div>`;
}
export function sampleDetail(info){
 if(!info)return notice('在名单中点“去向与依据”，查看该样本的层、入选概率、抽取序号、冻结名册记录和全部回应历史。');
 const s=info.sample,b=info.basis,st=b.stratum||{};
 return `<div class=result-sheet style="padding:18px"><span class=eyebrow>样本 № ${s.id}</span><h2 style="font-size:19px">${esc(s.code)} · ${esc(s.name)}</h2><p>${esc(s.campus)} / ${GROUPS[s.group]}　层 ${esc(st.campus||'')}|${esc(st.group||'')}</p><div class=stats-strip style="flex-wrap:wrap;gap:16px"><div><label>入选概率 π</label><strong>${pct(s.inclusion_probability)}</strong></div><div><label>层缺考 N</label><strong>${st.N??'—'}</strong></div><div><label>名额</label><strong>${st.quota??'—'}</strong></div><div><label>抽取序号</label><strong>#${s.selection_rank}</strong></div></div><p class=checksum>名单状态 ${DRAW_STATUS[info.draw.status]||info.draw.status}　／　发出 ${esc((info.draw.issued_at||'—').slice(0,19))}<br>冻结名册 SHA-256 ${esc(b.frame_sha256||'')}<br>设计校验 ${esc(info.draw.checksum||'')}</p><p class=method>${esc(b.method||'')}</p>${info.responses.length?table(['时间 UTC','回应','补测分','登记人','备注'],info.responses.map(r=>[esc(r.created_at.slice(0,19)),OUTCOMES[r.outcome]||esc(r.outcome),r.retest_score==null?'—':num(r.retest_score,1),esc(r.actor),esc(r.note)])):notice('尚未登记回应。未回应者不会被补抽。')}</div>`;
}
