package dev.annati.il2cppdumper.dumper

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel

/**
 * Metadata-free (".so only") analysis for the on-device app.
 *
 * Reads the native binary through a read-only memory map so multi-gigabyte
 * files never load into RAM, extracts the ELF structure and the exported symbol
 * table, and writes `il2cpp.h`, `script.json` and `lib-report.json`.  Every step
 * is guarded so a strange binary degrades to a partial report instead of
 * crashing.
 *
 * Developed by @c0derz.
 */
object LibOnly {

    private const val SHT_DYNSYM = 11
    private const val SHT_STRTAB = 3

    private data class Section(val name: String, val type: Long, val addr: Long,
                               val offset: Long, val size: Long, val link: Int,
                               val entsize: Long)

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
                val channel = raf.channel
                val size = channel.size()
                report["fileSize"] = size
                val buf = channel.map(FileChannel.MapMode.READ_ONLY, 0, size)
                buf.order(ByteOrder.LITTLE_ENDIAN)
                parseElf(buf, report).also { symbols = it }
            }
        } catch (e: Exception) {
            report["error"] = (e.message ?: e.toString())
        }

        // il2cpp.h
        try {
            val h = File(outDir, "il2cpp.h")
            h.writeText(HEADER)
            written.add(h)
        } catch (_: Exception) { }

        // script.json (exports, same schema as the full dumper)
        try {
            val methods = symbols.filter { it.value != 0L && it.name.isNotEmpty() }
                .sortedBy { it.value }
                .joinToString(",") { s ->
                    "{\"Address\":${s.value},\"Name\":${json(s.name)}}"
                }
            val s = File(outDir, "script.json")
            s.writeText("{\"ScriptMethod\":[$methods],\"ScriptString\":[]," +
                "\"ScriptMetadata\":[],\"ScriptMetadataMethod\":[],\"Addresses\":[]}")
            written.add(s)
        } catch (_: Exception) { }

        // lib-report.json
        try {
            report["exportedSymbols"] = symbols.size
            val r = File(outDir, "lib-report.json")
            r.writeText(toJson(report, 0))
            written.add(r)
        } catch (_: Exception) { }

        return written
    }

    /** Returns the exported symbols; fills [report] with structure info. */
    private fun parseElf(buf: ByteBuffer, report: MutableMap<String, Any>): List<Symbol> {
        if (buf.limit() < 0x34 || buf.get(0) != 0x7f.toByte() || buf.get(1) != 'E'.code.toByte()) {
            report["format"] = "not-ELF"
            return emptyList()
        }
        val is64 = buf.get(4).toInt() == 2
        val machine = u16(buf, 0x12)
        report["format"] = if (is64) "ELF64" else "ELF32"
        report["bits"] = if (is64) 64 else 32
        report["abi"] = abi(machine)

        val shoff = if (is64) buf.getLong(0x28) else u32(buf, 0x20)
        val shentsize = if (is64) u16(buf, 0x3A) else u16(buf, 0x2E)
        val shnum = if (is64) u16(buf, 0x3C) else u16(buf, 0x30)
        val shstrndx = if (is64) u16(buf, 0x3E) else u16(buf, 0x32)
        if (shoff == 0L || shnum == 0 || shentsize == 0) {
            report["sections"] = 0
            return emptyList()
        }

        fun shBase(i: Int): Long = shoff + i.toLong() * shentsize
        fun shNameOff(i: Int): Int = u32(buf, shBase(i)).toInt()
        fun shType(i: Int): Long = u32(buf, shBase(i) + 4)
        fun shOffset(i: Int): Long = if (is64) buf.getLong(shBase(i) + 24) else u32(buf, shBase(i) + 16)
        fun shSize(i: Int): Long = if (is64) buf.getLong(shBase(i) + 32) else u32(buf, shBase(i) + 20)
        fun shLink(i: Int): Int = u32(buf, shBase(i) + (if (is64) 40 else 24)).toInt()
        fun shEntsize(i: Int): Long = if (is64) buf.getLong(shBase(i) + 56) else u32(buf, shBase(i) + 36)
        fun shAddr(i: Int): Long = if (is64) buf.getLong(shBase(i) + 16) else u32(buf, shBase(i) + 12)

        // section-name string table
        val names = ArrayList<String>()
        val strOff = shOffset(shstrndx)
        val strSize = shSize(shstrndx)
        for (i in 0 until shnum) {
            names.add(cString(buf, strOff + shNameOff(i), strOff + strSize))
        }

        val sections = ArrayList<Section>()
        for (i in 0 until shnum) {
            sections.add(Section(names[i], shType(i), shAddr(i), shOffset(i),
                shSize(i), shLink(i), shEntsize(i)))
        }
        report["sections"] = sections.map { mapOf("name" to it.name, "vaddr" to it.addr, "size" to it.size) }

        // find .dynsym + its .dynstr
        val dynsym = sections.firstOrNull { it.type.toLong() == SHT_DYNSYM.toLong() }
            ?: return emptyList()
        val dynstr = sections.getOrNull(dynsym.link) ?: return emptyList()
        val entsize = if (dynsym.entsize > 0) dynsym.entsize else if (is64) 24L else 16L
        val count = (dynsym.size / entsize).toInt().coerceAtMost(1_000_000)

        val out = ArrayList<Symbol>()
        for (i in 1 until count) {
            val base = dynsym.offset + i.toLong() * entsize
            if (base + entsize > buf.limit()) break
            val nameOff: Int
            val value: Long
            if (is64) {
                nameOff = u32(buf, base).toInt()
                value = buf.getLong(base + 8)
            } else {
                nameOff = u32(buf, base).toInt()
                value = u32(buf, base + 4)
            }
            val name = cString(buf, dynstr.offset + nameOff, dynstr.offset + dynstr.size)
            if (name.isNotEmpty()) out.add(Symbol(name, value))
        }
        return out
    }

    private fun cString(buf: ByteBuffer, from: Long, limit: Long): String {
        if (from < 0 || from >= buf.limit()) return ""
        val sb = StringBuilder()
        var i = from
        val end = minOf(limit, buf.limit().toLong())
        while (i < end) {
            val b = buf.get(i.toInt())
            if (b.toInt() == 0) break
            sb.append(b.toInt().toChar())
            i++
            if (sb.length > 256) break
        }
        return sb.toString()
    }

    private fun u16(buf: ByteBuffer, at: Int): Int = buf.getShort(at).toInt() and 0xFFFF
    private fun u32(buf: ByteBuffer, at: Int): Long = buf.getInt(at).toLong() and 0xFFFFFFFFL

    private fun abi(machine: Int): String = when (machine) {
        40 -> "armeabi-v7a"
        183 -> "arm64-v8a"
        3 -> "x86"
        62 -> "x86_64"
        else -> "machine-$machine"
    }

    private fun json(s: String): String {
        val sb = StringBuilder("\"")
        for (c in s) when {
            c == '\\' -> sb.append("\\\\")
            c == '"' -> sb.append("\\\"")
            c == '\n' -> sb.append("\\n")
            c == '\r' -> sb.append("\\r")
            c == '\t' -> sb.append("\\t")
            c.code < 0x20 -> sb.append("\\u%04x".format(c.code))
            else -> sb.append(c)
        }
        return sb.append('"').toString()
    }

    private fun toJson(map: Map<String, Any>, indent: Int): String {
        val pad = "  ".repeat(indent + 1)
        val close = "  ".repeat(indent)
        val sb = StringBuilder("{\n")
        val entries = map.entries.toList()
        for ((i, e) in entries.withIndex()) {
            sb.append(pad).append(json(e.key)).append(": ")
            sb.append(valueJson(e.value, indent + 1))
            if (i < entries.size - 1) sb.append(",")
            sb.append("\n")
        }
        return sb.append(close).append("}").toString()
    }

    private fun valueJson(v: Any, indent: Int): String = when (v) {
        is Number -> v.toString()
        is Boolean -> v.toString()
        is Map<*, *> -> toJson(v.entries.associate { it.key.toString() to (it.value as Any) }, indent)
        is List<*> -> {
            if (v.isEmpty()) "[]"
            else v.joinToString(",", "[\n", "\n" + "  ".repeat(indent - 1) + "]") {
                "  ".repeat(indent) + valueJson(it as Any, indent)
            }
        }
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
