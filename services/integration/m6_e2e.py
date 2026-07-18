"""Deprecated M6 entry point.

The former implementation depended on machine-specific paths and made a live
Binance testnet request.  Security verification must be deterministic and
side-effect free, so this compatibility entry point delegates to the hardened
dry-run M6 v2 composition.
"""
from m6_e2e_v2 import main


if __name__ == "__main__":
    main()
