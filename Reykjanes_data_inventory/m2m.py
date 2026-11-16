import os
import time

import requests

API = "https://m2m.cr.usgs.gov/api/api/json/stable/"
DATASET = "landsat_ot_c2_l1"


class M2M:
    def __init__(self):
        self.key = None
        self.key = self.call("login-token", username=os.environ["USGS_USERNAME"], token=os.environ["USGS_TOKEN"])

    def call(self, endpoint, **payload):
        headers = {"X-Auth-Token": self.key} if self.key else {}
        r = requests.post(API + endpoint, json=payload, headers=headers, timeout=300)
        r.raise_for_status()
        j = r.json()
        if j.get("errorCode"):
            raise RuntimeError(f"M2M {endpoint}: {j['errorCode']} {j.get('errorMessage')}")
        return j["data"]

    def urls(self, product_ids, filenames, polls=12):
        label = f"reykjanes_{int(time.time() * 1000)}"
        self.call("scene-list-add", listId=label, datasetName=DATASET, idField="displayId", entityIds=list(product_ids))
        try:
            options = self.call("download-options", datasetName=DATASET, listId=label)
        finally:
            self.call("scene-list-remove", listId=label)
        wanted, names = [], {}
        for o in options or []:
            for s in o.get("secondaryDownloads") or []:
                if s.get("available") and s.get("displayId") in filenames:
                    wanted.append({"entityId": s["entityId"], "productId": s["id"]})
                    names[s["entityId"]] = s["displayId"]
        if not wanted:
            return {}
        got = {}
        res = self.call("download-request", downloads=wanted, label=label)
        self._collect(res.get("availableDownloads"), names, got)
        for _ in range(polls):
            if len(got) >= len(wanted):
                break
            time.sleep(15)
            self._collect((self.call("download-retrieve", label=label) or {}).get("available"), names, got)
        return got

    @staticmethod
    def _collect(items, names, got):
        for it in items or []:
            name = it.get("displayId") or names.get(it.get("entityId"))
            if name in names.values() and it.get("url"):
                got[name] = it["url"]

    def logout(self):
        try:
            self.call("logout")
        except Exception:
            pass