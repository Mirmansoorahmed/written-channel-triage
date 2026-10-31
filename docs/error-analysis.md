# Error analysis (v2)

This file is **generated** by `eval/harness_v2.py` from the actual misclassifications of the latest run over the held-out test split. If a system did not run (pending real model), it has no section here.

## System A_v1_regex

- Misclassified: **46**

### Most common confusions

| expected | predicted | count |
|---|---|---|
| Kündigung | Vertrag | 10 |
| Sonstiges | Störung | 7 |
| Tarifwechsel | Umzug | 5 |
| Sonstiges | Umzug | 4 |
| Rechnung | Umzug | 3 |
| Technik-Setup | Störung | 3 |
| Beschwerde | Umzug | 3 |
| Störung | Sonstiges | 2 |
| Technik-Setup | Sonstiges | 2 |
| Vertrag | Umzug | 1 |

### Examples

| id | family | expected | predicted | masked excerpt |
|---|---|---|---|---|
| item-00004 | normal | Rechnung | Umzug | Serh geehrte Damen und Herreen, ich habe eine Mahnun bkeommen, verstehe aber die offene Rchnung niccht.  Mit freundlichen Grüßen [[NAME_1]] |
| item-00089 | normal | Rechnung | Umzug | Sehr geehrtes ervicteeam, auf meiner Rechnugn tauhct eine Position auf, die ich nicht uzordnen kann. Kunennummer: 773904104, IBAN [[IBAN_1]], Mail [[EMAIL_1]].  |
| item-00097 | normal | Rechnung | Umzug | Moin, auf meiner Rechunng taucht eine Poistion auf, die ich nicht zuordnnen kann.  Viele Grüße [[NAME_1]] |
| item-00114 | normal | Vertrag | Umzug | Sehr geehret Damen un Herren, bis wann gilt meine Mindestlafuzeit? Ich finde die Angabe nicht.  Mit freundlichen rGüßen Lena Berg |
| item-00329 | normal | Störung | Sonstiges | Guetn TTag, die Verbinung funktioniert inch, allles tot seit gestern Abend.  Danke Max Berg |
| item-00337 | normal | Störung | Beschwerde | Sehr geehrtes Serviceteam, die Verbindung funktioniert nich, alles tot seit gestern Abend. Kunddennummer: 287492016.  Mit frendlichen Grüßen Erika Klein |
| item-00401 | normal | Kündigung | Vertrag | Hallo, hiermit kündige ich meinen Vertrag zum nächstmöglichen eTrmin.  Grüße [[NAME_1]] |
| item-00406 | normal | Kündigung | Vertrag | Moin, hiermit kündige ich meinen Vertrag zm nächstmöglichen Termin.  Vielee Grrüße Pal Mustermann |
| item-00427 | normal | Kündigung | Vertrag | Hallo, hiermit kündige ich meinen Vertrag zum nähcsstmöglichen Termin.  LG Erika Mustermann |
| item-00430 | normal | Kündigung | Vertrag | Sehr geehrte Damen und Herren, hiiermit kündige ich meinen Vertrag uzm nächstmöglich Termin. Kudnennummer: 871257418, IBAN [[IBAN_1]], Tel [[PHONE_1]], Mail [[E |
| item-00433 | normal | Kündigung | Vertrag | Guten Tg, bitte miene Kündigung zum Ende der Laufzeit vomerken.  Freundliche Grüße [[NAME_1]] |
| item-00495 | normal | Kündigung | Vertrag | From: [[EMAIL_1]] Subject: Anfrage: Kündigung Authentication-Results: mx.nordtel.example; spf=pass; dkim=pass; dmarc=pass  Hallo, bitte meine Kündigung zum Ende |
| item-00607 | normal | Tarifwechsel | Umzug | Guten Tag, kaann ich eminen Taarif  eine kleinere Option dwngraedn? (thankks in advance)  Beste Grüße [[NAME_1]] |
| item-00641 | normal | Tarifwechsel | Umzug | Hi, bitte eine Option zubuce und den Tarif entpsrechend ändren. Kundennummer: [[CUSTOMER_1]], Tel [[PHONE_1]], Mail [[EMAIL_1]].  Danke und Grüße [[NAME_1]] |
| item-00700 | normal | Tarifwechsel | Beschwerde | Sehr geehrtes Serviceteam, bitte ein Option zubuchn und den Tarif entsprehcend ändern.  Bestee Grüße [[NAME_1]] |

