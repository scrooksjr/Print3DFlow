type Data=Record<string,any>;
function Swatch({color}:{color?:string}){return color?<><span className="color-swatch" style={{backgroundColor:color}} aria-hidden="true"/>{color}</>:<>Not saved</>;}
export function ModelColors({file}:{file:Data}){
 if(file.source_format!=='3mf')return null;
 const info=file.color_info;
 if(!info)return <p className="form-note">Re-upload this 3MF to inspect its saved color assignments before quoting.</p>;
 return <section className="model-colors"><b>3MF colors &amp; filament assignments</b><span className="pill">MVP: up to 4 colors</span><p>{info.multicolor_detected?'Multicolor or painted model detected.':'No confirmed multicolor assignment detected.'} Assigned slots: {info.assigned_slots.length?info.assigned_slots.join(', '):'not specified'}. {info.painted_faces_detected?'Paint encoding detected; exact color count and mappings need review.':''}</p>
 {!!info.saved_filaments.length&&<div className="color-table"><table><thead><tr><th>Saved slot</th><th>Saved color</th><th>Material</th><th>Model assignment</th></tr></thead><tbody>{info.saved_filaments.map((f:Data)=><tr key={f.slot}><td>{f.slot}</td><td><Swatch color={f.color}/></td><td>{f.material||'Not saved'}</td><td>{info.assigned_slots.includes(f.slot)?'Assigned':'Use not established'}</td></tr>)}</tbody></table></div>}
 {!!info.saved_palette.length&&<details><summary>Saved 3MF color/material properties ({info.saved_palette.length})</summary>{info.saved_palette.map((c:Data,i:number)=><p key={i}><Swatch color={c.color}/> · resource {c.resource_id}, index {c.index}{c.name?' · '+c.name:''}</p>)}</details>}
 {!!info.assignments.length&&<details><summary>Saved assignments ({info.assignments.length})</summary>{info.assignments.map((a:Data,i:number)=><p key={i}>{a.source}: {a.filament_slot?`object ${a.object_id}, part ${a.part_id} → slot ${a.filament_slot}`:`resource ${a.resource_id}, property ${a.property_index} · ${a.triangles} triangles`}</p>)}</details>}
 {info.quoting_blocked&&<div role="status" className="form-error"><b>{info.exceeds_mvp_limit?'Exceeds four-color MVP limit':'Quoting blocked pending verification'}</b><ul>{info.block_reasons.map((r:string,i:number)=><li key={i}>{r}</li>)}</ul><p>Physical filament mappings and multicolor slicer results are not verified. Manual estimates cannot bypass this block.</p></div>}
 <small>{info.note} The preview displays geometry only, not the saved paint colors.</small></section>;
}
