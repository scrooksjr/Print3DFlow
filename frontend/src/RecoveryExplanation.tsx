import {useEffect,useState} from 'react';
import {Sparkles} from 'lucide-react';
type Data=Record<string,any>;
type Props={proposal:Data;configured:boolean;busy:boolean;run:(fn:()=>Promise<any>,message?:string)=>Promise<any>;request:(path:string,body?:unknown)=>Promise<any>};
const time=(s:string)=>new Date(s).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
export function RecoveryExplanation({proposal,configured,busy,run,request}:Props){
 const [explanation,setExplanation]=useState<Data>({status:'not_requested'}),[working,setWorking]=useState(false);
 useEffect(()=>{
  let live=true;
  const refresh=()=>fetch('/api/proposals/'+proposal.id+'/explanation').then(r=>r.ok?r.json():{status:'unavailable'}).then(r=>{if(live)setExplanation(r);}).catch(()=>{if(live)setExplanation({status:'unavailable'});});
  refresh();const timer=setInterval(refresh,10000);return()=>{live=false;clearInterval(timer);};
 },[proposal.id,proposal.choice.option_id]);
 async function explain(){setWorking(true);const result=await run(()=>request('/proposals/'+proposal.id+'/explanation',{}),'Meta explanation checked against the verified recovery options. No reservation changed.');setExplanation(result||{status:'unavailable'});setWorking(false);}
 return <div className="meta-recovery"><div className="assistant-heading"><Sparkles size={16}/><b>Meta recovery adviser</b><span className="pill">APPROVAL REQUIRED</span></div><p className="form-note">Meta compares verified scheduler results. It cannot change capacity, price, or reservations. Every approval checks current capacity again.</p>
 <button className="secondary full" disabled={busy||working||!configured||explanation.status==='stale'} onClick={explain}>{working?'Reviewing verified options…':explanation.status==='ready'?'Refresh Meta explanation':'Explain recovery options with Meta'}<Sparkles size={14}/></button>
 {!configured&&<p className="form-note">Configure Meta to enable explanations. The scheduler options remain available for manual review.</p>}
 {explanation.status==='stale'&&<p className="form-error" role="alert">{explanation.detail||'This explanation is stale.'} Use Propose recovery to regenerate the plan before approval.</p>}
 {explanation.status==='unavailable'&&<p className="form-note">Meta explanation unavailable. No reservation changed; verified plans can still be reviewed manually.</p>}
 {explanation.status==='ready'&&<><p className="form-note">{explanation.model} · Meta-selected reasons rendered from verified facts · {time(explanation.created_at)}</p><p className="form-note">{explanation.recommended_option_id?'Recommendation: '+explanation.recommended_option_id+'. You choose the proposal and approve separately.':'No on-time option is recommended. Review the deadline manually.'}</p>
 {explanation.options.map((option:Data)=><div className="recovery-option" key={option.option_id}><b>{option.option_id} · {option.printer_name}{option.option_id===explanation.recommended_option_id?' · Meta recommendation':''}</b><p>{time(option.start)} → {time(option.end)}</p><ul>{option.reasons.map((reason:string,i:number)=><li key={i}>{reason}</li>)}</ul>{option.option_id===proposal.choice.option_id?<span className="status scheduled">Selected proposal · awaiting approval</span>:<button className="secondary full" disabled={busy||!option.on_time} onClick={()=>run(()=>request('/proposals/'+proposal.id+'/select-option',{option_id:option.option_id}),'Proposal selection updated. The reservation is unchanged until you approve.')}>Select this proposal</button>}</div>)}
 <small>Customer updates remain drafts. This is a versioned explanation, not a guarantee of future availability.</small></>}
 </div>;
}
