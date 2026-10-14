export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, {...init, headers:{'Content-Type':'application/json',...init?.headers}})
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求未完成，请检查输入与服务状态。')
  return result
}
export const post = (path: string, data: unknown = {}) => api(path,{method:'POST',body:JSON.stringify(data)})
export type Skill = 'course_qa'|'learning_path'|'interview_practice'|'prd_review'|'resume_optimize'
export async function streamChat(session: string, content: string, onEvent: (event: string, value: any) => void, skill: Skill|null = null) {
  const response = await fetch(`/api/sessions/${session}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,skill})})
  if (!response.ok) { const e=await response.json(); throw new Error(typeof e.detail==='string'?e.detail:'无法提交问题。') }
  if (!response.body) throw new Error('浏览器不支持流式响应。')
  const reader=response.body.getReader(), decoder=new TextDecoder()
  let buffer='', doneEvent=false
  while(true) {
    const {value,done}=await reader.read()
    buffer+=decoder.decode(value,{stream:!done}).replace(/\r/g,'')
    let end:number
    while((end=buffer.indexOf('\n\n'))>=0) {
      const block=buffer.slice(0,end); buffer=buffer.slice(end+2)
      const event=block.split('\n').find(x=>x.startsWith('event: '))?.slice(7)
      const data=block.split('\n').filter(x=>x.startsWith('data: ')).map(x=>x.slice(6)).join('\n')
      if(event&&data) { onEvent(event,JSON.parse(data)); if(event==='done')doneEvent=true }
    }
    if(done)break
  }
  if(!doneEvent) throw new Error('连接中断，可刷新会话查看已保存的结果。')
}
export const intentNames: Record<string,string> = {course_qa:'课程问答',learning_path:'学习路径',interview_practice:'面试训练',prd_review:'PRD 点评',resume_optimize:'简历优化',badcase_feedback:'反馈记录',unknown:'澄清'}
export const statusNames: Record<string,string> = {success:'完成',error:'失败',need_clarification:'待澄清',running:'运行中',complete:'评测完成',pending:'待分析',analyzing:'分析中',resolved:'已解决'}
export const categories:Record<string,string>={retrieval_issue:'检索不相关',source_mismatch:'来源不一致',hallucination:'编造内容',low_helpfulness:'帮助不足',answer_error:'回答错误',other:'其他'}
export const ms=(value:number|null)=>value==null?'—':`${(value/1000).toFixed(2)} 秒`
export const percent=(value:number|null)=>value==null?'—':`${(value*100).toFixed(1)}%`
export const date=(value:string)=>new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
