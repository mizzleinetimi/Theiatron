"""Paired stock-SUMO laboratory fixture, with no camera/site fidelity claim.

python -m theiatron.sumo_demo --out out/sumo-example --duration 180 --pace 4
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from .config import SignalConfig
from .controller import Phase, PhaseStateMachine, SignalState
from .io import atomic_json
from .observations import PhaseObservation, pressure_request
from .preview import parent_watchdog

ROOT = Path(__file__).resolve().parents[1]
ARMS = {"north": (0, 150), "east": (150, 0), "south": (0, -150), "west": (-150, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
PHASE = {a: Phase.NS if a in {"north", "south"} else Phase.EW for a in ARMS}
STEP = 0.5
SIGNAL = SignalConfig(min_green=8, max_green=40, yellow=3, all_red=1,
                      fixed_split=20, hysteresis=3, pressure_ratio=1.5)


@dataclass(frozen=True)
class Scenario:
    duration: int = 180
    seed: int = 42
    demand: str = "tidal"
    scale: float = 1.0
    pace: float = 4.0
    site_revision: str | None = None
    generated_demand: bool = False
    baseline_policy: str = 'fixed'
    adaptive_policy: str = 'pressure-v1'

    def __post_init__(self):
        if self.baseline_policy not in {'fixed','actuated'} or self.adaptive_policy not in {'pressure-v1','service-v2'}:
            raise ValueError('unsupported controller policy')
        if not self.site_revision and (self.baseline_policy!='fixed' or self.adaptive_policy!='pressure-v1'):
            raise ValueError('service/actuated policies require an explicit network profile')
        if type(self.duration) is not int or not 30 <= self.duration <= (301 if self.site_revision else 300):
            raise ValueError("duration must be an integer from 30 to 300 seconds")
        if type(self.seed) is not int or not 0 <= self.seed <= 1_000_000:
            raise ValueError("seed must be an integer from 0 to 1000000")
        if self.demand not in {"balanced", "tidal", "heavy", "observed"}:
            raise ValueError("choose balanced, tidal, heavy or profile-linked observed demand")
        if self.site_revision is not None and (not isinstance(self.site_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", self.site_revision)):
            raise ValueError("invalid site revision")
        if type(self.generated_demand) is not bool:
            raise ValueError('generated_demand must be a boolean')
        if self.generated_demand and (not self.site_revision or self.demand == 'observed'):
            raise ValueError('generated demand requires a site revision and a synthetic demand pattern')
        if not self.generated_demand and (self.demand == "observed") != bool(self.site_revision):
            raise ValueError("observed demand requires an immutable site revision")
        if self.demand == 'observed' and self.scale != 1:
            raise ValueError("observed arrivals cannot be scaled or duplicated")
        for name, low, high in (("scale", .5, 2), ("pace", 0, 20)):
            val = getattr(self, name)
            if type(val) not in {int, float} or not math.isfinite(val) or not low <= val <= high:
                raise ValueError(f"{name} must be a finite number between {low} and {high}")


def binary(name: str) -> str:
    # Call the actual executable, not the wheel's Python subprocess wrapper.
    # Timeouts then terminate the binary itself instead of orphaning its child.
    try:
        import sumo
        candidate = Path(sumo.SUMO_HOME) / "bin" / name
        if candidate.is_file():
            return str(candidate)
    except ImportError:
        pass
    candidate = Path(sys.executable).parent / name
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError("SUMO missing. Install requirements-sumo.txt in .venv first.")
    return found


def preflight() -> dict:
    try:
        versions = {n: importlib.metadata.version(n) for n in ("eclipse-sumo", "traci", "sumolib")}
        for n, v in list(versions.items()):
            if v != "1.27.1":
                raise RuntimeError(f"{n} {v}: install pinned requirements-sumo.txt")
        for name in ("sumo", "netconvert"):
            # Newly installed macOS binaries can take longer on their first launch.
            # Do not disable OS verification; allow a bounded cold-start window.
            result = subprocess.run([binary(name), "--version"], capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise RuntimeError(f"{name} cannot start: {result.stderr[:500]}")
            versions[name + "_binary"] = result.stdout.splitlines()[0]
        return {"ready": True, "versions": versions}
    except (RuntimeError, OSError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as exc:
        return {"ready": False, "error": str(exc)}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def object_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _xml(path: Path, element: ET.Element) -> None:
    ET.indent(element)
    ET.ElementTree(element).write(path, encoding="utf-8", xml_declaration=True)


def make_fixture(out: Path, scenario: Scenario) -> tuple[list[dict], dict]:
    nodes, edges, connections = ET.Element("nodes"), ET.Element("edges"), ET.Element("connections")
    ET.SubElement(nodes, "node", id="J", x="0", y="0", type="traffic_light")
    for arm, (x, y) in ARMS.items():
        ET.SubElement(nodes, "node", id=arm, x=str(x), y=str(y))
        for source, target, suffix in ((arm, "J", "in"), ("J", arm, "out")):
            ET.SubElement(edges, "edge", {"id": arm + "_" + suffix, "from": source, "to": target,
                                         "numLanes": "1", "speed": "13.89", "width": "3.2"})
        ET.SubElement(connections, "connection", {"from": arm + "_in", "to": OPPOSITE[arm] + "_out",
                                                   "fromLane": "0", "toLane": "0"})
    for name, tree in (("nodes.nod.xml", nodes), ("edges.edg.xml", edges), ("connections.con.xml", connections)):
        _xml(out / name, tree)
    subprocess.run([binary("netconvert"), "--node-files", "nodes.nod.xml", "--edge-files", "edges.edg.xml",
                    "--connection-files", "connections.con.xml", "--output-file", "network.net.xml",
                    "--offset.disable-normalization", "true", "--no-turnarounds", "true"],
                   cwd=out, check=True, capture_output=True, text=True, timeout=30)
    # Remove generated comments (including timestamps/absolute paths) for reproducible network hashes.
    net = ET.parse(out / "network.net.xml")
    _xml(out / "network.net.xml", net.getroot())
    routes = ET.Element("routes")
    ET.SubElement(routes, "vType", id="car", length="4.5", width="1.8", accel="2.6", decel="4.5",
                  sigma="0", tau="1", minGap="2.5", maxSpeed="13.89", speedFactor="1")
    for arm in ARMS:
        ET.SubElement(routes, "route", id=arm, edges=f"{arm}_in {OPPOSITE[arm]}_out")
    rng = random.Random(scenario.seed)
    demand = []
    for arm in ARMS:
        # Explicitly synthetic rates. Tidal demand switches its dominant axis halfway through.
        t, index = 0.0, 0
        while t < scenario.duration:
            if scenario.demand == "balanced":
                rate = 450
            elif scenario.demand == "heavy":
                rate = 950
            else:
                dominant = (PHASE[arm] == Phase.NS) == (t < scenario.duration / 2)
                rate = 800 if dominant else 220
            t += rng.expovariate(rate * scenario.scale / 3600)
            if round(t, 3) >= scenario.duration:
                break
            index += 1
            demand.append({"id": f"{arm}.{index}", "approach": arm, "depart": round(t, 3)})
    demand.sort(key=lambda v: (v["depart"], v["id"]))
    for v in demand:
        ET.SubElement(routes, "vehicle", id=v["id"], type="car", route=v["approach"],
                      depart=str(v["depart"]), departSpeed="max")
    _xml(out / "demand.rou.xml", routes)
    atomic_json(out / "demand.json", demand)
    lanes = [{"id": lane.get("id"), "width": float(lane.get("width", "3.2")),
              "points": [[float(n) for n in p.split(",")] for p in lane.get("shape").split()]}
             for edge in net.findall("edge") if edge.get("function") != "internal" for lane in edge.findall("lane")]
    junction = next(j for j in net.findall("junction") if j.get("id") == "J")
    geometry = {"lanes": lanes, "junction": [[float(n) for n in p.split(",")] for p in junction.get("shape").split()],
                "label": "Synthetic four-arm laboratory junction · right-hand traffic · straight movements only",
                "units": "metres", "review_status": "synthetic-fixture-not-a-reviewed-site"}
    atomic_json(out / "geometry.json", geometry)
    return demand, geometry


def generated_profile_demand(out: Path, profile: dict, scenario: Scenario) -> list[dict]:
    """New synthetic population, never scaling/renaming the recorded events.

    Piecewise rates are generated independently on each half-window so tidal
    transitions do not carry an exponential draw from the previous regime.
    """
    rng = random.Random(scenario.seed)
    arms = sorted((a for a in profile['approaches'] if a['enabled']),key=lambda a:a['id'])
    routes = ET.Element('routes')
    ET.SubElement(routes,'vType',id='car',length='4.5',width='1.8',accel='2.6',decel='4.5',
                  sigma='0',tau='1',minGap='2.5',maxSpeed='16.67',speedFactor='1')
    demand = []
    for index,a in enumerate(arms):
        ET.SubElement(routes,'route',id=a['id'],edges=f"{a['id']}_in {a['exit']}_out")
        count = 0
        for half in (0,1):
            rate = (450 if scenario.demand=='balanced' else 950 if scenario.demand=='heavy'
                    else 800 if index%2==half else 220)*scenario.scale
            t, end = half*scenario.duration/2, (half+1)*scenario.duration/2
            while True:
                t += rng.expovariate(rate/3600)
                if round(t,3) >= end:
                    break
                count += 1
                demand.append({'id':f"synthetic.{a['id']}.{count}", 'approach':a['id'],
                               'depart':round(t,3),'exit':a['exit'],'exit_basis':'assumed',
                               'demand_basis':'generated-not-observed'})
    demand.sort(key=lambda e:(e['depart'],e['id']))
    for e in demand:
        ET.SubElement(routes,'vehicle',id=e['id'],type='car',route=e['approach'],
                      depart=str(e['depart']),departSpeed='max',departLane='free')
    _xml(out/'demand.rou.xml',routes)
    atomic_json(out/'demand.json',demand)
    return demand


def aggregate(demand: list[dict], records: dict, now: float, approaches=None) -> dict:
    """Common intended-demand cohort; unfinished delay is censored at `now`.

    Undeparted vehicles accrue insertion delay, never vanish from denominators.
    Delay means stopped time + insertion delay, NOT journey time/timeLoss.
    """
    offered = [v for v in demand if v["depart"] < now]
    def group(vehicles):
        values, stops, insertion = [], [], []
        arrived = active = pending = 0
        for v in vehicles:
            r = records.get(v["id"])
            if r is None:
                pending += 1
                wait, delay = 0.0, max(0, now - v["depart"])
            else:
                arrived += int(r["arrived"])
                active += int(not r["arrived"])
                wait, delay = r["wait"], r["insertion"]
            stops.append(wait)
            insertion.append(delay)
            values.append(wait + delay)
        count = len(values)
        avg = lambda xs: round(sum(xs) / count, 4) if count else 0.0
        return {"offered": count, "arrived": arrived, "active": active, "pending": pending,
                "mean_delay_s": avg(values), "mean_stopped_s": avg(stops), "mean_insertion_s": avg(insertion),
                "p95_delay_s": round(sorted(values)[max(0, math.ceil(.95 * count) - 1)], 4) if count else 0,
                "total_delay_s": round(sum(values), 4),
                "conserved": count == arrived + active + pending}
    return {**group(offered), "per_approach": {a: group([v for v in offered if v["approach"] == a]) for a in (approaches or ARMS)}}


class World:
    def __init__(self, conn, name: str, demand: list[dict], profile=None, policy=None):
        self.conn, self.name, self.demand = conn, name, demand
        self.profile = profile
        self.arms = [a['id'] for a in profile['approaches'] if a['enabled']] if profile else list(ARMS)
        self.phase_of = {a: a for a in self.arms} if profile else PHASE
        self.cfg = SignalConfig(**profile['signal']) if profile else SIGNAL
        self.policy=policy or ('fixed' if name=='fixed' else 'pressure-v1')
        if profile:
            from .site_profiles import IncomingStages
            from .junction_control import ServiceStages
            self.sm = (ServiceStages(self.arms,self.cfg,self.policy) if self.policy in {'actuated','service-v2'} else
                       IncomingStages(self.arms,self.cfg,'fixed' if self.policy=='fixed' else 'adaptive'))
        else:
            self.sm = PhaseStateMachine(self.cfg)
        self.records = {}
        self.offered = {v["id"]: v for v in demand}
        from .junction_control import JunctionObservation
        self.observations = {p: JunctionObservation() for p in self.phase_of.values()}
        self.link_phases = []
        for links in conn.trafficlight.getControlledLinks("J"):
            phases = {self.phase_of[link[0].rsplit("_in_", 1)[0]] for link in links}
            if len(phases) != 1:
                raise RuntimeError("ambiguous fixture signal mapping")
            self.link_phases.append(phases.pop())
        self.diagnostics = {"teleports": 0, "collisions": 0, "emergency_stops": 0}

    def step(self, now: float) -> dict:
        c = self.conn
        if self.profile:
            reason = self.sm.update(now, self.observations)
        elif self.name == "fixed":
            want, reason = self.sm.elapsed(now) >= SIGNAL.fixed_split, "fixed 20-second green"
        else:
            want, reason = pressure_request(self.sm, self.observations, SIGNAL)
        if not self.profile:
            self.sm.step(now, want)
        if self.sm.state == SignalState.YELLOW and self.sm.green_end_cause == "max_green":
            reason = "maximum-green cap"
        state = "".join("G" if self.sm.is_green(p) else "y" if self.sm.active == p and self.sm.state == SignalState.YELLOW else "r"
                        for p in self.link_phases)
        c.trafficlight.setRedYellowGreenState("J", state)
        c.simulationStep()
        t = c.simulation.getTime()
        for vid in c.simulation.getDepartedIDList():
            self.records[vid] = {"wait": 0.0, "insertion": c.vehicle.getDepartDelay(vid), "arrived": False}
        for vid in c.simulation.getArrivedIDList():
            self.records[vid]["arrived"] = True
        self.diagnostics["teleports"] += c.simulation.getStartingTeleportNumber()
        self.diagnostics["collisions"] += c.simulation.getCollidingVehiclesNumber()
        self.diagnostics["emergency_stops"] += c.simulation.getEmergencyStoppingVehiclesNumber()
        obs = {p: [0, 0.0] for p in self.phase_of.values()}
        presence={p:0 for p in self.phase_of.values()}
        eta={p:None for p in self.phase_of.values()}
        vehicles, queues = [], dict.fromkeys(self.arms, 0)
        for vid in c.vehicle.getIDList():
            self.records[vid]["wait"] = c.vehicle.getAccumulatedWaitingTime(vid)
            x, y = c.vehicle.getPosition(vid)
            angle, speed = c.vehicle.getAngle(vid), c.vehicle.getSpeed(vid)
            arm = self.offered[vid]["approach"]
            edge = c.vehicle.getRoadID(vid)
            if edge==arm+'_in':
                phase=self.phase_of[arm]
                presence[phase]+=1
                distance=max(0.,c.lane.getLength(c.vehicle.getLaneID(vid))-c.vehicle.getLanePosition(vid))
                arrival=distance/max(speed,.5)
                eta[phase]=min(eta[phase],arrival) if eta[phase] is not None else arrival
            if speed < .1 and edge == arm + "_in":
                obs[self.phase_of[arm]][0] += 1
                obs[self.phase_of[arm]][1] += c.vehicle.getWaitingTime(vid)
                queues[arm] += 1
            vehicles.append({"id": vid, "x": round(x, 3), "y": round(y, 3), "angle": round(angle, 2),
                             "speed": round(speed, 3), "length": 4.5, "width": 1.8, "approach": arm})
        from .junction_control import JunctionObservation
        self.observations = {p: JunctionObservation(*values,presence[p],eta[p]) for p, values in obs.items()}
        return {"vehicles": vehicles, "queues": queues, "phase": self.sm.active if self.profile else self.sm.active.value,
                "signal": self.sm.state.value, "reason": reason, 'policy':self.policy,
                'lane_presence':presence,'nearest_eta_s':eta,
                "metrics": aggregate(self.demand, self.records, t, self.arms)}


def final_metrics(path: Path, demand: list[dict], horizon: float, approaches=None) -> dict:
    records = {}
    intended = {v["id"] for v in demand}
    seen = set()
    for trip in ET.parse(path).getroot().findall("tripinfo"):
        vid = trip.get("id")
        if vid not in intended or vid in seen:
            raise ValueError("SUMO emitted an unknown or duplicate vehicle")
        seen.add(vid)
        if float(trip.get("depart")) < 0:
            continue
        records[trip.get("id")] = {"wait": float(trip.get("waitingTime")),
                                   "insertion": float(trip.get("departDelay")),
                                   "arrived": float(trip.get("arrival")) >= 0}
    if seen != intended:
        raise ValueError("SUMO trip output lost intended vehicles")
    return aggregate(demand, records, horizon, approaches)


def verify_bundle(out: Path) -> dict:
    report = json.loads((out / "report.json").read_text())
    stored_id = report.pop("artifact_id")
    if object_hash(report) != stored_id:
        raise ValueError("report checksum mismatch")
    for name, expected in report["files"].items():
        if Path(name).name != name or digest(out / name) != expected:
            raise ValueError(f"evidence checksum mismatch: {name}")
    return {"artifact_id": stored_id, "verified_files": len(report["files"])}


def run(out: Path, scenario: Scenario, profile: dict | None = None) -> dict:
    import traci
    if scenario.site_revision:
        from .site_profiles import load_profile, validate, build_network, source_horizon
        profile = profile or load_profile(ROOT, scenario.site_revision)
        if profile.get('revision') != scenario.site_revision or object_hash({k:v for k,v in profile.items() if k!='revision'}) != scenario.site_revision:
            raise ValueError('site revision checksum mismatch')
        validate(profile, runnable=True)
        if not scenario.generated_demand and scenario.duration != source_horizon(profile['source']):
            raise ValueError('observed horizon must cover the source window with a step after the last arrival')
    elif profile:
        raise ValueError('profile supplied without observed scenario')
    code_fingerprints = {name: digest(ROOT / name) for name in (
        "theiatron/sumo_demo.py", "theiatron/observations.py", "theiatron/controller.py", "theiatron/config.py", "theiatron/site_profiles.py",
        "theiatron/junction_control.py")}
    ready = preflight()
    if not ready["ready"]:
        raise RuntimeError(ready["error"])
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / "scenario.json", asdict(scenario))
    demand, geometry = build_network(out, profile) if profile else make_fixture(out, scenario)
    if scenario.generated_demand:
        demand = generated_profile_demand(out,profile,scenario)
    connections, worlds = [], {}
    started = time.monotonic()
    try:
        for name in ("fixed", "adaptive"):
            label = f"{out.name}-{name}"
            traci.start([binary("sumo"), "--net-file", str(out / "network.net.xml"),
                         "--route-files", str(out / "demand.rou.xml"), "--seed", str(scenario.seed),
                         "--step-length", str(STEP), "--waiting-time-memory", str(scenario.duration + 10),
                         "--time-to-teleport", "-1", "--collision.action", "warn",
                         "--tripinfo-output", str(out / f"{name}.tripinfo.xml"),
                         "--tripinfo-output.write-unfinished", "true", "--tripinfo-output.write-undeparted", "true",
                         "--precision", "6",
                         "--no-step-log", "true", "--duration-log.disable", "true",
                         "--log", str(out / f"{name}.sumo.log")], label=label, doSwitch=False, stdout=subprocess.DEVNULL)
            conn = traci.getConnection(label)
            connections.append(conn)
            worlds[name] = World(conn, name, demand, profile, scenario.baseline_policy if name=='fixed' else scenario.adaptive_policy)
        started = time.monotonic()
        with (out / "frames.jsonl").open("w") as frames:
            for i in range(int(scenario.duration / STEP)):
                now = i * STEP
                frame = {"t": now + STEP, "worlds": {name: world.step(now) for name, world in worlds.items()}}
                frames.write(json.dumps(frame, separators=(",", ":"), allow_nan=False) + "\n")
                atomic_json(out / "latest.json", {**frame, "published_at": time.time(), "state": "processing"})
                if i % 20 == 0:
                    print(f"SUMO {frame['t']:.1f}/{scenario.duration}s", flush=True)
                if scenario.pace:
                    time.sleep(max(0, started + (now + STEP) / scenario.pace - time.monotonic()))
    finally:
        for conn in connections:
            conn.close()
    metrics = {name: final_metrics(out / f"{name}.tripinfo.xml", demand, scenario.duration, worlds[name].arms) for name in worlds}
    if any(digest(ROOT / name) != expected for name, expected in code_fingerprints.items()):
        raise RuntimeError("Simulation source changed during execution; rerun against a stable checkout")
    diagnostics = {name: world.diagnostics for name, world in worlds.items()}
    for name in worlds:
        live = frame["worlds"][name]["metrics"]
        if live != metrics[name]:
            raise ValueError(f"{name}: streamed metrics diverged from SUMO trip output")
    valid = all(m["conserved"] and m["offered"] == len(demand) for m in metrics.values()) and not any(
        v for d in diagnostics.values() for v in d.values())
    baseline, adaptive = metrics["fixed"]["mean_delay_s"], metrics["adaptive"]["mean_delay_s"]
    files = ["scenario.json", "network.net.xml", "demand.rou.xml", "demand.json", "geometry.json", "frames.jsonl",
             "fixed.tripinfo.xml", "adaptive.tripinfo.xml", "fixed.sumo.log", "adaptive.sumo.log"]
    report = {"schema_version": 1, "backend": "stock-sumo", "versions": ready["versions"],
              "evidence_level": "synthetic-laboratory-comparison", "valid": valid,
              "scenario": asdict(scenario), "signal_config": asdict(SIGNAL), "metrics": metrics,
              'policies':{'fixed':scenario.baseline_policy,'adaptive':scenario.adaptive_policy},
              "diagnostics": diagnostics, "cohort": "Identical intended departures before the horizon, including pending insertion",
              "metric": "Stopped waiting + insertion delay accrued to horizon; not end-to-end journey time",
              "p95_method": "nearest rank across the common intended-demand cohort",
              "reduction_pct": round((baseline - adaptive) / baseline * 100, 2) if baseline > 0 and valid else None,
              "assumptions": [geometry["label"], "Generated demand; no footage used", "Empty initial network; no pedestrians or turns",
                              "Homogeneous 4.5 m cars, 13.89 m/s speed limit, deterministic driver model (sigma 0)",
                              "Ideal simulator queue observations; no vision errors", "One seed; fixed baseline not independently tuned",
                              "Unfinished trips are censored at the common horizon; not a field-benefit claim"],
              "files": {name: digest(out / name) for name in files},
              "code_sha256": code_fingerprints}
    if profile:
        source_phases = {a['name']: a['phase'] for a in profile['source']['approaches']}
        phase_counts = {p: sum(1 for e in profile['source']['events'] if source_phases[e['approach']] == p) for p in ('NS', 'EW')}
        report.update(evidence_level='observed-demand-network-hypothesis', review_status='draft-unreviewed',
                      impact_status='not-validated', reduction_pct=None, signal_config=profile['signal'],
                      profile_revision=profile['revision'], source_run=profile['source']['run_id'],
                      source_artifact_id=profile['source']['artifact_id'], source_video_sha256=profile['source']['video_sha256'],
                      observed_counts=profile['source']['counts'], source_duration=profile['source']['duration'],
                      assumed_tail_s=scenario.duration-profile['source']['duration'],
                      assumptions=profile['assumptions'],
                      controller_layout='exclusive-incoming-approach-stages',
                      observed_phase_counts=phase_counts,
                      sample_status='inconclusive' if len(demand)<10 or not all(phase_counts.values()) else 'unreviewed')
        if profile.get('demo_proposal'):
            report['geometry_basis'] = profile['demo_proposal']['basis']
            report['assumptions'] = [*report['assumptions'], *profile['demo_proposal']['notes']]
        if scenario.generated_demand:
            report.update(evidence_level='generated-demand-network-hypothesis',sample_status='synthetic-experiment',
                          demand_basis='generated-not-observed', assumed_tail_s=None,
                          simulation_reduction_pct=round((baseline-adaptive)/baseline*100,2) if baseline>0 and valid else None,
                          assumptions=[
                              'Synthetic demand replaces (does not augment) recorded arrivals for this experiment.',
                              'Estimated network and assumed exits; not a validated digital twin.',
                              'Independent baseline/candidate worlds share identical generated departures, routes and seed.',
                              'Stopped waiting plus insertion delay, including unfinished demand; not journey-time savings.',
                              'Empty initial network, homogeneous cars, ideal own-world queue sensing; no field actuation.',
                              'All displayed differences are within this hypothetical model, not measured field benefit.',
                              *profile.get('demo_proposal',{}).get('notes',[])])
        for file in ('site-profile.json','source-observations.json'):
            report['files'][file]=digest(out/file)
    report['controller_comparison'] = {
        'baseline': 'Fixed timing' if scenario.baseline_policy == 'fixed' else 'Actuated gap-out',
        'candidate': 'Theiatron pressure v1' if scenario.adaptive_policy == 'pressure-v1' else 'Theiatron service v2',
        'sensing': 'Ideal own-world incoming-lane presence, speed and stopped waiting; not live camera control',
    }
    report['assumptions'].append(
        f"Comparator: {report['controller_comparison']['baseline']}; candidate: {report['controller_comparison']['candidate']}. "
        'This single run does not establish baseline tuning or superiority to an incumbent installation.')
    report["artifact_id"] = object_hash(report)
    atomic_json(out / "report.json", report)
    atomic_json(out / "latest.json", {**frame, "published_at": time.time(), "state": "complete",
                                      "worlds": {n: {**v, "metrics": metrics[n]} for n, v in frame["worlds"].items()}})
    verify_bundle(out)
    print(f"SUMO complete: {report['artifact_id']}", flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duration", type=int, default=180)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--demand", default="tidal")
    p.add_argument("--scale", type=float, default=1)
    p.add_argument("--pace", type=float, default=4)
    p.add_argument("--site-revision")
    p.add_argument('--generated-demand', choices=['True','False'], default='False')
    p.add_argument('--baseline-policy',default='fixed')
    p.add_argument('--adaptive-policy',default='pressure-v1')
    p.add_argument("--verify", action="store_true")
    args = p.parse_args()
    if args.verify:
        print(verify_bundle(args.out))
    else:
        run(args.out, Scenario(args.duration, args.seed, args.demand, args.scale, args.pace, args.site_revision,
                               args.generated_demand=='True',args.baseline_policy,args.adaptive_policy))


if __name__ == "__main__":
    parent_watchdog()
    main()
