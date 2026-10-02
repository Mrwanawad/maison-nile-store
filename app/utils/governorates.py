"""The 27 governorates of Egypt. Codes are stable identifiers used in `.env`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Governorate:
    code: str
    name_en: str
    name_ar: str

    def name(self, locale: str) -> str:
        return self.name_ar if locale == "ar" else self.name_en


GOVERNORATES: tuple[Governorate, ...] = (
    Governorate("cairo", "Cairo", "القاهرة"),
    Governorate("giza", "Giza", "الجيزة"),
    Governorate("alexandria", "Alexandria", "الإسكندرية"),
    Governorate("qalyubia", "Qalyubia", "القليوبية"),
    Governorate("dakahlia", "Dakahlia", "الدقهلية"),
    Governorate("sharqia", "Sharqia", "الشرقية"),
    Governorate("gharbia", "Gharbia", "الغربية"),
    Governorate("monufia", "Monufia", "المنوفية"),
    Governorate("beheira", "Beheira", "البحيرة"),
    Governorate("kafr_el_sheikh", "Kafr El Sheikh", "كفر الشيخ"),
    Governorate("damietta", "Damietta", "دمياط"),
    Governorate("port_said", "Port Said", "بورسعيد"),
    Governorate("ismailia", "Ismailia", "الإسماعيلية"),
    Governorate("suez", "Suez", "السويس"),
    Governorate("faiyum", "Faiyum", "الفيوم"),
    Governorate("beni_suef", "Beni Suef", "بني سويف"),
    Governorate("minya", "Minya", "المنيا"),
    Governorate("asyut", "Asyut", "أسيوط"),
    Governorate("sohag", "Sohag", "سوهاج"),
    Governorate("qena", "Qena", "قنا"),
    Governorate("luxor", "Luxor", "الأقصر"),
    Governorate("aswan", "Aswan", "أسوان"),
    Governorate("red_sea", "Red Sea", "البحر الأحمر"),
    Governorate("new_valley", "New Valley", "الوادي الجديد"),
    Governorate("matrouh", "Matrouh", "مطروح"),
    Governorate("north_sinai", "North Sinai", "شمال سيناء"),
    Governorate("south_sinai", "South Sinai", "جنوب سيناء"),
)

BY_CODE: dict[str, Governorate] = {g.code: g for g in GOVERNORATES}


def get(code: str) -> Governorate | None:
    return BY_CODE.get(code)
