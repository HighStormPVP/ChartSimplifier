"""ChartSimplifier core - strips an ADOFAI level down to its layout.

Takes a level folder or zip, removes all decorations (except text), all visual
events (except Move Camera / Set Frame Rate), resets background settings to the
fresh-level defaults, removes the video background, and drops image/video files
that are no longer referenced. Gameplay, track, DLC, convenience and modifier
events are untouched. Output is "<level folder> - Simplified.zip" written next
to the original.
"""

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Event classification (eventType values as they appear in .adofai files)
# ---------------------------------------------------------------------------

KEEP_EVENTS = {
    # Gameplay
    "SetSpeed", "Twirl", "Checkpoint", "SetHitsound", "PlaySound",
    "SetPlanetRotation", "Pause", "AutoPlayTiles", "ScalePlanets",
    # Track
    "MoveTrack", "PositionTrack", "AnimateTrack", "ColorTrack", "RecolorTrack",
    # Text decoration events (the only decoration events kept)
    "SetText", "SetDefaultText",
    # Allowed visual events
    "MoveCamera", "SetFrameRate",
    # Event modifiers
    "RepeatEvents", "SetConditionalEvents",
    # Conveniences
    "EditorComment", "Bookmark",
    # DLC / gameplay extensions
    "Hold", "SetHoldSound", "MultiPlanet",
    "FreeRoam", "FreeRoamTwirl", "FreeRoamRemove",
    "Hide", "ScaleMargin", "ScaleRadius",
}

REMOVE_EVENTS = {
    # Decoration events
    "AddDecoration", "AddObject", "AddParticle", "AddText",  # AddText handled separately
    "MoveDecorations", "EmitParticle", "SetParticle", "SetObject",
    # Visual events
    "Flash", "SetFilter", "SetFilterAdvanced", "HallOfMirrors",
    "ShakeScreen", "Bloom", "ScreenTile", "ScreenScroll",
    "CustomBackground", "SetBackground",
}

# Decoration objects (in the "decorations" array) that are kept
KEEP_DECORATIONS = {"AddText"}

# Fresh-level defaults (version 18) - Background Settings tab
BACKGROUND_DEFAULTS = {
    "backgroundColor": "000000",
    "showDefaultBGIfNoImage": True,
    "showDefaultBGTile": True,
    "defaultBGTileColor": "101121",
    "defaultBGShapeType": "Default",
    "defaultBGShapeColor": "ffffff",
    "bgImage": "",
    "bgImageColor": "ffffff",
    "parallax": [100, 100],
    "bgDisplayMode": "FitToScreen",
    "imageSmoothing": True,
    "lockRot": False,
    "loopBG": False,
    "scalingRatio": 100,
}

# Fresh-level defaults - the video background part of Misc Settings
VIDEO_DEFAULTS = {
    "bgVideo": "",
    "loopVideo": False,
    "vidOffset": 0,
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".avi", ".webm", ".mov", ".mkv", ".wmv", ".flv", ".m4v"}


# ---------------------------------------------------------------------------
# Tolerant .adofai parsing (files often contain trailing commas / BOMs)
# ---------------------------------------------------------------------------

def load_adofai(path):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    # strict=False allows the literal tabs/newlines ADOFAI writes inside
    # strings (e.g. multiline editor comments)
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass

    # Remove trailing commas before } or ]
    cleaned = re.sub(r",(\s*[}\]])", r"\1", text)

    # ADOFAI itself writes files with missing commas (e.g. between the
    # "actions" array and "decorations"). Insert them where parsing fails.
    for _ in range(100000):
        try:
            return json.loads(cleaned, strict=False)
        except json.JSONDecodeError as exc:
            if exc.msg.startswith("Expecting ',' delimiter"):
                cleaned = cleaned[:exc.pos] + "," + cleaned[exc.pos:]
            else:
                raise
    raise ValueError("Could not repair chart file - too many JSON errors")


def save_adofai(data, path):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    Path(path).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Chart simplification
# ---------------------------------------------------------------------------

def simplify_chart(data, log):
    """Simplify one parsed .adofai chart in place. Returns stats dict."""
    stats = {
        "visual_removed": 0, "deco_events_removed": 0,
        "kept": 0, "unknown_kept": 0, "decorations_removed": 0, "text_kept": 0,
        "bg_reset": False, "video_removed": False,
    }

    # --- Tile events ---
    actions = data.get("actions")
    if isinstance(actions, list):
        kept_actions = []
        for event in actions:
            etype = event.get("eventType", "") if isinstance(event, dict) else ""
            if etype in KEEP_DECORATIONS and "decText" in event:
                # AddText living in the actions array (older format) is a text
                # decoration - keep it.
                kept_actions.append(event)
                stats["text_kept"] += 1
            elif etype in REMOVE_EVENTS:
                if etype in ("AddDecoration", "AddObject", "AddParticle", "AddText",
                             "MoveDecorations", "EmitParticle", "SetParticle", "SetObject"):
                    stats["deco_events_removed"] += 1
                else:
                    stats["visual_removed"] += 1
            elif etype in KEEP_EVENTS:
                kept_actions.append(event)
                stats["kept"] += 1
            else:
                # Unknown event type - keep it so gameplay is never broken
                kept_actions.append(event)
                stats["unknown_kept"] += 1
        data["actions"] = kept_actions

    # --- Decorations array (Decorations tab: images, objects, particles, text) ---
    decorations = data.get("decorations")
    if isinstance(decorations, list):
        kept_decorations = []
        for deco in decorations:
            etype = deco.get("eventType", "") if isinstance(deco, dict) else ""
            if etype in KEEP_DECORATIONS:
                kept_decorations.append(deco)
                stats["text_kept"] += 1
            else:
                stats["decorations_removed"] += 1
        data["decorations"] = kept_decorations

    # --- Settings ---
    settings = data.get("settings")
    if isinstance(settings, dict):
        for key, default in BACKGROUND_DEFAULTS.items():
            if key in settings and settings[key] != default:
                settings[key] = default
                stats["bg_reset"] = True
        had_video = bool(settings.get("bgVideo"))
        for key, default in VIDEO_DEFAULTS.items():
            if key in settings:
                settings[key] = default
        stats["video_removed"] = had_video

    return stats


