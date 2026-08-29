package dev.annati.il2cppdumper

import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.lifecycle.lifecycleScope
import dev.annati.il2cppdumper.databinding.ActivityMainBinding
import dev.annati.il2cppdumper.dumper.ApkExtractor
import dev.annati.il2cppdumper.dumper.DumpWriter
import dev.annati.il2cppdumper.dumper.Metadata
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * IL2CPP Dumper Studio - Android entry point.
 *
 * Developed by Mohamed Annati.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    private var apkPath: String? = null
    private var soPath: String? = null
    private var datPath: String? = null
    private var lastDumpDir: File? = null

    private val pickApk = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) { apkPath = cache(uri, "game.apk"); soPath = null; datPath = null; refreshSelected() }
    }
    private val pickSo = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) { soPath = cache(uri, "libil2cpp.so"); refreshSelected() }
    }
    private val pickDat = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) { datPath = cache(uri, "global-metadata.dat"); refreshSelected() }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnPickApk.setOnClickListener { pickApk.launch(arrayOf("*/*")) }
        binding.btnPickSo.setOnClickListener { pickSo.launch(arrayOf("*/*")) }
        binding.btnPickDat.setOnClickListener { pickDat.launch(arrayOf("*/*")) }
        binding.btnDump.setOnClickListener { runDump() }
        binding.btnShare.setOnClickListener { shareDump() }

        binding.progress.progress = 0
    }

    private fun cache(uri: Uri, name: String): String {
        val dest = File(cacheDir, name)
        contentResolver.openInputStream(uri)?.use { input ->
            dest.outputStream().use { input.copyTo(it) }
        }
        return dest.absolutePath
    }

    private fun refreshSelected() {
        val parts = ArrayList<String>()
        apkPath?.let { parts.add("APK: " + File(it).name) }
        soPath?.let { parts.add(".so: " + File(it).name) }
        datPath?.let { parts.add(".dat: " + File(it).name) }
        binding.txtSelected.text = parts.joinToString("\n")
    }

    private fun runDump() {
        val hasApk = apkPath != null
        val hasPair = soPath != null && datPath != null
        if (!hasApk && !hasPair) {
            Toast.makeText(this, R.string.no_files, Toast.LENGTH_LONG).show()
            return
        }

        binding.btnDump.isEnabled = false
        binding.btnShare.isEnabled = false
        binding.txtStatus.setText(R.string.dumping)
        binding.btnDump.setText(R.string.dumping)
        setProgress(5)
        appendLog("Starting dump…")

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                try {
                    val outDir = File(getExternalFilesDir(null), "dump")
                    var metadataPath: String?
                    if (hasApk) {
                        appendLog("Extracting APK…")
                        val pair = ApkExtractor.extract(apkPath!!, cacheDir)
                        appendLog("ABI: " + (pair.abi ?: "unknown"))
                        metadataPath = pair.metadata?.absolutePath
                    } else {
                        metadataPath = datPath
                    }

                    appendLog("Parsing global-metadata.dat…")
                    setProgress(30)
                    val metadata = Metadata.fromFile(metadataPath!!)
                    val s = metadata.summary()
                    appendLog("Metadata v${metadata.version} | ${s["types"]} types, ${s["methods"]} methods")

                    setProgress(70)
                    appendLog("Writing dump.cs …")
                    val files = DumpWriter.write(metadata, outDir)
                    setProgress(100)
                    lastDumpDir = outDir
                    "OK|" + outDir.absolutePath + "|" + files.size
                } catch (e: Exception) {
                    "ERR|" + (e.message ?: e.toString())
                }
            }

            binding.btnDump.isEnabled = true
            binding.btnDump.setText(R.string.dump)
            if (result.startsWith("OK")) {
                val parts = result.split("|")
                binding.txtStatus.text = getString(R.string.done, parts[1])
                binding.btnShare.isEnabled = true
                appendLog("Done. ${parts[2]} files written to ${parts[1]}")
            } else {
                binding.txtStatus.text = getString(R.string.error, result.substringAfter("|"))
                appendLog("ERROR: " + result.substringAfter("|"))
            }
        }
    }

    private fun appendLog(line: String) {
        binding.txtLog.post { binding.txtLog.append(line + "\n") }
    }

    private fun setProgress(value: Int) {
        binding.progress.post { binding.progress.progress = value }
    }

    private fun shareDump() {
        val dir = lastDumpDir ?: return
        val dumpCs = File(dir, "dump.cs")
        if (!dumpCs.exists()) return
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", dumpCs)
        val share = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(android.content.Intent.EXTRA_STREAM, uri)
            addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(android.content.Intent.createChooser(share, getString(R.string.share)))
    }
}
