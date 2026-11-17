import os
import time
from datetime import date, timedelta

import requests

API = "https://m2m.cr.usgs.gov/api/api/json/stable/"
DATASET = "landsat_ot_c2_l1"
L2 = "landsat_ot_c2_l2"


def scene_of(id_):
    if "_" in id_:
        f = id_.split("_")
        return f"{f[0]}_{f[2]}_{f[3]}" if len(f) > 3 else None
    if len(id_) >= 16 and id_[3:16].isdigit():
        day = date(int(id_[9:13]), 1, 1) + timedelta(int(id_[13:16]) - 1)
        return f"{id_[:2]}0{id_[2]}_{id_[3:9]}_{day:%Y%m%d}"
    return None


def file_key(name):
    f = name.split("_")
    return f"{f[0]}_{f[2]}_{f[3]}|{'_'.join(f[7:])}" if len(f) > 7 else None


class M2M:
    def __init__(self, bbox=None, start="2020-01-01", end="2026-12-31"):
        self.bbox, self.start, self.end, self._l2 = bbox, start, end, None
        self.login()

    def login(self):
        self.key = None
        self.key = self.call("login-token", username=os.environ["USGS_USERNAME"], token=os.environ["USGS_TOKEN"])
        self.since = time.time()

    def call(self, endpoint, **payload):
        headers = {"X-Auth-Token": self.key} if self.key else {}
        r = requests.post(API + endpoint, json=payload, headers=headers, timeout=300)
        r.raise_for_status()
        j = r.json()
        if j.get("errorCode"):
            raise RuntimeError(f"M2M {endpoint}: {j['errorCode']} {j.get('errorMessage')}")
        return j["data"]

    def l2_scenes(self):
        if self._l2 is None:
            w, s, e, n = self.bbox
            res = self.call("scene-search", datasetName=L2, maxResults=10000, sceneFilter={
                "spatialFilter": {"filterType": "mbr", "lowerLeft": {"latitude": s, "longitude": w},
                                  "upperRight": {"latitude": n, "longitude": e}},
                "acquisitionFilter": {"start": self.start, "end": self.end}})
            self._l2 = {}
            for r in (res or {}).get("results", []):
                sc = scene_of(r.get("displayId") or "") or scene_of(r.get("entityId") or "")
                if sc:
                    self._l2[sc] = r["entityId"]
            print(f"  USGS L2: {len(self._l2)} scen nad ROI w katalogu")
        return self._l2

    def urls(self, product_ids, filenames, dataset=DATASET, polls=12):
        if time.time() - self.since > 90 * 60:
            self.login()
        if dataset == L2:
            found = self.l2_scenes()
            ids, field = [found[s] for s in {scene_of(p) for p in product_ids} if s in found], "entityId"
        else:
            ids, field = list(product_ids), "displayId"
        if not ids:
            return {}
        want = {file_key(f): f for f in filenames}
        label = f"reykjanes_{int(time.time() * 1000)}"
        self.call("scene-list-add", listId=label, datasetName=dataset, idField=field, entityIds=ids)
        try:
            options = self.call("download-options", datasetName=dataset, listId=label)
        finally:
            self.call("scene-list-remove", listId=label)
        wanted, by_ent, by_disp = [], {}, {}
        for o in options or []:
            for s in o.get("secondaryDownloads") or []:
                name = want.get(file_key(s.get("displayId") or ""))
                if s.get("available") and name:
                    wanted.append({"entityId": s["entityId"], "productId": s["id"]})
                    by_ent[s["entityId"]], by_disp[s["displayId"]] = name, name
        if not wanted:
            return {}
        got = {}
        res = self.call("download-request", downloads=wanted, label=label)
        self._collect(res.get("availableDownloads"), by_ent, by_disp, got)
        for _ in range(polls):
            if len(got) >= len(wanted):
                break
            time.sleep(15)
            self._collect((self.call("download-retrieve", label=label) or {}).get("available"), by_ent, by_disp, got)
        return got

    @staticmethod
    def _collect(items, by_ent, by_disp, got):
        for it in items or []:
            name = by_ent.get(it.get("entityId")) or by_disp.get(it.get("displayId"))
            if name and it.get("url"):
                got[name] = it["url"]

    def logout(self):
        try:
            self.call("logout")
        except Exception:
            pass