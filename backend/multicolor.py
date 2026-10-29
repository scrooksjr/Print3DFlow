"""X2D four-PLA project slicing. Candidate prices never select themselves."""
import copy
import hashlib
import io
import json
import math
import os
import subprocess
import threading
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import File, Form, UploadFile, HTTPException
from pydantic import BaseModel
from typing import Literal
from starlette.concurrency import run_in_threadpool

from backend import integrations

SLOTS = [1, 2, 3, 4]
_lock = threading.BoundedSemaphore(1)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(content, target):
    """Keep validated model resources/settings, never embedded sliced instructions."""
    with ZipFile(io.BytesIO(content)) as source:
        raw = source.read('Metadata/project_settings.config')
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError('Project settings exceed limits')
        settings = json.loads(raw)
        if (settings.get('printer_model') != 'Bambu Lab X2D'
                or settings.get('nozzle_diameter') != ['0.4', '0.4']
                or settings.get('filament_type') != ['PLA'] * 4
                or settings.get('post_process')):
            raise ValueError('Use a full X2D project with two 0.4 mm nozzles, four PLA slots and no post-processing scripts')
        config = source.read('Metadata/model_settings.config')
        if len(config)>4*1024*1024:
            raise ValueError('Model settings exceed limits')
        if b'<!DOCTYPE' in config.upper() or b'<!ENTITY' in config.upper():
            raise ValueError('Unsupported XML declarations')
        root = ET.fromstring(config)
        if len(root.findall('object')) != 1 or len(root.findall('plate')) != 1:
            raise ValueError('Only one keychain assembly and one plate are supported')
        if any(p.get('subtype','normal_part') != 'normal_part' for p in root.findall('.//part')):
            raise ValueError('Modifiers are not supported')
        if any(x.get('key') == 'post_process' and x.get('value') for x in root.findall('.//metadata')):
            raise ValueError('Post-processing scripts are not permitted')
        if settings.get('enable_prime_tower') not in ('1', True, 1):
            raise ValueError('Enable the prime tower in the reviewed reference project')
        with ZipFile(target, 'w', compression=ZIP_DEFLATED) as out:
            for name in source.namelist():
                if name in ('[Content_Types].xml','_rels/.rels','Metadata/project_settings.config','Metadata/model_settings.config') or (name.startswith('3D/') and name.endswith(('.model','.rels'))):
                    out.writestr(name, source.read(name))
    return settings


