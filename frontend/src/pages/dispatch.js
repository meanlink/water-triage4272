import {patrolBatches, dispatches, jobs} from '../api/entities.js';
import {downloadDispatch} from '../api/client.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc, notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

let selectedDispatchId = null;

function ruleUsable(job) {
 return Boolean(job.result && job.result.rule_artifact && job.result.rule_artifact.artifact_version === 1);
}

export async function dispatchPage() {
 const [batches, allJobs, list] = await Promise.all([patrolBatches.list(), jobs.list(), dispatches.list()]);
 workspace.patrolBatches = batches;
 workspace.dispatches = list;
 const approved = allJobs.filter(j => j.approved && j.status === 'completed');
 const usable = approved.filter(ruleUsable);
 const legacy = approved.filter(j => !ruleUsable(j));
 const readonly = session.user.role === 'viewer';
 const cols = workspace.meta.patrol_columns || [];
 return heading('06 / PATROL DISPATCH', '待巡管段规则派单', '用已批准试验的原规则快照，给无标签待巡批次评分；按巡检名额取风险最高管段，入选清单按编号排序。派单冻结当时规则与输入，之后新增试验或批次不改变已派结果。', '<button class="button" id="refresh-dispatch">刷新派单 ↻</button>')
  + '<div class="report-grid"><section class="panel">'
  + '<div class="section-title"><h2>① 接入无标签待巡批次</h2><span>' + batches.length + ' 批</span></div>'
  + '<form id="patrol-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：城东 11 月待巡批次"></label>'
  + '<label>上传 CSV 或 JSON（无复核标签）<input type="file" id="patrol-file" accept=".json,.csv"></label>'
  + '<label>记录 JSON<textarea name="records" rows="5" placeholder="仅含管段编号与四项测量值" required></textarea></label>'
  + '<p class="hint">字段：' + cols.map(c => esc(c.key) + ' / ' + esc(c.label)).join('，') + '。坏行或重复编号将整批拒绝。</p>'
  + '<button type="submit" class="primary" ' + (readonly ? 'disabled' : '') + '>校验并接入批次</button></form>'
  + '<div class="section-title"><h2>② 按规则快照派单</h2></div>'
  + '<form id="dispatch-form"><label>派单名称<input name="name" required minlength="2" value="城北巡检派单 · 按原规则"></label>'
  + '<label>已批准规则试验<select name="job_id" required>'
  + usable.map(j => '<option value="' + j.id + '">' + esc(j.name) + '（含规则快照）</option>').join('')
  + (legacy.length ? legacy.map(j => '<option value="' + j.id + '" disabled>' + esc(j.name) + '（旧试验·缺规则快照，不可派单）</option>').join('') : '')
  + '</select></label>'
  + (legacy.length ? '<p class="warning">有 ' + legacy.length + ' 个旧试验缺少可用规则快照：系统不会重训冒充原规则，请新建试验并批准后再派单。</p>' : '')
  + '<label>待巡批次<select name="patrol_batch_id" required>' + batches.map(b => '<option value="' + b.id + '">' + esc(b.name) + ' · ' + b.rows + ' 段</option>').join('') + '</select></label>'
  + '<label>巡检名额（段）<input type="number" name="quota" value="10" min="1" required></label>'
  + '<button type="submit" class="primary" ' + (readonly || !usable.length || !batches.length ? 'disabled' : '') + '>按原规则评分并派单</button>'
  + '<p class="hint">评分只读取派单时冻结的规则快照，不重新训练；相同规则与输入重放结果完全一致。</p></form></section>'
  + '<section><div class="section-title"><h2>已派清单（不可变）</h2><span>' + list.length + ' 张</span></div>'
  + '<div class="schedule-list">' + list.map(d => '<article class="dispatch-item' + (d.id === selectedDispatchId ? ' active' : '') + '" data-dispatch="' + d.id + '"><div><strong>' + esc(d.name) + '</strong><p>名额 ' + d.quota + ' 段 · 入选 ' + (d.selected_count ?? 0) + '/' + (d.candidate_count ?? 0) + ' · 试验#' + d.job_id + '</p><small>输入指纹 ' + esc(d.input_checksum.slice(0, 18)) + '…</small></div><button class="text-button" data-view="' + d.id + '">核对详情</button></article>').join('')
  + (!list.length ? '<p class="empty">还没有派单。先在左侧接入待巡批次并选择已批准规则。</p>' : '') + '</div>'
  + '<section class="panel" id="dispatch-detail"><div class="empty">选择上方任一派单，核对入选与未入选原因、规则路径与冻结快照。</div></section></section></div>';
}

