"""Immutable, footage-linked network hypotheses. No automatic 'reviewed' state.

Camera count lines are provenance, not a metric survey. Editing this network
does not silently change/recount the source observations.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from .artifacts import fingerprint, load_artifact
from .config import SignalConfig, config_from_dict
from .controller import SignalState
from .io import atomic_json

REVISION = re.compile(r"[0-9a-f]{64}")
RUN_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,120}")
ASSUMPTIONS = [
    "Draft network hypothesis, not a surveyed or reviewed site model",
    "Camera-plane directions only seed the sketch; there is no metric camera calibration",
    "Road lengths, widths, lane counts, speeds and all exit assignments are assumptions",
    "Recorded crossing timestamps become SUMO boundary departures without upstream travel-time reconstruction",
    "SUMO samples motion at 0.5 seconds; exact source timestamps are retained separately from simulator time quantisation",
    "No arrivals are added for unobserved approaches; zero detections do not prove zero traffic",
    "Empty initial network; initial queues, pedestrians and mixed vehicle classes are not reconstructed",
    "Hypothetical signal installation/operation; neither comparator is the observed real-site baseline",
    "Each approach has an exclusive stage; this is not the earlier two-phase fixture policy",
    "Ideal own-world queue sensing; detection and calibration errors are not modelled",
    "Short single-clip experiment, not held-out evaluation or a traffic-benefit claim",
]


def store_path(root: Path) -> Path:
    return root / "out" / ".profiles"


def source_horizon(source: dict) -> int:
    """Leave a step after the last arrival, including one at an integer endpoint."""
    return max(math.ceil(source['duration']), math.floor(max(e['t'] for e in source['events'])) + 1)


def _seal(root: Path, profile: dict) -> dict:
    profile = deepcopy(profile)
    profile.pop("revision", None)
    validate(profile)
    profile["revision"] = fingerprint(profile)
    path = store_path(root) / (profile["revision"] + ".json")
    if not path.exists():
        atomic_json(path, profile)
    return profile


def load_profile(root: Path, revision: str) -> dict:
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("invalid profile revision")
    path = store_path(root) / (revision + ".json")
    if path.is_symlink() or store_path(root).is_symlink():
        raise ValueError("profile symlinks are not allowed")
    profile = json.loads(path.read_text())
    stored = profile.pop("revision", None)
    if stored != revision or fingerprint(profile) != revision:
        raise ValueError("profile checksum mismatch")
    validate(profile)
    return {**profile, "revision": revision}


def from_run(root: Path, run_id: str) -> dict:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid source run")
    directory = root / "out" / run_id
    if directory.is_symlink() or (directory / "simulation.json").is_symlink():
        raise ValueError("source symlinks are not allowed")
    artifact = load_artifact(directory / "simulation.json")
    meta = artifact["source_meta"]
    if meta.get("kind") != "live-video-analysis" or not re.fullmatch(r"[0-9a-f]{64}", meta.get("source_sha256", "")):
        raise ValueError("a completed, fingerprinted real-video analysis is required")
    cfg = artifact["config"]
    config_from_dict(cfg)
    if not 2 <= len(cfg["approaches"]) <= 4:
        raise ValueError("this prototype supports two to four candidate approaches")
    if any(len(a['count_line']) != 2 or len(a['approach_side']) != 2 for a in cfg['approaches']):
        raise ValueError("source needs commissioned count lines and approach-side markers")
    events = [{"id": v["id"], "approach": v["a"], "t": v["t0"]}
              for v in artifact["scenarios"]["theiatron"]["vehicles"]]
    events.sort(key=lambda v: (v["t"], v["id"]))
    if not events:
        raise ValueError("no recorded arrivals to simulate")
    centre = [sum(sum(p[d] for p in a["count_line"]) / 2 for a in cfg["approaches"]) / len(cfg["approaches"])
              for d in (0, 1)]
    approaches = []
    for index, a in enumerate(cfg["approaches"]):
        dx, dy = a["approach_side"][0] - centre[0], centre[1] - a["approach_side"][1]
        size = math.hypot(dx, dy)
        if size < 1:
            dx, dy, size = math.sin(index * math.pi / 2), math.cos(index * math.pi / 2), 1
        approaches.append({"id": a["name"], "enabled": True, "x": round(100 * dx / size, 1),
                           "y": round(100 * dy / size, 1), "lanes": 1, "width": 3.2, "speed": 8.33,
                           "exit": None})
    source = {"run_id": run_id, "artifact_id": artifact["artifact_id"], "video_sha256": meta["source_sha256"],
              "filename": Path(meta["source"]).name, "duration": artifact["duration"],
              "events": events, "approaches": cfg["approaches"],
              "counts": dict(Counter(e["approach"] for e in events)),
              "runtime_provenance": meta.get("runtime_provenance", {})}
    profile = {"schema_version": 1, "kind": "footage-network-hypothesis", "review_status": "draft-unreviewed",
               "label": source["filename"] + " · network hypothesis", "source": source,
               "source_checksum": fingerprint(source), "approaches": approaches,
               "signal": asdict(SignalConfig(min_green=8, max_green=40, yellow=3, all_red=2,
                                            fixed_split=20, hysteresis=3)),
               "traffic_side": "right", "assumptions": ASSUMPTIONS,
               "parent_revision": None}
    return _seal(root, profile)


def revise(root: Path, revision: str, changes: dict) -> dict:
    if not isinstance(changes, dict) or set(changes) - {"label", "approaches", "signal", "traffic_side"}:
        raise ValueError("only label, network approaches, timings and traffic side are editable")
    profile = load_profile(root, revision)
    profile.update(deepcopy(changes))
    profile["parent_revision"] = revision
    return _seal(root, profile)


def validate(profile: dict, runnable: bool = False) -> None:
    if profile.get("schema_version") != 1 or profile.get("kind") != "footage-network-hypothesis":
        raise ValueError("unsupported profile")
    if profile.get("review_status") != "draft-unreviewed" or profile.get("assumptions") != ASSUMPTIONS:
        raise ValueError("draft status and evidence limitations cannot be removed")
    source = profile["source"]
    if fingerprint(source) != profile["source_checksum"]:
        raise ValueError("source observations have changed")
    if 'demo_proposal' in profile:
        proposal = profile['demo_proposal']
        if proposal.get('basis') not in {'camera-estimated-ground','camera-direction-sketch'}:
            raise ValueError('unknown demo geometry basis')
        if proposal['basis']=='camera-estimated-ground':
            binding=proposal['binding']
            if binding['source_run']!=source['run_id'] or binding['source_sha256']!=source['video_sha256']:
                raise ValueError('demo geometry belongs to a different source')
            if not 3<=len(proposal['road'])<=100 or any(len(p)!=2 or any(
                type(v) not in {int,float} or not math.isfinite(v) or abs(v)>1000 for v in p) for p in proposal['road']):
                raise ValueError('invalid demo road footprint')
    if not isinstance(profile.get("label"), str) or not 1 <= len(profile["label"]) <= 120:
        raise ValueError("profile label must be 1–120 characters")
    if profile["traffic_side"] not in {"left", "right"}:
        raise ValueError("traffic side must be left or right")
    def number(value, low, high):
        return type(value) in {int, float} and math.isfinite(value) and low <= value <= high
    if not number(source["duration"], 30, 300):
        raise ValueError("source observation window must be 30–300 seconds")
    cfg = config_from_dict({"signal": profile["signal"]})
    if set(profile["signal"]) != set(asdict(SignalConfig())):
        raise ValueError("complete signal configuration is required")
    if not (2 <= cfg.signal.min_green <= cfg.signal.fixed_split <= cfg.signal.max_green <= 90
            and .5 <= cfg.signal.yellow <= 10 and .5 <= cfg.signal.all_red <= 10):
        raise ValueError("timings outside prototype bounds")
    if any(v * 2 != round(v * 2) for v in (cfg.signal.min_green, cfg.signal.max_green, cfg.signal.fixed_split,
                                         cfg.signal.yellow, cfg.signal.all_red)):
        raise ValueError("timings must align with the 0.5-second simulator step")
    approaches = profile["approaches"]
    source_ids = {a["name"] for a in source["approaches"]}
    if len(approaches) != len(source_ids) or {a["id"] for a in approaches} != source_ids:
        raise ValueError("approach IDs must preserve the source mapping")
    active = [a for a in approaches if a["enabled"] is True]
    if not 2 <= len(active) <= 4:
        raise ValueError("enable two to four network approaches")
    active_ids = {a["id"] for a in active}
    for a in approaches:
        if set(a) != {"id", "enabled", "x", "y", "lanes", "width", "speed", "exit"}:
            raise ValueError("unknown or missing approach fields")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,31}", a["id"]) or type(a["enabled"]) is not bool:
            raise ValueError("invalid approach ID or enabled flag")
        if not all(number(a[k], -300, 300) for k in ("x", "y")) or not 35 <= math.hypot(a["x"], a["y"]) <= 300:
            raise ValueError("approach endpoints must be 35–300 assumed metres from the junction")
        if type(a["lanes"]) is not int or not 1 <= a["lanes"] <= 3:
            raise ValueError("lane count must be an integer from one to three")
        if not number(a["width"], 2.5, 4.5) or not number(a["speed"], 3, 16.67):
            raise ValueError("width/speed outside prototype bounds")
        if a["enabled"] and a["exit"] is not None and (a["exit"] not in active_ids or a["exit"] == a["id"]):
            raise ValueError("exit must be another enabled approach; U-turns are unsupported")
        if runnable and a["enabled"] and a["exit"] is None:
            raise ValueError(f"choose an explicit assumed exit for {a['id']}")
    ids = set()
    for event in source["events"]:
        if event["id"] in ids or event["approach"] not in source_ids or not number(event["t"], 0, source["duration"]):
            raise ValueError("invalid or duplicate source event")
        ids.add(event["id"])
        if event["approach"] not in active_ids:
            raise ValueError("cannot disable an approach with observed arrivals")
    if len(ids) > 5000 or not ids:
        raise ValueError("source must contain 1–5000 observed arrivals")
    if runnable:
        for i, a in enumerate(active):
            for b in active[i+1:]:
                cos = (a["x"]*b["x"] + a["y"]*b["y"]) / math.hypot(a["x"],a["y"]) / math.hypot(b["x"],b["y"])
                if cos > math.cos(math.radians(25)):
                    raise ValueError("network arms are less than 25 degrees apart; review the sketch")


def build_network(out: Path, profile: dict) -> tuple[list[dict], dict]:
    from .sumo_demo import _xml, binary
    validate(profile, runnable=True)
    approaches = [a for a in profile["approaches"] if a["enabled"]]
    by_id = {a["id"]: a for a in approaches}
    nodes, edges, connections = ET.Element("nodes"), ET.Element("edges"), ET.Element("connections")
    ET.SubElement(nodes, "node", id="J", x="0", y="0", type="traffic_light")
    for a in approaches:
        name = a["id"]
        ET.SubElement(nodes, "node", id=name, x=str(a["x"]), y=str(a["y"]))
        for start, end, suffix in ((name,"J","in"),("J",name,"out")):
            ET.SubElement(edges,"edge", {"id": name+"_"+suffix,"from": start,"to": end,"numLanes": str(a["lanes"]),
                                         "width": str(a["width"]),"speed": str(a["speed"])})
        target = by_id[a["exit"]]
        for lane in range(a["lanes"]):
            ET.SubElement(connections,"connection", {"from": name+"_in","to": target["id"]+"_out",
                                                       "fromLane": str(lane),"toLane": str(min(lane,target["lanes"]-1))})
    for name, tree in (("nodes.nod.xml",nodes),("edges.edg.xml",edges),("connections.con.xml",connections)):
        _xml(out/name,tree)
    result = subprocess.run([binary("netconvert"),"--node-files","nodes.nod.xml","--edge-files","edges.edg.xml",
        "--connection-files","connections.con.xml","--output-file","network.net.xml","--offset.disable-normalization","true",
        "--no-turnarounds","true","--tls.layout","incoming","--lefthand",str(profile["traffic_side"]=="left").lower()],
        cwd=out,capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise ValueError("SUMO rejected the network sketch: " + result.stderr[-1000:])
    net=ET.parse(out/"network.net.xml")
    _xml(out/"network.net.xml",net.getroot())
    atomic_json(out/"site-profile.json",profile)
    atomic_json(out/"source-observations.json",profile["source"])
    routes=ET.Element("routes")
    ET.SubElement(routes,"vType",id="car",length="4.5",width="1.8",accel="2.6",decel="4.5",sigma="0",tau="1",minGap="2.5",maxSpeed="16.67",speedFactor="1")
    for a in approaches:
        ET.SubElement(routes,"route",id=a["id"],edges=f"{a['id']}_in {a['exit']}_out")
    demand=[]
    for event in profile["source"]["events"]:
        a=by_id[event["approach"]]
        demand.append({"id":event["id"],"approach":a["id"],"depart":event["t"],"exit":a["exit"],"exit_basis":"assumed"})
        ET.SubElement(routes,"vehicle",id=event["id"],type="car",route=a["id"],depart=f"{event['t']:.6f}",departSpeed="max",departLane="free")
    _xml(out/"demand.rou.xml",routes)
    atomic_json(out/"demand.json",demand)
    lanes=[]
    for edge in net.findall("edge"):
        if edge.get("function") == "internal":
            continue
        arm=edge.get("id").rsplit("_",1)[0]
        for lane in edge.findall("lane"):
            lanes.append({"id":lane.get("id"),"arm":arm,"signal_phase":arm,"width":float(lane.get("width","3.2")),
                          "points":[[float(v) for v in p.split(",")] for p in lane.get("shape").split()]})
    junction=next(j for j in net.findall("junction") if j.get("id")=="J")
    geometry={"lanes":lanes,"junction":[[float(n) for n in p.split(",")] for p in junction.get("shape").split()],
              "label":profile["label"],"units":"assumed-metres","review_status":"draft-unreviewed",
              "source_run":profile["source"]["run_id"],"profile_revision":profile["revision"]}
    if profile.get('demo_proposal'):
        geometry['context_road'] = profile['demo_proposal']['road']
        geometry['geometry_basis'] = profile['demo_proposal']['basis']
        geometry['context_label'] = 'Estimated visible footprint; procedural lanes and extensions are hypothetical'
    atomic_json(out/"geometry.json",geometry)
    return demand, geometry


class IncomingStages:
    """Exclusive-approach laboratory stages. Not certified field timing logic."""
    def __init__(self, names: list[str], cfg: SignalConfig, policy: str):
        self.names, self.cfg, self.policy = names, cfg, policy
        self.active = names[0]
        self.next = names[1]
        self.state = SignalState.GREEN
        self.since = 0.0
        self.green_end_cause = None

    def is_green(self, phase):
        return self.state == SignalState.GREEN and phase == self.active

    def update(self, now, observations):
        elapsed = now-self.since
        reason="fixed sequence" if self.policy=="fixed" else "serving active queue"
        if self.state == SignalState.GREEN:
            order = self.names[self.names.index(self.active)+1:] + self.names[:self.names.index(self.active)]
            pressure=lambda n: observations[n].queued + self.cfg.wait_weight*observations[n].stopped_seconds
            best=max(order,key=pressure)
            target=order[0] if self.policy=="fixed" else best
            want=elapsed>=self.cfg.fixed_split if self.policy=="fixed" else (
                pressure(best)>0 and (observations[self.active].queued==0 or pressure(best)>pressure(self.active)*self.cfg.pressure_ratio+self.cfg.hysteresis))
            force=elapsed>=self.cfg.max_green
            if (want and elapsed>=self.cfg.min_green) or force:
                self.next=target
                self.state,self.since=SignalState.YELLOW,now
                self.green_end_cause="max_green" if force else "policy"
                reason="maximum-green cap" if force else "fixed split" if self.policy=="fixed" else "queue-pressure handover"
        elif self.state == SignalState.YELLOW:
            reason="yellow clearance"
            if elapsed>=self.cfg.yellow:
                self.state,self.since=SignalState.ALL_RED,now
        else:
            reason="all-red clearance"
            if elapsed>=self.cfg.all_red:
                self.active,self.state,self.since=self.next,SignalState.GREEN,now
                reason="new approach green"
        return reason
