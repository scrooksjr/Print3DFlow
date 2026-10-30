import {useEffect,useState} from 'react';
type Data=Record<string,any>;
type Props={printerId:string;onBedReview?:()=>void;sessionId?:string;busy:boolean;run:(fn:()=>Promise<any>,message?:string)=>Promise<any>;request:(path:string,body?:unknown)=>Promise<any>};
const names:Data={appears_empty:'Appears empty',occupied:'Object or print detected',uncertain:'Uncertain - inspect manually'};
export function BedCheck({printerId,sessionId,busy,run,request,onBedReview}:Props){
 const [capture,setCapture]=useState<Data|null>(null),[assessment,setAssessment]=useState<Data|null>(null),[consent,setConsent]=useState(false),[reviewed,setReviewed]=useState(false),[now,setNow]=useState(Date.now());
 useEffect(()=>{let active=true;const load=()=>fetch('/api/printers/'+printerId+'/bed-check').then(r=>r.ok?r.json():null).then(x=>{if(active&&x)setAssessment(x);}).catch(()=>{});load();const t=setInterval(load,5000),clock=setInterval(()=>setNow(Date.now()),1000);return()=>{active=false;clearInterval(t);clearInterval(clock);};},[printerId]);
 const freshCapture=!!capture&&Date.parse(capture.expires_at)>now;
 const freshAssessment=!!assessment?.id&&!assessment.stale&&Date.parse(assessment.expires_at)>now;
 const imageId=freshCapture?capture?.id:freshAssessment?assessment?.capture_id:null;
 async function take(){if(!sessionId)return;const r=await run(()=>request('/printers/'+printerId+'/bed-check/capture',{session_id:sessionId,confirmed:true}),'Fresh bed image captured locally. Nothing sent to Meta.');if(r){setCapture(r);setAssessment(null);setConsent(false);setReviewed(false);setNow(Date.now());onBedReview?.();}}
 async function assess(){if(!capture)return;const r=await run(()=>request('/printers/'+printerId+'/bed-check/assess',{capture_id:capture.id,consent_to_send_image:true}),'Meta bed assessment ready for physical review. No price or reservation changes.');setConsent(false);if(r){setAssessment(r);setReviewed(false);onBedReview?.();}}
 return <section><h4>Check bed with Meta</h4><p>A current image can help review printer choices. It does not establish cleanliness, correct plate installation or future availability. Check again near the actual start time.</p>
 <button className="secondary" disabled={busy||!sessionId} onClick={take}>Capture fresh bed image locally</button>{!sessionId&&<p>Start camera viewing above before capturing.</p>}
 {imageId&&<img alt="Bed-check evidence image" src={'/api/printers/'+printerId+'/bed-check/'+imageId+'/image'} style={{width:'100%',maxHeight:320,objectFit:'contain'}}/>}
 {capture&&<p>Captured {new Date(capture.captured_at).toLocaleTimeString()} · {freshCapture?'Available for review':'Expired - capture again'}. Image retained in memory for up to 60 seconds.</p>}
 <label><input type="checkbox" disabled={busy||!freshCapture} checked={consent} onChange={e=>setConsent(e.target.checked)}/> Allow sending this single bed image to the selected Meta provider (Baseten or Meta API). It may show the print and printer interior. Customer text, prices, credentials and stream URLs are excluded. Provider data policies apply.</label>
 <button className="secondary" disabled={busy||!freshCapture||!consent} onClick={assess}>Check bed with Meta</button>
 {assessment?.id&&<><p role="status"><b>{names[assessment.state]}</b> · {freshAssessment?'Current visual advice':'Stale visual advice - do not rely on it'}</p><p>{assessment.model} via {assessment.provider} · Image captured {new Date(assessment.captured_at).toLocaleTimeString()}</p><ul>{assessment.reasons?.map((r:string)=><li key={r}>{r}</li>)}</ul>
 <label><input type="checkbox" disabled={busy||!freshAssessment} checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> I physically inspected the bed and it is empty now. If an object was detected, I cleared it; if uncertain, I inspected directly. This is my observation, not Meta approval.</label>
 <button className="secondary" disabled={busy||!freshAssessment||!reviewed} onClick={()=>run(()=>request('/printers/'+printerId+'/bed-check/confirm',{assessment_id:assessment.id,physically_inspected_empty:true,confirmed:true}),'Physical bed inspection recorded. Price, reservation and printer execution unchanged.').then(r=>{if(r){setAssessment(r);setReviewed(false);onBedReview?.();}})}>Record physical bed inspection</button>
 {assessment.operator_confirmation_current&&freshAssessment&&<p>Physical inspection recorded separately from the model assessment.</p>}</>}
 <small>Future reservations still require capacity checks and your approval. No automatic printer selection, reservation, price change or print start.</small></section>;
}
