#!/bin/env python3
"""مولّد ملفات ton-assets — نسخة محصّنة:
- لا يُفرّغ ملفات API عند فشل الشبكة (يحتفظ بالبيانات الموجودة)
- TON_ASSETS_OFFLINE=1 يتخطى كل الاستدعاءات الخارجية
- يمنع تكرار عناوين الحسابات
"""
import json
import os
import glob
import logging
import yaml

from dexes import (__get_stonfi_assets, __get_dedust_assets, __get_backed_assets,
                   update_stonfi_routers)
from utlis import normalize_address

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

OFFLINE = os.environ.get("TON_ASSETS_OFFLINE") == "1"
# لا تُعد كتابة ملف مُولّد من API إذا قلت عناصره عن هذه النسبة من الموجود
MIN_KEEP_RATIO = 0.5

EXPLORER_JETTONS = "https://tonviewer.com/"
EXPLORER_ACCOUNTS = "https://tonviewer.com/"
EXPLORER_COLLECTIONS = "https://tonviewer.com/"

DEXES_FILE_NAME = "imported_from_dex.yaml"
BACKED_FILE_NAME = "backed.yaml"


def _safe_write_yaml(path, new_items, label):
    """يكتب فقط إذا كانت البيانات الجديدة موثوقة — يحمي من فقدان الأصول عند 403/انقطاع الشبكة."""
    old_items = []
    if os.path.isfile(path):
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8"))
            old_items = doc if isinstance(doc, list) else ([doc] if doc else [])
        except Exception:
            old_items = []
    if not new_items:
        logging.warning("%s: النتيجة 0 عنصر — الاحتفاظ بالملف الموجود (%d عنصر)", label, len(old_items))
        return False
    if old_items and len(new_items) < len(old_items) * MIN_KEEP_RATIO:
        logging.warning("%s: %d عنصر جديد < %.0f%% من الموجود (%d) — الاحتفاظ بالملف",
                        label, len(new_items), MIN_KEEP_RATIO * 100, len(old_items))
        return False
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_items, f, sort_keys=True, allow_unicode=True)
    logging.info("%s: كُتب %d عنصراً", label, len(new_items))
    return True


def collect_all_dexes():
    if OFFLINE:
        logging.warning("وضع OFFLINE — تخطّي تحديث DEX")
        return
    temp, jettons = list(), list()
    for file in sorted(glob.glob("jettons/*.yaml")):
        if file.endswith(DEXES_FILE_NAME):
            continue
        temp.append(yaml.safe_load(open(file)))
    for item in temp:
        if isinstance(item, list):
            jettons.extend(item)
        else:
            jettons.append(item)

    already_exist_address = dict()
    for jetton in jettons:
        if not isinstance(jetton, dict) or "address" not in jetton:
            continue
        already_exist_address[normalize_address(jetton["address"], True)] = True

    assets = __get_dedust_assets() + __get_stonfi_assets()
    assets_for_save = dict()
    for asset in assets:
        asset.address = normalize_address(asset.address, True)
        if already_exist_address.get(asset.address, None):
            continue
        assets_for_save[asset.address] = {
            "name": asset.name, "address": asset.address, "symbol": asset.symbol
        }
    _safe_write_yaml(f"jettons/{DEXES_FILE_NAME}",
                     list(sorted(assets_for_save.values(), key=lambda x: x["symbol"])), "DEX")


def collect_all_backed():
    if OFFLINE:
        logging.warning("وضع OFFLINE — تخطّي تحديث backed")
        return
    assets = __get_backed_assets()
    assets_for_save = dict()
    for asset in assets:
        asset.address = normalize_address(asset.address, True)
        assets_for_save[asset.address] = {
            "name": asset.name, "address": asset.address, "symbol": asset.symbol
        }
    _safe_write_yaml(f"jettons/{BACKED_FILE_NAME}",
                     list(sorted(assets_for_save.values(), key=lambda x: x["symbol"])), "backed")


ALLOWED_KEYS = {"symbol", "name", "address", "description", "image", "social",
                "websites", "decimals", "coinmarketcap", "coingecko"}


