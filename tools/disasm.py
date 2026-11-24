"""Disassemble a flat module image's text with string/xref annotation.
Usage: disasm.py image.bin text_end out.txt"""
import sys, re, capstone
img = open(sys.argv[1], 'rb').read(); tend = int(sys.argv[2], 0)
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
def cstr(a):
    if a >= len(img): return None
    e = img.find(b'\0', a, a + 200)
    if e <= a: return None
    s = img[a:e]
    return s.decode() if all(32 <= c < 127 or c in (9, 10) for c in s) and len(s) >= 3 else None
out = open(sys.argv[3], 'w')
adrp = {}
for off in range(0, tend, 4):
    w = img[off:off + 4]
    ins = list(md.disasm(w, off))
    if not ins:
        out.write(f'{off:08x}: .word {int.from_bytes(w,"little"):#010x}\n'); continue
    i = ins[0]; note = ''
    if i.mnemonic == 'adrp':
        rd = i.op_str.split(',')[0]; adrp[rd] = int(i.op_str.split('#')[1], 16)
    elif i.mnemonic in ('add', 'ldr', 'ldrb', 'ldrh', 'str', 'ldp', 'stp', 'ldrsw', 'strb'):
        m = re.search(r'\[?(x\d+)(?:, #(0x[0-9a-f]+|\d+))?', i.op_str.split(',', 1)[1] if i.mnemonic == 'add' else i.op_str[i.op_str.find('['):] if '[' in i.op_str else '')
        if m and m.group(1) in adrp:
            imm = int(m.group(2), 0) if m.group(2) else 0
            a = adrp[m.group(1)] + imm
            s = cstr(a)
            note = f'  ; ={a:#x}' + (f' "{s[:90]}"' if s else '')
    elif i.mnemonic == 'adr':
        a = int(i.op_str.split('#')[1], 16); s = cstr(a); note = f'  ; "{s[:90]}"' if s else ''
    if i.mnemonic in ('ret', 'b') : adrp.clear()
    out.write(f'{off:08x}: {i.mnemonic} {i.op_str}{note}\n')
