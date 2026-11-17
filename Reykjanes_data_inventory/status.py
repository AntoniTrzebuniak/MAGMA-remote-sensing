import warnings

import pandas as pd

from download import GCS, ROOT, gcs

warnings.filterwarnings("ignore", category=FutureWarning)

m = pd.read_csv(ROOT / "manifest" / "download_manifest.csv")
blobs = {b.name: b.size or 0 for b in gcs().list_blobs(prefix=f"{GCS['prefix']}/")}

m["key"] = GCS["prefix"] + "/" + m.dst
m["done"] = m.key.isin(blobs)
m["gb"] = m.key.map(blobs).fillna(0) / 1e9
m["typ"] = m.sensor.where(m.sensor == "EnMAP", "Landsat") + " " + m.day_night.map({"day": "dzień", "night": "noc"})

t = m.groupby(["typ", "priority"]).agg(plikow=("done", "size"), jest=("done", "sum"), GB=("gb", "sum"))
t["brakuje"] = t.plikow - t.jest
t["%"] = (100 * t.jest / t.plikow).round().astype(int)
print(t[["plikow", "jest", "brakuje", "%", "GB"]].round(2).to_string())

keys = set(m.key)
extra = [k for k in blobs if k not in keys]
print(f"\nRazem z manifestu: {m.done.sum()} z {len(m)} plików ({100 * m.done.mean():.0f}%), {m.gb.sum():.1f} GB")
print(f"Cały prefiks gs://{GCS['bucket']}/{GCS['prefix']}/: {len(blobs)} plików, {sum(blobs.values()) / 1e9:.1f} GB")
if extra:
    print(f"Pliki spoza manifestu: {len(extra)}, np. {extra[0]}")