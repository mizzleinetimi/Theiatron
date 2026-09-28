"""Experimental exclusive-approach controllers; not roadside signal logic.

Only current own-world lane observations enter decisions. No demand schedule,
uninserted vehicles, future arrivals or competing world's state is available.
"""
from dataclasses import dataclass

from .controller import SignalState


@dataclass(frozen=True)
class JunctionObservation:
    queued: int = 0
    stopped_seconds: float = 0.
    vehicles: int = 0
    nearest_eta_s: float | None = None


class ServiceStages:
    """Presence/gap baseline or demand-proportional committed service budget.

    Moving cars remain demand. A queue becoming mobile must not trigger an
    immediate handover. Stage transitions retain minimum green, yellow, all-red,
    maximum green and a committed target during clearance.
    """
    VERSION = 'service-v2'
    GAP_SECONDS = 3.0

    def __init__(self,names,cfg,mode='service-v2'):
        if mode not in {'service-v2','actuated'}:
            raise ValueError('unknown service policy')
        self.names,self.cfg,self.mode=list(names),cfg,mode
        self.active,self.next=names[:2]
        self.state=SignalState.GREEN
        self.since=0.
        self.green_end_cause=None
        self.budget=cfg.fixed_split
        self.waiting_since={n:None for n in names}

    def is_green(self,phase):
        return self.state==SignalState.GREEN and self.active==phase

    def update(self,now,observations):
        for name in self.names:
            if self.is_green(name) or not observations[name].vehicles:
                self.waiting_since[name]=None
            elif self.waiting_since[name] is None:
                self.waiting_since[name]=now
        elapsed=now-self.since
        if self.state==SignalState.YELLOW:
            if elapsed>=self.cfg.yellow:self.state,self.since=SignalState.ALL_RED,now
            return 'yellow clearance'
        if self.state==SignalState.ALL_RED:
            if elapsed>=self.cfg.all_red:
                self.active,self.state,self.since=self.next,SignalState.GREEN,now
                total=sum(o.vehicles for o in observations.values())
                share=observations[self.active].vehicles/max(total,1)
                budget=self.cfg.fixed_split*len(self.names)*share
                # Fixed for this green, rather than changing each detector tick.
                self.budget=max(self.cfg.min_green,min(self.cfg.max_green,round(budget*2)/2))
                return 'new approach green'
            return 'all-red clearance'
        order=self.names[self.names.index(self.active)+1:]+self.names[:self.names.index(self.active)]
        waiting=[n for n in order if observations[n].vehicles>0]
        age=lambda n:now-self.waiting_since[n] if self.waiting_since[n] is not None else 0.
        overdue=[n for n in waiting if age(n)>=(len(self.names)-1)*(self.cfg.fixed_split+self.cfg.yellow+self.cfg.all_red)]
        if overdue:target=max(overdue,key=age)
        elif self.mode=='actuated':target=(waiting or order)[0]
        else:target=max(waiting or order,key=lambda n:observations[n].vehicles + .02*observations[n].stopped_seconds)
        current=observations[self.active]
        gap=current.queued==0 and (current.nearest_eta_s is None or current.nearest_eta_s>self.GAP_SECONDS)
        force=elapsed>=self.cfg.max_green
        reason='serving moving platoon / committed service interval'
        handover=False
        if force:handover,reason=True,'maximum-green cap'
        elif elapsed>=self.cfg.min_green and waiting:
            if overdue:handover,reason=True,'waiting-approach service bound'
            elif gap:handover,reason=True,'presence gap-out'
            elif self.mode=='service-v2' and elapsed>=self.budget:
                handover,reason=True,'committed service budget complete'
        if handover:
            self.next=target
            self.state,self.since=SignalState.YELLOW,now
            self.green_end_cause='max_green' if force else 'policy'
        return reason
