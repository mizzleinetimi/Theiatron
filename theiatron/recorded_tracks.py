"""Dense, original detector observations for reconstruction, not queue animation."""
from collections import Counter


class RecordedTracks:
    def __init__(self):
        self.tracks = {}

    def update(self, timestamp, detections):
        for d in detections:
            row = self.tracks.setdefault(d.track_id, {'id':str(d.track_id), 'samples':[]})
            row['samples'].append({'t':timestamp, 'anchor':[d.x,d.y],
                'box':list(d.box), 'class_id':d.cls, 'confidence':d.conf})

    def export(self, extractors):
        counted = {tid:(name,number) for name,ex in extractors.items() for tid,number in ex.count_num.items()}
        tracks=[]
        for tid,record in self.tracks.items():
            votes=Counter(s['class_id'] for s in record['samples'])
            class_id=min(votes, key=lambda cls:(-votes[cls],cls))
            approach,number=counted.get(tid,(None,None))
            tracks.append({**record, 'class_id':class_id,
                'class_consistency':votes[class_id]/len(record['samples']),
                'mean_confidence':sum(s['confidence'] for s in record['samples'])/len(record['samples']),
                'approach':approach, 'count_number':number})
        return {'schema_version':1, 'image_size':[1280,720],
            'anchor':'detector-bottom-centre', 'sampling':'every-processed-frame-no-thinning',
            'vehicle_dimensions':'not-measured', 'tracks':tracks}
