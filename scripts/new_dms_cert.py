"""Creates the certificate the DMS signs in to SharePoint with (DMS_SP_AUTH=certificate), without OpenSSL.

    cd webapi
    .\\.venv\\Scripts\\python ..\\scripts\\new_dms_cert.py

It writes, next to webapi (webapi\\cert\\):
    dms-webapi.pem   the private key and the certificate: DMS_CERT_PATH. Keep it readable by the DMS account only
    dms-webapi.cer   the certificate alone: upload this one to the Entra app (Certificates & secrets > Certificates)
and prints the thumbprint for DMS_CERT_THUMBPRINT. Run it once, on the machine that runs the DMS.
A site cannot sign in through a browser, so interactive mode works only when you run the DMS by hand.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

NAME = "dms-webapi"
YEARS = 2


def main(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    pem, cer = folder / f"{NAME}.pem", folder / f"{NAME}.cer"
    if pem.exists():
        print(f"{pem} already exists. Delete it first to make a new certificate.")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365 * YEARS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))

    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption())
                    + cert.public_bytes(serialization.Encoding.PEM))
    cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    print(f"DMS_CERT_PATH={pem}")
    print(f"DMS_CERT_THUMBPRINT={cert.fingerprint(hashes.SHA1()).hex().upper()}")   # noqa: S303 - Entra uses SHA-1 here
    print(f"\nUpload to the Entra app (Certificates & secrets > Certificates): {cer}")
    print(f"Valid until {cert.not_valid_after_utc:%Y-%m-%d}. The DMS stops reaching SharePoint after that.")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "webapi" / "cert")
