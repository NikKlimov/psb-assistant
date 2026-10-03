"""Export trusted Windows roots for requests without disabling TLS verification."""
import ssl
from pathlib import Path

import certifi

target = Path(__file__).resolve().parents[1] / "data" / "system-ca.pem"
target.parent.mkdir(exist_ok=True)
bundle = Path(certifi.where()).read_text(encoding="ascii")
for store in ("ROOT", "CA"):
    for cert, encoding, trust in ssl.enum_certificates(store):
        if encoding == "x509_asn" and (trust is True or "1.3.6.1.5.5.7.3.1" in trust):
            bundle += ssl.DER_cert_to_PEM_cert(cert)
target.write_text(bundle, encoding="ascii")
print(target)
