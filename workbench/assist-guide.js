/* Bounded click guide; fitting and approval always happen on the server. */
(function(root) {
  "use strict";
  class AssistGuide {
    constructor() { this.points = []; }
    add(point) {
      if (this.points.length >= 8) return false;
      if (!Array.isArray(point) || point.length !== 2 || point.some((v,i) => !Number.isFinite(v) || v<0 || v>(i?719:1279)))
        throw Error("Select a point inside the source image.");
      this.points.push([...point]); return true;
    }
    undo() { this.points.pop(); }
    reset() { this.points = []; }
    get complete() { return this.points.length === 8; }
    get lines() {
      return Array.from({length:Math.floor(this.points.length/2)},(_,i) => this.points.slice(i*2,i*2+2).map(p=>[...p]));
    }
    get message() {
      if (this.complete) return "Four lines selected. Preview will test stability before applying any correction.";
      const labels=["A1 — first ground edge", "A2 — another edge parallel to A1 in the real road", "B1 — edge perpendicular to direction A in the real road", "B2 — another edge parallel to B1"];
      return `${this.points.length+1}/8: click the ${this.points.length%2?"end":"start"} of ${labels[Math.floor(this.points.length/2)]}.`;
    }
    request(binding,revision,calibration) {
      if (!this.complete) throw Error("Select all eight endpoints first.");
      return JSON.parse(JSON.stringify({binding,base_revision:revision,calibration,lines:this.lines}));
    }
  }
  if (typeof module !== "undefined") module.exports = AssistGuide;
  else root.AssistGuide = AssistGuide;
})(typeof window !== "undefined" ? window : globalThis);
