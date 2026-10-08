"""Run a read-only, full-corpus HyperRAG retrieval benchmark on hyper_base.

The runner never instantiates HyperRAG (whose constructor refreshes run_config),
never calls storage callbacks, and never filters candidates by source_doc_id.
"""
from __future__ import annotations
import argparse, asyncio, json, os, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT=Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path: sys.path.insert(0,str(REPO_ROOT))
from hyperrag.base import QueryParam
from hyperrag.storage import JsonKVStorage, NanoVectorDBStorage, HypergraphStorage
from hyperrag.operate import (_get_query_keywords_prompt, _parse_query_keywords,
    _build_entity_query_context, _build_relation_query_context)
from scripts.build_experiment_cache import split_key_pool, build_embedding_func, build_llm_func

def load_json(p:Path)->Any: return json.loads(p.read_text(encoding='utf-8'))
def write_json(p:Path,v:Any)->None: p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def env_required(name:str)->str:
 v=os.getenv(name,'').strip()
 if not v: raise RuntimeError(f'{name} is required')
 return v

def storage_components(cache:Path, embedding_func):
 cfg={'working_dir':str(cache),'embedding_batch_num':int(os.getenv('EMB_BATCH_NUM','16')),
      'cosine_better_than_threshold':float(os.getenv('COSINE_THRESHOLD','0.2'))}
 text=JsonKVStorage(namespace='text_chunks',global_config=cfg)
 graph=HypergraphStorage(namespace='chunk_entity_relation',global_config=cfg)
 ent=NanoVectorDBStorage(namespace='entities',global_config=cfg,embedding_func=embedding_func,
   meta_fields={'entity_name','canonical_id','canonical_name','raw_name','entity_type','semantic_group','index_view','content'})
 rel=NanoVectorDBStorage(namespace='relationships',global_config=cfg,embedding_func=embedding_func,
   meta_fields={'id_set','relation_type','source_doc_id','source_chunk_id','index_view','content'})
 chunk=NanoVectorDBStorage(namespace='chunks',global_config=cfg,embedding_func=embedding_func)
 return cfg,text,graph,ent,rel,chunk

def content_lookup(chunks:dict[str,Any]):
 exact=defaultdict(list); normalized=defaultdict(list)
 for cid,dp in chunks.items():
  content=str(dp.get('content') or '')
  exact[content].append(cid); normalized[' '.join(content.split())].append(cid)
 return exact,normalized

def map_context_units(context:dict[str,Any]|None, exact, normalized):
 out=[]
 if not context: return out
 for unit in context.get('text_units') or []:
  content=str(unit.get('content') or '')
  ids=exact.get(content) or normalized.get(' '.join(content.split())) or []
  for cid in ids: out.append(cid)
 return out

