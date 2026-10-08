const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { transformSync } = require('esbuild')

const source = fs.readFileSync(path.join(__dirname, '../src/services/retrieval.ts'), 'utf8').replace("import { SERVER_URL } from '@/utils'", "const SERVER_URL = '/api'")
const compiled = transformSync(source, { loader: 'ts', format: 'cjs', target: 'es2022' }).code
function client(fetch) {
  const module = { exports: {} }
  vm.runInNewContext(compiled, { module, exports: module.exports, fetch, TextDecoder, AbortSignal })
  return module.exports
}
const encode = text => new TextEncoder().encode(text)
const response = chunks => new Response(new ReadableStream({ start(controller) { chunks.forEach(chunk => controller.enqueue(chunk)); controller.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })

test('payload keeps legacy candidate count separate from final evidence top-k', () => {
  const payload = client(() => undefined).buildQueryPayload('问题', 'hyper', 'case1')
  assert.equal(payload.top_k, 60)
  assert.equal(payload.evidence_top_k, 5)
  assert.equal(payload.retrieval_profile, 'auto')
  assert.equal(payload.database, 'case1')
})

test('split UTF-8 and CRLF frames preserve one-request evidence and text', async () => {
  const wire = 'event: retrieval\r\ndata: {"entities":[{"entity_name":"条件"}],"text_units":[{"id":"chunk-1"}],"retrieval_meta":{"profile":"f1"}}\r\n\r\nevent: token\r\ndata: {"text":"中文回答"}\r\n\r\nevent: done\r\ndata: {}\r\n\r\n'
  const bytes = encode(wire)
  const chunks = Array.from(bytes, byte => Uint8Array.of(byte))
  let requests = 0
  let evidence
  let text
  const api = client(async () => { requests++; return response(chunks) })
  const result = await api.queryStream(api.buildQueryPayload('q', 'hyper'), { onRetrieval: value => { evidence = value }, onToken: value => { text = value } }, true)
  assert.equal(requests, 1)
  assert.equal(evidence.text_units[0].id, 'chunk-1')
  assert.equal(text, '中文回答')
  assert.equal(result.response, '中文回答')
})

test('partial stream error never retries or discards callbacks', async () => {
  let requests = 0
  let received = ''
  const api = client(async () => { requests++; return response([encode('event: token\ndata: {"text":"partial"}\n\nevent: error\ndata: {"message":"channel failure"}\n\n')]) })
  await assert.rejects(api.queryStream(api.buildQueryPayload('q', 'hyper'), { onRetrieval() {}, onToken: value => { received = value } }), /channel failure/)
  assert.equal(requests, 1)
  assert.equal(received, 'partial')
})

test('missing done event is reported instead of marking incomplete answer complete', async () => {
  const api = client(async () => response([encode('event: token\ndata: {"text":"incomplete"}\n\n')]))
  await assert.rejects(api.queryStream(api.buildQueryPayload('q', 'hyper'), { onRetrieval() {}, onToken() {} }), /连接提前结束/)
})

test('cancellation passes one AbortSignal and does not retry', async () => {
  let requests = 0
  const abort = new AbortController()
  const api = client(async (_url, options) => {
    requests++
    assert.equal(options.signal, abort.signal)
    return new Response(new ReadableStream({ start(controller) { options.signal.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError'))) } }))
  })
  const pending = api.queryStream(api.buildQueryPayload('q', 'hyper'), { onRetrieval() {}, onToken() {} }, false, abort.signal)
  await new Promise(resolve => setImmediate(resolve))
  abort.abort()
  await assert.rejects(pending, error => error.name === 'AbortError')
  assert.equal(requests, 1)
})
