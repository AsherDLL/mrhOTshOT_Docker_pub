// Visualization registry - each process visualization is one self-contained module.
// A module is: {
//   kind:  "heating",                         // matches the scenario manifest's watch.kind
//   title: "District Heating Substation",
//   map(raw)          -> process-meaningful state (raw = the live PLC read),
//   build(stage)      -> refs (draws the picture + readouts into the stage element),
//   update(refs,state)-> { level, msg }        // level: normal|warning|critical|offline
// }
// The shell (visualizer.js) drives the alert banner + status from {level, msg}.
window.VIZ = window.VIZ || {};
window.registerViz = function (m) { window.VIZ[m.kind] = m; };

// Shared helpers. Defined here rather than inside visualizer.js because this file
// loads first and is the module contract - both the shell and any viz module use
// the same implementations.
//   digPath  resolve an IO_POINTS `key` ("centrifuges.0.reported") against a reader dict
//   fmtIo    render a value the way the I/O map does (true->ON, null->--)
//   esc      HTML-escape before innerHTML
window.VIZ_UTIL = {
  digPath(obj, path) {
    return String(path).split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
  },
  fmtIo(v) {
    if (v === undefined || v === null) return "--";
    if (v === true) return "ON";
    if (v === false) return "OFF";
    return String(v);
  },
  esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },
};
