import {useEffect,useState} from 'react';
type Data=Record<string,any>;
type Props={job:Data;configured:boolean;busy:boolean;run:(fn:()=>Promise<any>,message?:string)=>Promise<any>;request:(path:string,body?:unknown)=>Promise<any>};
export function ProductionPlanner({job,configured,busy,run,request}:Props){
 const [plan,setPlan]=useState<Data>({status:'not_requested'}),[consent,setConsent]=useState(false),[working,setWorking]=useState(false);
 async function refresh(){const r=await fetch('/api/jobs/'+job.id+'/planner');if(r.ok)setPlan(await r.json());}
 useEffect(()=>{refresh();const timer=setInterval(refresh,10000);return()=>clearInterval(timer);},[job.id,job.version,job.latest_quote_id,job.status]);
 async function start(){setWorking(true);const r=await run(()=>request('/jobs/'+job.id+'/planner',{consent_to_send_planning_facts:true}),'Meta planning complete. Prices and reservations unchanged.');if(r)setPlan(r);setWorking(false);}
 return <section className="meta-recovery"><h3>Meta-assisted production planner</h3><span className="pill">ADVICE ONLY</span><p>Meta requests read-only checks, then recommends a next step using verified evidence. Create fresh comparisons below when needed. This planner cannot create quotes, change prices, or reserve capacity.</p>
 <label><input type="checkbox" checked={consent} disabled={working} onChange={e=>setConsent(e.target.checked)}/> Allow Meta to receive requirement blocker codes and verified slice/schedule facts. Customer text, model files, printer names, prices and rate cards stay local.</label>
 <button className="secondary full" disabled={busy||working||!configured||!consent} onClick={start}>{working?'Meta is checking verified tool results...':'Plan with Meta'}</button>{!configured&&<p>Configure the local Meta API key to use the planner.</p>}
 {plan.status==='ready'&&<><p>{plan.model} · Meta Model API tool calls · Checked {new Date(plan.created_at).toLocaleString()}</p><p>No price or reservation changes were made. Use the separate exact-price and reservation approval controls in the comparison workflow.</p>
 {plan.stale?<p role="alert">This plan is stale. Run the planner again before relying on its recommendation.</p>:plan.recommendation&&<div className="recovery-option"><b>{plan.recommendation.next_step}</b>{plan.recommendation.recommended_option_id&&<p>Recommended comparison option: {plan.recommendation.recommended_option_id} · comparison {plan.comparison_id?.slice(0,8)}</p>}<ul>{plan.recommendation.reasons.map((r:string,i:number)=><li key={i}>{r}</li>)}</ul></div>}
 <h4>Verified tool trail</h4>{plan.trail?.map((t:Data)=><details key={t.sequence} open><summary>{t.sequence}. Meta requested {t.tool} — {plan.stale?'historical result':'verified result'}</summary><p>Read-only call; no production changes.</p><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:11}}>{JSON.stringify(t.result,null,2)}</pre></details>)}
 </>}
 </section>;
}
