/* IL2CPP Dumper Studio client - Mohamed Annati. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const state = { mode: "apk", files: { apk: null, so: null, dat: null, lib: null }, jobId: null, poller: null, nextLog: 0 };

  fetch("/api/health").then((r) => r.json()).then((d) => { if (d && d.version) $("#versionPill").textContent = "v" + d.version; }).catch(() => {});

  /* modes */
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => { t.classList.toggle("on", t === tab); t.setAttribute("aria-selected", t === tab ? "true" : "false"); });
      state.mode = tab.dataset.mode;
      $("#zoneApk").hidden = state.mode !== "apk";
      $("#zonePair").hidden = state.mode !== "pair";
      $("#zoneLib").hidden = state.mode !== "lib";
      $("#verRow").hidden = state.mode !== "lib";
      $("#abiRow").hidden = state.mode !== "apk" || !state.files.apk;
      const lib = state.mode === "lib";
      ["optDummy", "optStrings", "optOffsets"].forEach((id) => { $("#" + id).disabled = lib; $("#" + id).closest(".opt").style.opacity = lib ? ".45" : "1"; });
      refreshDump();
    });
  });

  /* drop zones */
  function wire(z, i, key) {
    const zone = $(z), input = $(i);
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-drag"));
    zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("is-drag"); if (e.dataTransfer.files.length) handle(e.dataTransfer.files, key, zone); });
    input.addEventListener("change", () => handle(input.files, key, zone));
  }
  wire("#zoneApk", "#fileApk", "apk"); wire("#zoneSo", "#fileSo", "so");
  wire("#zoneDat", "#fileDat", "dat"); wire("#zoneLib", "#fileLib", "lib");

  function handle(list, key, zone) {
    const file = list[0]; if (!file) return;
    zone.classList.add("is-filled");
    const form = new FormData(); form.append("file", file);
    setStatus("running", "Uploading…");
    fetch("/api/upload", { method: "POST", body: form }).then((r) => r.json()).then((d) => {
      if (!d.ok) { setStatus("error", "Upload failed"); return; }
      state.files[key] = d.files[0]; renderChips();
      if (key === "apk") probeAbis(state.files[key].path);
      setStatus("idle", "Ready"); refreshDump();
    }).catch(() => setStatus("error", "Upload error"));
  }

  function renderChips() {
    const box = $("#fileChips"); box.innerHTML = "";
    const labels = { apk: "APK", so: "libil2cpp.so", dat: "global-metadata.dat", lib: "lib-only" };
    for (const key in state.files) {
      const f = state.files[key]; if (!f) continue;
      const li = document.createElement("li"); li.className = "chip";
      li.innerHTML = "<span>" + labels[key] + "</span><strong>" + esc(f.name) + "</strong><span class='sz'>" + human(f.size) + "</span><button title='remove'>&times;</button>";
      li.querySelector("button").addEventListener("click", () => { state.files[key] = null; renderChips(); refreshDump(); if (key === "apk") $("#abiRow").hidden = true; });
      box.appendChild(li);
    }
  }

  function probeAbis(path) {
    fetch("/api/apk/abis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }) }).then((r) => r.json()).then((d) => {
      const row = $("#abiRow");
      if (d.ok && d.abis.length && state.mode === "apk") {
        const sel = $("#abiSelect"); sel.innerHTML = "";
        const pref = ["arm64-v8a", "armeabi-v7a", "x86_64", "x86"];
        d.abis.sort((a, b) => pref.indexOf(a) - pref.indexOf(b));
        d.abis.forEach((abi) => { const o = document.createElement("option"); o.value = abi; o.textContent = abi; sel.appendChild(o); });
        row.hidden = false;
      } else row.hidden = true;
    }).catch(() => { $("#abiRow").hidden = true; });
  }

  function refreshDump() {
    const f = state.files;
    $("#dumpBtn").disabled = state.mode === "apk" ? !f.apk : state.mode === "pair" ? !(f.so && f.dat) : !f.lib;
  }

  /* run */
  $("#dumpBtn").addEventListener("click", () => {
    const lib = state.mode === "lib", f = state.files;
    const payload = {
      libOnly: lib,
      apkPath: state.mode === "apk" ? (f.apk || {}).path : null,
      binaryPath: state.mode === "pair" ? (f.so || {}).path : lib ? (f.lib || {}).path : null,
      metadataPath: state.mode === "pair" ? (f.dat || {}).path : null,
      preferredAbi: $("#abiRow").hidden ? null : $("#abiSelect").value,
      il2cppVersion: lib ? $("#verSelect").value : null,
      outputDir: "dump",
      dummyDll: !lib && $("#optDummy").checked,
      scriptJson: $("#optScript").checked,
      il2cppHeader: $("#optHeader").checked,
      stringLiterals: !lib && $("#optStrings").checked,
      dump: { dumpFieldOffset: $("#optOffsets").checked, dumpMethodOffset: $("#optOffsets").checked }
    };
    $("#resultWrap").hidden = true; $("#errorBox").hidden = true; $("#logBox").innerHTML = "";
    state.nextLog = 0; setBusy(true); setStatus("running", "Running");
    fetch("/api/dump", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }).then((r) => r.json()).then((d) => {
      if (!d.ok) { setStatus("error", "Error"); setBusy(false); return; }
      state.jobId = d.jobId; startPolling();
    }).catch(() => { setBusy(false); setStatus("error", "Error"); });
  });

  function startPolling() { stopPolling(); state.poller = setInterval(poll, 400); poll(); }
  function stopPolling() { if (state.poller) { clearInterval(state.poller); state.poller = null; } }

  function poll() {
    if (!state.jobId) return;
    fetch("/api/status/" + state.jobId).then((r) => r.json()).then((d) => {
      if (!d.ok) return;
      $("#progressFill").style.width = Math.round(d.progress * 100) + "%";
      $("#progressPct").textContent = Math.round(d.progress * 100) + "%";
      const box = $("#logBox"), start = d.logStart || 0;
      if (state.nextLog < start) box.textContent += (box.textContent ? "\n" : "") + "…";
      for (let i = Math.max(0, state.nextLog - start); i < d.logs.length; i++)
        box.textContent += (box.textContent ? "\n" : "") + d.logs[i];
      state.nextLog = d.logCount || d.logs.length;
      box.scrollTop = box.scrollHeight;
      if (d.status === "running") return;
      stopPolling(); setBusy(false);
      if (d.status === "done") { setStatus("done", "Done"); renderResult(d.result); }
      else { setStatus("error", "Error"); const b = $("#errorBox"); b.hidden = false; b.textContent = d.error || "Unknown error."; }
    }).catch(() => {});
  }

  /* result */
  function renderResult(result) {
    $("#resultWrap").hidden = false;
    const s = result.stats || {}, grid = $("#statsGrid"), lib = state.mode === "lib";
    grid.innerHTML = "";
    const items = lib ? [
      { num: s.typeCount, lbl: "Types", ac: 1 }, { num: s.dumpedMethods, lbl: "Symbols" },
      { num: s.dumpedFields, lbl: "Offsets" }, { num: s.images, lbl: "Modules" },
      { num: s.il2cppVersion || "—", lbl: "il2cpp ver", ac: 1 }, { num: (s.binaryAbi || "").split("-")[0] || "—", lbl: "ABI" }
    ] : [
      { num: s.types, lbl: "Types", ac: 1 }, { num: s.dumpedMethods, lbl: "Methods" },
      { num: s.dumpedFields, lbl: "Fields" }, { num: s.images, lbl: "Images" },
      { num: s.metadataVersion, lbl: "Meta ver" }, { num: s.dummyDllCount, lbl: "DummyDll" }
    ];
    if (!lib && s.mode) items.push({ num: s.mode === "full" ? "FULL" : "META", lbl: "Mode", ac: 1 });
    if (!lib && s.binaryAbi) items.push({ num: s.binaryAbi.split("-")[0], lbl: "ABI" });
    items.forEach((it) => {
      const div = document.createElement("div"); div.className = "stat" + (it.ac ? " ac" : "");
      const num = (it.num == null) ? "—" : it.num;
      div.innerHTML = "<div class='num'>" + esc(String(num)) + "</div><div class='lbl'>" + esc(it.lbl) + "</div>";
      grid.appendChild(div);
    });

    const list = $("#fileList"); list.innerHTML = "";
    const icons = { "dump.cs": "📄", "il2cpp.h": "🧾", "script.json": "🧭", "stringliteral.json": "🔤", "DummyDll/": "📦", "lib-report.json": "🗒", "dump-manifest.json": "🗒" };
    let total = 0;
    (result.files || []).forEach((f) => {
      total += f.size || 0;
      const row = document.createElement("div"); row.className = "frow";
      row.innerHTML = "<span class='ico'>" + (icons[f.name] || "📁") + "</span><div><div class='nm'>" + esc(f.name) + "</div></div>" +
        "<span class='ds'>" + esc(f.description || "") + "</span><span class='sz'>" + human(f.size || 0) + "</span>" +
        "<a class='dl' href='/api/download/" + state.jobId + "/" + encodeURIComponent(f.name) + "' download>Download</a>";
      list.appendChild(row);
    });
    $("#totalSize").textContent = "Total output: " + human(total);
    $("#zipBtn").onclick = () => { window.location.href = "/api/download/" + state.jobId + "/all.zip"; };
    $("#previewWrap").style.display = lib ? "none" : "";
    $("#previewCode").style.display = lib ? "none" : "";
    if (!lib) loadPreview("");
  }

  let previewTimer = null;
  $("#previewSearch").addEventListener("input", (e) => { clearTimeout(previewTimer); previewTimer = setTimeout(() => loadPreview(e.target.value), 250); });
  function loadPreview(q) {
    if (!state.jobId) return;
    fetch("/api/preview/" + state.jobId + "?q=" + encodeURIComponent(q || "")).then((r) => r.json()).then((d) => { $("#previewCode").textContent = d.ok ? d.content : ""; }).catch(() => {});
  }

  /* helpers */
  function setBusy(busy) {
    $("#dumpBtn").classList.toggle("is-busy", busy);
    if (busy) $("#dumpBtnLabel").innerHTML = "Dumping…";
    else { $("#dumpBtnLabel").innerHTML = "&#9889; Dump IL2CPP"; refreshDump(); }
  }
  function setStatus(kind, text) {
    const b = $("#statusBadge");
    b.className = "status" + (kind !== "idle" ? " " + kind : "");
    b.textContent = text;
  }
  function human(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
    return (bytes / 1073741824).toFixed(2) + " GB";
  }
  function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
})();
