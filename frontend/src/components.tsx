import {useEffect,useRef,useState} from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {X,ChevronDown,ExternalLink,BookOpen,Copy,Check} from 'lucide-react'
import {api,intentNames,ms,statusNames} from './api'

export function Markdown({text,onSource}:{text:string,onSource?:(id:string)=>void}) {
  const transformed=text.replace(/\[(?:chunk_id\s*:\s*)?([A-Z][A-Z0-9_]+_\d+)\](?!\()/g,'[$1](#source-$1)')
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a:({href,children})=>href?.startsWith('#source-')?<button className="inline-source" onClick={()=>onSource?.(href.slice(8))}>{children}</button>:<a href={href} target="_blank" rel="noreferrer">{children}<ExternalLink size={12}/></a>}}>{transformed}</ReactMarkdown></div>
}
export function Empty({title,detail}:{title:string,detail:string}){return <div className="empty"><BookOpen size={28}/><h3>{title}</h3><p>{detail}</p></div>}
export function Loading(){return <div className="skeleton" aria-label="正在加载"><span/><span/><span/></div>}
export function Badge({value}:{value:string}){return <span className={`badge ${value}`}>{statusNames[value]||value}</span>}
export function CopyButton({text}:{text:string}){const[copied,setCopied]=useState(false);return <button className="icon-label" onClick={async()=>{await navigator.clipboard.writeText(text);setCopied(true);setTimeout(()=>setCopied(false),1500)}}>{copied?<Check size={14}/>:<Copy size={14}/>} {copied?'已复制':'复制'}</button>}
export function SourceDialog({id,onClose}:{id:string|null,onClose:()=>void}){
  const ref=useRef<HTMLDialogElement>(null),[data,setData]=useState<any>(),[error,setError]=useState('')
  useEffect(()=>{if(!id)return;setData(null);setError('');ref.current?.showModal();let valid=true;api(`/chunks/${encodeURIComponent(id)}`).then(d=>{if(valid)setData(d)}).catch(e=>{if(valid)setError(e.message)});return()=>{valid=false;ref.current?.close()}},[id])
  return <dialog ref={ref} className="source-dialog" onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose()}}><header><div><small>课程整理稿 / 切片正文</small><h2>{data?.subtopic||id}</h2></div><button aria-label="关闭课程原文" className="icon" onClick={onClose}><X size={20}/></button></header>{error?<p className="error-text">{error}</p>:data?<><p className="muted">{data.doc_name} · {data.topic}</p><code>{data.chunk_id}</code><p className="source-body">{data.chunk_text}</p><CopyButton text={data.chunk_text}/></>:<Loading/>}</dialog>
}
export function Sources({sources,onOpen,cited=[],candidateLabel='检索候选'}:{sources:any[],onOpen:(id:string)=>void,cited?:any[],candidateLabel?:string}){
  const citedIds=new Set(cited.map(x=>x.chunk_id))
  return <div className="source-list">{sources.map((s,i)=><button className="source-item" key={s.chunk_id} onClick={()=>onOpen(s.chunk_id)}><div><span className="source-number">{i+1}</span><b>{s.subtopic}</b><ChevronDown size={14}/></div><p>{s.doc_name}</p><small>{s.similarity!=null?`相似度 ${s.similarity.toFixed(3)}`:''} {citedIds.has(s.chunk_id)?' · 答案已引用':' · '+candidateLabel}</small></button>)}</div>
}
export function Evidence({execution,onSource,onClose}:{execution:any,onSource:(id:string)=>void,onClose:()=>void}){
  if(!execution)return null
  return <aside className="evidence"><header><h3>证据与执行过程</h3><button className="icon" aria-label="收起证据面板" onClick={onClose}><X size={17}/></button></header><p className="muted">证据来自当前课程知识库</p><dl><dt>业务任务</dt><dd>{intentNames[execution.intent]||'识别中'}</dd><dt>执行状态</dt><dd><Badge value={execution.status}/></dd><dt>总耗时</dt><dd>{ms(execution.duration_ms)}</dd></dl>{execution.rewritten_query&&<section><h4>检索 Query</h4><p>{execution.rewritten_query}</p></section>}{execution.route&&<details open><summary>意图识别</summary><p>{execution.route.reason}</p>{execution.route.mode==='manual'?<small>标签指定工作流，跳过语义意图识别</small>:<small>模型自评置信度 {execution.route.confidence?.toFixed(2)}，不代表真实准确率</small>}</details>}<details open><summary>执行阶段</summary><ol className="trace-list">{(execution.stages||[]).map((s:any,i:number)=><li key={i}><b>{s.name}</b><small>{s.detail} · 开始于 {ms(s.elapsed_ms)}</small></li>)}</ol></details><details open><summary>课程来源 · {execution.sources?.length||0}</summary><Sources sources={execution.sources||[]} cited={execution.cited_sources||[]} onOpen={onSource}/>{!execution.sources?.length&&<p className="muted">本次未返回课程检索结果。</p>}</details><details><summary>模型调用 · {execution.model_calls?.length||0}</summary>{(execution.model_calls||[]).map((c:any,i:number)=><p key={i}>{c.model} · {ms(c.duration_ms)}<br/><small>{c.usage?.total_tokens!=null?`${c.usage.total_tokens} tokens`:'服务未返回用量'}</small></p>)}<small>数据版本 {execution.data_version}</small></details>{execution.error_message&&<p className="error-text">{execution.error_message}</p>}</aside>
}
