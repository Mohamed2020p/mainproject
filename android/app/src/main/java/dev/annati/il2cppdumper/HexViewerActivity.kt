package dev.annati.il2cppdumper

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.io.File
import java.io.RandomAccessFile

/**
 * Minimal hex viewer / byte patcher for any dumped or selected file.
 *
 * Shows a windowed hex + ASCII view (never loads the whole file, so >1 GB is
 * fine) and lets the user rewrite a single byte at an offset.  Everything is
 * guarded so a bad input shows a toast instead of crashing.
 *
 * Developed by @c0derz.
 */
class HexViewerActivity : AppCompatActivity() {

    private lateinit var hexView: TextView
    private lateinit var title: TextView
    private var path: String? = null
    private var offset = 0L
    private val window = 32 * 1024

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hex)
        hexView = findViewById(R.id.hexText)
        title = findViewById(R.id.hexTitle)
        path = intent.getStringExtra("path")

        findViewById<Button>(R.id.btnNext).setOnClickListener { offset += window; render() }
        findViewById<Button>(R.id.btnPrev).setOnClickListener { offset = (offset - window).coerceAtLeast(0); render() }
        findViewById<Button>(R.id.btnPatch).setOnClickListener { patch() }

        title.text = File(path ?: "").name
        render()
    }

    private fun render() {
        val p = path ?: return
        try {
            RandomAccessFile(File(p), "r").use { raf ->
                val size = raf.length()
                val sb = StringBuilder()
                sb.append("// ").append(File(p).name).append("  size=").append(size)
                    .append("  offset=").append(offset).append("\n\n")
                raf.seek(offset)
                val buf = ByteArray(window)
                val read = raf.read(buf)
                var i = 0
                while (i < read) {
                    val lineOff = offset + i
                    sb.append("%08X  ".format(lineOff))
                    val ascii = StringBuilder()
                    for (j in 0 until 16) {
                        if (i + j < read) {
                            val b = buf[i + j]
                            sb.append("%02X ".format(b))
                            ascii.append(if (b in 32..126) b.toInt().toChar() else '.')
                        } else sb.append("   ")
                    }
                    sb.append(" |").append(ascii).append("|\n")
                    i += 16
                }
                hexView.text = sb.toString()
            }
        } catch (e: Exception) {
            hexView.text = "Error: " + (e.message ?: e.toString())
        }
    }

    private fun patch() {
        val p = path ?: return
        val offText = findViewById<EditText>(R.id.txtOffset).text.toString().trim()
        val hexText = findViewById<EditText>(R.id.txtByte).text.toString().trim()
        try {
            val off = if (offText.startsWith("0x", true)) offText.substring(2).toLong(16) else offText.toLong()
            val value = hexText.toInt(16) and 0xFF
            RandomAccessFile(File(p), "rw").use { raf ->
                if (off >= raf.length()) throw IllegalArgumentException("offset beyond end of file")
                raf.seek(off)
                raf.write(value)
            }
            offset = (off / 256) * 256
            render()
            Toast.makeText(this, "Patched 0x%X -> %02X".format(off, value), Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Patch failed: " + (e.message ?: e.toString()), Toast.LENGTH_LONG).show()
        }
    }
}
