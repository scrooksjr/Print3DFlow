import copy
import io
import json
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from backend import multicolor, integrations
from backend.tests.test_colors import color_project


COLORS=['#161616','#FFFFFF','#FFF144','#0ACC38']


def project():
    with ZipFile(io.BytesIO(color_project(slots=(1,2,3,4)))) as z:
        parts={n:z.read(n) for n in z.namelist()}
    settings=json.loads(parts['Metadata/project_settings.config'])
    settings.update(printer_model='Bambu Lab X2D',nozzle_diameter=['0.4','0.4'],enable_prime_tower='1',filament_colour=COLORS)
    parts['Metadata/project_settings.config']=json.dumps(settings).encode()
    root=ET.fromstring(parts['Metadata/model_settings.config']);ET.SubElement(root,'plate')
    parts['Metadata/model_settings.config']=ET.tostring(root)
    out=io.BytesIO()
    with ZipFile(out,'w') as z:
        for n,b in parts.items():z.writestr(n,b)
        z.writestr('Metadata/plate_1.gcode','M112')
    return out.getvalue()


def report():
    return dict(return_code=0,layer_height=.2,sparse_infill_density=15,wall_loops=2,sliced_plates=[dict(
        warning_message='',objects=[{}],triangle_count=48,total_predication=1200,filament_change_times=4,
        feature_type_times={'Flush':100,'Prime tower':50},
        filaments=[dict(id=i,main_used_g=1,total_used_g=2) for i in range(1,5)])])


def archive(path):
    root=ET.Element('config');p=ET.SubElement(root,'plate')
    for k,v in dict(support_used='false',outside='false',filament_maps='2 1 1 1',weight='8',prediction='1200').items():
        ET.SubElement(p,'metadata',key=k,value=v)
    for i,color in enumerate(COLORS,1):
        ET.SubElement(p,'filament',id=str(i),type='PLA',color=color,used_g='2',total_load_time='20',total_unload_time='10')
    with ZipFile(path,'w') as z:z.writestr('Metadata/slice_info.config',ET.tostring(root))


def test_report_accounts_for_all_slots_and_does_not_add_times_twice(tmp_path):
    path=tmp_path/'quote.3mf';archive(path)
    x=multicolor.parse_result(report(),path,COLORS,48)
    assert x['total_grams']==8 and x['main_grams']==4 and x['purge_and_tower_grams']==4
    assert x['total_seconds']==1200 and x['load_unload_seconds']==120 and x['filament_changes']==4
    assert [r['tool'] for r in x['slots']]==[2,1,1,1]


@pytest.mark.parametrize('change',[lambda p:p['filaments'].pop(),lambda p:p.update(warning_message='review'),lambda p:p.update(triangle_count=12),lambda p:p.update(total_predication=float('nan')),lambda p:p['filaments'][0].update(total_used_g=.5),lambda p:p.update(filament_change_times=0)])
def test_incomplete_or_inconsistent_reports_fail_closed(tmp_path,change):
    path=tmp_path/'quote.3mf';archive(path);r=report();change(r['sliced_plates'][0])
    with pytest.raises(ValueError):multicolor.parse_result(r,path,COLORS,48)


def test_preparation_removes_embedded_gcode(tmp_path):
    target=tmp_path/'input.3mf';multicolor.prepare(project(),target)
    with ZipFile(target) as z:
        assert not any(n.endswith('.gcode') for n in z.namelist())


def test_manual_color_request_is_not_silently_overridden(client,monkeypatch):
    from backend import main as m
    with m.transaction() as c:
        m.put(c,'printer',dict(id='bambu-x2d',active=True))
    data=project()
    staged=client.post('/api/model-uploads',files={'file':('four.3mf',data)}).json()
    j=client.post('/api/jobs',json=dict(title='Purple request',quantity=1,material='PLA',color='Purple',finish='as-printed',units='mm',model_upload_id=staged['id'],deadline=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat())).json()
    def forbidden(*args):
        raise AssertionError('Conflicting colors must not reach the slicer')
    monkeypatch.setattr(multicolor,'native',forbidden)
    r=client.post('/api/jobs/'+j['id']+'/multicolor',files={'file':('four.3mf',data)},data={'confirmed':'true','feeder':'AMS 2 Pro'})
    assert r.status_code==422 and 'Requested color text differs' in r.text


