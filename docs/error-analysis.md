# Error analysis (v2)

This file is **generated** by `eval/harness_v2.py` from the actual misclassifications of the latest run. Results are broken out per split bucket: **seen-template** (test items whose template is also in train -- empty under the template-family split, which is the point), **unseen-template** (the normal held-out test items), and **unseen** (the hand-varied `eval/unseen/` set). A system that did not run has no section.

## System A_v1_regex

### Split: seen_template

- Misclassified: **0**

No category errors in this bucket.

### Split: unseen_template

- Misclassified: **106**

Most common confusions:

| expected | predicted | count |
|---|---|---|
| Sonstiges | Störung | 34 |
| Kündigung | Vertrag | 17 |
| Kündigung | Umzug | 9 |
| Technik-Setup | Umzug | 7 |
| Datenschutz | Umzug | 6 |
| Vertrag | Umzug | 4 |
| Sonstiges | Umzug | 4 |
| Rechnung | Sonstiges | 2 |

Examples:

| id | family | expected | predicted | masked excerpt |
|---|---|---|---|---|
| item-00063 | normal | Rechnung | Sonstiges | Guten Tg, warum ist die bAbucuhng diesen Monat höher als sonst? Bitte die eGbühr erklären.  Mit freudnlichen Grüüßen [[NAME_1]] |
| item-00068 | normal | Rechnung | Vertrag | Gtuen Tga, warum ist die Abbuchugn diesen Monat höher als sonst? Bitte die Gebühr erklären. Vertragsnummer: [[CUSTOMER_1]], IBAAN E02 1203 [[PHONE_1]], Tel [[PH |
| item-00282 | normal | Vertrag | Beschwerde | Sehr geehrtes Serviceteam, bis wnn gilt meine Mindetslaufzei? Ich finde die Angabe nicht.  Mit freundlicen Grüßen [[NAME_1]] |
| item-00283 | normal | Vertrag | Umzug | Guten Tag, bis wann ggilt meine Minndestlafzeit? Ich finde die Angabe nicth.  Grüße [[NAME_1]] |
| item-00292 | normal | Vertrag | Umzug | Guten Tag, bis wann gilt meine Mindestlufzeit? Ich finde die Angabe nicht.  Mit freundlcihen Grüßen [[NAME_1]] |
| item-00299 | normal | Vertrag | Umzug | Hallo, bis wann ggilt meine Mindestlaufzet? Ich finde die Angabe nicht. Kundnenummer: [[CUSTOMER_1]], Tel [[PHONE_1]], Mail [[EMAIL_1]].  Danke [[NAME_1]] |
| item-00312 | normal | Vertrag | Umzug | Mion, bis wann gilt meine Mindestlafzeit? Ich finde die Angabe nicht.  Viele Grüße [[NAME_1]] |
| item-00370 | normal | Umzug | Vertrag | Moin, ich ziee um und möchte meineen Aschluss an die neue Adrsessee mitnehmen. Vertragsnummer: [[CUSTOMER_1]], Tel [[PHONE_1]], neue [[ADDRESS_1]].  LG [[NAME_1 |
| item-00383 | normal | Umzug | Störung | Sehr geehrte Damen und Herren, ich ziehe um und mcöhte mienen Anschluss an die neue Adrsese mitnnehmen.  Mit freundlichen Grüßen [[NAME_1]] |
| item-00490 | normal | Störung | Beschwerde | Shr geehrtes Serviceteam, mei Inetrnet ist seit heute früh komplett tot, kein Ancshluss mehr. (best regards)  Freundliche Grüße [[NAME_1]] |

### Split: unseen

- Misclassified: **30**

Most common confusions:

| expected | predicted | count |
|---|---|---|
| Sonstiges | Umzug | 3 |
| Störung | Sonstiges | 2 |
| Beschwerde | Sonstiges | 2 |
| Datenschutz | Umzug | 2 |
| Technik-Setup | Sonstiges | 2 |
| Rechnung | Sonstiges | 2 |
| Umzug | Störung | 1 |
| Beschwerde | Störung | 1 |

Examples:

| id | family | expected | predicted | masked excerpt |
|---|---|---|---|---|
| unseen-002 | unseen_normal | Störung | Sonstiges | Guten Abend, seit dem Update der Firmware startet die Box alle paar Minuten neu und das Netz ist dann weg. |
| unseen-003 | unseen_normal | Umzug | Störung | Hallo zusammen, ich pendle ab Januar nach Hamburg und würde den Anschluss gern dorthin mitnehmen statt neu zu buchen. |
| unseen-005 | unseen_normal | Beschwerde | Störung | Mir reicht es langsam: dritter Termin, dritter Techniker, der nicht kommt. So kann man mit Kunden nicht umgehen. |
| unseen-006 | unseen_normal | Datenschutz | Sonstiges | Please send me a copy of all data you hold about me, I am exercising my GDPR right of access. |
| unseen-007 | unseen_normal | Tarifwechsel | Datenschutz | Ich telefoniere praktisch nie mehr, surfe aber viel. Gibt es ein reines Datenpaket, auf das ich wechseln kann? |
| unseen-009 | unseen_normal | Kündigung | Vertrag | Zum Vertragsende möchte ich aussteigen; bitte senden Sie mir eine schriftliche Bestätigung mit dem Abschalttag. |
| unseen-010 | unseen_normal | Sonstiges | Umzug | Nur eine kurze allgemeine Erkundigung: bieten Sie eigentlich auch Verträge für Gewerbekunden an? |
| unseen-011 | unseen_normal | Rechnung | Umzug | Es wurden im Oktober zwei Beträge abgebucht, einmal 39,99 und einmal 44,98. Normalerweise ist es nur einer. |
| unseen-012 | unseen_normal | Störung | Sonstiges | Abends zwischen 20 und 23 Uhr habe ich regelmäßig Paketverluste beim Spielen, sonst läuft alles. |
| unseen-013 | unseen_normal | Umzug | Sonstiges | We are relocating the office next month and would like to keep the current business line at the new address. |