def parse_result(report, archive, expected_colors, expected_triangles):
    if report.get('return_code') != 0 or len(report.get('sliced_plates',[])) != 1:
        raise ValueError('Native slicing did not return exactly one successful plate')
    p = report['sliced_plates'][0]
    if p.get('warning_message') or len(p.get('objects',[])) != 1 or p.get('triangle_count') != expected_triangles:
        raise ValueError('Native geometry or warning review failed')
    rows = p['filaments']
    if sorted(r['id'] for r in rows) != SLOTS:
        raise ValueError('Native slice must use all four assigned slots, with no extra filaments')
    result = []
    for r in sorted(rows, key=lambda r:r['id']):
        total, main = float(r['total_used_g']), float(r['main_used_g'])
        if not all(math.isfinite(v) for v in (total,main)) or not 0 < main <= total <= 10000:
            raise ValueError('Invalid per-slot material accounting')
        result.append(dict(slot=r['id'], total_grams=total, main_grams=main, purge_and_tower_grams=total-main))
    seconds = float(p['total_predication'])
    changes = p['filament_change_times']
    if not math.isfinite(seconds) or not 0 < seconds <= 864000 or type(changes) is not int or not 1 <= changes <= 10000:
        raise ValueError('Invalid total time or filament-change count')
    with ZipFile(archive) as z:
        raw = z.read('Metadata/slice_info.config')
        if len(raw) > 2*1024*1024 or b'<!' in raw:
            raise ValueError('Invalid native slice metadata')
        plate = ET.fromstring(raw).find('plate')
        fields = {x.get('key'):x.get('value') for x in plate.findall('metadata')}
        if fields.get('support_used') != 'false' or fields.get('outside') != 'false':
            raise ValueError('Support or out-of-bed geometry requires separate review')
        maps = [int(x) for x in fields['filament_maps'].split()]
        if len(maps) != 4 or any(v not in (1,2) for v in maps):
            raise ValueError('Native nozzle/tool mapping could not be verified')
        filaments = plate.findall('filament')
        if sorted(int(f.get('id')) for f in filaments) != SLOTS:
            raise ValueError('Native filament metadata mismatch')
        for f in filaments:
            slot = int(f.get('id')); row = result[slot-1]
            actual = f.get('color','').upper().removesuffix('FF') if len(f.get('color',''))==9 else f.get('color','').upper()
            expected = expected_colors[slot-1][:7].upper()
            if f.get('type') != 'PLA' or actual != expected or not math.isfinite(float(f.get('used_g'))) or abs(float(f.get('used_g'))-row['total_grams']) > .03:
                raise ValueError('Native colors, polymer or material totals do not match reviewed slots')
            load, unload = float(f.get('total_load_time')), float(f.get('total_unload_time'))
            if not all(math.isfinite(v) and 0 <= v <= seconds for v in (load,unload)):
                raise ValueError('Native load/unload timing is unavailable')
            row.update(color=expected, tool=maps[slot-1], load_seconds=load, unload_seconds=unload)
        grams = sum(r['total_grams'] for r in result)
        if not all(math.isfinite(float(fields[k])) for k in ('weight','prediction')) or abs(float(fields['weight'])-grams) > .05 or abs(float(fields['prediction'])-seconds) > 1.1:
            raise ValueError('Native plate time or mass does not agree with the report')
    times=[float(p['feature_type_times'][k]) for k in ('Flush','Prime tower')]
    if any(not math.isfinite(t) or not 0 <= t <= seconds for t in times):
        raise ValueError('Invalid purge or tower time')
    if sum(r['load_seconds']+r['unload_seconds'] for r in result)>seconds:
        raise ValueError('Load/unload diagnostics exceed total time')
    return dict(slots=result,total_grams=grams,main_grams=sum(r['main_grams'] for r in result),
                purge_and_tower_grams=sum(r['purge_and_tower_grams'] for r in result),
                total_seconds=seconds,filament_changes=changes,
                load_unload_seconds=sum(r['load_seconds']+r['unload_seconds'] for r in result),
                flush_seconds=float(p['feature_type_times']['Flush']),
                prime_tower_seconds=float(p['feature_type_times']['Prime tower']))


