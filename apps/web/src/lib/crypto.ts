/**
 * AES-256-GCM twin of shared/voiceqa_shared/crypto.py.
 *
 * Must stay byte-compatible: same key derivation (base64 32-byte key, else
 * sha256 of the raw string) and the same wire format
 * `base64(nonce) + "." + base64(ciphertext || tag)` (16-byte GCM tag
 * appended to the ciphertext, matching Python's cryptography AESGCM output).
 *
 * Used server-side only, by the lazy NextAuth init, to decrypt the SSO
 * client secret read from the sso_config row.
 *
 * Cross-language test vector (APP_ENCRYPTION_KEY = "dGVzdC1rZXktMzItYnl0ZXMtZXhhY3RseSEhMTIzNDU="):
 *   decrypt_str(encrypt_str("hello")) === "hello" in BOTH Python and Node, and
 *   a token produced by one decrypts in the other. Verified in CI / by hand.
 */

import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

const TAG_BYTES = 16;

function derivedKey(): Buffer {
  const raw = process.env.APP_ENCRYPTION_KEY ?? "";
  const decoded = Buffer.from(raw, "base64");
  // Mirror Python's base64.b64decode(raw, validate=True) + len==32 check:
  // only the base64 path when it round-trips to the exact same string.
  if (decoded.length === 32 && decoded.toString("base64") === raw) {
    return decoded;
  }
  return createHash("sha256").update(raw, "utf8").digest();
}

export function encryptStr(plaintext: string): string {
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", derivedKey(), nonce);
  const ct = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  const combined = Buffer.concat([ct, tag]);
  return `${nonce.toString("base64")}.${combined.toString("base64")}`;
}

export function decryptStr(token: string): string {
  const [nonceB64, ctB64] = token.split(".");
  const nonce = Buffer.from(nonceB64, "base64");
  const combined = Buffer.from(ctB64, "base64");
  const ct = combined.subarray(0, combined.length - TAG_BYTES);
  const tag = combined.subarray(combined.length - TAG_BYTES);
  const decipher = createDecipheriv("aes-256-gcm", derivedKey(), nonce);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]).toString("utf8");
}
