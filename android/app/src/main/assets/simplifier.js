/*
 * ChartSimplifier core - JavaScript port of simplifier.py.
 *
 * Strips an ADOFAI level down to its layout: removes decorations (except text),
 * visual events (except Move Camera / Set Frame Rate), resets background
 * settings, removes the video background, drops unreferenced image/video files.
 * Behaviour is kept byte-for-byte in sync with the Python version (validated by
 * a Node parity test against real charts).
 *
 * Works in a browser/WebView (attaches to window.ChartSimplifier) and in Node
 * (module.exports). Zip handling needs JSZip to be available.
 */
(function (root) {
  "use strict";

  // -------------------------------------------------------------------------
  // Event classification (eventType values as they appear in .adofai files)
  // -------------------------------------------------------------------------
  var KEEP_EVENTS = new Set([
    // Gameplay
    "SetSpeed", "Twirl", "Checkpoint", "SetHitsound", "PlaySound",
    "SetPlanetRotation", "Pause", "AutoPlayTiles", "ScalePlanets",
    // Track
    "MoveTrack", "PositionTrack", "AnimateTrack", "ColorTrack", "RecolorTrack",
    // Text decoration events (the only decoration events kept)
    "SetText", "SetDefaultText",
    // Allowed visual events
    "MoveCamera", "SetFrameRate",
    // Event modifiers
    "RepeatEvents", "SetConditionalEvents",
    // Conveniences
    "EditorComment", "Bookmark",
    // DLC / gameplay extensions
    "Hold", "SetHoldSound", "MultiPlanet",
    "FreeRoam", "FreeRoamTwirl", "FreeRoamRemove",
    "Hide", "ScaleMargin", "ScaleRadius"
  ]);

  var REMOVE_EVENTS = new Set([
    // Decoration events
    "AddDecoration", "AddObject", "AddParticle", "AddText",
    "MoveDecorations", "EmitParticle", "SetParticle", "SetObject",
    // Visual events
    "Flash", "SetFilter", "SetFilterAdvanced", "HallOfMirrors",
    "ShakeScreen", "Bloom", "ScreenTile", "ScreenScroll",
    "CustomBackground", "SetBackground"
  ]);

  // Decoration events counted as "decoration" (vs "visual") in the log
  var DECO_EVENTS = new Set([
    "AddDecoration", "AddObject", "AddParticle", "AddText",
    "MoveDecorations", "EmitParticle", "SetParticle", "SetObject"
  ]);

  var KEEP_DECORATIONS = new Set(["AddText"]);

  // Fresh-level defaults (version 18) - Background Settings tab
  var BACKGROUND_DEFAULTS = {
    backgroundColor: "000000",
    showDefaultBGIfNoImage: true,
    showDefaultBGTile: true,
    defaultBGTileColor: "101121",
    defaultBGShapeType: "Default",
    defaultBGShapeColor: "ffffff",
    bgImage: "",
    bgImageColor: "ffffff",
    parallax: [100, 100],
    bgDisplayMode: "FitToScreen",
    imageSmoothing: true,
    lockRot: false,
    loopBG: false,
    scalingRatio: 100
  };

  // Fresh-level defaults - the video background part of Misc Settings
  var VIDEO_DEFAULTS = { bgVideo: "", loopVideo: false, vidOffset: 0 };

  // Fresh-level defaults - track color/style (track animation keys left alone)
  var TRACK_COLOR_DEFAULTS = {
    trackColorType: "Single",
    trackColor: "debb7b",
    secondaryTrackColor: "ffffff",
    trackColorAnimDuration: 2,
    trackColorPulse: "None",
    trackPulseLength: 10,
    trackStyle: "Standard",
    trackTexture: "",
    trackTextureScale: 1,
    trackGlowIntensity: 100
  };

  // Camera Settings defaults (used when "keep camera movements" is off) -
  // fresh-level values except zoom, which is set to 150%
  var CAMERA_DEFAULTS = {
    relativeTo: "Player",
    position: [0, 0],
    rotation: 0,
    zoom: 150,
    pulseOnFloor: true
  };

  var IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"]);
  var VIDEO_EXTS = new Set([".mp4", ".avi", ".webm", ".mov", ".mkv", ".wmv", ".flv", ".m4v"]);

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------
  function valuesEqual(a, b) {
    // Deep value equality mirroring Python's == for the default values we use
    // (primitives and flat number arrays).
    if (Array.isArray(a) && Array.isArray(b)) {
      if (a.length !== b.length) return false;
      for (var i = 0; i < a.length; i++) {
        if (!valuesEqual(a[i], b[i])) return false;
      }
      return true;
    }
    return a === b;
  }

  function clone(value) {
    return Array.isArray(value) ? value.slice() : value;
  }

  function extLower(name) {
    var dot = name.lastIndexOf(".");
    var slash = Math.max(name.lastIndexOf("/"), name.lastIndexOf("\\"));
    if (dot <= slash) return "";
    return name.slice(dot).toLowerCase();
  }

  function baseName(path) {
    var norm = path.replace(/\\/g, "/");
    var parts = norm.split("/");
    return parts[parts.length - 1];
  }

  // -------------------------------------------------------------------------
  // Tolerant .adofai parsing (matches simplifier.py load_adofai)
  // -------------------------------------------------------------------------
  function decodeBytes(bytes) {
    // bytes: Uint8Array. Try utf-8-sig, utf-16, utf-8 (as Python does).
    if (bytes.length >= 3 && bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF) {
      return new TextDecoder("utf-8").decode(bytes.subarray(3));
    }
    if (bytes.length >= 2 && bytes[0] === 0xFF && bytes[1] === 0xFE) {
      return new TextDecoder("utf-16le").decode(bytes.subarray(2));
    }
    if (bytes.length >= 2 && bytes[0] === 0xFE && bytes[1] === 0xFF) {
      return new TextDecoder("utf-16be").decode(bytes.subarray(2));
    }
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch (e) {
      return new TextDecoder("utf-8").decode(bytes);
    }
  }

  // Escape raw control characters that ADOFAI writes inside strings (multiline
  // editor comments etc). JSON.parse is strict and rejects them, whereas
  // Python's json.loads(strict=False) accepts them - this preprocessing gives
  // JSON.parse the same tolerance.
  function escapeControlCharsInStrings(text) {
    var out = "";
    var inString = false;
    var escaped = false;
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      var code = text.charCodeAt(i);
      if (inString) {
        if (escaped) {
          out += ch;
          escaped = false;
        } else if (ch === "\\") {
          out += ch;
          escaped = true;
        } else if (ch === "\"") {
          out += ch;
          inString = false;
        } else if (code < 0x20) {
          if (ch === "\n") out += "\\n";
          else if (ch === "\t") out += "\\t";
          else if (ch === "\r") out += "\\r";
          else if (ch === "\b") out += "\\b";
          else if (ch === "\f") out += "\\f";
          else out += "\\u" + ("0000" + code.toString(16)).slice(-4);
        } else {
          out += ch;
        }
      } else {
        out += ch;
        if (ch === "\"") inString = true;
      }
    }
    return out;
  }

  function parsePosition(message) {
    var m = /position (\d+)/.exec(message);
    return m ? parseInt(m[1], 10) : -1;
  }

  function loadAdofai(input) {
    // input: Uint8Array or string
    var text = (typeof input === "string") ? input : decodeBytes(input);
    text = escapeControlCharsInStrings(text);

    try {
      return JSON.parse(text);
    } catch (e) { /* fall through to repair */ }

    // Remove trailing commas before } or ]
    var cleaned = text.replace(/,(\s*[}\]])/g, "$1");

    // ADOFAI writes files with missing commas (e.g. between the "actions" array
    // and "decorations"). Insert them where parsing fails.
    for (var n = 0; n < 100000; n++) {
      try {
        return JSON.parse(cleaned);
      } catch (err) {
        var msg = String(err.message || "");
        // V8 missing-delimiter errors: "Expected ',' or ']' after array
        // element..." / "Expected ',' or '}' after property value..."
        if (/Expected ',' or/.test(msg)) {
          var pos = parsePosition(msg);
          if (pos < 0) throw err;
          cleaned = cleaned.slice(0, pos) + "," + cleaned.slice(pos);
        } else {
          throw err;
        }
      }
    }
    throw new Error("Could not repair chart file - too many JSON errors");
  }

  function dumpAdofai(data) {
    return JSON.stringify(data, null, 2);
  }

  // -------------------------------------------------------------------------
  // Chart simplification (matches simplifier.py simplify_chart)
  // -------------------------------------------------------------------------
  function simplifyChart(data, options) {
    options = options || {};
    var keepTrackColor = options.keep_track_color !== false;
    var keepCamera = options.keep_camera !== false;
    var stats = {
      visual_removed: 0, deco_events_removed: 0,
      track_color_removed: 0, camera_removed: 0,
      kept: 0, unknown_kept: 0, decorations_removed: 0, text_kept: 0,
      bg_reset: false, video_removed: false,
      track_reset: false, camera_reset: false
    };

    // --- Tile events ---
    var actions = data.actions;
    if (Array.isArray(actions)) {
      var keptActions = [];
      for (var i = 0; i < actions.length; i++) {
        var event = actions[i];
        var etype = (event && typeof event === "object" && !Array.isArray(event))
          ? (event.eventType || "") : "";
        if (KEEP_DECORATIONS.has(etype) && event && ("decText" in event)) {
          keptActions.push(event);
          stats.text_kept++;
        } else if (!keepTrackColor && (etype === "ColorTrack" || etype === "RecolorTrack")) {
          stats.track_color_removed++;
        } else if (!keepCamera && etype === "MoveCamera") {
          stats.camera_removed++;
        } else if (REMOVE_EVENTS.has(etype)) {
          if (DECO_EVENTS.has(etype)) stats.deco_events_removed++;
          else stats.visual_removed++;
        } else if (KEEP_EVENTS.has(etype)) {
          keptActions.push(event);
          stats.kept++;
        } else {
          // Unknown event type - keep it so gameplay is never broken
          keptActions.push(event);
          stats.unknown_kept++;
        }
      }
      data.actions = keptActions;
    }

    // --- Decorations array (images, objects, particles, text) ---
    var decorations = data.decorations;
    if (Array.isArray(decorations)) {
      var keptDecorations = [];
      for (var d = 0; d < decorations.length; d++) {
        var deco = decorations[d];
        var dtype = (deco && typeof deco === "object" && !Array.isArray(deco))
          ? (deco.eventType || "") : "";
        if (KEEP_DECORATIONS.has(dtype)) {
          keptDecorations.push(deco);
          stats.text_kept++;
        } else {
          stats.decorations_removed++;
        }
      }
      data.decorations = keptDecorations;
    }

    // --- Settings ---
    var settings = data.settings;
    if (settings && typeof settings === "object" && !Array.isArray(settings)) {
      var key;
      for (key in BACKGROUND_DEFAULTS) {
        if (key in settings && !valuesEqual(settings[key], BACKGROUND_DEFAULTS[key])) {
          settings[key] = clone(BACKGROUND_DEFAULTS[key]);
          stats.bg_reset = true;
        }
      }
      var hadVideo = !!settings.bgVideo;
      for (key in VIDEO_DEFAULTS) {
        if (key in settings) settings[key] = clone(VIDEO_DEFAULTS[key]);
      }
      stats.video_removed = hadVideo;
      if (!keepTrackColor) {
        for (key in TRACK_COLOR_DEFAULTS) {
          if (key in settings && !valuesEqual(settings[key], TRACK_COLOR_DEFAULTS[key])) {
            settings[key] = clone(TRACK_COLOR_DEFAULTS[key]);
            stats.track_reset = true;
          }
        }
      }
      if (!keepCamera) {
        for (key in CAMERA_DEFAULTS) {
          if (key in settings && !valuesEqual(settings[key], CAMERA_DEFAULTS[key])) {
            settings[key] = clone(CAMERA_DEFAULTS[key]);
            stats.camera_reset = true;
          }
        }
      }
    }

    return stats;
  }

  function collectReferencedFiles(data, refs) {
    refs = refs || new Set();
    (function walk(node) {
      if (Array.isArray(node)) {
        for (var i = 0; i < node.length; i++) walk(node[i]);
      } else if (node && typeof node === "object") {
        for (var k in node) if (Object.prototype.hasOwnProperty.call(node, k)) walk(node[k]);
      } else if (typeof node === "string" && node) {
        var name = baseName(node).trim().toLowerCase();
        if (name) refs.add(name);
      }
    })(data);
    return refs;
  }

  // -------------------------------------------------------------------------
  // Zip level handling (matches simplifier.py simplify_level, zip in/out)
  // -------------------------------------------------------------------------
  function noop() {}

  // Determine the shallowest directory containing a .adofai, like
  // find_level_root. entryPaths: array of forward-slash paths (files only).
  function findLevelRoot(chartPaths) {
    // chartPaths sorted; pick the one whose parent has fewest segments.
    var sorted = chartPaths.slice().sort();
    var best = null;
    var bestParts = Infinity;
    for (var i = 0; i < sorted.length; i++) {
      var parent = sorted[i].indexOf("/") >= 0
        ? sorted[i].slice(0, sorted[i].lastIndexOf("/")) : "";
      var parts = parent === "" ? 0 : parent.split("/").length;
      if (parts < bestParts) {
        bestParts = parts;
        best = parent;
      }
    }
    return best === null ? "" : best;
  }

  /*
   * simplifyLevelFromZip(zipBytes, options, log, fallbackName)
   *   zipBytes: Uint8Array/ArrayBuffer of the input .zip
   *   options: { keep_track_color, keep_camera }
   *   log: function(string)
   *   fallbackName: level name to use if the level sits at the zip root
   * Returns a Promise resolving to { name, blob } where name is the output
   * folder/zip base name ("<level> - Simplified") and blob is the zip Blob.
   */
  function simplifyLevelFromZip(zipBytes, options, log, fallbackName) {
    log = log || noop;
    var JSZipLib = root.JSZip || (typeof require === "function" ? require("jszip") : null);
    if (!JSZipLib) return Promise.reject(new Error("JSZip is not available"));

    return JSZipLib.loadAsync(zipBytes).then(function (zip) {
      // Some Windows zip tools store paths with backslashes; normalise to "/"
      // for all logic and output, but keep the original name to fetch bytes.
      var fileEntries = [];   // normalised forward-slash paths
      var origOf = {};        // normalised path -> original stored name
      zip.forEach(function (relPath, entry) {
        if (entry.dir) return;
        var norm = relPath.replace(/\\/g, "/");
        fileEntries.push(norm);
        origOf[norm] = relPath;
      });
      var chartPaths = fileEntries.filter(function (p) {
        return p.toLowerCase().endsWith(".adofai");
      });
      if (chartPaths.length === 0) {
        throw new Error("No .adofai file found - is this an ADOFAI level?");
      }

      var levelRoot = findLevelRoot(chartPaths);
      var levelName = levelRoot === ""
        ? (fallbackName || "Level")
        : baseName(levelRoot);
      log("Level found: " + levelName);

      var prefix = levelRoot === "" ? "" : levelRoot + "/";
      // Only include entries under the level root (mirrors rglob on level_root)
      var included = fileEntries.filter(function (p) {
        return prefix === "" || p.indexOf(prefix) === 0;
      });

      var chartSet = {};
      chartPaths.forEach(function (p) { chartSet[p] = true; });

      // Simplify every chart, gather referenced files and totals.
      var totals = newTotals();
      var referenced = new Set();
      var simplified = {}; // path -> serialized text
      var chartOrder = included.filter(function (p) { return chartSet[p]; }).sort();

      var chain = Promise.resolve();
      chartOrder.forEach(function (p) {
        chain = chain.then(function () {
          return zip.file(origOf[p]).async("uint8array").then(function (bytes) {
            var data = loadAdofai(bytes);
            var stats = simplifyChart(data, options);
            simplified[p] = dumpAdofai(data);
            collectReferencedFiles(data, referenced);
            addTotals(totals, stats);
          });
        });
      });

      return chain.then(function () {
        logTotals(log, totals, chartOrder.length);

        var outName = levelName + " - Simplified";
        var out = new JSZipLib();
        var skipped = 0;

        var includeSorted = included.slice().sort();
        var addChain = Promise.resolve();
        includeSorted.forEach(function (p) {
          addChain = addChain.then(function () {
            var rel = prefix === "" ? p : p.slice(prefix.length);
            var arc = outName + "/" + rel;
            if (chartSet[p]) {
              out.file(arc, simplified[p]);
              return;
            }
            var ext = extLower(p);
            if ((IMAGE_EXTS.has(ext) || VIDEO_EXTS.has(ext)) &&
                !referenced.has(baseName(p).trim().toLowerCase())) {
              skipped++;
              return;
            }
            return zip.file(origOf[p]).async("uint8array").then(function (bytes) {
              out.file(arc, bytes);
            });
          });
        });

        return addChain.then(function () {
          if (skipped) log("Deleted " + skipped + " unused image/video file(s) from the level folder");
          return out.generateAsync({
            type: "blob",
            compression: "DEFLATE",
            compressionOptions: { level: 6 }
          }).then(function (blob) {
            log("Done! Saved: " + outName + ".zip");
            return { name: outName, blob: blob };
          });
        });
      });
    });
  }

  function newTotals() {
    return {
      visual_removed: 0, deco_events_removed: 0,
      track_color_removed: 0, camera_removed: 0,
      kept: 0, unknown_kept: 0, decorations_removed: 0, text_kept: 0,
      bg_reset: false, video_removed: false,
      track_reset: false, camera_reset: false
    };
  }

  function addTotals(totals, stats) {
    for (var k in stats) {
      if (typeof stats[k] === "boolean") totals[k] = totals[k] || stats[k];
      else totals[k] += stats[k];
    }
  }

  function logTotals(log, totals, chartCount) {
    log("Processed " + chartCount + " chart file(s)");
    if (totals.decorations_removed) log("Removed " + totals.decorations_removed + " decorations (images, objects, particles)");
    if (totals.deco_events_removed) log("Removed " + totals.deco_events_removed + " decoration events from tiles");
    if (totals.visual_removed) log("Removed " + totals.visual_removed + " visual events (flash, filters, bloom, shake...)");
    if (totals.text_kept) log("Kept " + totals.text_kept + " text decorations");
    log("Kept " + totals.kept + " gameplay/track/camera events");
    if (totals.unknown_kept) log("Kept " + totals.unknown_kept + " unrecognized events (left untouched for safety)");
    if (totals.track_color_removed) log("Removed " + totals.track_color_removed + " track color events");
    if (totals.camera_removed) log("Removed " + totals.camera_removed + " camera movement events");
    if (totals.bg_reset) log("Reset background settings to fresh-level defaults");
    if (totals.track_reset) log("Reset track color settings to default");
    if (totals.camera_reset) log("Reset camera settings to default (zoom 150%)");
    if (totals.video_removed) log("Removed video background");
  }

  var api = {
    KEEP_EVENTS: KEEP_EVENTS,
    REMOVE_EVENTS: REMOVE_EVENTS,
    loadAdofai: loadAdofai,
    dumpAdofai: dumpAdofai,
    decodeBytes: decodeBytes,
    simplifyChart: simplifyChart,
    collectReferencedFiles: collectReferencedFiles,
    findLevelRoot: findLevelRoot,
    simplifyLevelFromZip: simplifyLevelFromZip
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ChartSimplifier = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
