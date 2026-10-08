import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    if (!argv[i].startsWith('--')) continue;
    const key = argv[i].slice(2);
    out[key] = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
  }
  return out;
}
const args = parseArgs(process.argv.slice(2));
if (args.help || args.h) {
  console.log('Usage: node scripts/llm_judge_shared_retrieval_pool.mjs --queries FILE --candidate-union FILE --output-dir DIR --resume');
  process.exit(0);
}
for (const name of ['queries', 'candidate-union', 'output-dir']) if (!args[name]) throw new Error('--' + name + ' is required');
const queryPath = path.resolve(String(args.queries));
const unionPath = path.resolve(String(args['candidate-union']));
const outputDir = path.resolve(String(args['output-dir']));
const model = String(args.model || process.env.LLM_MODEL || 'deepseek-ai/DeepSeek-V4-Flash');
const baseUrl = String(args['base-url'] || process.env.LLM_BASE_URL || 'https://api.siliconflow.cn/v1').replace(/\/$/, '').replace(/\/chat\/completions$/, '');
const timeoutMs = Number(args.timeout || 3600000);
const concurrency = Math.max(1, Number(args.concurrency || 5));
const batchSize = Math.max(1, Number(args['batch-size'] || 8));
const maxRetries = Math.max(1, Number(args['max-retries'] || 5));
const resume = Boolean(args.resume);
const promptVersion = 'shared-retrieval-qrels-v1';
const labels = {0: 'IRRELEVANT', 1: 'BACKGROUND', 2: 'STRONG_SUPPORT', 3: 'DIRECT'};
const readJson = async file => JSON.parse(await fs.readFile(file, 'utf8'));
const writeJson = async (file, value) => fs.writeFile(file, JSON.stringify(value, null, 2) + '\n', 'utf8');
const readJsonl = async file => { try { return (await fs.readFile(file, 'utf8')).split(/\r?\n/).filter(Boolean).map(JSON.parse); } catch (e) { if (e && e.code === 'ENOENT') return []; throw e; } };
const sha256File = async file => crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex').toUpperCase();
const getRows = (value, keys) => {
  if (Array.isArray(value)) return value.filter(row => row && typeof row === 'object');
  for (const key of keys) if (Array.isArray(value && value[key])) return value[key].filter(row => row && typeof row === 'object');
  throw new Error('Missing rows under ' + keys.join(', '));
};
const pairKey = (qid, cid) => String(qid) + '|' + String(cid);
const keys = String(process.env.LLM_API_KEY || process.env.EMB_API_KEY || '').split(/[;,\r\n]+/).map(x => x.trim()).filter(Boolean);
if (!keys.length) throw new Error('Set LLM_API_KEY or EMB_API_KEY');
let keyCursor = 0;
let appendChain = Promise.resolve();
function appendJsonl(file, rows) {
  if (!rows.length) return appendChain;
  appendChain = appendChain.then(() => fs.appendFile(file, rows.map(x => JSON.stringify(x)).join('\n') + '\n', 'utf8'));
  return appendChain;
}
function parseObject(text) {
  const value = String(text || '').trim();
  try { return JSON.parse(value); } catch (_) {}
  const start = value.indexOf('{');
  const end = value.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('No JSON object in response');
  return JSON.parse(value.slice(start, end + 1));
}
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
async function callLLM(prompt) {
  const errors = [];
  const attempts = Math.max(maxRetries, Math.min(keys.length, maxRetries + 2));
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const slot = keyCursor++ % keys.length;
    const started = Date.now();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    console.log('[SharedQrels] REQUEST attempt=' + attempt + '/' + attempts + ' key_slot=' + (slot + 1) + '/' + keys.length + ' prompt_chars=' + prompt.length);
    try {
      const response = await fetch(baseUrl + '/chat/completions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + keys[slot]},
        body: JSON.stringify({model, temperature: 0, max_tokens: 5000, messages: [
          {role: 'system', content: 'You are a strict scientific retrieval relevance judge. Return one valid JSON object only.'},
          {role: 'user', content: prompt}
        ]}),
        signal: controller.signal
      });
      const body = await response.text();
      clearTimeout(timer);
      if (!response.ok) throw new Error('HTTP ' + response.status + ': ' + body.slice(0, 500));
      const content = JSON.parse(body).choices?.[0]?.message?.content || '';
      const parsed = parseObject(content);
      console.log('[SharedQrels] DONE key_slot=' + (slot + 1) + ' elapsed_s=' + ((Date.now() - started) / 1000).toFixed(2) + ' chars=' + content.length);
      return {parsed, raw: content, attempt};
    } catch (e) {
      clearTimeout(timer);
      errors.push((e?.name || 'Error') + ': ' + String(e?.message || e).slice(0, 500));
      console.log('[SharedQrels] FAILED key_slot=' + (slot + 1) + ' error=' + String(e?.message || e).slice(0, 300));
      if (attempt < attempts) await sleep(Math.min(5000, 500 * attempt));
    }
  }
  throw new Error('LLM failed after retries: ' + errors.join(' || '));
}
function makePrompt(query, candidates) {
  const q = {query_id: query.query_id, question: query.question, retrievable: Boolean(query.retrievable), gold_claim: query.gold_claim || null, reference_answer: query.reference_answer || null, required_elements: query.required_elements || null, gold_chunk_ids: query.gold_chunk_ids || [], difficulty: query.difficulty || null, support_mode: query.support_mode || null, fact_arity: query.fact_arity || null};
  const cs = candidates.map(c => ({chunk_id: c.chunk_id, source_doc_ids: c.source_doc_ids || [], source_file: c.source_file || null, retrieved_by_systems: (c.system_occurrences || []).map(x => ({system: x.system, rank: x.retrieval_rank})), content: c.content || ''}));
  return 'Judge every candidate chunk independently for the same retrieval query.\n\n' +
    'Grade 3 DIRECT if the chunk directly answers the question or contains decisive question-specific evidence.\n' +
    'Grade 2 STRONG_SUPPORT if it supplies a critical requested component but is insufficient alone.\n' +
    'Grade 1 BACKGROUND if it is relevant context without the requested evidence.\n' +
    'Grade 0 IRRELEVANT if unrelated, terminology-only, bibliography/reference-only, or unsupported.\n\n' +
    'Judge only supplied chunk text. Same paper or shared terminology is not automatically relevant. Use the reference answer only to understand the target evidence. For unretrievable queries still judge honestly. Every candidate exactly once; rationale must be specific and non-empty.\n\nQUERY:\n' + JSON.stringify(q) + '\n\nCANDIDATES:\n' + JSON.stringify(cs) + '\n\nReturn exactly JSON: {"query_id":"...","judgments":[{"chunk_id":"...","relevance_grade":0,"supported_elements":[],"conflicts":[],"rationale":"..."}]}';
}
function validate(parsed, qid, candidates) {
  if (String(parsed?.query_id || '') !== String(qid)) throw new Error('query_id mismatch');
  if (!Array.isArray(parsed?.judgments)) throw new Error('judgments must be an array');
  const expected = new Set(candidates.map(c => String(c.chunk_id)));
  const seen = new Set();
  const rows = [];
  for (const item of parsed.judgments) {
    const cid = String(item?.chunk_id || '');
    const grade = Number(item?.relevance_grade);
    const rationale = String(item?.rationale || '').trim();
    if (!expected.has(cid) || seen.has(cid)) throw new Error('unknown or duplicate chunk_id ' + cid);
    if (![0, 1, 2, 3].includes(grade)) throw new Error('invalid relevance_grade for ' + cid);
    if (!rationale) throw new Error('empty rationale for ' + cid);
    seen.add(cid);
    rows.push({query_id: String(qid), chunk_id: cid, relevance_grade: grade, relevance_label: labels[grade], supported_elements: Array.isArray(item.supported_elements) ? item.supported_elements : [], conflicts: Array.isArray(item.conflicts) ? item.conflicts : [], rationale, annotation_status: 'llm_judged_complete', annotation_method: promptVersion, model});
  }
  if (seen.size !== expected.size) throw new Error('missing judgments expected=' + expected.size + ' received=' + seen.size);
  return rows;
}
async function mapLimit(items, limit, worker) {
  let cursor = 0;
  const failures = [];
  async function loop() { while (true) { const index = cursor++; if (index >= items.length) return; try { await worker(items[index]); } catch (e) { failures.push({task: items[index], error: String(e?.stack || e)}); } } }
  await Promise.all(Array.from({length: Math.min(limit, Math.max(1, items.length))}, loop));
  return failures;
}