def test_candidate_requires_mapping_and_exact_price_approval_before_scheduling(client,monkeypatch,tmp_path):
    from backend import main as m
    executable=tmp_path/'slicer.exe';executable.write_bytes(b'owned-test-executable')
    monkeypatch.setattr(integrations,'bambu_executable',lambda:executable)
    def native(content,directory,colors,triangles):
        multicolor.prepare(content,directory/'input.3mf');archive(directory/'quote.3mf')
        (directory/'result.json').write_text(json.dumps(report()))
        return multicolor.parse_result(report(),directory/'quote.3mf',colors,triangles),dict(
            profile_id='x2d-pla-0.4-v1',profile_name='Test X2D',profile_sha256=multicolor.digest(directory/'input.3mf'),
            report_sha256=multicolor.digest(directory/'result.json'),export_sha256=multicolor.digest(directory/'quote.3mf'),executable_sha256=multicolor.digest(executable),verified_multicolor=True,
            settings=dict(layer_height_mm=.2,infill_percent=15,walls=2,supports=False))
    monkeypatch.setattr(multicolor,'native',native)
    with m.transaction() as c:
        m.put(c,'printer',dict(id='bambu-x2d',name='Test X2D',profile='x2d-pla-0.4-v1',material='PLA',active=True,bed_mm=[235,256,256]))
    data=project();st=client.post('/api/model-uploads',files={'file':('keychain.3mf',data)}).json()
    j=client.post('/api/jobs',json=dict(title='Four-color fixture',quantity=2,material='PLA',finish='as-printed',units='mm',model_upload_id=st['id'],deadline=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat())).json()
    jid=j['id'];assert client.post('/api/jobs/'+jid+'/quotes',json=dict(confirmed=True,grams_per_part=1,hours_per_part=1)).status_code==422
    r=client.post('/api/jobs/'+jid+'/multicolor',files={'file':('keychain.3mf',data)},data={'confirmed':'true','feeder':'AMS 2 Pro'})
    assert r.status_code==201,r.text
    candidate=r.json();q=candidate['quote'];assert q['grams']==16 and q['hours']==pytest.approx(2/3)
    state=client.get('/api/state').json();stored=next(x for x in state['jobs'] if x['id']==jid)
    assert not stored.get('latest_quote_id') and not state['reservations']
    assert client.post('/api/jobs/'+jid+'/proposals').status_code==409
    url='/api/multicolor/'+candidate['id']+'/approve-price'
    body=dict(confirmed=True,mappings_confirmed=True,total_cents=q['total_cents'],currency=q['currency'])
    assert client.post(url,json=body|dict(mappings_confirmed=False)).status_code==422
    assert client.post(url,json=body|dict(total_cents=q['total_cents']+1)).status_code==409
    assert client.post(url,json=body|dict(currency='XXX')).status_code==409
    artifact=m.DATA/'multicolor'/candidate['id']/'input.3mf'
    original=artifact.read_bytes();artifact.write_bytes(b'changed')
    assert client.post(url,json=body).status_code==409
    artifact.write_bytes(original)
    assert client.post(url,json=body).status_code==200
    assert client.post(url,json=body).status_code==200
    assert not client.get('/api/state').json()['reservations']
    proposal=client.post('/api/jobs/'+jid+'/proposals');assert proposal.status_code==201,proposal.text
    assert not client.get('/api/state').json()['reservations']
    result=client.post('/api/proposals/'+proposal.json()['id']+'/approve',json={'idempotency_key':'four-color-test-approval'})
    assert result.status_code==200,result.text
    assert len(client.get('/api/state').json()['reservations'])==1
