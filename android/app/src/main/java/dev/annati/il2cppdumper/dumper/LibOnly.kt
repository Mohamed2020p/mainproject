package dev.annati.il2cppdumper.dumper

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Metadata-free (".so only") analysis for the on-device app.
 *
 * Only the small tables (ELF header, section table, .dynstr, .dynsym) are read
 * into memory via [RandomAccessFile], so multi-gigabyte binaries never load into
 * RAM and nothing can index past 2 GB.  Writes `il2cpp.h`, `script.json`
 * (exports) and `lib-report.json`.  Every step is guarded so a strange binary
 * degrades to a partial report instead of crashing.
 *
 * Developed by @c0derz.
 */
object LibOnly {

    private const val SHT_DYNSYM = 11

    private data class Symbol(val name: String, val value: Long)

    fun dump(soPath: String, outDir: File): List<File> {
        outDir.mkdirs()
        val written = ArrayList<File>()
        val report = LinkedHashMap<String, Any>()
        report["generator"] = "IL2CPP Dumper Studio (Android)"
        report["developer"] = "@c0derz"
        report["mode"] = "lib-only"

        var symbols: List<Symbol> = emptyList()
        try {
            RandomAccessFile(File(soPath), "r").use { raf ->
                val size = raf.length()
                report["fileSize"] = size
                symbols = parseElf(raf, size, report)
            }
        } catch (e: Exception) {
            report["error"] = (e.message ?: e.toString())
        }

        try { File(outDir, "il2cpp.h").writeText(HEADER); written.add(File(outDir, "il2cpp.h")) }
        catch (_: Exception) { }

        try {
            val methods = symbols.filter { it.value != 0L && it.name.isNotEmpty() }
                .sortedBy { it.value }
                .joinToString(",") { s -> "{\"Address\":${s.value},\"Name\":${json(s.name)}}" }
            val s = File(outDir, "script.json")
            s.writeText("{\"ScriptMethod\":[$methods],\"ScriptString\":[]," +
                "\"ScriptMetadata\":[],\"ScriptMetadataMethod\":[],\"Addresses\":[]}")
            written.add(s)
        } catch (_: Exception) { }

        try {
            report["exportedSymbols"] = symbols.size
            val r = File(outDir, "lib-report.json")
            r.writeText(toJson(report, 0))
            written.add(r)
        } catch (_: Exception) { }

        return written
    }

    private fun readAt(raf: RandomAccessFile, at: Long, n: Int): ByteArray? {
        if (at < 0 || at > raf.length()) return null
        val b = ByteArray(n)
        raf.seek(at)
        val read = raf.read(b)
        return if (read <= 0) null else b
    }

