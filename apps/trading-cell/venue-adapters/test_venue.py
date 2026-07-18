import tempfile, os, uuid
from venue_adapter import make_venue, OrderIntent, VENUES, LiveVenueDisabled
from external_effect_registry import ExternalEffectRegistry
st = tempfile.mkdtemp()
def intent(): return OrderIntent(str(uuid.uuid4()), "BTCUSDT", "BUY", "MARKET", 1500000, 0)
R={}
# 1. all three venues submit in dry-run with correct native id field mapping
for name, field in [("binance","newClientOrderId"),("hyperliquid","cloid"),("bitunix","clientId")]:
    v = make_venue(name, dry_run=True); i = intent(); res = v.submit(i)
    ok = res.ok and res.status=="DRY_RUN" and v.native_client_id_field==field
    # verify the native id field is present in the payload
    payload = res.detail["payload"]
    ok = ok and (field in payload or (name=="hyperliquid" and "cloid" in payload))
    R[f"{name} dry-run + native id field"] = ok
# 2. idempotent submit via ExternalEffectRegistry: replay does not double-send
reg = ExternalEffectRegistry(os.path.join(st,"eff.db"))
v = make_venue("binance", dry_run=True); i = intent()
r1 = v.submit(i, effect_registry=reg); r2 = v.submit(i, effect_registry=reg)
R["idempotent submit (replay no double-send)"] = r1.status=="DRY_RUN" and r2.status=="REPLAYED"
# 3. reconcile works per venue
R["reconcile binance"] = make_venue("binance").reconcile()["reconciled"] is True
R["reconcile hyperliquid"] = make_venue("hyperliquid").reconcile()["reconciled"] is True
R["reconcile bitunix"] = make_venue("bitunix").reconcile()["reconciled"] is True
# 4. registry of venues
R["all 3 venues registered"] = set(VENUES) == {"binance","hyperliquid","bitunix"}
# 5. legacy adapter cannot be switched live by a caller
try:
    make_venue("binance", client=object(), dry_run=False)
    R["legacy live mode hard-disabled"] = False
except LiveVenueDisabled:
    R["legacy live mode hard-disabled"] = True

print("== VenueAdapter (Binance/Hyperliquid/Bitunix) ==")
ok=True
for k,v in R.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
reg.close()
print("\n"+("ALL PASS ("+str(sum(R.values()))+"/"+str(len(R))+")" if ok else "FAIL"))
import shutil,sys; shutil.rmtree(st,ignore_errors=True); sys.exit(0 if ok else 1)