def collect_referenced_files(data):
    """Every string value in the chart, lowercased - used to keep referenced files."""
    refs = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node:
            name = node.replace("\\", "/").split("/")[-1].strip().lower()
            if name:
                refs.add(name)

    walk(data)
    return refs


# ---------------------------------------------------------------------------
# Level folder / zip handling
# ---------------------------------------------------------------------------

def find_level_root(base):
    """Find the folder that actually contains .adofai files (handles nesting)."""
    base = Path(base)
    charts = sorted(base.rglob("*.adofai"))
    if not charts:
        raise FileNotFoundError("No .adofai file found - is this an ADOFAI level?")
    # The level root is the shallowest folder containing a chart
    root = min((c.parent for c in charts), key=lambda p: len(p.parts))
    return root


def simplify_level(input_path, log):
    """Simplify a level folder or zip. Returns the path of the output zip."""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Path does not exist: {input_path}")

    temp_dir = None
    try:
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            log(f"Extracting {input_path.name} ...")
            temp_dir = Path(tempfile.mkdtemp(prefix="chartsimplifier_"))
            with zipfile.ZipFile(input_path) as zf:
                zf.extractall(temp_dir)
            level_root = find_level_root(temp_dir)
            # Prefer the extracted folder's own name; fall back to the zip name
            level_name = level_root.name if level_root != temp_dir else input_path.stem
            output_dir = input_path.parent
        elif input_path.is_dir():
            # Works even when the level sits in a folder inside the picked folder
            level_root = find_level_root(input_path)
            level_name = level_root.name
            output_dir = input_path.parent
        else:
            raise ValueError("Please select a level folder or a .zip file.")

        log(f"Level found: {level_name}")

        # --- Simplify every chart in the level ---
        totals = {}
        referenced = set()
        simplified_charts = {}  # absolute path -> simplified data
        charts = sorted(level_root.rglob("*.adofai"))
        for chart_path in charts:
            data = load_adofai(chart_path)
            stats = simplify_chart(data, log)
            simplified_charts[chart_path] = data
            referenced |= collect_referenced_files(data)
            for key, value in stats.items():
                if isinstance(value, bool):
                    totals[key] = totals.get(key, False) or value
                else:
                    totals[key] = totals.get(key, 0) + value

        log(f"Processed {len(charts)} chart file(s)")
        if totals.get("decorations_removed"):
            log(f"Removed {totals['decorations_removed']} decorations (images, objects, particles)")
        if totals.get("deco_events_removed"):
            log(f"Removed {totals['deco_events_removed']} decoration events from tiles")
        if totals.get("visual_removed"):
            log(f"Removed {totals['visual_removed']} visual events (flash, filters, bloom, shake...)")
        if totals.get("text_kept"):
            log(f"Kept {totals['text_kept']} text decorations")
        log(f"Kept {totals.get('kept', 0)} gameplay/track/camera events")
        if totals.get("unknown_kept"):
            log(f"Kept {totals['unknown_kept']} unrecognized events (left untouched for safety)")
        if totals.get("bg_reset"):
            log("Reset background settings to fresh-level defaults")
        if totals.get("video_removed"):
            log("Removed video background")

        # --- Build the output zip ---
        output_name = f"{level_name} - Simplified"
        output_zip = output_dir / f"{output_name}.zip"
        skipped_files = 0

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(level_root.rglob("*")):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(level_root)
                arcname = f"{output_name}/{rel.as_posix()}"
                ext = file_path.suffix.lower()
                if file_path in simplified_charts:
                    text = json.dumps(simplified_charts[file_path],
                                      ensure_ascii=False, indent=2)
                    zf.writestr(arcname, text)
                elif ext in IMAGE_EXTS or ext in VIDEO_EXTS:
                    if file_path.name.strip().lower() in referenced:
                        zf.write(file_path, arcname)
                    else:
                        skipped_files += 1
                else:
                    zf.write(file_path, arcname)

        if skipped_files:
            log(f"Deleted {skipped_files} unused image/video file(s) from the level folder")
        log(f"Done! Saved: {output_zip}")
        return output_zip
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python simplifier.py <level folder or zip>")
        sys.exit(1)
    simplify_level(sys.argv[1], print)
