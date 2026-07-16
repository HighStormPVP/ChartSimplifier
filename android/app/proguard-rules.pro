# Keep the JavaScript bridge methods callable from the WebView.
-keepclassmembers class com.chartsimplifier.MainActivity$JsBridge {
    public *;
}
