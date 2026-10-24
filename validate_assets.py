#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""فحص شامل لملفات ton-assets. يُستخدم في CI وفي run_all.sh."""
import json, re, sys, glob, os
from collections import Counter
import yaml

HEX = re.compile(r"^-?\d+:[0-9a-f]{64}$")
ALLOWED_KEYS = {"symbol","name","address","description","image","social",
                "websites","decimals","coinmarketcap","coingecko"}
BLACKLIST_B64 = {
    "EQBiyZMUXvdnRYFUk3_R5uPdsR2ROI9mes_1S-jL1tIQDhDK",
    "EQB22u_EPF5DyqtZRhjJ2YiZliN-w5ZCq6F_PY6Ia6bvi3Et",
}
errs, warns = [], []

def norm(a):
    import base64
    a = str(a).strip()
    if ":" in a:
        return a.lower()
    if len(a) == 48:
        raw = base64.urlsafe_b64decode(a)
        wc = raw[1] - 256 if raw[1] == 255 else raw[1]
        return "%d:%s" % (wc, raw[2:34].hex())
    return None

BL = {norm(x) for x in BLACKLIST_B64}

for f in ["accounts.json", "jettons.json", "collections.json"]:
    try:
        data = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        errs.append(f"{f}: لا يمكن قراءته — {e}")
        continue
    if not isinstance(data, list):
        errs.append(f"{f}: ليس قائمة JSON")
        continue
    for i, x in enumerate(data):
        if not isinstance(x, dict):
            errs.append(f"{f}[{i}]: ليس كائناً")
            continue
        a = str(x.get("address", "")).strip()
        if not HEX.match(a):
            errs.append(f"{f}[{i}]: عنوان غير صالح '{a}'")
        n = norm(a)
        if n in BL:
            errs.append(f"{f}[{i}]: عنوان محظور (قائمة سوداء): {a}")
        if f == "jettons.json":
            miss = {"name", "symbol", "address"} - set(x.keys())
            if miss:
                errs.append(f"{f}[{i}]: حقول ناقصة {miss}")
            extra = set(x.keys()) - ALLOWED_KEYS
            if extra:
                errs.append(f"{f}[{i}]: مفاتيح غير مسموحة {extra}")
            for field in ["symbol", "name", "address", "description", "image", "coinmarketcap", "coingecko"]:
                if field in x and not isinstance(x[field], str):
                    errs.append(f"{f}[{i}]: حقل {field} ليس نصاً")
            for field in ["social", "websites"]:
                if field in x and (not isinstance(x[field], list) or any(not isinstance(v, str) for v in x[field])):
                    errs.append(f"{f}[{i}]: حقل {field} يجب أن يكون قائمة نصوص")
            if str(x.get("image", "")).startswith("https://cache.tonapi.io"):
                errs.append(f"{f}[{i}]: صورة من cache.tonapi.io ممنوعة")
    c = Counter(str(x.get("address", "")).lower() for x in data if isinstance(x, dict))
    for a, n in c.items():
        if n > 1:
            errs.append(f"{f}: عنوان مكرر {n} مرات: {a}")
    print(f"{f}: {len(data)} عنصر")

# اتساق JSON مع ملفات yaml المصدر
def yaml_addrs(pattern, label):
    out = set()
    for p in sorted(glob.glob(pattern)):
        try:
            d = yaml.safe_load(open(p, encoding="utf-8"))
        except Exception as e:
            errs.append(f"{label}/{os.path.basename(p)}: yaml تالف — {e}")
            continue
        items = d if isinstance(d, list) else ([d] if d else [])
        for x in items:
            if isinstance(x, dict) and x.get("address"):
                n = norm(x["address"])
                if n:
                    out.add(n)
    return out

for pattern, jsonfile in [("jettons/*.yaml", "jettons.json"),
                          ("collections/*.yaml", "collections.json")]:
    src = yaml_addrs(pattern, pattern.split("/")[0])
    try:
        gen = {str(x["address"]).lower() for x in json.load(open(jsonfile, encoding="utf-8"))}
    except Exception:
        continue
    missing = src - gen
    extra = gen - src
    if missing:
        errs.append(f"{jsonfile}: {len(missing)} عنوان موجود في yaml وغير موجود في JSON — شغّل generator.py")
    if extra:
        errs.append(f"{jsonfile}: {len(extra)} عنوان في JSON بلا مصدر yaml")
    if not missing and not extra:
        print(f"{jsonfile}: متطابق مع ملفات yaml ✅")

if errs:
    print("\n" + "\n".join("❌ " + e for e in errs))
    sys.exit(1)
print("✅ كل الفحوصات ناجحة")
