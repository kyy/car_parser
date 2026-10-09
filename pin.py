#!/usr/bin/env python3
import sys, hmac, hashlib

def filter_id(s: str) -> str:
    res = []
    for c in s:
        o = ord(c)
        if 0x61 <= o <= 0x7a:
            o -= 0x20
        if (0x41 <= o <= 0x5A) or (0x30 <= o <= 0x39):
            res.append(chr(o))
    return "".join(res)

def make_machine_code(id_str: str) -> str:
    filtered = filter_id(id_str)
    if len(filtered) < 10:
        return ""
    h = hmac.new(b"machine", filtered.encode(), hashlib.sha256).digest()
    return f"{h[0]:02X}{h[1]:02X}-{h[2]:02X}{h[3]:02X}"

def make_pin(id_str: str) -> str:
    filtered = filter_id(id_str)
    if len(filtered) < 7:
        return ""
    h = hmac.new(b"pin", filtered.encode(), hashlib.sha256).digest()
    b0, b1, b2, b3 = h[0], h[1], h[2], h[3]
    val = (b1 << 16) | ((b0 & 0x7F) << 24) | (b2 << 8) | b3
    return f"{val % 1_000_000:06d}"

if __name__ == "__main__":
    #aid = 'C478EFE3CEAEFBF7'
    aid = 'C478EFE3CEAEFBF7'
    print("Filtered   :", filter_id(aid))
    print("MachineCode:", make_machine_code(aid))
    print("PIN        :", make_pin(aid))