def merge_jettons():
    temp = [yaml.safe_load(open(file)) for file in sorted(glob.glob("jettons/*.yaml"))]
    jettons = []
    for j in temp:
        if isinstance(j, list):
            jettons.extend(j)
        else:
            jettons.append(j)

    already_exist_address = dict()
    for j in jettons:
        if not isinstance(j, dict):
            raise Exception("invalid jetton entry (not a mapping)")
        extra = set(j.keys()) - ALLOWED_KEYS
        if extra:
            raise Exception(f"invalid keys {extra} in {j.get('name')}")
        if len(set(j.keys()) & {"name", "symbol", "address"}) < 3:
            raise Exception(f"name, symbol, and address are required in {j.get('name')}")
        if "image" in j and j["image"].startswith("https://cache.tonapi.io"):
            raise Exception(f"don't use cache.tonapi.io as image source in {j.get('name')}")
        normalized = normalize_address(j["address"], True)
        if normalized in already_exist_address:
            raise Exception(f"duplicate address for {j['name']} and {already_exist_address[normalized]}")
        already_exist_address[normalized] = j["name"]
        j["address"] = normalized
        for field in ["symbol", "name", "address", "description", "image", "coinmarketcap", "coingecko"]:
            if not isinstance(j.get(field, ""), str):
                raise Exception(f"invalid field type for {field} in {j.get('name')}")
        for field in ["social", "websites"]:
            if field in j and (not isinstance(j[field], list) or any(not isinstance(x, str) for x in j[field])):
                raise Exception(f"invalid list field type for {field} in {j.get('name')}")
        if "decimals" in j:
            j["decimals"] = int(j["decimals"])

    with open("jettons.json", "w", encoding="utf-8") as out:
        json.dump(jettons, out, indent=" ", sort_keys=True, ensure_ascii=False)
    return sorted([(j.get("name", "unknown"), j.get("address", "unknown")) for j in jettons])


def merge_accounts(accounts):
    """مثل الأصل + منع التكرار (كان التكرار يمرّ بصمت)."""
    main_page = list()
    collected = list()

    def extend(items, to_main=False):
        for x in items or []:
            if not isinstance(x, dict) or "address" not in x:
                continue
            addr = normalize_address(x["address"], True)
            x["address"] = addr
            collected.append(x)
            if to_main:
                main_page.append((x.get("name", ""), addr))

    for file in ("accounts/infrastructure.yaml", "accounts/defi.yaml", "accounts/celebrities.yaml"):
        extend(yaml.safe_load(open(file, encoding="utf-8")), to_main=True)
    for file in ("accounts/givers.yaml", "accounts/custodians.yaml", "accounts/bridges.yaml",
                 "accounts/validators.yaml", "accounts/scammers.yaml", "accounts/notcoin.yaml",
                 "accounts/dapps.yaml", "accounts/ston.yaml"):
        extend(yaml.safe_load(open(file, encoding="utf-8")))

    seen, deduped = set(), []
    for x in collected:
        if x["address"] in seen:
            logging.warning("duplicate account %s (%s) — skipped", x["address"], x.get("name"))
            continue
        seen.add(x["address"])
        deduped.append(x)

    accounts.extend(deduped)
    with open("accounts.json", "w", encoding="utf-8") as out:
        json.dump(accounts, out, indent=" ", sort_keys=True, ensure_ascii=False)

    seen_main, mp = set(), []
    for name, addr in main_page:
        if addr in seen_main:
            continue
        seen_main.add(addr)
        mp.append((name, addr))
    return mp


def merge_collections():
    raw = [yaml.safe_load(open(file)) for file in sorted(glob.glob("collections/*.yaml"))]
    collections = list()
    for c in raw:
        if isinstance(c, list):
            collections.extend(c)
        else:
            collections.append(c)
    for collection in collections:
        collection["address"] = normalize_address(collection["address"], True)
    with open("collections.json", "w", encoding="utf-8") as out:
        json.dump(collections, out, indent=" ", sort_keys=True, ensure_ascii=False)
    return sorted([(c.get("name", "unknown"), c.get("address", "unknown")) for c in collections])


def main():
    if len([x for x in glob.glob("*.yaml")]) > 0:
        raise Exception("please don't add yaml files to root directory. use jettons/ or collections/")
    update_stonfi_routers()
    collect_all_dexes()
    collect_all_backed()
    merge_jettons()
    collections = merge_collections()
    accounts = merge_accounts([])
    accounts_md = "\n".join(
        "[%s](%s%s) | %s" % (n, EXPLORER_ACCOUNTS, a, normalize_address(a, False))
        for n, a in accounts)
    collections_md = "\n".join(
        "[%s](%s%s) | %s" % (n, EXPLORER_COLLECTIONS, a, normalize_address(a, False))
        for n, a in collections)
    # القالب يحوي معاملين فقط (حسابات + مجموعات)
    open("README.md", "w", encoding="utf-8").write(
        open("readme.md.template", encoding="utf-8").read() % (accounts_md, collections_md))


if __name__ == "__main__":
    main()
