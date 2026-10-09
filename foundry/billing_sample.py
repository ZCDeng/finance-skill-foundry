"""华宸物业 海口城市公司 收费明细: the billing-system export the example uses to show the 收费明细 channel.

About twelve thousand properties in six projects (洋房、别墅、车位、储藏室、写字楼、商业), every bill from
账期 2025-01 to 2026-08 plus the future bills prepayers have already paid, and every receipt up to the
statistics date 2026-08-31: some eight hundred thousand rows. The export is written by this module on
demand rather than shipped, so the app carries a few kilobytes of code instead of tens of megabytes of CSV.
The same seed writes the same bytes on every machine and every Python 3 (``random.Random`` with integer
draws only, amounts in fen).

Eight things are planted for the analysis to find (方案 notes/billing-detail-collection-plan-20261008.md, 五):

1. 南洋城 has 380 vacant flats and 150 parking spaces still held by the developer (产权归属 地产) that
   barely pay, and the developer's own shops at 国贸中心 pay little better: leaving related parties out
   moves the total rate by several points.
2. 150 villa owners at 滨海壹号 prepaid their 2027 fees in August 2026, and the cashier labelled the
   receipts 当期.
3. 70 receipts in 2026 against 2025 bills at 观澜府 are labelled 当期 instead of 清欠.
4. 260 bills were voided but are still in the export, and 90 bills carry a separate red-letter line.
5. 4 parking spaces at 观澜府 are billed under 房产编号 the property master does not have.
6. 云海苑 waives half the fee of more than a third of its flats as 空置减免, far above any other project.
7. The billing system's own 本年收缴率 counts receipts by their label, so it agrees with the 套表 (83.76%);
   by 账期 the rate is lower.
8. Flats collect well in the year but 国贸中心's commercial tenants recover almost none of last year's arrears.
"""

from __future__ import annotations

import calendar
import csv
import random
from pathlib import Path

SEED = 20261008
CITY = "海口城市公司"
AS_OF = (2026, 8, 31)
AS_OF_TEXT = "2026-08-31"
# 11·城市公司明细表, 海口城市公司, 本年收缴率: what the 套表 reports for the city, to reconcile against.
REPORTED_CURRENT = "0.8375607752862742"
FIRST_PERIOD = (2025, 1)
PREFIX = "华宸物业_海口"
FILES = {
    "property": [f"{PREFIX}_房产主数据.csv"],
    "receivable": [f"{PREFIX}_应收明细_2025.csv", f"{PREFIX}_应收明细_2026.csv"],
    "receipt": [f"{PREFIX}_实收明细.csv"],
}
SAMPLE_WORKBOOK = f"{PREFIX}_收费明细抽样.xlsx"
NAMES = {"property": "房产主数据", "receivable": "应收明细", "receipt": "实收明细"}

PROPERTY_COLUMNS = ["项目编码", "项目", "城市公司", "楼栋", "房产编号", "门牌号", "房产性质", "房产类型",
                    "产权归属", "计费面积", "空间状态", "起费日期", "收房日期"]
RECEIVABLE_COLUMNS = ["应收单号", "房产编号", "项目", "客户性质", "收费项目", "账期", "计费面积", "单价",
                      "应收原额", "减免额", "应收净额", "到期日", "单据状态"]
RECEIPT_COLUMNS = ["收款单号", "收款日期", "房产编号", "收费项目", "对应账期", "应收单号", "收款金额", "收款方式", "款项性质"]

# 项目编码, 项目, flats by type, parking, storage, payment profile weights (prompt, lag, prepay, debtor).
PROJECTS = [
    ("HK01", "椰林湾", {"洋房": 2300}, 700, 150, (72, 17, 8, 3)),
    ("HK02", "滨海壹号", {"别墅": 420, "洋房": 800}, 500, 100, (72, 11, 14, 3)),
    ("HK03", "观澜府", {"洋房": 2200}, 450, 0, (50, 26, 3, 21)),
    ("HK04", "南洋城", {"洋房": 1800}, 400, 100, (64, 19, 7, 10)),
    ("HK05", "云海苑", {"洋房": 1000}, 200, 50, (70, 17, 7, 6)),
    ("HK06", "国贸中心", {"写字楼": 160, "商业": 140}, 0, 0, (64, 22, 0, 14)),
]
PROFILES = ("prompt", "lag", "prepay", "debtor")
DEVELOPER_FLATS = ("HK04", 300)
DEVELOPER_PARKING = ("HK04", 150)
DEVELOPER_SHOPS = ("HK06", 20)
PREPAID_2027 = ("HK02", 36)
ARREARS_LABELLED_CURRENT = ("HK03", 70)
VOID_BILLS = 260
RED_LETTER_BILLS = 90
ORPHAN_PARKING = ("HK03", 4)
VACANCY_WAIVER = ("HK05", 36)  # percent of flats


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    year, month = start
    out = []
    while (year, month) <= end:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _add_months(period: tuple[int, int], count: int) -> tuple[int, int]:
    index = period[0] * 12 + period[1] - 1 + count
    return index // 12, index % 12 + 1