await fs.mkdir(outputDir, {recursive: true});
const partialPath = path.join(outputDir, 'shared_qrels_partial.jsonl');
const auditPath = path.join(outputDir, 'shared_qrels_audit.jsonl');
const errorPath = path.join(outputDir, 'shared_qrels_errors.json');
const finalPath = path.join(outputDir, 'shared_qrels.json');
const protocolPath = path.join(outputDir, 'shared_qrels_protocol.json');
const queryPayload = await readJson(queryPath);
const unionPayload = await readJson(unionPath);
const queries = getRows(queryPayload, ['queries', 'retrieval_queries']);
const candidates = getRows(unionPayload, ['candidate_union', 'candidate_evidence']);
const queryMap = new Map(queries.map(q => [String(q.query_id || q.id || ''), q]));
for (const c of candidates) { if (!queryMap.has(String(c.query_id))) throw new Error('unknown query_id ' + c.query_id); if (!c.chunk_id) throw new Error('candidate missing chunk_id'); }
const poolKeys = new Set(candidates.map(c => pairKey(c.query_id, c.chunk_id)));
if (poolKeys.size !== candidates.length) throw new Error('duplicate query_id/chunk_id pair in candidate union');
const protocol = {protocol_version: promptVersion, query_file: queryPath, query_sha256: await sha256File(queryPath), candidate_union: unionPath, candidate_union_sha256: await sha256File(unionPath), model, base_url: baseUrl, timeout_ms: timeoutMs, concurrency, batch_size: batchSize, key_pool_size: keys.length, qrel_key: ['query_id', 'chunk_id'], grade_schema: labels};
try { const old = await readJson(protocolPath); if (JSON.stringify(old) !== JSON.stringify(protocol)) throw new Error('different existing qrels protocol; use a new output directory'); } catch (e) { if (e?.code !== 'ENOENT') throw e; await writeJson(protocolPath, protocol); }
const existing = resume ? await readJsonl(partialPath) : [];
if (!resume && existing.length) throw new Error('partial qrels exists; pass --resume');
const completed = new Map();
for (const row of existing) { const key = pairKey(row.query_id, row.chunk_id); if (poolKeys.has(key) && [0,1,2,3].includes(Number(row.relevance_grade)) && String(row.rationale || '').trim()) completed.set(key, row); }
const byQuery = new Map();
for (const c of candidates) { const key = pairKey(c.query_id, c.chunk_id); if (completed.has(key)) continue; const qid = String(c.query_id); if (!byQuery.has(qid)) byQuery.set(qid, []); byQuery.get(qid).push(c); }
const tasks = [];
for (const [qid, rows] of byQuery) { rows.sort((a,b) => Number(a.best_retrieval_rank || 9999) - Number(b.best_retrieval_rank || 9999) || String(a.chunk_id).localeCompare(String(b.chunk_id))); for (let start = 0; start < rows.length; start += batchSize) tasks.push({qid, batch: rows.slice(start, start + batchSize)}); }
console.log(JSON.stringify({queries: queries.length, pooled_pairs: candidates.length, resumed_pairs: completed.size, pending_pairs: candidates.length - completed.size, batches: tasks.length, concurrency, model, key_pool_size: keys.length}, null, 2));
const failures = await mapLimit(tasks, concurrency, async task => {
  const query = queryMap.get(task.qid);
  let lastError;
  for (let validationAttempt = 1; validationAttempt <= 3; validationAttempt++) {
    try { const response = await callLLM(makePrompt(query, task.batch) + (validationAttempt > 1 ? '\nPrevious output was invalid. Return every requested chunk exactly once in valid JSON.' : '')); const rows = validate(response.parsed, task.qid, task.batch); await appendJsonl(partialPath, rows); await appendJsonl(auditPath, [{query_id: task.qid, chunk_ids: task.batch.map(c => c.chunk_id), response_attempt: response.attempt, validation_attempt: validationAttempt, raw_response: response.raw}]); for (const row of rows) completed.set(pairKey(row.query_id, row.chunk_id), row); console.log('[SharedQrels] BATCH_DONE ' + task.qid + ' rows=' + rows.length + ' completed=' + completed.size + '/' + candidates.length); return; } catch (e) { lastError = e; console.log('[SharedQrels] BATCH_INVALID ' + task.qid + ' error=' + String(e?.message || e).slice(0, 400)); }
  }
  throw lastError || new Error('batch failed');
});
await appendChain;
await writeJson(errorPath, failures.map(x => ({query_id: x.task.qid, chunk_ids: x.task.batch.map(c => c.chunk_id), error: x.error})));
const allRows = await readJsonl(partialPath);
const finalMap = new Map();
for (const row of allRows) { const key = pairKey(row.query_id, row.chunk_id); if (poolKeys.has(key) && [0,1,2,3].includes(Number(row.relevance_grade)) && String(row.rationale || '').trim()) finalMap.set(key, row); }
const missing = candidates.filter(c => !finalMap.has(pairKey(c.query_id, c.chunk_id))).map(c => ({query_id: c.query_id, chunk_id: c.chunk_id}));
const qrels = candidates.map(c => finalMap.get(pairKey(c.query_id, c.chunk_id))).filter(Boolean).sort((a,b) => String(a.query_id).localeCompare(String(b.query_id)) || String(a.chunk_id).localeCompare(String(b.chunk_id)));
const distribution = Object.fromEntries([0,1,2,3].map(g => [String(g), qrels.filter(r => Number(r.relevance_grade) === g).length]));
const metadata = {created_at: new Date().toISOString(), status: missing.length ? 'incomplete_shared_qrels' : 'complete_shared_qrels', gold_status: missing.length ? 'not_gold_incomplete' : 'llm_judged_pending_final_audit', query_file: queryPath, candidate_union: unionPath, qrel_key: ['query_id', 'chunk_id'], prompt_version: promptVersion, model, base_url: baseUrl, timeout_ms: timeoutMs, concurrency, batch_size: batchSize, key_pool_size: keys.length, grade_schema: labels, pooled_pairs: candidates.length, judged_pairs: qrels.length, unjudged_pairs: missing.length, grade_distribution: distribution};
await writeJson(finalPath, {metadata, qrels, missing_pairs: missing});
console.log(JSON.stringify({output: finalPath, status: metadata.status, pooled_pairs: candidates.length, judged_pairs: qrels.length, missing_pairs: missing.length, failed_batches: failures.length, grade_distribution: distribution}, null, 2));
if (missing.length) process.exitCode = 2;
