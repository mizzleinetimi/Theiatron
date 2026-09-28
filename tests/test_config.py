import pytest
from theiatron.config import config_from_dict


@pytest.mark.parametrize('raw', [[], {'unknown':{}}, {'signal':{'min_green':-1}},
    {'signal':{'max_green':1}}, {'signal':{'yellow':float('nan')}}, {'queue':{'lanes':True}},
    {'vision':{'process_fps':0}}, {'vision':{'conf':1.1}}, {'vision':{'imgsz':float('inf')}},
    {'approaches':[dict(name='east',phase='NO',video='')]},
    {'approaches':[dict(name='east',phase='EW',video='',count_line=[[1,1],[1,1]])]},
    {'approaches':[dict(name='east',phase='EW',video='')]*2}])
def test_bad_config_fails_early(raw):
    with pytest.raises(ValueError):
        config_from_dict(raw)


def test_uncommissioned_config_remains_allowed():
    cfg=config_from_dict({'approaches':[dict(name='east',phase='EW',video='')]})
    assert cfg.approaches[0].count_line == []