    private fun parseElf(raf: RandomAccessFile, size: Long,
                         report: MutableMap<String, Any>): List<Symbol> {
        val head = readAt(raf, 0, 0x40) ?: return emptyList()
        val hb = ByteBuffer.wrap(head).order(ByteOrder.LITTLE_ENDIAN)
        if (head[0] != 0x7f.toByte() || head[1] != 'E'.code.toByte()) {
            report["format"] = "not-ELF"; return emptyList()
        }
        val is64 = head[4].toInt() == 2
        val machine = hb.getShort(0x12).toInt() and 0xFFFF
        report["format"] = if (is64) "ELF64" else "ELF32"
        report["bits"] = if (is64) 64 else 32
        report["abi"] = abi(machine)

        val shoff = if (is64) hb.getLong(0x28) else hb.getInt(0x20).toLong() and 0xFFFFFFFFL
        val shentsize = (if (is64) hb.getShort(0x3A) else hb.getShort(0x2E)).toInt() and 0xFFFF
        val shnum = (if (is64) hb.getShort(0x3C) else hb.getShort(0x30)).toInt() and 0xFFFF
        val shstrndx = (if (is64) hb.getShort(0x3E) else hb.getShort(0x32)).toInt() and 0xFFFF
        if (shoff == 0L || shnum == 0 || shentsize == 0 || shstrndx >= shnum) {
            report["sections"] = 0; return emptyList()
        }

        val table = readAt(raf, shoff, shnum * shentsize) ?: return emptyList()
        val tb = ByteBuffer.wrap(table).order(ByteOrder.LITTLE_ENDIAN)

        fun s32(i: Int, off: Int): Int = tb.getInt(i * shentsize + off)
        fun s64(i: Int, off: Int): Long =
            if (is64) tb.getLong(i * shentsize + off)
            else tb.getInt(i * shentsize + off).toLong() and 0xFFFFFFFFL

        // section-name string table
        val strOff = s64(shstrndx, if (is64) 24 else 16)
        val strSize = s64(shstrndx, if (is64) 32 else 20)
        val strTab = readAt(raf, strOff, strSize.toInt().coerceAtMost(4_000_000)) ?: ByteArray(0)

        data class Sec(val name: String, val type: Int, val addr: Long, val size: Long,
                       val link: Int, val offset: Long, val entsize: Long)
        val sections = ArrayList<Sec>()
        for (i in 0 until shnum) {
            val name = cString(strTab, s32(i, 0))
            sections.add(Sec(name, s32(i, 4), s64(i, if (is64) 16 else 12),
                s64(i, if (is64) 32 else 20), s32(i, if (is64) 40 else 24),
                s64(i, if (is64) 24 else 16), s64(i, if (is64) 56 else 36)))
        }
        report["sections"] = sections.map { mapOf("name" to it.name, "vaddr" to it.addr, "size" to it.size) }

        val dynsym = sections.firstOrNull { it.type == SHT_DYNSYM } ?: return emptyList()
        val dynstr = sections.getOrNull(dynsym.link) ?: return emptyList()
        val entsize = (if (dynsym.entsize > 0) dynsym.entsize else if (is64) 24L else 16L).toInt()
        val count = (dynsym.size / entsize).toInt().coerceAtMost(200_000)
        val symTab = readAt(raf, dynsym.offset, (count * entsize).coerceAtMost(8_000_000))
            ?: return emptyList()
        val sb_ = ByteBuffer.wrap(symTab).order(ByteOrder.LITTLE_ENDIAN)
        val dynStr = readAt(raf, dynstr.offset, dynstr.size.toInt().coerceAtMost(8_000_000))
            ?: ByteArray(0)

        val out = ArrayList<Symbol>()
        for (i in 1 until minOf(count, symTab.size / entsize)) {
            val base = i * entsize
            val nameOff: Int
            val value: Long
            if (is64) {
                nameOff = sb_.getInt(base)
                value = sb_.getLong(base + 8)
            } else {
                nameOff = sb_.getInt(base)
                value = sb_.getInt(base + 4).toLong() and 0xFFFFFFFFL
            }
            val name = cString(dynStr, nameOff)
            if (name.isNotEmpty()) out.add(Symbol(name, value))
        }
        return out
    }

    private fun cString(arr: ByteArray, from: Int): String {
        if (from < 0 || from >= arr.size) return ""
        val sb = StringBuilder()
        var i = from
        while (i < arr.size && arr[i].toInt() != 0 && sb.length < 256) {
            sb.append(arr[i].toInt().toChar()); i++
        }
        return sb.toString()
    }

    private fun abi(machine: Int): String = when (machine) {
        40 -> "armeabi-v7a"; 183 -> "arm64-v8a"; 3 -> "x86"; 62 -> "x86_64"
        else -> "machine-$machine"
    }

    private fun json(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) when {
            c == '\\' -> sb.append("\\\\"); c == '"' -> sb.append("\\\"")
            c == '\n' -> sb.append("\\n"); c == '\r' -> sb.append("\\r")
            c == '\t' -> sb.append("\\t"); c.code < 0x20 -> sb.append("\\u%04x".format(c.code))
            else -> sb.append(c)
        }
        return sb.append('"').toString()
    }

    private fun toJson(map: Map<String, Any>, indent: Int): String {
        val pad = "  ".repeat(indent + 1); val close = "  ".repeat(indent)
        val sb = StringBuilder("{\n")
        val entries = map.entries.toList()
        for ((i, e) in entries.withIndex()) {
            sb.append(pad).append(json(e.key)).append(": ").append(valueJson(e.value, indent + 1))
            if (i < entries.size - 1) sb.append(",")
            sb.append("\n")
        }
        return sb.append(close).append("}").toString()
    }

    private fun valueJson(v: Any, indent: Int): String = when (v) {
        is Number -> v.toString()
        is Boolean -> v.toString()
        is Map<*, *> -> toJson(v.entries.associate { it.key.toString() to (it.value as Any) }, indent)
        is List<*> -> if (v.isEmpty()) "[]" else v.joinToString(",", "[\n",
            "\n" + "  ".repeat(indent - 1) + "]") { "  ".repeat(indent) + valueJson(it as Any, indent) }
        else -> json(v.toString())
    }

    private val HEADER = """
#pragma once
/* il2cpp.h - generated by IL2CPP Dumper Studio (Android, lib-only)
 * Developer: @c0derz
 */
typedef void(*Il2CppMethodPointer)();
struct MethodInfo;
struct Il2CppClass;
struct Il2CppType { void* data; unsigned int bits; };
struct Il2CppObject { Il2CppClass* klass; void* monitor; };
"""
}
