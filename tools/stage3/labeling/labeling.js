// MAVI blind labelling page (S3.2 plan T4/T5). Opens from disk: no server, no
// network. It shows evidence images only; it never receives a prediction, a
// model score or any MAVI identifier. Decisions are exported as a local file.
(function () {
  "use strict";

  var pack = window.MAVI_PACK;
  var adjudication = window.MAVI_ADJUDICATION || null;
  var LABELS = [["1", "car"], ["2", "truck"], ["3", "bus"], ["4", "motorcycle"], ["0", "unknown"]];
  var element = function (id) { return document.getElementById(id); };

  if (!pack || !Array.isArray(pack.items)) {
    document.body.textContent = "pack-data.js is missing or invalid.";
    return;
  }

  var byId = {};
  pack.items.forEach(function (item) { byId[item.itemId] = item; });
  var queue = adjudication
    ? adjudication.items.filter(function (entry) { return entry.needsDecision; }).map(function (entry) { return entry.itemId; })
    : pack.items.map(function (item) { return item.itemId; });
  // Labelling resumes per pack; adjudication resumes per frozen primary/overlap pair (its session).
  var storeKey = adjudication ? "mavi-s32-adjudication:" + adjudication.sessionId : "mavi-s32-labels:" + pack.packSha256;
  var state = { reviewer: "", decisions: {} };
  try {
    var saved = window.localStorage.getItem(storeKey);
    if (saved) { state = JSON.parse(saved); }
  } catch (ignored) { /* resume is a convenience only */ }
  var index = 0;

  function save() {
    try { window.localStorage.setItem(storeKey, JSON.stringify(state)); } catch (ignored) { /* convenience only */ }
  }

  function current() { return state.decisions[queue[index]] || null; }

  function setDecision(change) {
    var id = queue[index];
    var decision = state.decisions[id] || {};
    Object.keys(change).forEach(function (key) { decision[key] = change[key]; });
    if (decision.label !== "unknown") { delete decision.unknownReason; }
    state.decisions[id] = decision;
    save();
    render();
  }

  function render() {
    element("mode").textContent = adjudication
      ? "Adjudication: choose the final label where the two reviewers disagree."
      : "Label each vehicle from the evidence shown.";
    element("reviewer").value = state.reviewer || "";
    if (queue.length === 0) {
      element("position").textContent = "Nothing to decide.";
      return;
    }
    var id = queue[index];
    var item = byId[id];
    element("position").textContent = (index + 1) + " / " + queue.length;
    element("itemId").textContent = "Item " + id;
    var views = element("views");
    views.textContent = "";
    item.views.forEach(function (view) {
      var figure = document.createElement("figure");
      var image = document.createElement("img");
      image.src = view.path;
      image.alt = view.label;
      var caption = document.createElement("figcaption");
      caption.textContent = view.label;
      figure.appendChild(image);
      figure.appendChild(caption);
      views.appendChild(figure);
    });
    var others = element("others");
    others.textContent = "";
    if (adjudication) {
      var entry = adjudication.items.filter(function (candidate) { return candidate.itemId === id; })[0];
      others.textContent = "Primary: " + describe(entry.primary) + " · Overlap: " + describe(entry.overlap);
    }
    var decision = current() || {};
    var labels = element("labels");
    labels.textContent = "";
    LABELS.forEach(function (pair) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = pair[0] + " " + pair[1];
      if (decision.label === pair[1]) { button.className = "chosen"; }
      button.addEventListener("click", function () { setDecision({ label: pair[1] }); });
      labels.appendChild(button);
    });
    element("reasonLine").style.display = decision.label === "unknown" ? "block" : "none";
    element("reason").value = decision.unknownReason || "";
    element("noteLine").style.display = adjudication ? "none" : "block";
    element("note").value = decision.note || "";
    var complete = queue.filter(function (candidate) { return valid(state.decisions[candidate]); }).length;
    element("progress").textContent = complete + " of " + queue.length + " decided";
    element("status").textContent = valid(decision) ? "" : "Not decided yet.";
  }

  function describe(human) {
    return human.label + (human.unknownReason ? " (" + human.unknownReason + ")" : "") + (human.note ? " — " + human.note : "");
  }

  function valid(decision) {
    return !!decision && !!decision.label && (decision.label !== "unknown" || !!decision.unknownReason);
  }

  function sortedObject(source) {
    var result = {};
    Object.keys(source).sort().forEach(function (key) { result[key] = source[key]; });
    return result;
  }

  function exportDecisions() {
    var missing = queue.filter(function (id) { return !valid(state.decisions[id]); });
    if (missing.length > 0) {
      element("status").textContent = missing.length + " item(s) still need a decision.";
      return;
    }
    var decisions = queue.slice().sort().map(function (id) {
      var decision = state.decisions[id];
      var out = adjudication ? { itemId: id, adjudicatedLabel: decision.label } : { itemId: id, label: decision.label };
      if (decision.label === "unknown") {
        out[adjudication ? "adjudicatedUnknownReason" : "unknownReason"] = decision.unknownReason;
      }
      if (!adjudication && decision.note) { out.note = decision.note; }
      return sortedObject(out);
    });
    var document_ = adjudication
      ? { decisions: decisions, overlapLabelsSha256: adjudication.overlapLabelsSha256, primaryLabelsSha256: adjudication.primaryLabelsSha256,
          sessionId: adjudication.sessionId }
      : { decisions: decisions, packSha256: pack.packSha256, reviewerName: (state.reviewer || "").trim() };
    var blob = new Blob([JSON.stringify(sortedObject(document_))], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = (adjudication ? "adjudication-decisions-" : "label-decisions-") + pack.packSha256.slice(0, 12) + ".json";
    link.click();
  }

  element("previous").addEventListener("click", function () { if (index > 0) { index -= 1; render(); } });
  element("next").addEventListener("click", function () { if (index < queue.length - 1) { index += 1; render(); } });
  element("reason").addEventListener("change", function (event) { setDecision({ unknownReason: event.target.value || undefined }); });
  element("note").addEventListener("change", function (event) {
    var note = event.target.value.replace(/[\r\n]+/g, " ").trim().slice(0, 200);
    setDecision({ note: note || undefined });
  });
  element("reviewer").addEventListener("change", function (event) { state.reviewer = event.target.value.trim(); save(); });
  element("export").addEventListener("click", exportDecisions);
  document.addEventListener("keydown", function (event) {
    if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "SELECT")) { return; }
    var match = LABELS.filter(function (pair) { return pair[0] === event.key; })[0];
    if (match && queue.length > 0) { setDecision({ label: match[1] }); }
    if (event.key === "ArrowRight" && index < queue.length - 1) { index += 1; render(); }
    if (event.key === "ArrowLeft" && index > 0) { index -= 1; render(); }
  });
  render();
}());
