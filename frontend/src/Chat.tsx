import {useEffect,useRef,useState} from 'react'
import {ArrowUp,Route,ThumbsUp,ThumbsDown,Download,PanelLeftOpen} from 'lucide-react'
import {api,post,streamChat,categories,intentNames,type Skill} from './api'
import {Markdown,CopyButton,Evidence} from './components'

const workflowTags: {skill:Skill,label:string}[] = [{skill:'course_qa',label:'课程知识问答'},{skill:'learning_path',label:'学习路径推荐'},{skill:'interview_practice',label:'面试题训练'},{skill:'prd_review',label:'PRD点评'},{skill:'resume_optimize',label:'简历优化'}]
export function Chat({session,setSession,refreshSessions,onSource,onError,health,busy,setBusy,onToggleSidebar}:{session:string|null,setSession:(id:string)=>void,refreshSessions:()=>void,onSource:(id:string)=>void,onError:(e:string)=>void,health:any,busy:boolean,setBusy:(b:boolean)=>void,onToggleSidebar:()=>void}){
  const[messages,setMessages]=useState<any[]>([]),[input,setInput]=useState(''),[trace,setTrace]=useState<any>(),[feedback,setFeedback]=useState<string|null>(null),[note,setNote]=useState(''),[category,setCategory]=useState('answer_error'),[saved,setSaved]=useState<Record<string,boolean>>({}),[loading,setLoading]=useState(false)
  const[selectedSkill,setSelectedSkill]=useState<Skill|null>(null),[evidenceOpen,setEvidenceOpen]=useState(false)
  const end=useRef<HTMLDivElement>(null),field=useRef<HTMLTextAreaElement>(null)
  useEffect(()=>{if(busy)return;setSelectedSkill(null);setTrace(null);setEvidenceOpen(false);if(!session){setMessages([]);return}let live=true;setLoading(true);api(`/sessions/${session}/messages`).then(d=>{if(live)setMessages(d)}).catch(e=>onError(e.message)).finally(()=>{if(live)setLoading(false)});return()=>{live=false}},[session])
  useEffect(()=>{if(messages.length)end.current?.scrollIntoView({behavior:'auto',block:'end'});else end.current?.parentElement?.scrollTo({top:0})},[messages])
  async function submit(override?:string){
    if(!(override||input).trim()||busy)return
    const skill=selectedSkill
    const text=(override||input).trim();setBusy(true);setInput('');setEvidenceOpen(false);setTrace({status:'running',stages:[],sources:[]})
    try{
      let id=session
      if(!id){id=(await post('/sessions')).id;setSession(id!)}
      setMessages(old=>[...old,{id:'user-pending',role:'user',content:text},{id:'pending',role:'assistant',content:''}])
      await streamChat(id!,text,(event,data)=>{
        if(event==='stage')setTrace((t:any)=>({...t,stages:[...(t?.stages||[]),data]}))
        if(event==='route')setTrace((t:any)=>({...t,route:data,intent:data.intent}))
        if(event==='sources')setTrace((t:any)=>({...t,...data}))
        if(event==='delta')setMessages(old=>old.map(m=>m.id==='pending'?{...m,content:m.content+data.text}:m))
        if(event==='error')onError(data.message)
        if(event==='done'){setTrace(data.message.execution);setMessages(old=>old.map(m=>m.id==='pending'?data.message:m))}
      },skill)
      setMessages(await api(`/sessions/${id}/messages`));refreshSessions()
    }catch(e){onError((e as Error).message);if(text&&!messages.length)setInput(text)}finally{setBusy(false)}
  }
  async function vote(id:string,rating:string){try{await post('/feedback',{message_id:id,rating,category,note});setSaved(s=>({...s,[id]:true}));setFeedback(null);setNote('')}catch(e){onError((e as Error).message)}}
  return <div className={`chat-layout ${evidenceOpen&&trace?'with-evidence':''}`}><section className="chat"><header className="page-toolbar"><div><button className="mobile-only icon" aria-label="展开导航" onClick={onToggleSidebar}><PanelLeftOpen size={20}/></button><h2>学习助手</h2></div>{session&&<a className="button subtle" href={`/api/sessions/${session}/export`}><Download size={16}/>导出对话</a>}</header><div className={`chat-scroll ${!messages.length&&!loading?'chat-scroll-empty':''}`}>{!messages.length&&!loading?<div className="welcome"><h1>今天想学什么？</h1></div>:messages.map(m=><article className={`message ${m.role}`} key={m.id}><div className="message-role">{m.role==='user'?'你':'课程助手'}{m.execution&&<span>{intentNames[m.execution.intent]}</span>}</div>{m.content?<Markdown text={m.content} onSource={onSource}/>:<div className="generating"><span className="pulse"/>{trace?.stages?.at(-1)?.name||'正在连接课程助手'}…</div>}{m.role==='assistant'&&m.id!=='pending'&&<><div className="message-actions"><CopyButton text={m.content}/>{m.execution?.status==='error'&&<button className="icon-label" disabled={busy} onClick={()=>{const previous=messages.slice(0,messages.findIndex(x=>x.id===m.id)).reverse().find(x=>x.role==='user');if(previous)submit(previous.content)}}>重新提交</button>}{m.execution&&<button className="icon-label" onClick={()=>{setTrace(m.execution);setEvidenceOpen(true)}}><Route size={14}/>来源与过程 {m.execution.sources?.length?`· ${m.execution.sources.length}`:''}</button>}<button className="icon-label" disabled={saved[m.id]} onClick={()=>vote(m.id,'positive')}><ThumbsUp size={14}/>{saved[m.id]?'已记录':'有帮助'}</button><button className="icon-label" onClick={()=>setFeedback(feedback===m.id?null:m.id)}><ThumbsDown size={14}/>有问题</button></div>{feedback===m.id&&<div className="feedback-form"><label>问题类型<select value={category} onChange={e=>setCategory(e.target.value)}>{Object.entries(categories).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label>反馈原因<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="哪部分不准确？你期望怎样的回答？"/></label><button className="button primary" onClick={()=>vote(m.id,'negative')}>提交反馈</button></div>}</>}</article>)}<div ref={end}/></div><form className="composer-wrap" onSubmit={e=>{e.preventDefault();submit()}}><div className="composer"><label className="sr-only" htmlFor="chat-input">问题或待点评文本</label><textarea ref={field} id="chat-input" value={input} maxLength={20000} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();submit()}}} placeholder="你可以提问课程知识、学习路径，进行面试题训练，或者发送你的PRD、简历进行点评优化" rows={3}/><div className="composer-actions"><div className="workflow-tags" role="group" aria-label="选择回答工作流">{workflowTags.map(tag=><button key={tag.skill} type="button" aria-pressed={selectedSkill===tag.skill} disabled={busy} className={selectedSkill===tag.skill?'selected':''} onClick={()=>{setSelectedSkill(selectedSkill===tag.skill?null:tag.skill);field.current?.focus()}}>{tag.label}</button>)}</div><button className="send" type="submit" disabled={busy||!input.trim()} aria-label="发送问题"><ArrowUp size={20}/></button></div></div><p>模型可能出错，请结合课程来源判断。所有回答均实时生成。</p></form></section>{evidenceOpen&&trace&&<Evidence execution={trace} onSource={onSource} onClose={()=>setEvidenceOpen(false)}/>}</div>
}
