/* IL2CPP Dumper Studio - client.
 * Developed by Mohamed Annati.
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const state = {
    mode: "apk",
    files: { apk: null, so: null, dat: null },
    jobId: null,
    poller: null,
    lastLogIndex: 0,
  };

  /* ---------------- header version ---------------- */
  fetch("/api/health").then((r) => r.json()).then((d) => {
    if (d && d.version) $("#versionPill").textContent = "v" + d.version;
  }).catch(() => {});

  /* ---------------- tabs ---------------- */
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      state.mode = tab.dataset.mode;
      $("#zoneApk").hidden = state.mode !== "apk";
      $("#zonePair").hidden = state.mode !== "pair";
      refreshDumpButton();
    });
  });

  /* ---------------- drop zones ---------------- */
  function wireZone(zoneId, inputId, key) {
    const zone = $(zoneId);
    const input = $(inputId);
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-drag"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault(); zone.classList.remove("is-drag");
      if (e.dataTransfer.files && e.dataTransfer.files.length) handleFiles(e.dataTransfer.files, key, zone);
    });
    input.addEventListener("change", () => handleFiles(input.files, key, zone));
  }

  wireZone("#zoneApk", "#fileApk", "apk");
  wireZone("#zoneSo", "#fileSo", "so");
  wireZone("#zoneDat", "#fileDat", "dat");

  function handleFiles(fileList, key, zone) {
    const file = fileList[0];
    if (!file) return;
    zone.classList.add("is-filled");
    const form = new FormData();
    form.append("file", file);
    setStatus("uploading", "Uploading…");
    fetch("/api/upload", { method: "POST", body: form })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { setStatus("error", "Upload failed"); return; }
        state.files[key] = d.files[0];
        renderChips();
        if (key === "apk") probeAbis(state.files[key].path);
        refreshDumpButton();
        setStatus("idle", "Ready");
      })
      .catch((e) => { setStatus("error", "Upload error"); console.error(e); });
  }

  function renderChips() {
    const box = $("#fileChips");
    box.innerHTML = "";
    const labels = { apk: "APK", so: "libil2cpp.so", dat: "global-metadata.dat" };
    for (const key of Object.keys(state.files)) {
      const f = state.files[key];
      if (!f) continue;
      const li = document.createElement("li");
      li.className = "chip";
      li.innerHTML =
        "<span>" + labels[key] + "</span><strong>" + esc(f.name) + "</strong>" +
        "<span class='size'>" + human(f.size) + "</span><button title='remove'>&times;</button>";
      li.querySelector("button").addEventListener("click", () => {
        state.files[key] = null;
        renderChips(); refreshDumpButton();
        if (key === "apk") { $("#abiRow").hidden = true; }
      });
      box.appendChild(li);
    }
  }

  function probeAbis(path) {
    fetch("/api/apk/abis", { method: "POST", headers: { "Content-Type": "application/json" },
                           body: JSON.stringify({ path }) })
      .then((r) => r.json())
      .then((d) => {
        const row = $("#abiRow");
        if (d.ok && d.abis && d.abis.length) {
          const sel = $("#abiSelect");
          sel.innerHTML = "";
          const pref = ["arm64-v8a", "armeabi-v7a", "x86_64", "x86"];
          d.abis.sort((a, b) => pref.indexOf(a) - pref.indexOf(b));
          d.abis.forEach((abi) => {
            const o = document.createElement("option");
            o.value = abi; o.textContent = abi;
            sel.appendChild(o);
          });
          row.hidden = false;
        } else {
          row.hidden = true;
        }
      }).catch(() => { $("#abiRow").hidden = true; });
  }

  function refreshDumpButton() {
    let ready;
    if (state.mode === "apk") ready = !!state.files.apk;
    else ready = !!state.files.so && !!state.files.dat;
    $("#dumpBtn").disabled = !ready;
  }

  /* ---------------- run ---------------- */
  $("#dumpBtn").addEventListener("click", () => {
    const payload = {
      apkPath: state.mode === "apk" ? (state.files.apk || {}).path : null,
      binaryPath: state.mode === "pair" ? (state.files.so || {}).path : null,
      metadataPath: state.mode === "pair" ? (state.files.dat || {}).path : null,
      preferredAbi: $("#abiRow").hidden ? null : $("#abiSelect").value,
      outputDir: "dump",
      dummyDll: $("#optDummy").checked,
      scriptJson: $("#optScript").checked,
      il2cppHeader: $("#optHeader").checked,
      stringLiterals: $("#optStrings").checked,
      dump: { dumpFieldOffset: $("#optOffsets").checked,
              dumpMethodOffset: $("#optOffsets").checked },
    };

    $("#resultWrap").hidden = true;
    $("#errorBox").hidden = true;
    $("#logBox").innerHTML = "";
    state.lastLogIndex = 0;
    setBusy(true);
    setStatus("running", "Running");

    fetch("/api/dump", { method: "POST", headers: { "Content-Type": "application/json" },
                       body: JSON.stringify(payload) })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { setStatus("error", "Error"); setBusy(false); return; }
        state.jobId = d.jobId;
        startPolling();
      })
      .catch((e) => { console.error(e); setBusy(false); setStatus("error", "Error"); });
  });

  function startPolling() {
    stopPolling();
    state.poller = setInterval(poll, 400);
    poll();
  }
  function stopPolling() { if (state.poller) { clearInterval(state.poller); state.poller = null; } }

  function poll() {
    if (!state.jobId) return;
    fetch("/api/status/" + state.jobId).then((r) => r.json()).then((d) => {
      if (!d.ok) return;
      $("#progressFill").style.width = Math.round(d.progress * 100) + "%";
      $("#progressPct").textContent = Math.round(d.progress * 100) + "%";

      const logBox = $("#logBox");
      for (let i = state.lastLogIndex; i < d.logs.length; i++) {
        logBox.textContent += (logBox.textContent ? "\n" : "") + d.logs[i];
      }
      state.lastLogIndex = d.logs.length;
      logBox.scrollTop = logBox.scrollHeight;

      if (d.status === "running") return;

      stopPolling();
      setBusy(false);
      if (d.status === "done") {
        setStatus("done", "Done");
        renderResult(d.result);
      } else {
        setStatus("error", "Error");
        const box = $("#errorBox");
        box.hidden = false;
        box.textContent = d.error || "Unknown error.";
      }
    }).catch(() => {});
  }

  /* ---------------- result ---------------- */
  function renderResult(result) {
    $("#resultWrap").hidden = false;
    const s = result.stats || {};
    const grid = $("#statsGrid");
    grid.innerHTML = "";
    const stats = [
      { num: s.types, lbl: "Types", accent: true },
      { num: s.dumpedMethods, lbl: "Methods" },
      { num: s.dumpedFields, lbl: "Fields" },
      { num: s.images, lbl: "Images" },
      { num: s.metadataVersion, lbl: "Meta ver" },
      { num: s.dummyDllCount, lbl: "DummyDll" },
    ];
    if (s.mode) stats.push({ num: s.mode === "full" ? "FULL" : "META", lbl: "Mode", accent: true });
    if (s.binaryAbi) stats.push({ num: s.binaryAbi.split("-")[0], lbl: "ABI" });
    stats.forEach((item) => {
      const div = document.createElement("div");
      div.className = "stat" + (item.accent ? " accent" : "");
      const num = (item.num === undefined || item.num === null) ? "—" : item.num;
      div.innerHTML = "<div class='num'>" + esc(String(num)) + "</div><div class='lbl'>" + esc(item.lbl) + "</div>";
      grid.appendChild(div);
    });

    const list = $("#fileList");
    list.innerHTML = "";
    const icons = { "dump.cs": "📄", "il2cpp.h": "🧾", "script.json": "🧭",
                    "stringliteral.json": "🔤", "DummyDll/": "", "dump-manifest.json": "🗒" };
    (result.files || []).forEach((f) => {
      const row = document.createElement("div");
      row.className = "file-row";
      const download = f.kind === "folder" ? f.name : f.name;
      row.innerHTML =
        "<span class='ico'>" + (icons[f.name] || "📁") + "</span>" +
        "<div><div class='name'>" + esc(f.name) + "</div></div>" +
        "<span class='desc'>" + esc(f.description || "") + "</span>" +
        "<span class='size'>" + human(f.size || 0) + "</span>" +
        "<a class='dl' href='/api/download/" + state.jobId + "/" + encodeURIComponent(download) + "' download>Download</a>";
      list.appendChild(row);
    });

    $("#zipBtn").onclick = () => {
      window.location.href = "/api/download/" + state.jobId + "/all.zip";
    };

    loadPreview("");
  }

  let previewTimer = null;
  $("#previewSearch").addEventListener("input", (e) => {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => loadPreview(e.target.value), 250);
  });

  function loadPreview(query) {
    if (!state.jobId) return;
    fetch("/api/preview/" + state.jobId + "?q=" + encodeURIComponent(query || ""))
      .then((r) => r.json())
      .then((d) => { $("#previewCode").textContent = d.ok ? d.content : ""; })
      .catch(() => {});
  }

  /* ---------------- helpers ---------------- */
  function setBusy(busy) {
    const btn = $("#dumpBtn");
    btn.classList.toggle("is-busy", busy);
    btn.disabled = busy ? false : false;
    if (busy) {
      btn.disabled = false;
      $("#dumpBtnLabel").textContent = "Dumping…";
    } else {
      $("#dumpBtnLabel").textContent = "Dump IL2CPP";
      refreshDumpButton();
    }
  }

  function setStatus(kind, text) {
    const badge = $("#statusBadge");
    badge.className = "status" + (kind !== "idle" ? " " + kind : "");
    badge.textContent = text;
  }

  function human(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    if (bytes < 1024 * 1024 * 1024) return (bytes / 1048576).toFixed(1) + " MB";
    return (bytes / 1073741824).toFixed(2) + " GB";
  }

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
})();