function detailView(d) {
 const r = d.result || {};
 const ranking = r.ranking || [];
 const selectedIds = new Set((r.selected || []).map(s => s.segment_id));
 const rows = ranking.map(item => ({
  rank: item.rank,
  segment_id: item.segment_id,
  risk_pct: item.risk_pct,
  leaf_node: item.leaf_node,
  selected: item.selected ? '入选' : '未入选',
  reason: item.reason,
  rule_path_text: item.rule_path_text,
 }));
 const columns = [
  {key: 'rank', label: '风险排名'}, {key: 'segment_id', label: '管段编号'},
  {key: 'risk_pct', label: '规则风险率(%)'}, {key: 'leaf_node', label: '命中叶节点'},
  {key: 'selected', label: '是否入选'}, {key: 'reason', label: '入选/未入选原因'},
  {key: 'rule_path_text', label: '命中规则路径'},
 ];
 const snapshot = d.rule_snapshot || {};
 return '<div class="section-title"><h2>' + esc(d.name) + '</h2><span>' + esc(d.status) + '</span></div>'
  + '<div class="metrics"><div><span>候选管段</span><strong>' + (r.candidate_count ?? 0) + '<small>段</small></strong></div>'
  + '<div><span>巡检名额</span><strong>' + d.quota + '<small>段</small></strong></div>'
  + '<div><span>实际入选</span><strong>' + (r.selected_count ?? 0) + '<small>段</small></strong></div>'
  + '<div><span>规则叶节点</span><strong>' + (snapshot.n_leaves ?? '-') + '<small>个</small></strong></div></div>'
  + '<div class="method-sheet compact"><p class="eyebrow">FROZEN AT ISSUE</p><p>' + esc(r.summary || '') + '</p>'
  + '<p class="hint">' + esc(r.tie_note || '') + '</p>'
  + '<p class="hint">规则参数：' + esc(JSON.stringify(d.rule_params)) + '；输入指纹 SHA256 ' + esc(d.input_checksum) + '</p></div>'
  + '<div class="dispatch-actions"><button class="button small" data-dl="' + d.id + '" data-format="csv">下载核对表 CSV ↓</button>'
  + '<button class="button small" data-dl="' + d.id + '" data-format="json">下载快照 JSON ↓</button></div>'
  + '<div class="section-title"><h2>入选清单（按编号排序）</h2><span>' + (r.selected || []).length + ' 段</span></div>'
  + table(columns.filter(c => ['segment_id', 'risk_pct', 'selected', 'reason'].includes(c.key)), (r.selected || []).map(s => ({segment_id: s.segment_id, risk_pct: s.risk_pct, selected: '入选', reason: s.reason})), '无入选管段。')
  + '<div class="section-title"><h2>全部候选评分与原因</h2><span>' + rows.length + ' 行（风险降序，并列按编号）</span></div>'
  + table(columns, rows, '暂无评分记录。');
}

export function bindDispatch(refresh) {
 document.querySelector('#refresh-dispatch').onclick = refresh;
 const file = document.querySelector('#patrol-file');
 file?.addEventListener('change', async e => {
  try {
   const f = e.target.files[0]; if (!f) return;
   const text = await f.text();
   const records = f.name.endsWith('.csv') ? parseCSV(text) : JSON.parse(text);
   document.querySelector('[name=records]').value = JSON.stringify(records, null, 2);
  } catch (error) { notify(error.message, true); }
 });
 submit(document.querySelector('#patrol-form'), async f => {
  await patrolBatches.create({name: f.get('name'), source: file.files[0]?.name || 'manual.json', records: JSON.parse(f.get('records'))});
  notify('待巡批次已接入，坏行与重复编号已整批校验');
  await refresh();
 });
 submit(document.querySelector('#dispatch-form'), async f => {
  const d = await dispatches.create({name: f.get('name'), job_id: Number(f.get('job_id')), patrol_batch_id: Number(f.get('patrol_batch_id')), quota: Number(f.get('quota'))});
  selectedDispatchId = d.id;
  notify('派单已生成，规则与输入已冻结');
  await refresh();
 });
 document.querySelectorAll('[data-view]').forEach(b => b.onclick = async () => {
  selectedDispatchId = Number(b.dataset.view);
  const detail = await dispatches.get(selectedDispatchId);
  document.querySelector('#dispatch-detail').innerHTML = detailView(detail);
  bindDownloads();
  document.querySelectorAll('.dispatch-item').forEach(el => el.classList.toggle('active', Number(el.dataset.dispatch) === selectedDispatchId));
 });
 if (selectedDispatchId) {
  dispatches.get(selectedDispatchId).then(detail => {
   const box = document.querySelector('#dispatch-detail');
   if (box) { box.innerHTML = detailView(detail); bindDownloads(); }
  }).catch(e => notify(e.message, true));
 }
 function bindDownloads() {
  document.querySelectorAll('[data-dl]').forEach(b => b.onclick = () =>
   downloadDispatch(b.dataset.dl, b.dataset.format).catch(e => notify(e.message, true)));
 }
}
