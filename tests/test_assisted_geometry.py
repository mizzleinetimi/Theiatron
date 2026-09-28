import copy
import json

import numpy as np
import pytest

from test_ground_plane import camera
from test_site_profiles import make_source
from theiatron.assisted_geometry import propose
from theiatron.ground_plane import project
from theiatron import reconstruction


def selection(half_width=8,half_depth=6):
    _,n,x,z,_,_,image=camera()
    # The two selected families are the world X and Z axes, not the rotated
    # vanishing families in the fixture; rotate the rectangle into those axes.
    yaw=np.radians(35)
    u=x*np.cos(yaw)+z*np.sin(yaw);v=-x*np.sin(yaw)+z*np.cos(yaw)
    centre=z*-30+n*8
    pixels=image([centre+a*u+b*v for a,b in [(-half_width,-half_depth),(half_width,-half_depth),(half_width,half_depth),(-half_width,half_depth)]]).tolist()
    lines=[[pixels[0],pixels[1]],[pixels[3],pixels[2]],
           [pixels[0],pixels[3]],[pixels[1],pixels[2]]]
    calibration={'anchors':pixels,'road':pixels,'width_m':float(2*half_width),'depth_m':float(2*half_depth),'label':'Test input'}
    return lines,calibration


def test_assisted_fit_preserves_true_aspect_without_claiming_measured_scale():
    lines,base=selection();before=copy.deepcopy((lines,base))
    candidate,quality=propose(lines,base)
    road=project(quality['pixel_to_ground'],base['road'])
    lengths=np.linalg.norm(np.roll(road,-1,axis=0)-road,axis=1)
    assert np.allclose(lengths,[16,12,16,12])
    assert (lines,base)==before
    assert candidate['road']==base['road']
    assert quality['sensitivity']['accepted']>=52
    assert quality['metric_accuracy_validated'] is False
    assert quality['physical_scale_measured'] is False


def test_short_baseline_still_rejects_click_sensitive_shape():
    lines,base=selection(4,3)
    with pytest.raises(ValueError,match='too sensitive'):propose(lines,base)


@pytest.mark.parametrize('mutation', ['missing','nan','outside','duplicate','short','image-parallel'])
def test_bad_line_selections_fail_closed(mutation):
    lines,base=selection()
    if mutation=='missing':lines.pop()
    elif mutation=='nan':lines[0][0][0]=float('nan')
    elif mutation=='outside':lines[0][0][0]=1280
    elif mutation=='duplicate':lines[1]=copy.deepcopy(lines[0])
    elif mutation=='short':lines[0][1]=[lines[0][0][0]+1,lines[0][0][1]]
    else:lines[:2]=[[[100,400],[500,400]],[[100,500],[500,500]]]
    with pytest.raises(ValueError):propose(lines,base)


def test_preview_is_read_only_and_save_recomputes_source_bound_assistance(tmp_path):
    make_source(tmp_path)
    folder=tmp_path/'out'/'source'
    (folder/'tracks.json').write_text(json.dumps({'counted':[],'extras':[]}))
    (folder/'plate.jpg').write_bytes(b'test plate')
    current=reconstruction.source(tmp_path,'source')
    lines,base=selection()
    request={'binding':current['binding'],'base_revision':None,'calibration':base,'lines':lines}
    preview=reconstruction.preview_assisted(tmp_path,'source',request)
    assert preview['status']=='unsaved-assisted-estimate'
    assert not (tmp_path/'out'/'.reconstructions').exists()
    saved=reconstruction.save_assisted(tmp_path,'source',request)
    assert saved['calibration']==preview['calibration']
    fresh=reconstruction.source(tmp_path,'source')
    assert fresh['assistance']['method']=='operator-road-directions-v1'
    assert fresh['assistance']['lines']==lines
    assert fresh['metric_accuracy_validated'] is False
    with pytest.raises(ValueError,match='draft changed'):
        reconstruction.save_assisted(tmp_path,'source',request)
    bad={**request,'base_revision':saved['revision'],'quality':{'accepted':True}}
    with pytest.raises(ValueError,match='provide'):reconstruction.preview_assisted(tmp_path,'source',bad)
    # A subsequent manual edit is a manual draft, not a forged assisted result.
    reconstruction.save(tmp_path,'source',{'binding':current['binding'],'calibration':saved['calibration']})
    assert reconstruction.source(tmp_path,'source')['assistance'] is None
    request['binding']={**current['binding'],'source_sha256':'0'*64}
    with pytest.raises(ValueError,match='source changed'):
        reconstruction.preview_assisted(tmp_path,'source',request)
