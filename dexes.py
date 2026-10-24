import logging
import os
import yaml
from typing import List

import requests
from pydantic import BaseModel

OFFLINE = os.environ.get("TON_ASSETS_OFFLINE") == "1"
TIMEOUT = 30   # يمنع تعليق الـ job إلى الأبد


class Asset(BaseModel):
    name: str
    address: str
    symbol: str


class MegatonAsset(Asset):
    type: int
    isVisible: int


class StonfiAsset(BaseModel):
    contract_address: str
    display_name: str
    symbol: str
    kind: str
    decimals: int
    community: bool
    blacklisted: bool
    deprecated: bool


def __get_stonfi_assets() -> List[Asset]:
    if OFFLINE:
        return list()
    try:
        response = requests.get("https://api.ston.fi/v1/assets", timeout=TIMEOUT)
        if response.status_code != 200:
            logging.error("failed to get stonfi assets (%s)", response.status_code)
            return list()
        data = response.json()
    except Exception as e:
        logging.error("stonfi request failed: %s", e)
        return list()
    assets = list()
    for item in data.get("asset_list", []):
        try:
            a = StonfiAsset(**item)
            if a.community or a.blacklisted or a.deprecated or a.kind != "Jetton":
                continue
            assets.append(Asset(name=a.display_name, address=a.contract_address, symbol=a.symbol))
        except Exception:
            continue
    return assets


def __get_megaton_assets() -> List[Asset]:
    if OFFLINE:
        return list()
    try:
        response = requests.get("https://megaton.fi/api/token/infoList", timeout=TIMEOUT)
        if response.status_code != 200:
            return list()
        data = response.json()
    except Exception as e:
        logging.error("megaton request failed: %s", e)
        return list()
    assets = list()
    for item in data:
        try:
            a = MegatonAsset(**item)
            if a.isVisible == 1 and a.type == 2:
                assets.append(Asset(name=a.name, address=a.address, symbol=a.symbol))
        except Exception:
            continue
    return assets


def __get_dedust_assets() -> List[Asset]:
    if OFFLINE:
        return list()
    try:
        response = requests.get("https://assets.dedust.io/list.json", timeout=TIMEOUT)
        if response.status_code != 200:
            logging.error("failed to get dedust assets (%s)", response.status_code)
            return list()
        data = response.json()
    except Exception as e:
        logging.error("dedust request failed: %s", e)
        return list()
    # عناوين غير موثوقة — لا تُدرج في القائمة أبداً
    b_addrs = {
        "EQBiyZMUXvdnRYFUk3_R5uPdsR2ROI9mes_1S-jL1tIQDhDK",
        "EQB22u_EPF5DyqtZRhjJ2YiZliN-w5ZCq6F_PY6Ia6bvi3Et",  # DUROV, untrusted (#6312)
    }
    assets = list()
    for item in data:
        addr = item.get("address")
        if not addr or addr in b_addrs:
            continue
        try:
            assets.append(Asset(**item))
        except Exception:
            continue
    return assets


def __get_backed_assets() -> List[Asset]:
    if OFFLINE:
        return list()
    try:
        response = requests.get("https://api.backed.fi/api/v1/token", timeout=TIMEOUT)
        if response.status_code != 200:
            logging.error("failed to get backed assets (%s)", response.status_code)
            return list()
        data = response.json()
    except Exception as e:
        logging.error("backed request failed: %s", e)
        return list()
    assets = list()
    for item in data.get("nodes", []):
        ton_addr = ""
        for d in item.get("deployments", []):
            if d.get("network", "").lower() == "ton":
                ton_addr = d["address"].removeprefix("ton:")
        if ton_addr == "":
            continue
        try:
            assets.append(Asset(name=item["name"], address=ton_addr, symbol=item["symbol"]))
        except Exception:
            continue
    return assets


def update_stonfi_routers():
    if OFFLINE:
        logging.warning("OFFLINE — تخطّي تحديث راوترات STON.fi")
        return
    try:
        response = requests.get("https://api.ston.fi/v1/routers", timeout=TIMEOUT)
        if response.status_code != 200:
            logging.error("failed to update stonfi routers (%s)", response.status_code)
            return
        data = response.json()
    except Exception as e:
        logging.error("routers request failed: %s", e)
        return
    routers = [{"address": item["address"], "name": "STON.fi DEX"}
               for item in data.get("router_list", []) if item.get("address")]
    if len(routers) == 0:
        logging.warning("0 راوتر — الاحتفاظ بـ accounts/ston.yaml الموجود")
        return
    path = "accounts/ston.yaml"
    try:
        old = yaml.safe_load(open(path, encoding="utf-8")) or []
        if isinstance(old, dict):
            old = [old]
    except Exception:
        old = []
    if old and len(routers) < len(old) * 0.5:
        logging.warning("الراوترات الجديدة (%d) أقل من نصف الموجودة (%d) — الاحتفاظ", len(routers), len(old))
        return
    routers.sort(key=lambda x: x["address"])
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(routers, f, sort_keys=True, allow_unicode=True)
