import {PrinterView} from './PrinterView';
import {useEffect,useState} from 'react';
type Data=Record<string,any>;
type Props={job:Data;onOpenPrinters?:()=>void;busy:boolean;run:(fn:()=>Promise<any>,message?:string)=>Promise<any>;request:(path:string,body?:unknown)=>Promise<any>};
const checks=[['artifact_reviewed','I reviewed the sliced artifact for the reserved printer.'],['filament_loaded','The required filament and slot/tool mappings are loaded correctly.'],['sufficient_material','There is sufficient filament, including purge and tower material.'],['plate_clear','The build plate is clear, fitted and ready.'],['printer_ready','I checked the printer locally: no faults and no other print running.']];
export function ExecutionReadiness({job,busy,run,request,onOpenPrinters}:Props){
 const [state,setState]=useState<Data|null>(null),[error,setError]=useState(''),[checked,setChecked]=useState<Record<string,boolean>>({});
 useEffect(()=>{let active=true; const load=()=>fetch('/api/jobs/'+job.id+'/execution').then(async r=>{if(!r.ok)throw Error('Could not load execution readiness');return r.json();}).then(x=>{if(active){setState(x);setError('');}}).catch(e=>{if(active){setState(null);setError(e.message);}});load();const timer=setInterval(load,30000);return()=>{active=false;clearInterval(timer);};},[job.id,job.version,job.latest_quote_id]);
 useEffect(()=>setChecked({}),[state?.snapshot]);
 if(!job.reservation_id)return null;
 return <section className="meta-recovery"><h3>Execution readiness</h3>{state?.printer_name&&<p><b>Reserved printer: {state.printer_name}</b>. These readiness checks apply to that reservation.</p>}{state?.connection?.status==="not_configured"&&onOpenPrinters&&<button className="secondary" onClick={onOpenPrinters}>Open printer schedule / X2D camera</button>}<p>Printer connection: <b>{state?.connection?.status||"Loading"}</b>. {state?.connection?.connected?"Fresh read-only status received; this is a sampled check, not continuous monitoring.":"No verified current telemetry."} Filament quantity and bed clearance require your inspection. Physical print commands are disabled.</p>{error&&<p role="alert">{error}</p>}{state&&<>
 {state.printer_id&&<PrinterView printerId={state.printer_id} printerName={state.printer_name} busy={busy} run={run} request={request}/>}
 {state.printer_id&&<button className="secondary full" disabled={busy||state.connection?.status==="not_configured"} onClick={()=>run(()=>request('/printers/'+state.printer_id+'/connection/check',{confirmed:true}),'Read-only printer check finished. No commands sent.').then(r=>{if(r)request('/jobs/'+job.id+'/execution').then(setState);})}>Check read-only printer connection</button>}
 {state.connection?.telemetry&&<p>Reported state: {state.connection.telemetry.state} · Progress: {state.connection.telemetry.progress_percent??'Unknown'}% · Error status: {state.connection.telemetry.error_known?(state.connection.telemetry.error_present?'Reported error':'No print error reported'):'Unknown'}. Physical checks remain required.</p>}
 <label>Execution policy for this printer<select value={state.policy?.mode||'manual'} disabled={busy||!state.printer_id} onChange={e=>{const mode=e.target.value;run(()=>request('/printers/'+state.printer_id+'/execution-policy',{mode,confirmed:true}),'Execution policy saved. No printer commands sent.').then(r=>{if(r)request('/jobs/'+job.id+'/execution').then(setState);});}}><option value="manual">Manual  -  operator runs the printer</option><option value="assisted">Assisted  -  readiness checklist, manual start</option><option value="automatic" disabled>Automatic  -  requires verified connector</option></select></label>
 <p>Changing this policy does not approve a price, reservation, or printer start.</p>
 {state.blockers.length>0?<><b>Resolve before readiness review</b><ul>{state.blockers.map((b:string)=><li key={b}>{b}</li>)}</ul></>:<>
 <p>These confirmations record your observations, not device telemetry. They expire after 10 minutes or when planning evidence changes.</p>
 {checks.map(([key,text])=><label key={key}><input type="checkbox" checked={!!checked[key]} disabled={busy} onChange={e=>setChecked({...checked,[key]:e.target.checked})}/>{text}</label>)}
 <button className="secondary full" disabled={busy||!checks.every(([key])=>checked[key])} onClick={()=>run(()=>request('/jobs/'+job.id+'/execution-review',{snapshot:state.snapshot,confirmed:true,...Object.fromEntries(checks.map(([key])=>[key,true]))}),'Readiness recorded. Start manually at the printer; no commands were sent.').then(r=>{if(r){setState(r);setChecked({});}})}>Record physical readiness review  -  no remote start</button>
 </>}
 <p role="status">{state.review_current?'Current operator review recorded.':state.last_review?'Previous review is stale or expired.':'No current operator review.'} {state.next_step}</p>
 <small>Exact-price approval and reservation approval remain separate. Automatic execution is unavailable.</small>
 </>}</section>;
}
