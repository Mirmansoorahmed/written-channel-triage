"""Category definitions for the triage classifier (R10, R12).

These are my own definitions for a fictional telco. Each category has a short
German description (used by the local retrieval step), the keyword cues that hint
at it, the fields a human would need, and whether it implies an account-changing
action (used later by the policy gate).

I do not copy any standard text here; this is all my own wording.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    name: str
    description: str
    keywords: tuple[str, ...]
    required_fields: tuple[str, ...]
    # Action type this category usually implies.
    account_changing: bool = False


CATEGORIES: list[Category] = [
    Category(
        name="Rechnung",
        description="Fragen zu Rechnungen, Beträgen, Abbuchungen und Zahlungen.",
        keywords=("rechnung", "betrag", "abbuchung", "zahlung", "mahnung", "gebühr"),
        required_fields=("kundennummer", "rechnungsmonat"),
    ),
    Category(
        name="Vertrag",
        description="Fragen zu Vertragslaufzeit, Konditionen und Verlängerung.",
        keywords=("vertrag", "laufzeit", "verlängerung", "konditionen", "tarifdetails"),
        required_fields=("kundennummer",),
    ),
    Category(
        name="Umzug",
        description="Mitnahme oder Ummeldung des Anschlusses an eine neue Adresse.",
        keywords=("umzug", "umziehen", "neue adresse", "ummelden", "anschluss mitnehmen"),
        required_fields=("kundennummer", "neue_adresse", "umzugsdatum"),
        account_changing=True,
    ),
    Category(
        name="Störung",
        description="Technische Störung: kein Internet, kein Anschluss, Ausfall.",
        keywords=("störung", "ausfall", "kein internet", "funktioniert nicht", "offline", "langsam"),
        required_fields=("kundennummer", "fehlerbeschreibung"),
    ),
    Category(
        name="Kündigung",
        description="Wunsch, den Vertrag zu beenden oder zu widerrufen.",
        keywords=("kündigen", "kündigung", "widerruf", "beenden", "vertrag auflösen"),
        required_fields=("kundennummer", "kündigungsdatum"),
        account_changing=True,
    ),
    Category(
        name="Datenschutz",
        description="Auskunft, Löschung oder Berichtigung personenbezogener Daten.",
        keywords=("datenschutz", "auskunft", "löschung", "dsgvo", "meine daten", "berichtigung"),
        required_fields=("kundennummer", "anliegen_art"),
    ),
    Category(
        name="Tarifwechsel",
        description="Wechsel in einen anderen Tarif oder Anpassung von Optionen.",
        keywords=("tarifwechsel", "tarif ändern", "anderer tarif", "upgrade", "downgrade", "option buchen"),
        required_fields=("kundennummer", "zieltarif"),
        account_changing=True,
    ),
    Category(
        name="Technik-Setup",
        description="Hilfe bei Einrichtung von Router, WLAN oder Geräten.",
        keywords=("router", "wlan", "einrichten", "konfiguration", "passwort wlan", "fritzbox"),
        required_fields=("gerät",),
    ),
    Category(
        name="Beschwerde",
        description="Unzufriedenheit mit Service, Wartezeit oder Bearbeitung.",
        keywords=("beschwerde", "unzufrieden", "ärgerlich", "beschweren", "schlechter service"),
        required_fields=("kundennummer", "beschwerdegrund"),
    ),
    Category(
        name="Sonstiges",
        description="Anliegen, das in keine andere Kategorie passt.",
        keywords=(),
        required_fields=(),
    ),
]

CATEGORY_NAMES = [c.name for c in CATEGORIES]
BY_NAME = {c.name: c for c in CATEGORIES}


def get(name: str) -> Category:
    return BY_NAME[name]
