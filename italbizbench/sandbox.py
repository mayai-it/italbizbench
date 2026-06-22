"""Sandbox di fatturazione + simulatore SDI.

REGOLA D'ORO: questo modulo non tocca MAI API reali. E uno stato in-memory che imita
il comportamento di un gestionale (stile Fatture in Cloud) e dello SDI, abbastanza
fedele da rendere i task verificabili. In produzione il benchmark sostituira questo
con `fatture-cli` puntato all'ambiente di TEST, mai a quello live.

Ogni chiamata a `emit_invoice` viene contata come un tool-call (per la metrica efficienza).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import InvoiceLine

# Tipo alias per un'anagrafica cliente.
Client = dict[str, Any]


# Anagrafiche sintetiche (P.IVA fittizie). Mai dati reali.
DEFAULT_CLIENTS: dict[str, Client] = {
    "Rossi Costruzioni Srl": {"piva": "01234567890", "codice_destinatario": "ABCDEF1", "pa": False},
    "Comune di Esempio": {"piva": "09876543210", "codice_destinatario": "UFE000", "pa": True},
    "Bianchi GmbH": {"piva": "DE123456789", "codice_destinatario": "XXXXXXX", "estero": True},
}


@dataclass
class Invoice:
    client: str
    imponibile: float
    iva: float
    totale: float
    regime: str
    bollo: float = 0.0
    sdi_outcome: str = "in_attesa"


@dataclass
class InvoicingSandbox:
    clients: dict[str, Client] = field(default_factory=lambda: dict(DEFAULT_CLIENTS))
    issued: list[Invoice] = field(default_factory=list)
    tool_calls: int = 0

    # --- strumenti esposti all'agente ---------------------------------------

    def lookup_client(self, name: str) -> Client | None:
        self.tool_calls += 1
        return self.clients.get(name)

    def validate_piva(self, piva: str) -> bool:
        """Validazione P.IVA italiana: 11 cifre + check digit (variante Luhn).

        Le P.IVA estere (prefisso non numerico, es. 'DE...') non seguono questo
        algoritmo: qui le consideriamo 'non validabili con questo metodo' -> False.
        """
        self.tool_calls += 1
        if not (piva.isdigit() and len(piva) == 11):
            return False
        s = 0
        for i, ch in enumerate(piva[:10]):
            d = int(ch)
            if i % 2 == 1:  # posizioni pari (1-indexed): raddoppia
                d *= 2
                if d > 9:
                    d -= 9
            s += d
        check = (10 - (s % 10)) % 10
        return check == int(piva[10])

    def emit_invoice(
        self, client: str, lines: list[InvoiceLine], regime: str = "ordinario"
    ) -> Invoice:
        """Emette una fattura calcolando imponibile, IVA e bollo secondo il regime.

        regime: ordinario | reverse_charge | split_payment | esente
        """
        self.tool_calls += 1
        imponibile = round(sum(ln.quantita * ln.prezzo_unitario for ln in lines), 2)

        if regime == "reverse_charge":
            iva = 0.0  # l'IVA e a carico del committente (es. edilizia, N6.x)
        elif regime == "esente":
            iva = 0.0
        else:  # ordinario e split_payment hanno la stessa IVA in fattura
            iva = round(
                sum(ln.quantita * ln.prezzo_unitario * ln.aliquota_iva / 100 for ln in lines), 2
            )

        # Bollo 2 euro su fatture esenti/non imponibili/reverse > 77,47 euro
        bollo = 0.0
        if regime in ("reverse_charge", "esente") and imponibile > 77.47:
            bollo = 2.0

        if regime == "split_payment":
            # con split payment il cliente PA paga solo l'imponibile; l'IVA va all'Erario
            totale = round(imponibile + bollo, 2)
        else:
            totale = round(imponibile + iva + bollo, 2)

        inv = Invoice(client=client, imponibile=imponibile, iva=iva,
                      totale=totale, regime=regime, bollo=bollo)
        inv.sdi_outcome = self._simulate_sdi(client, inv, regime)
        self.issued.append(inv)
        return inv

    # --- simulatore SDI -------------------------------------------------------

    def _simulate_sdi(self, client_name: str, inv: Invoice, regime: str) -> str:
        """Applica i controlli di scarto SDI piu comuni (sottoinsieme didattico)."""
        c = self.clients.get(client_name)
        if c is None:
            return "scarto:00200"  # destinatario/anagrafica non valida
        cd = c.get("codice_destinatario", "")
        if c.get("estero"):
            return "accettata"  # estero: codice convenzionale (es. XXXXXXX)
        if c.get("pa"):
            # PA: codice univoco ufficio a 6 caratteri; richiede split payment
            if len(cd) != 6:
                return "scarto:00312"
            if regime != "split_payment":
                return "scarto:00400"  # regime incoerente per la PA
            return "accettata"
        # Privati: codice destinatario a 7 caratteri
        if len(cd) != 7:
            return "scarto:00312"
        return "accettata"
