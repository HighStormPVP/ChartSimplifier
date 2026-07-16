package com.chartsimplifier

import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream

/**
 * ChartSimplifier for Android - a thin native shell around the shared, validated
 * JavaScript simplifier. The WebView runs the UI (index.html) and all chart
 * logic (simplifier.js). Kotlin only handles picking the input .zip and saving
 * the simplified .zip into the Downloads folder.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private val main = Handler(Looper.getMainLooper())

    // The bytes of the currently-picked input zip, served to the WebView at
    // https://appassets.androidplatform.net/input/current.zip so JS can fetch it.
    @Volatile private var inputBytes: ByteArray? = null

    // Output being streamed from JS (base64 chunks) into Downloads.
    private var outStream: OutputStream? = null
    private var outUri: Uri? = null
    private var outFile: File? = null
    private var outDisplayPath: String = ""

    private val pickLauncher =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
            if (uri == null) return@registerForActivityResult
            Thread {
                try {
                    val bytes = contentResolver.openInputStream(uri)!!.use { it.readBytes() }
                    inputBytes = bytes
                    val name = queryDisplayName(uri)
                    main.post { evalJs("window.onInputPicked(${JSONObject.quote(name)})") }
                } catch (e: Exception) {
                    main.post { evalJs("window.onError(${JSONObject.quote(e.message ?: "read failed")})") }
                }
            }.start()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val assetLoader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .addPathHandler("/input/", InputPathHandler())
            .build()

        webView = WebView(this)
        webView.settings.javaScriptEnabled = true
        webView.settings.allowFileAccess = false
        webView.settings.domStorageEnabled = true
        webView.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView, request: WebResourceRequest
            ): WebResourceResponse? = assetLoader.shouldInterceptRequest(request.url)
        }
        webView.addJavascriptInterface(JsBridge(), "Android")
        setContentView(webView)
        webView.loadUrl("https://appassets.androidplatform.net/assets/index.html")
    }

    override fun onDestroy() {
        try { outStream?.close() } catch (_: Exception) {}
        super.onDestroy()
    }

    private fun evalJs(script: String) = webView.evaluateJavascript(script, null)

    private fun queryDisplayName(uri: Uri): String {
        var name = "level.zip"
        contentResolver.query(uri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
        }
        return name
    }

    /** Serves the picked input zip to the WebView so JS can fetch() it. */
    private inner class InputPathHandler : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse? {
            val bytes = inputBytes ?: return WebResourceResponse(
                "text/plain", "utf-8", 404, "Not Found", emptyMap(), ByteArrayInputStream(ByteArray(0)))
            return WebResourceResponse(
                "application/zip", null, 200, "OK",
                mapOf("Access-Control-Allow-Origin" to "*"),
                ByteArrayInputStream(bytes))
        }
    }

    /** Methods callable from JavaScript as Android.*(). Run on a binder thread. */
    inner class JsBridge {

        @JavascriptInterface
        fun pickZip() {
            main.post {
                pickLauncher.launch(arrayOf(
                    "application/zip", "application/x-zip-compressed", "application/octet-stream"))
            }
        }

        @JavascriptInterface
        fun toast(message: String) {
            main.post { Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show() }
        }

        /** Begin a streamed save of "<name>.zip" into Downloads. */
        @JavascriptInterface
        fun saveStart(name: String): Boolean {
            return try {
                val fileName = "$name.zip"
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                        put(MediaStore.Downloads.MIME_TYPE, "application/zip")
                        put(MediaStore.Downloads.IS_PENDING, 1)
                    }
                    val resolver = contentResolver
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                        ?: return false
                    outUri = uri
                    outStream = resolver.openOutputStream(uri)
                    outDisplayPath = "Downloads/$fileName"
                } else {
                    val dir = Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS)
                    if (!dir.exists()) dir.mkdirs()
                    val file = File(dir, fileName)
                    outFile = file
                    outStream = FileOutputStream(file)
                    outDisplayPath = "Downloads/$fileName"
                }
                true
            } catch (e: Exception) {
                main.post { evalJs("window.onError(${JSONObject.quote(e.message ?: "save failed")})") }
                false
            }
        }

        /** Append one base64-encoded chunk of the output zip. */
        @JavascriptInterface
        fun saveChunk(base64: String): Boolean {
            return try {
                outStream?.write(Base64.decode(base64, Base64.DEFAULT))
                true
            } catch (e: Exception) {
                main.post { evalJs("window.onError(${JSONObject.quote(e.message ?: "write failed")})") }
                false
            }
        }

        /** Finalise the save and tell JS where it went. */
        @JavascriptInterface
        fun saveFinish() {
            try {
                outStream?.flush()
                outStream?.close()
                outStream = null
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && outUri != null) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.IS_PENDING, 0)
                    }
                    contentResolver.update(outUri!!, values, null, null)
                }
                inputBytes = null // free memory
                main.post { evalJs("window.onSaved(${JSONObject.quote(outDisplayPath)})") }
            } catch (e: Exception) {
                main.post { evalJs("window.onError(${JSONObject.quote(e.message ?: "finalise failed")})") }
            }
        }
    }
}
