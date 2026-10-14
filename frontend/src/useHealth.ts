import {useCallback,useEffect,useRef,useState} from 'react'
import {api} from './api'

// Connection state is separate from errors raised by an individual user operation.
// Serial polling avoids overlapping checks; transient errors clear on recovery.
export function useHealth(){
  const[health,setHealth]=useState<any>(),[connectionError,setConnectionError]=useState('')
  const failures=useRef(0),generation=useRef(0),inFlight=useRef<Promise<void>|null>(null),controller=useRef<AbortController|null>(null)
  const refreshHealth=useCallback(()=>{
    if(inFlight.current)return inFlight.current
    const token=++generation.current,abort=new AbortController()
    controller.current=abort
    const timeout=setTimeout(()=>abort.abort(),8000)
    const work=(async()=>{
      try{
        const data=await api('/health',{signal:abort.signal})
        if(token!==generation.current)return
        failures.current=0
        setHealth(data)
        setConnectionError('')
      }catch{
        if(token!==generation.current)return
        failures.current+=1
        if(failures.current>=2)setConnectionError('本地服务暂时未响应，正在自动重连。请检查启动窗口或服务日志。')
      }finally{
        clearTimeout(timeout)
        if(token===generation.current)inFlight.current=null
      }
    })()
    inFlight.current=work
    return work
  },[])
  useEffect(()=>{
    let stopped=false,timer:ReturnType<typeof setTimeout>
    const poll=async()=>{await refreshHealth();if(!stopped)timer=setTimeout(poll,5000)}
    poll()
    return()=>{stopped=true;clearTimeout(timer);generation.current+=1;controller.current?.abort();inFlight.current=null}
  },[refreshHealth])
  return {health,connectionError,refreshHealth,dismissConnectionError:()=>setConnectionError('')}
}
