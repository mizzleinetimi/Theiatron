"""Rejected speed candidate kept for repeatable experiments, never production.

Fewer features passed residual gates but differed from the full fit by >10 px
in paired tests. Do not enable based on residuals or throughput alone.
"""
import cv2
from theiatron.camera_registration import BackgroundRegistrar


class _SmallSearch(BackgroundRegistrar):
    def __init__(self,reference,boxes=()):
        self.orb=cv2.ORB_create(nfeatures=2400,fastThreshold=12)
        self.matcher=cv2.BFMatcher(cv2.NORM_HAMMING)
        self.reference_points,self.reference_descriptors=self._features(reference,boxes)


class AdaptiveBackgroundRegistrar:
    def __init__(self,reference,boxes=()):
        self.reference=reference
        self.boxes=tuple(boxes)
        self.fast=_SmallSearch(reference,boxes)
        self.full=None

    def _full(self):
        if self.full is None:self.full=BackgroundRegistrar(self.reference,self.boxes)
        return self.full

    def register(self,frame,boxes=()):
        candidate=self.fast.register(frame,boxes)
        if (candidate['status']=='accepted' and candidate['inliers']>=80
                and candidate['inlier_fraction']>=.65
                and candidate['background_coverage']>=.15
                and candidate['residual_px']['p90']<=1.9):
            return {**candidate,'search_mode':'fast-pass','feature_budget':2400}
        result=self._full().register(frame,boxes)
        return {**result,'search_mode':'full-fallback','feature_budget':6000,
                'fast_rejection':candidate.get('reason') or 'fast-path-extra-quality-gate'}