async def main_async(a):
 keys_emb=split_key_pool(env_required('EMB_API_KEY')); keys_llm=split_key_pool(os.getenv('LLM_API_KEY') or env_required('EMB_API_KEY'))
 emb_model=os.getenv('EMB_MODEL','Qwen/Qwen3-Embedding-4B'); emb_base=os.getenv('EMB_BASE_URL','https://api.siliconflow.cn/v1')
 llm_model=os.getenv('LLM_MODEL','deepseek-ai/DeepSeek-V4-Flash'); llm_base=os.getenv('LLM_BASE_URL','https://api.siliconflow.cn/v1')
 timeout=float(os.getenv('API_TIMEOUT_SECONDS','3600'))
 emb=build_embedding_func(model=emb_model,base_url=emb_base,api_keys=keys_emb,dim=int(os.getenv('EMB_DIM','2560')),timeout=timeout)
 llm_raw=build_llm_func(model=llm_model,base_url=llm_base,api_keys=keys_llm,timeout=timeout)
 cfg,text_db,graph,entities_vdb,relationships_vdb,chunks_vdb=storage_components(a.cache_dir,emb)
 chunks=text_db._data; exact,norm=content_lookup(chunks)
 query_obj=load_json(a.queries); all_queries=query_obj.get('queries') or query_obj
 positives=[q for q in all_queries if q.get('retrievable')]; negatives=[q for q in all_queries if not q.get('retrievable')]
 if a.limit: positives=positives[:a.limit]
 a.output_dir.mkdir(parents=True,exist_ok=True)
 sem=asyncio.Semaphore(a.query_concurrency); llm_sem=asyncio.Semaphore(a.llm_concurrency)
 query_param=QueryParam(top_k=a.graph_top_k,max_token_for_text_unit=a.context_token_budget,
   max_token_for_entity_context=a.entity_token_budget,max_token_for_relation_context=a.relation_token_budget,
   only_need_context=True,return_type='json')
 global_cfg={'domain':a.domain,'prompt_profile':'default','llm_model_func':llm_raw}
 started=time.perf_counter(); result_rows=[]; dense_rows=[]
 async def extract_keywords(question:str):
  prompt=_get_query_keywords_prompt(question,global_cfg); last=None
  for attempt in range(1,4):
   try:
    async with llm_sem: raw=await llm_raw(prompt,skip_cache=True)
    low,high=_parse_query_keywords(raw,prompt,need_relation_keywords=True)
    if low or high: return low,high,raw,attempt
    last=RuntimeError('empty keyword extraction')
   except Exception as exc: last=exc
  raise RuntimeError(f'keyword extraction failed after 3 parse attempts: {last}')
 async def run_hyper(q):
  qid=str(q['query_id']); question=str(q['question']); t0=time.perf_counter()
  print(f'[Retrieval] START {qid}',flush=True)
  async with sem:
   low,high,raw,attempt=await extract_keywords(question)
   tasks=[]; labels=[]
   if low: labels.append('entity'); tasks.append(_build_entity_query_context(low,graph,entities_vdb,text_db,query_param))
   if high: labels.append('relation'); tasks.append(_build_relation_query_context(high,graph,entities_vdb,relationships_vdb,text_db,query_param))
   vals=await asyncio.gather(*tasks,return_exceptions=True)
   contexts={}; errors=[]
   for label,val in zip(labels,vals):
    if isinstance(val,Exception): errors.append(f'{label}:{type(val).__name__}:{val}')
    else: contexts[label]=val
   ranked=[]; seen=set(); channels=defaultdict(list)
   for label in ('relation','entity'):
    for cid in map_context_units(contexts.get(label),exact,norm):
     channels[cid].append(label)
     if cid not in seen: seen.add(cid); ranked.append(cid)
   candidates=[]
   for rank,cid in enumerate(ranked[:a.output_top_k],1):
    dp=chunks[cid]
    candidates.append({'query_id':qid,'candidate_group':'hyper_base','candidate_id':f'hyper_base:{cid}',
      'retrieval_rank':rank,'chunk_id':cid,'source_doc_ids':[dp.get('source_doc_id') or dp.get('doc_id')],
      'source_file':dp.get('source_file'),'content':dp.get('content'),'retrieval_channels':channels[cid]})
   elapsed=time.perf_counter()-t0; print(f'[Retrieval] DONE {qid} chunks={len(candidates)} elapsed={elapsed:.2f}s',flush=True)
   return {'query_id':qid,'question':question,'entity_keywords':low,'relation_keywords':high,
     'keyword_attempts':attempt,'raw_keyword_response':raw,'candidate_count':len(candidates),
     'candidates':candidates,'channel_errors':errors,'elapsed_seconds':round(elapsed,3)}
 async def run_dense(q):
  qid=str(q['query_id'])
  async with sem:
   rows=await chunks_vdb.query(str(q['question']),top_k=a.dense_top_k)
  out=[]
  for rank,row in enumerate(rows,1):
   cid=str(row.get('id') or row.get('__id__')); dp=chunks.get(cid,{})
   out.append({'query_id':qid,'candidate_group':'hyper_base_chunk_dense','candidate_id':f'hyper_base_chunk_dense:{cid}',
    'retrieval_rank':rank,'retrieval_score':row.get('distance'),'chunk_id':cid,
    'source_doc_ids':[dp.get('source_doc_id') or dp.get('doc_id')],'source_file':dp.get('source_file'),'content':dp.get('content')})
  return {'query_id':qid,'retrievable':bool(q.get('retrievable')),'candidates':out}
 hyper_results=await asyncio.gather(*[run_hyper(q) for q in positives],return_exceptions=True)
 dense_results=await asyncio.gather(*[run_dense(q) for q in positives+negatives],return_exceptions=True)
 failures=[]
 for q,res in zip(positives,hyper_results):
  if isinstance(res,Exception): failures.append({'query_id':q['query_id'],'stage':'hyper','error':f'{type(res).__name__}: {res}'})
  else: result_rows.append(res)
 for q,res in zip(positives+negatives,dense_results):
  if isinstance(res,Exception): failures.append({'query_id':q['query_id'],'stage':'dense','error':f'{type(res).__name__}: {res}'})
  else: dense_rows.append(res)
 candidates=[c for r in result_rows for c in r['candidates']]
 dense_candidates=[c for r in dense_rows for c in r['candidates']]
 meta={'created_at':datetime.now(timezone.utc).isoformat(),'method':'hyper_base_full_corpus_relation_then_entity_context_order',
  'cache_dir':str(a.cache_dir.resolve()),'cache_read_only':True,'source_doc_filter_used':False,
  'query_count_requested':len(positives),'query_count_completed':len(result_rows),'failure_count':len(failures),
  'graph_top_k':a.graph_top_k,'output_top_k':a.output_top_k,'dense_top_k':a.dense_top_k,
  'query_concurrency':a.query_concurrency,'llm_concurrency':a.llm_concurrency,'embedding_pool_size':len(keys_emb),
  'llm_pool_size':len(keys_llm),'embedding_model':emb_model,'llm_model':llm_model,'domain':a.domain,
  'timeout_seconds':timeout,'elapsed_seconds':round(time.perf_counter()-started,3)}
 write_json(a.output_dir/'retrieval_results.json',{'metadata':meta,'results':result_rows,'failures':failures})
 write_json(a.output_dir/'candidate_evidence.json',{'metadata':meta,'candidate_evidence':candidates})
 write_json(a.output_dir/'dense_semantic_validation.json',{'metadata':meta,'results':dense_rows,'candidate_evidence':dense_candidates})
 write_json(a.output_dir/'run_summary.json',meta|{'failures':failures})
 print(json.dumps(meta,ensure_ascii=False,indent=2),flush=True)
 if failures: print(json.dumps(failures,ensure_ascii=False,indent=2),flush=True)

def main():
 p=argparse.ArgumentParser(); p.add_argument('--queries',required=True,type=Path); p.add_argument('--cache-dir',required=True,type=Path); p.add_argument('--output-dir',required=True,type=Path)
 p.add_argument('--domain',default='default'); p.add_argument('--graph-top-k',type=int,default=60); p.add_argument('--output-top-k',type=int,default=20); p.add_argument('--dense-top-k',type=int,default=20)
 p.add_argument('--context-token-budget',type=int,default=100000); p.add_argument('--entity-token-budget',type=int,default=10000); p.add_argument('--relation-token-budget',type=int,default=10000)
 p.add_argument('--query-concurrency',type=int,default=10); p.add_argument('--llm-concurrency',type=int,default=10); p.add_argument('--limit',type=int)
 a=p.parse_args(); asyncio.run(main_async(a))
if __name__=='__main__': main()
