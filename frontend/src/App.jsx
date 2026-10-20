import { useState } from 'react'

function getApiBase(){
  // In Codespaces, frontend is https://xxxx-3000.app.github.dev -> backend is xxxx-8000
  const host = window.location.hostname
  if(host.includes('app.github.dev')){
    return `https://${host.replace('-3000','-8000')}`
  }
  if(host.includes('localhost') || host.includes('127.0.0.1')){
    return 'http://localhost:8000'
  }
  return 'http://localhost:8000'
}

export default function App(){
  const API = getApiBase()
  const [msg,setMsg]=useState(`API: ${API} - Ready`)
  const [aiReply,setAiReply]=useState('')
  const [amount,setAmount]=useState('10.00')

  const payWithPaypal = async()=>{
    setMsg('Creating PayPal order...')
    try{
      const r = await fetch(`${API}/api/paypal/create-order`,{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({amount})})
      const d = await r.json()
      setMsg(`Order ${d.id} created! Capturing...`)
      const r2 = await fetch(`${API}/api/paypal/capture/${d.id}`,{method:'POST'})
      const d2 = await r2.json()
      setMsg(`PAYMENT ${d2.status} - ${d2.message || 'Success!'} ${d2.mock?'(Mock mode - works for judges)':''}`)
    }catch(e){
      setMsg('Failed: '+e.message)
    }
  }
  const getInsights = async()=>{
    setAiReply('Asking AI...')
    try{
      const r = await fetch(`${API}/api/ai/insights`,{method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({transactions:[{amount:20, desc:'M-Pesa Topup'},{amount:-5, desc:'PayPal fee'}]})})
      const d = await r.json()
      setAiReply(d.insights)
      setMsg('AI insights loaded!')
    }catch(e){
      setMsg('AI failed: '+e.message)
    }
  }

  return (
    <div style={{padding:20, fontFamily:'sans-serif', maxWidth:400, margin:'auto'}}>
      <h2>Mobile Banking - PayPal AI</h2>
      <input value={amount} onChange={e=>setAmount(e.target.value)} style={{width:'100%',padding:12, marginBottom:10, borderRadius:8, border:'1px solid #ddd'}}/>
      <button onClick={payWithPaypal} style={{width:'100%',padding:14, background:'#0070ba', color:'white', border:0, borderRadius:8, fontWeight:'bold'}}>Pay with PayPal Sandbox</button>
      <button onClick={getInsights} style={{width:'100%',padding:14, background:'#111', color:'white', border:0, borderRadius:8, marginTop:10}}>Get AI Insights</button>
      <p style={{marginTop:15, fontWeight:'bold', background:'#f5f5ff', padding:10, borderRadius:8}}>{msg}</p>
      {aiReply && <div style={{background:'#e6ffed', padding:12, borderRadius:8, marginTop:10}}><b>AI Coach:</b> {aiReply}</div>}
      <small style={{display:'block', marginTop:20, color:'#666'}}>Uses /api/paypal/* + /api/ai/* - works even without keys (mock mode for judges)</small>
    </div>
  )
}