def _yuan(fen: int) -> str:
    sign = "-" if fen < 0 else ""
    fen = abs(fen)
    return f"{sign}{fen // 100}.{fen % 100:02d}"


def _day(rng: random.Random, period: tuple[int, int], low: int = 1, high: int | None = None) -> tuple[int, int, int]:
    last = calendar.monthrange(*period)[1]
    return (period[0], period[1], rng.randint(low, min(high or last, last)))


def _date(day: tuple[int, int, int]) -> str:
    return f"{day[0]}-{day[1]:02d}-{day[2]:02d}"


def _period(period: tuple[int, int]) -> str:
    return f"{period[0]}-{period[1]:02d}"


class _Book:
    """The properties, bills and receipts, built in memory in one pass of the generator."""

    def __init__(self) -> None:
        self.rng = random.Random(SEED)
        self.properties: list[dict] = []
        self.bills: list[dict] = []
        self.receipts: list[dict] = []
        self.bill_seq = 0
        self.receipt_seq = 0
        self.ghosts: list[dict] = []

    # Properties.

    def build_properties(self) -> None:
        rng = self.rng
        for code, name, flats, parking, storage, weights in PROJECTS:
            serial = 0
            for kind, count in flats.items():
                for index in range(count):
                    serial += 1
                    if kind in ("洋房", "别墅"):
                        building = (serial - 1) // 120 + 1
                        unit = (serial - 1) % 120 // 40 + 1
                        floor = (serial - 1) % 40 // 2 + 2
                        room = (serial - 1) % 2 + 1
                        pid = f"{code}-{building:02d}-{unit}-{floor:02d}{room:02d}"
                        door = f"{building}栋{unit}单元{floor:02d}{room:02d}"
                        area = rng.randint(7800, 14200) if kind == "洋房" else rng.randint(19000, 34000)
                        nature = "住宅"
                    elif kind == "写字楼":
                        floor = index // 10 + 6
                        pid = f"{code}-XZL-{floor:02d}{index % 10 + 1:02d}"
                        door = f"写字楼{floor}层{index % 10 + 1:02d}室"
                        area = rng.randint(8000, 30000)
                        nature = "商业/办公"
                    else:
                        floor = index // 50 + 1
                        pid = f"{code}-SY-{floor}F-{index % 50 + 1:03d}"
                        door = f"商业{floor}层{index % 50 + 1:03d}号"
                        area = rng.randint(4000, 26000)
                        nature = "商业/办公"
                    self._add_property(code, name, building_of(pid), pid, door, nature, kind, area, weights)
            for index in range(parking):
                pid = f"{code}-CW-B{index // 400 + 1}-{index % 400 + 1:04d}"
                self._add_property(code, name, "地下车库", pid, f"B{index // 400 + 1}-{index % 400 + 1:04d}车位",
                                   "住宅", "车位", 1250, weights)
            for index in range(storage):
                pid = f"{code}-CC-B1-{index + 1:03d}"
                self._add_property(code, name, "地下车库", pid, f"B1-{index + 1:03d}储藏室", "住宅", "储藏室",
                                   rng.randint(600, 1500), weights)
        self._plant_owners()

    def _add_property(self, code, name, building, pid, door, nature, kind, area, weights) -> None:
        rng = self.rng
        draw = rng.randrange(100)
        profile = PROFILES[0]
        for candidate, weight in zip(PROFILES, weights):
            if draw < weight:
                profile = candidate
                break
            draw -= weight
        state_draw = rng.randrange(100)
        state = "自住" if state_draw < 70 else "出租" if state_draw < 85 else "空置" if state_draw < 95 else "闲置"
        if kind in ("写字楼", "商业"):
            state = "出租" if state_draw < 80 else "自用" if state_draw < 92 else "空置"
        start = _date(_day(rng, (2019 + rng.randrange(5), rng.randint(1, 12))))
        self.properties.append({
            "project_code": code, "project": name, "building": building, "id": pid, "door": door,
            "nature": nature, "type": kind, "owner": "业主", "area": area, "state": state,
            "start": start, "received": start, "profile": profile, "waiver": False,
        })

    def _plant_owners(self) -> None:
        rng = self.rng
        by_project: dict[tuple[str, str], list[dict]] = {}
        for item in self.properties:
            by_project.setdefault((item["project_code"], item["type"]), []).append(item)
        flats = [item for item in by_project[(DEVELOPER_FLATS[0], "洋房")]]
        for item in rng.sample(flats, DEVELOPER_FLATS[1]):
            item.update(owner="地产", state="空置", profile="related")
        for item in rng.sample(by_project[(DEVELOPER_PARKING[0], "车位")], DEVELOPER_PARKING[1]):
            item.update(owner="地产", state="空置", profile="related")
        for item in rng.sample(by_project[(DEVELOPER_SHOPS[0], "商业")], DEVELOPER_SHOPS[1]):
            item.update(owner="地产", state="出租", profile="related")
        flats = by_project[(VACANCY_WAIVER[0], "洋房")]
        for item in rng.sample(flats, len(flats) * VACANCY_WAIVER[1] // 100):
            item.update(waiver=True, state="空置")
        villas = [item for item in by_project[(PREPAID_2027[0], "别墅")] if item["profile"] != "related"]
        for item in rng.sample(villas, PREPAID_2027[1]):
            item["profile"] = "prepay_2027"

    # Bills.

    def _fees(self, item: dict) -> list[tuple[str, int]]:
        """收费项目 and monthly gross in fen for one property."""
        rng = self.rng
        kind, area = item["type"], item["area"]
        if kind == "洋房":
            return [("住宅物业服务费", area * 220 // 100), ("公摊水电", rng.randint(1500, 4500))]
        if kind == "别墅":
            return [("住宅物业服务费", area * 380 // 100), ("公摊水电", rng.randint(3000, 7000))]
        if kind == "车位":
            return [("车位管理费", 15000 if item["project_code"] == "HK02" else 12000)]
        if kind == "储藏室":
            return [("储藏室管理费", area * 350 // 100)]
        if kind == "写字楼":
            return [("商办物业服务费", area * 950 // 100), ("能耗费", area * 120 // 100)]
        fees = [("商办物业服务费", area * 750 // 100)]
        if rng.randrange(100) < 30:
            fees.append(("商业租金代收", rng.randint(200000, 600000)))
        return fees

    def _bill(self, item: dict, fee: str, gross: int, period: tuple[int, int], status: str = "正常") -> dict:
        self.bill_seq += 1
        waiver = 0
        if fee.endswith("物业服务费"):
            if item["waiver"]:
                waiver = gross // 2
            elif item["type"] in ("洋房", "别墅") and self.rng.randrange(1000) < 6:
                waiver = gross // 10
        bill = {"id": f"YS{period[0]}{period[1]:02d}{self.bill_seq:07d}", "property": item, "pid": item["id"], "fee": fee,
                "period": period, "gross": gross, "waiver": waiver, "net": gross - waiver, "status": status, "red": 0}
        self.bills.append(bill)
        return bill

    def build_bills(self) -> None:
        months = _months(FIRST_PERIOD, AS_OF[:2])
        future_2026 = _months(_add_months(AS_OF[:2], 1), (2026, 12))
        future_2027 = _months((2027, 1), (2027, 12))
        for item in self.properties:
            fees = self._fees(item)
            periods = list(months)
            if item["profile"] in ("prepay", "prepay_2027"):
                periods += future_2026
            if item["profile"] == "prepay_2027":
                periods += future_2027
            item["bills"] = [self._bill(item, fee, gross, period) for period in periods for fee, gross in fees]
        rng = self.rng
        # 5: parking billed under property numbers the master does not have.
        project = next(item for item in self.properties if item["project_code"] == ORPHAN_PARKING[0])
        for index in range(ORPHAN_PARKING[1]):
            ghost = {**project, "id": f"{ORPHAN_PARKING[0]}-CW-B2-{901 + index:04d}", "type": "车位", "profile": "prompt",
                     "waiver": False, "area": 1250}
            ghost["bills"] = [self._bill(ghost, "车位管理费", 12000, period) for period in _months((2026, 1), AS_OF[:2])]
            self.ghosts.append(ghost)
        live = [bill for bill in self.bills if bill["period"] <= AS_OF[:2]]
        # 4: red-letter corrections on some bills, and voided duplicates left in the export.
        for bill in rng.sample(live, RED_LETTER_BILLS):
            bill["red"] = bill["gross"] // 5
        for bill in rng.sample(live, VOID_BILLS):
            self.bill_seq += 1
            self.bills.append({**bill, "id": f"YS{bill['period'][0]}{bill['period'][1]:02d}{self.bill_seq:07d}",
                               "status": "作废", "red": 0, "void": True})

    # Receipts.

    def _receipt(self, bill: dict, day: tuple[int, int, int], amount: int, label: str | None = None) -> None:
        if day > AS_OF or amount <= 0:
            return
        rng = self.rng
        self.receipt_seq += 1
        if label is None:
            label = "清欠" if bill["period"][0] < day[0] else "预收" if bill["period"] > day[:2] else "当期"
        draw = rng.randrange(100)
        method = "微信" if draw < 45 else "银行转账" if draw < 75 else "支付宝" if draw < 85 else "POS刷卡" if draw < 95 else "现金"
        self.receipts.append({"id": f"SK{day[0]}{day[1]:02d}{self.receipt_seq:07d}", "date": _date(day), "bill": bill,
                              "amount": amount, "method": method, "label": label})

    def build_receipts(self) -> None:
        rng = self.rng
        for item in self.properties:
            self._pay(item)
        for ghost in self.ghosts:
            self._pay(ghost)
        # 2: the 2027 prepayments, labelled 当期 by the cashier.
        for item in self.properties:
            if item["profile"] != "prepay_2027":
                continue
            day = _day(rng, (2026, 8), 3, 28)
            for bill in item["bills"]:
                if bill["period"][0] == 2027:
                    self._receipt(bill, day, bill["net"] * 95 // 100, label="当期")
        # 3: 2026 receipts against 2025 bills labelled 当期.
        cleared = [receipt for receipt in self.receipts
                   if receipt["label"] == "清欠" and receipt["bill"]["property"]["project_code"] == ARREARS_LABELLED_CURRENT[0]]
        for receipt in rng.sample(cleared, ARREARS_LABELLED_CURRENT[1]):
            receipt["label"] = "当期"

    def _pay(self, item: dict) -> None:
        rng = self.rng
        profile = item["profile"]
        commercial = item["type"] in ("写字楼", "商业")
        bills = item["bills"]
        if profile in ("prepay", "prepay_2027"):
            # Each year paid in one go in the December before it.
            for year in (2025, 2026):
                day = _day(rng, (year - 1, 12), 5, 28)
                for bill in bills:
                    if bill["period"][0] == year:
                        self._receipt(bill, day, bill["net"] - bill["red"])
            return
        clearing = None
        if profile == "debtor" and rng.randrange(100) < (5 if commercial else 34):
            clearing = _day(rng, (2026, rng.randint(2, 8)), 1, 28)
        for bill in bills:
            amount = bill["net"] - bill["red"]
            period = bill["period"]
            if profile == "prompt":
                draw = rng.randrange(100)
                if draw < 92:
                    self._receipt(bill, _day(rng, period, 3, 28), amount)
                elif draw < 98:
                    self._receipt(bill, _day(rng, _add_months(period, rng.randint(1, 6))), amount)
            elif profile == "lag":
                if rng.randrange(100) < 93:
                    self._receipt(bill, _day(rng, _add_months(period, rng.choice((1, 1, 1, 2, 2, 3)))), amount)
            elif profile == "debtor":
                if period[0] == 2025 and clearing is not None:
                    if rng.randrange(100) < 30:
                        self._receipt(bill, _day(rng, _add_months(period, rng.randint(1, 3))), amount)
                    else:
                        self._receipt(bill, clearing, amount)
                elif rng.randrange(100) < (10 if commercial and period[0] == 2025 else 45):
                    self._receipt(bill, _day(rng, _add_months(period, rng.randint(1, 5))), amount)
            elif profile == "related":
                if rng.randrange(100) < (30 if commercial else 12):
                    self._receipt(bill, _day(rng, _add_months(period, rng.randint(2, 9))), amount)


def building_of(pid: str) -> str:
    parts = pid.split("-")
    if parts[1] == "XZL":
        return "写字楼"
    if parts[1] == "SY":
        return "商业街"
    return f"{int(parts[1])}栋"


def build() -> _Book:
    book = _Book()
    book.build_properties()
    book.build_bills()
    book.build_receipts()
    return book


def _property_row(item: dict) -> list:
    return [item["project_code"], item["project"], CITY, item["building"], item["id"], item["door"], item["nature"],
            item["type"], item["owner"], _yuan(item["area"]), item["state"], item["start"], item["received"]]


def _bill_rows(bill: dict) -> list[list]:
    item = bill["property"]
    customer = "企业" if item["owner"] == "地产" or item["type"] in ("写字楼", "商业") else "个人"
    last = calendar.monthrange(*bill["period"])[1]
    due = f"{_period(bill['period'])}-{last:02d}"
    area = _yuan(item["area"]) if bill["fee"].endswith("物业服务费") or bill["fee"] == "储藏室管理费" else ""
    price = ""
    if area:
        price = _yuan(round(bill["gross"] * 100 / item["area"]))
    rows = [[bill["id"], bill["pid"], item["project"], customer, bill["fee"], _period(bill["period"]), area, price,
             _yuan(bill["gross"]), _yuan(bill["waiver"]), _yuan(bill["net"]), due, bill["status"]]]
    if bill["red"]:
        rows.append([bill["id"], bill["pid"], item["project"], customer, bill["fee"], _period(bill["period"]), area, price,
                     _yuan(-bill["red"]), "0.00", _yuan(-bill["red"]), due, "冲红"])
    return rows


def _receipt_row(receipt: dict) -> list:
    bill = receipt["bill"]
    return [receipt["id"], receipt["date"], bill["pid"], bill["fee"], _period(bill["period"]), bill["id"],
            _yuan(receipt["amount"]), receipt["method"], receipt["label"]]


def write(destination: Path, book: _Book | None = None) -> dict:
    """Write the export into ``destination`` (which must exist) and return what was written, by detail kind."""
    destination = Path(destination)
    book = book or build()
    written: dict[str, list[dict]] = {}

    def save(name: str, encoding: str, columns: list[str], rows) -> dict:
        count = 0
        with (destination / name).open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle, lineterminator="\r\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow(row)
                count += 1
        return {"name": name, "rows": count}

    # The billing system exports GBK; the receipts come from the cashier module, which writes UTF-8.
    written["property"] = [save(FILES["property"][0], "gbk", PROPERTY_COLUMNS, (_property_row(item) for item in book.properties))]
    ordered = sorted(book.bills, key=lambda bill: (bill["period"], bill["id"]))
    written["receivable"] = [
        save(FILES["receivable"][0], "gbk", RECEIVABLE_COLUMNS,
             (row for bill in ordered if bill["period"][0] == 2025 for row in _bill_rows(bill))),
        save(FILES["receivable"][1], "gbk", RECEIVABLE_COLUMNS,
             (row for bill in ordered if bill["period"][0] >= 2026 for row in _bill_rows(bill))),
    ]
    receipts = sorted(book.receipts, key=lambda receipt: (receipt["date"], receipt["id"]))
    written["receipt"] = [save(FILES["receipt"][0], "utf-8-sig", RECEIPT_COLUMNS, (_receipt_row(receipt) for receipt in receipts))]
    return written


def write_sample_workbook(path: Path, book: _Book | None = None) -> dict:
    """A few thousand rows to open in Excel: one building of 椰林湾, its bills and its receipts, one sheet each."""
    from openpyxl import Workbook

    book = book or build()
    chosen = {item["id"] for item in book.properties if item["project_code"] == "HK01" and item["building"] == "1栋"}
    workbook = Workbook()
    sheets = {"房产主数据": (PROPERTY_COLUMNS, [_property_row(item) for item in book.properties if item["id"] in chosen])}
    sheets["应收明细"] = (RECEIVABLE_COLUMNS, [row for bill in sorted(book.bills, key=lambda bill: (bill["period"], bill["id"]))
                                           if bill["pid"] in chosen for row in _bill_rows(bill)])
    sheets["实收明细"] = (RECEIPT_COLUMNS, [_receipt_row(receipt) for receipt in sorted(book.receipts, key=lambda r: (r["date"], r["id"]))
                                          if receipt["bill"]["pid"] in chosen])
    counts = {}
    first = True
    for title, (columns, rows) in sheets.items():
        sheet = workbook.active if first else workbook.create_sheet()
        first = False
        sheet.title = title
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        counts[title] = len(rows)
    workbook.save(path)
    return {"name": Path(path).name, "rows": counts}
