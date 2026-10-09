import hashlib
import hmac

def normalize(s):
    out = []
    for c in s:
        if 'a' <= c <= 'z':
            c = c.upper()

        if ('A' <= c <= 'Z') or ('0' <= c <= '9'):
            out.append(c)

    return ''.join(out)


def derive_key(mode):
    s = f"courage+/v1/{mode}:3f1c-uzmaster-9a7d"
    return hashlib.sha256(s.encode()).digest()


def hmac_digest(mode, android_id):
    normalized = normalize(android_id)
    key = derive_key(mode)

    return hmac.new(
        key,
        normalized.encode(),
        hashlib.sha256
    ).digest()


def machine_code(android_id):
    h = hmac_digest("machine", android_id)

    return f"{h[0]:02X}{h[1]:02X}-{h[2]:02X}{h[3]:02X}"


def pin(android_id):
    h = hmac_digest("pin", android_id)

    n = (
        ((h[0] & 0x7F) << 24)
        | (h[1] << 16)
        | (h[2] << 8)
        | h[3]
    )

    return f"{n % 1_000_000:06d}"

print(pin('C478EFE3CEAEFBF7'))