<div align="center">

<img src="assets/brand/icon-256.png" width="128" alt="IL2CPP Dumper Studio logo">

# IL2CPP Dumper Studio

**Turn a Unity Android APK into readable C#.**

A complete, dependency-free IL2CPP dumper for Android builds — with a modern
web studio, a Google-Colab notebook, a CLI, and an on-device Android app.

**Developed by Mohamed Annati**

[Quick start](#quick-start) · [Web studio](#web-studio) · [Colab](#google-colab) · [CLI](#command-line) · [Android](#android-app) · [Outputs](#outputs) · [What's new](#whats-new--change-log)

</div>

---

## What it does

Upload **`libil2cpp.so` + `global-metadata.dat`** — or just the **`.apk` / `.xapk` / `.aab`** —
and get back everything a reverse-engineer needs:

| Output | Purpose |
|---|---|
| `dump.cs` | C# pseudo-code of every type: methods, fields, properties, events, RVAs, field offsets |
| `DummyDll/` | Rebuilt .NET assemblies you can open in **dnSpy / ILSpy** |
| `il2cpp.h` | Runtime structures + ECMA-335 constants for **IDA / Ghidra** |
| `script.json` | Symbol + string table to auto-rename everything in IDA / Ghidra |
| `stringliteral.json` | Every managed string literal in the game |
| `lib-report.json` | Metadata-free analysis of the native binary (lib-only mode) |
| `dump-manifest.json` | Machine-readable summary of the run |

The core is **pure Python** (no dependencies). It parses metadata versions **16–31**,
supports **ELF32/ELF64** (`armeabi-v7a`, `arm64-v8a`, `x86`, `x86_64`) and **PE**
(`GameAssembly.dll`), applies relocations, locates the `CodeRegistration` /
`MetadataRegistration` tables (symbol *and* heuristic search), resolves the full
`Il2CppType` table (generics, arrays, pointers, by-refs), and rebuilds valid
ECMA-335 assemblies.

If the native binary can't be analysed (encrypted metadata, packed `.so`), it
gracefully falls back to **metadata-only mode** and still produces a useful
`dump.cs` — and tells you exactly why.

Every front end (web / Android) also offers a **lib-only mode**: give it just the
`libil2cpp.so` (no metadata) and it recovers the ELF structure, exported symbols
and registration tables, writing `il2cpp.h`, `script.json` and `lib-report.json`.

---

## Quick start

```bash
git clone https://github.com/Mohamed2020p/mainproject && cd mainproject
python3 run.py cli game.apk -o dump          # dump straight from an APK
```

See [installl.txt](installl.txt) for the full, copy-paste recipe for Colab,
local, and Android-APK builds.

---

## Web studio

```bash
pip install -r requirements.txt
python3 run.py               # -> http://localhost:8050
```

Drag-and-drop an APK (or a `.so` + `.dat` pair), pick an ABI, press **Dump**,
watch live progress + logs, browse stats, search the `dump.cs` preview and
download every artefact or a single zip. A third **".so only"** tab runs the
metadata-free lib-only analysis, with an il2cpp-version selector
(auto-detect by default).

The studio now ships a proper identity: an SVG logo/favicon, `favicon.ico`,
apple-touch + PWA icons and a `site.webmanifest` (installable), and a Poppins
UI. The header logo no longer 404s, the live log no longer drops lines past 400,
and results show the total output size.

<p><img src="assets/brand/preview.png" alt="web studio preview" width="560"></p>

---

## Google Colab

Open [`colab/IL2CPP_Dumper_Studio.ipynb`](colab/IL2CPP_Dumper_Studio.ipynb) in
Colab and run the cells — it clones the repo, installs Flask and launches the
web studio through the Colab reverse proxy. Nothing leaves the VM.

To **build the Android APK on Colab**, open
[`colab/Build_APK_on_Colab.ipynb`](colab/Build_APK_on_Colab.ipynb) — it installs
JDK 17 + Android SDK 34 + Gradle 8.7 (reusing them on re-runs), builds the
release APK and downloads it. See the [Android](#android-app) section.

---

## Command line

```
usage: il2cpp-dumper <apk | libil2cpp.so global-metadata.dat> [-o dump] [--abi ABI]
                     [--no-dummy-dll] [--no-script-json] [--no-il2cpp-header]
                     [--no-string-literals] [--no-field-offset] [--no-method-offset]
```

```bash
python3 -m dumper.cli game.apk -o dump --abi arm64-v8a
python3 -m dumper.cli libil2cpp.so global-metadata.dat -o dump
```

---

## Android app

A complete, buildable Kotlin app in [`android/`](android/) with a Material 3
dark UI and the same hexagon + `</>` brand as the web studio. On-device it can:

* pick an **APK / `.so` + `.dat`** and produce `dump.cs`, `stringliteral.json`
  and `il2cpp.h` (metadata mode),
* run **lib-only mode** (checkbox) from a `.so` or straight from an APK — no
  metadata needed,
* open a **hex viewer** to inspect and patch any dumped / selected file,
* handle **>1 GB** binaries via memory mapping without crashing.

On-device outputs and the app credit line are stamped **@c0derz**.

```bash
./scripts/build_apk.sh       # or see installl.txt / colab/Build_APK_on_Colab.ipynb
```

---

## Tests

```bash
python3 tests/test_dumper.py
```

The suite builds a synthetic-but-real `libil2cpp.so` + `global-metadata.dat`
pair and runs the actual parser/writers over it — 24 tests covering metadata
parsing, ELF loading, the registration-table search, type resolution,
`dump.cs`, `script.json`, APK extraction and the DummyDll PE/CLI writer.

---

## What's new / change log

### Web studio
* `app/templates/index.html`, `app/static/css/style.css`, `app/static/js/app.js`
  — Poppins redesign, third **".so only"** tab + il2cpp-version select, toggle
  switches, focus/reduced-motion accessibility, total-output-size readout. The
  three files stay at or under their original byte sizes.
* `app/server.py` — lib-only wiring, serves the new `favicon.ico`, adds
  `logStart`/`logCount` (fixes the log dropping lines past 400) and purges stale
  `.uploads` on startup so repeated dumps don't grow the folder.
* New `dumper/lib_only.py` — metadata-free analysis (auto-detects the il2cpp
  version, resolves registration tables, emits `il2cpp.h` + `script.json` +
  `lib-report.json`). Core dumper untouched.
* New `app/make_icons.py` + regenerated `app/static/img/*` + `site.webmanifest`
  — real SVG logo/favicon, `favicon.ico`, apple-touch, PWA and maskable icons
  (the icon set shrank ~79 KB → ~35 KB and the header logo no longer 404s).

### Android app
* `dumper/Structs.kt` — fixed `METADATA_SANITY` to `-89056337` (`0xFAB11BAF`
  signed). The previous wrong constant made **every valid** `global-metadata.dat`
  fail with "may be encrypted".
* New `dumper/LibOnly.kt` — on-device lib-only ELF analysis over a read-only
  memory map (>1 GB-safe, fully guarded so it degrades instead of crashing).
* New `HexViewerActivity.kt` + `res/layout/activity_hex.xml` — windowed
  hex/ASCII viewer with a single-byte patcher.
* `MainActivity.kt`, `res/layout/activity_main.xml`, `res/values/strings.xml`,
  `AndroidManifest.xml` — ".so only" picker, lib-only checkbox, hex-viewer
  button, `@c0derz` credit.
* `dumper/DumpWriter.kt` — on-device output headers credit `@c0derz`.

### Build tooling
* New `colab/Build_APK_on_Colab.ipynb` — ready-to-run APK build on Colab
  (forces JDK 17, silences the Colab cgroup/`jmod` issue, reuses SDK/Gradle,
  find-based APK copy, optional full-wipe cleanup cell).

---

## Repository map

```
dumper/            pure-Python dumper engine (metadata, binary, outputs)
  binary/          ELF / PE readers + registration-table search
  outputs/         dump.cs, il2cpp.h, script.json, stringliteral.json, DummyDll
  lib_only.py      metadata-free (".so only") analysis used by the web studio
app/               Flask web studio (templates / css / js)
  make_icons.py    regenerates web + Android icons from one vector mark
colab/             Google Colab notebooks (web studio + APK build)
android/           Android Studio app (Kotlin, Material 3, lib-only + hex viewer)
tests/             pytest/unittest suite + synthetic fixture
assets/brand/      logo.svg + generated PNGs / Android mipmaps
scripts/           build_apk.sh
installl.txt       install / deploy / build cheat-sheet
```

---

> For educational reverse-engineering of software you own or are licensed to analyse.