def native(content, directory, colors, triangles):
    if not _lock.acquire(blocking=False):
        raise ValueError('Another multicolor slice is running; retry shortly')
    try:
        settings = prepare(content, directory/'input.3mf')
        executable = integrations.bambu_executable().resolve()
        environment = {k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG')}
        environment.update(APPDATA=str(directory/'appdata'),LOCALAPPDATA=str(directory/'localappdata'))
        with (directory/'slicer.log').open('wb') as log:
            r=subprocess.run([str(executable),'--slice','1','--arrange','1','--outputdir',str(directory),'--export-3mf','quote.3mf',str(directory/'input.3mf')],cwd=directory,env=environment,stdout=log,stderr=subprocess.STDOUT,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        path=directory/'result.json'
        if r.returncode or not path.is_file() or path.stat().st_size > 2*1024*1024:
            raise ValueError('Native multicolor slicing failed; review the saved project')
        report=json.loads(path.read_text(encoding='utf-8'))
        metrics=parse_result(report,directory/'quote.3mf',colors,triangles)
        return metrics,dict(profile_id='x2d-pla-0.4-v1',profile_name='Reviewed X2D four-PLA project',
                            profile_sha256=digest(directory/'input.3mf'),executable_sha256=digest(executable),
                            report_sha256=digest(path),export_sha256=digest(directory/'quote.3mf'),verified_multicolor=True,calibrated=False,
                            settings=dict(layer_height_mm=float(report['layer_height']),infill_percent=float(report['sparse_infill_density']),walls=int(report['wall_loops']),supports=False))
    finally:
        _lock.release()


def validate_quote(m,c,job,q):
    candidate=m.get(c,q['slicer']['multicolor_id'],'multicolor')
    if candidate['quote_id'] != q['id'] or candidate['status'] != 'price_approved' or candidate['job_id'] != job['id']:
        m.fail('Approve the verified multicolor price before scheduling',409)
    directory=m.DATA/'multicolor'/candidate['id']
    for name,key in [('input.3mf','profile_sha256'),('result.json','report_sha256'),('quote.3mf','export_sha256')]:
        if not (directory/name).is_file() or digest(directory/name)!=q['slicer'][key]:
            m.fail('Verified multicolor artifacts changed; slice again',409)
    if digest(integrations.bambu_executable().resolve()) != q['slicer']['executable_sha256']:
        m.fail('Slicer changed; repeat multicolor verification',409)
    if job.get('finish','as-printed')!='as-printed' or job['material']!='PLA':
        m.fail('Material or finishing review is required',422)


class PriceApproval(BaseModel):
    confirmed: Literal[True]
    mappings_confirmed: Literal[True]
    total_cents: int
    currency: str


def register(app):
    from backend import main as m
    from backend.model_processing import process_upload
    from backend.planner import fingerprint

    @app.get('/api/multicolor/{candidate_id}/report')
    def report_file(candidate_id:str):
        from fastapi.responses import FileResponse
        with m.engine.connect() as c:
            m.get(c,candidate_id,'multicolor')
        return FileResponse(m.DATA/'multicolor'/candidate_id/'result.json',media_type='application/json')

    @app.get('/api/multicolor/{candidate_id}/native-project')
    def native_project(candidate_id:str):
        from fastapi.responses import FileResponse
        with m.engine.connect() as c:
            m.get(c,candidate_id,'multicolor')
        return FileResponse(m.DATA/'multicolor'/candidate_id/'quote.3mf',media_type='application/vnd.ms-package.3dmanufacturing-3dmodel+xml',filename='X2D-four-color-slice-review.3mf')

    @app.get('/api/jobs/{job_id}/multicolor')
    def latest(job_id:str):
        with m.engine.connect() as c:
            m.get(c,job_id,'job')
            records=sorted([r for r in m.rows(c,'multicolor') if r['job_id']==job_id],key=lambda r:r['created_at'],reverse=True)
            if not records:return dict(status='not_requested')
            result=copy.deepcopy(records[0]);result.pop('snapshot_hash',None)
            result['quote']=m.get(c,result['quote_id'],'quote')
            result['stale']=records[0]['status']!='price_approved' and records[0]['snapshot_hash']!=fingerprint(m,c,job_id)
            return result

    @app.post('/api/jobs/{job_id}/multicolor',status_code=201)
    async def slice_project(job_id:str,file:UploadFile=File(...),confirmed:bool=Form(...),feeder:str=Form(...)):
        if not confirmed or feeder!='AMS 2 Pro':m.fail('Confirm the X2D / AMS 2 Pro setup before slicing',422)
        with m.transaction() as c:
            job=m.get(c,job_id,'job');before=fingerprint(m,c,job_id)
            if job['material']!='PLA' or job.get('finish','as-printed')!='as-printed' or job.get('reservation_id'):
                m.fail('Only unreserved, as-printed PLA jobs are supported in this first multicolor workflow',422)
            if not any(p['id']=='bambu-x2d' and p['active'] for p in m.rows(c,'printer')):
                m.fail('Configure an active X2D before slicing',422)
        metadata,_,_=await process_upload(file,m.DATA)
        info=metadata.get('color_info') or {}
        if metadata['source_format']!='3mf' or info.get('assigned_slots')!=SLOTS or info.get('painted_faces_detected') or info.get('material_inference',{}).get('suggested_material')!='PLA':
            m.fail('Use a component-assigned four-slot PLA 3MF; encoded paint is not supported',422)
        if metadata['sha256'] != job['file']['sha256'] or info['saved_filaments'] != job['file']['color_info']['saved_filaments']:
            m.fail('Project geometry or saved filament metadata differs from this job; submit it as a new job',422)
        if job.get('color') and job['color'].strip().casefold()!=info['color_inference']['suggested_color'].strip().casefold():
            m.fail('Requested color text differs from the assigned four-color set. Resolve the request or upload a matching project before quoting.',422)
        await file.seek(0);content=await file.read(64*1024*1024+1)
        if len(content)>64*1024*1024:m.fail('Project exceeds upload limit',413)
        if hashlib.sha256(content).hexdigest()!=metadata['source_sha256']:
            m.fail('Source project changed during validation',409)
        cid=m.uid();directory=m.DATA/'multicolor'/cid;directory.mkdir(parents=True)
        colors=[f['color'] for f in info['saved_filaments']]
        from backend.color_inspection import color_name
        if [color_name(x) for x in colors]!=['Black','White','Yellow','Green']:
            m.fail('This reviewed AMS setup requires slots 1 black, 2 white, 3 yellow, 4 green',422)
        try:
            metrics,provenance=await run_in_threadpool(native,content,directory,colors,metadata['triangles'])
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:
            m.fail('Multicolor verification failed: '+str(exc)[:300],422)
        provenance['multicolor_id']=cid
        with m.transaction() as c:
            current=m.get(c,job_id,'job')
            if before!=fingerprint(m,c,job_id):m.fail('Inputs changed during slicing; repeat verification',409)
            original=copy.deepcopy(current)
            q=m.build_quote(c,current,m.Estimates(confirmed=True,grams_per_part=metrics['total_grams'],hours_per_part=metrics['total_seconds']/3600,support_percent=0),provenance)
            q['source']='bambu_multicolor';q['multicolor']=metrics
            q['assumptions'].append('Native total includes all four slots, purge/tower material and change time; no extra waste multiplier or time addition. Each copy repeats a complete one-keychain plate sequentially.')
            m.put(c,'quote',q);m.put(c,'job',original)
            m.audit(c,job_id,'multicolor_candidate_verified',dict(candidate_id=cid,quote_id=q['id'],selected_price_changed=False))
            result=dict(id=cid,job_id=job_id,quote_id=q['id'],status='review_required',created_at=m.stamp(),feeder=feeder,metrics=metrics,expires_at=q['expires_at'])
            # Candidate quote creation is not a change to the selected price.
            result['snapshot_hash']=fingerprint(m,c,job_id)
            m.put(c,'multicolor',result)
            return {**{k:v for k,v in result.items() if k!='snapshot_hash'},'quote':q,'stale':False}

    @app.post('/api/multicolor/{candidate_id}/approve-price')
    def approve_price(candidate_id:str,body:PriceApproval):
        with m.transaction() as c:
            r=m.get(c,candidate_id,'multicolor');q=m.get(c,r['quote_id'],'quote');j=m.get(c,r['job_id'],'job')
            if body.total_cents!=q['total_cents'] or body.currency!=q['currency']:
                m.fail('Approval must match the exact displayed price and currency',409)
            if r['status']=='price_approved':
                if j.get('latest_quote_id')!=q['id']:m.fail('Selected quote changed',409)
                return q
            if r['snapshot_hash']!=fingerprint(m,c,j['id']) or m.parse(q['expires_at'])<=m.now():
                m.fail('Multicolor evidence is stale; slice again',409)
            r['status']='price_approved';m.put(c,'multicolor',r)
            validate_quote(m,c,j,q)
            j.update(latest_quote_id=q['id'],status='quote_ready');m.put(c,'job',j)
            m.audit(c,j['id'],'multicolor_price_approved',dict(candidate_id=candidate_id,quote_id=q['id']))
            return q
