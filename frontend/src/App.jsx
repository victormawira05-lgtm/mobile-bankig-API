async function totp(){
  // Backend secret is base32 of "1234567890123456" = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
  const secretStr = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
  const secret = new TextEncoder().encode(secretStr)
  const counter = Math.floor(Date.now()/30000)
  const buf = new ArrayBuffer(8)
  new DataView(buf).setBigUint64(0, BigInt(counter), false)
  const key = await crypto.subtle.importKey("raw", secret, {name:"HMAC", hash:"SHA-256"}, false, ["sign"])
  const sig = await crypto.subtle.sign("HMAC", key, buf)
  const offset = new Uint8Array(sig).slice(-1)[0] & 0xF
  const val = (new DataView(sig).getUint32(offset) & 0x7FFFFFFF) % 1000000
  return String(val).padStart(6,'0')
}