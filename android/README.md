# ChartSimplifier for Android

A native Android app that turns any ADOFAI chart into a layout, on your phone.

Pick a level **ZIP**, and the simplified level is saved to your **Downloads** as
`<level name> - Simplified.zip`. Same rules as the desktop app: decorations
(except text), visual effects, and backgrounds are stripped; gameplay, track,
DLC, convenience and modifier events are kept. The two switches (keep track
colors / keep camera movements) work here too.

## How it works

The chart logic is the shared, validated JavaScript core in
[`app/src/main/assets/simplifier.js`](app/src/main/assets/simplifier.js) - the
same code the web/desktop paths use, verified to produce byte-identical output
to the Python version on real charts. The app is a thin native shell:

- A `WebView` runs the UI (`assets/index.html`) and the simplifier (JS + JSZip).
- Kotlin (`MainActivity.kt`) only picks the input `.zip` (Storage Access
  Framework) and streams the output `.zip` into Downloads (MediaStore on
  Android 10+, public Downloads folder on older versions).

Because Android's storage is sandboxed, the mobile flow is **ZIP in → ZIP out**
(there's no "write next to the original folder" like on desktop).

## Build

Requires the Android SDK (platform 34, build-tools 34) and a JDK 17+.

```
cd android
./gradlew assembleDebug        # or gradlew.bat on Windows
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`. Copy it to your
phone and install (you'll need to allow installing from unknown sources).

For a Play-ready signed build, set up a keystore and run `./gradlew assembleRelease`.

## Notes

- minSdk 24 (Android 7.0), targetSdk 34.
- Large levels are processed in memory; very large packs (hundreds of MB) may be
  heavy on low-RAM devices.
