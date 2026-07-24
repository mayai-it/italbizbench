"""Sandbox di fatturazione + simulatore SDI.

REGOLA D'ORO: questo modulo non tocca MAI API reali. E uno stato in-memory che imita
il comportamento di un gestionale (stile Fatture in Cloud) e dello SDI, abbastanza
fedele da rendere i task verificabili. In produzione il benchmark sostituira questo
con `fatture-cli` puntato all'ambiente di TEST, mai a quello live.

Ogni chiamata a `emit_invoice` viene contata come un tool-call (per la metrica efficienza).
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .models import InvoiceLine
from .piva import is_valid_piva

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
    # Famiglia E (riconciliazione): numero del documento e stato di incasso.
    # Default retro-compatibili: i task A/B/C non li dichiarano.
    numero: str = ""
    paid: bool = False


@dataclass
class CreditNote:
    """Nota di credito (TD04): storna in tutto o in parte una fattura.

    Modellazione semplificata (vedi docs/FISCAL-RULES.md §9): importi calcolati con le
    stesse regole della fattura che storna; transita dallo SDI come un documento normale.
    """
    client: str
    imponibile: float
    iva: float
    totale: float
    regime: str
    refers_to: str = ""       # riferimento libero alla fattura stornata
    sdi_outcome: str = "in_attesa"


@dataclass
class PecMessage:
    """Messaggio PEC simulato (famiglia D — ciclo passivo).

    `invoice` e l'allegato strutturato: la fattura del fornitore gia estratta in
    forma di dict (fornitore, piva, numero, imponibile, iva, totale, ...). Il
    parsing dell'XML FatturaPA reale e fuori perimetro: qui si misura la capacita
    dell'agente di leggere il documento giusto e registrarlo fedelmente.
    """
    id: str
    sender: str
    subject: str
    body: str = ""
    invoice: dict[str, Any] | None = None


@dataclass
class PurchaseInvoice:
    """Fattura passiva registrata (registro acquisti, modellazione semplificata).

    Vedi docs/FISCAL-RULES.md §10: la registrazione replica i dati del documento;
    detraibilita IVA, integrazione/autofattura reverse charge (TD16) e termini di
    registrazione non sono modellati.
    """
    fornitore: str
    piva: str
    numero: str
    imponibile: float
    iva: float
    totale: float


@dataclass
class BankTransaction:
    """Movimento bancario simulato (famiglia E — riconciliazione).

    `importo` positivo = incasso, negativo = pagamento in uscita. La `causale` e
    il testo libero del bonifico: puo citare il numero fattura oppure no.
    """
    id: str
    data: str
    importo: float
    controparte: str
    causale: str = ""


@dataclass
class Reconciliation:
    """Abbinamento movimento bancario <-> fattura emessa (per numero documento)."""
    tx_id: str
    numero: str


@dataclass
class InvoicingSandbox:
    # deepcopy: ogni sandbox ha copie PROPRIE delle anagrafiche. Con una copia
    # shallow, update_client muterebbe i dict condivisi di DEFAULT_CLIENTS e lo
    # stato colerebbe tra un task e l'altro.
    clients: dict[str, Client] = field(default_factory=lambda: deepcopy(DEFAULT_CLIENTS))
    issued: list[Invoice] = field(default_factory=list)
    credit_notes: list[CreditNote] = field(default_factory=list)
    pec_inbox: list[PecMessage] = field(default_factory=list)
    purchases: list[PurchaseInvoice] = field(default_factory=list)
    transactions: list[BankTransaction] = field(default_factory=list)
    reconciliations: list[Reconciliation] = field(default_factory=list)
    tool_calls: int = 0
    # Numero di documenti SEMINATI dallo stato iniziale (famiglie C/D): non sono
    # opera dell'agente e non contano come sua azione.
    seeded_invoices: int = 0
    seeded_purchases: int = 0

    @property
    def agent_acted(self) -> bool:
        """True se l'agente ha prodotto side effect oltre lo stato seminato."""
        return (len(self.issued) > self.seeded_invoices
                or bool(self.credit_notes)
                or len(self.purchases) > self.seeded_purchases
                or bool(self.reconciliations))

    # --- strumenti esposti all'agente ---------------------------------------

    def lookup_client(self, name: str) -> Client | None:
        self.tool_calls += 1
        return self.clients.get(name)

    def update_client(self, name: str, **fields: Any) -> Client | None:
        """Corregge l'anagrafica di un cliente esistente (es. codice destinatario).

        Ritorna l'anagrafica aggiornata, o None se il cliente non esiste (l'agente
        deve allora censirlo con `add_client`).
        """
        self.tool_calls += 1
        c = self.clients.get(name)
        if c is None:
            return None
        c.update(fields)
        return c

    def add_client(self, name: str, piva: str, codice_destinatario: str,
                   pa: bool = False, estero: bool = False) -> Client:
        """Censisce un nuovo cliente in anagrafica (dati sintetici, mai reali)."""
        self.tool_calls += 1
        c: Client = {"piva": piva, "codice_destinatario": codice_destinatario, "pa": pa}
        if estero:
            c["estero"] = True
        self.clients[name] = c
        return c

    def validate_piva(self, piva: str) -> bool:
        """Validazione P.IVA italiana: 11 cifre + check digit (variante Luhn).

        L'algoritmo vive in `italbizbench.piva` (unica fonte di verita, condivisa
        con il generatore di P.IVA sintetiche dei task). Le P.IVA estere
        (prefisso non numerico, es. 'DE...') non sono validabili con questo
        metodo -> False.
        """
        self.tool_calls += 1
        return is_valid_piva(piva)

    def list_pec(self) -> list[dict[str, str]]:
        """Elenca i messaggi in casella PEC (id, mittente, oggetto), senza allegati.

        Per leggere il contenuto e l'eventuale fattura allegata serve `read_pec`:
        l'agente deve scegliere il messaggio giusto, non riceve tutto in blocco.
        """
        self.tool_calls += 1
        return [{"id": m.id, "sender": m.sender, "subject": m.subject}
                for m in self.pec_inbox]

    def read_pec(self, msg_id: str) -> PecMessage | None:
        """Legge un messaggio PEC per id (None se non esiste)."""
        self.tool_calls += 1
        for m in self.pec_inbox:
            if m.id == msg_id:
                return m
        return None

    def register_purchase(self, fornitore: str, piva: str, numero: str,
                          imponibile: float, iva: float, totale: float) -> PurchaseInvoice:
        """Registra una fattura passiva nel registro acquisti.

        Modellazione semplificata (FISCAL-RULES §10): la registrazione replica i
        dati del documento ricevuto; nessun ricalcolo, nessuna detraibilita.
        """
        self.tool_calls += 1
        p = PurchaseInvoice(fornitore=fornitore, piva=piva, numero=numero,
                            imponibile=imponibile, iva=iva, totale=totale)
        self.purchases.append(p)
        return p

    def list_transactions(self) -> list[dict[str, Any]]:
        """Elenca i movimenti bancari (estratto conto simulato)."""
        self.tool_calls += 1
        return [dict(t.__dict__) for t in self.transactions]

    def list_open_invoices(self) -> list[dict[str, Any]]:
        """Fatture emesse non ancora incassate (numero, cliente, totale)."""
        self.tool_calls += 1
        return [{"numero": i.numero, "client": i.client, "totale": i.totale}
                for i in self.issued if not i.paid]

    def reconcile(self, tx_id: str, numero: str) -> dict[str, Any]:
        """Abbina un movimento bancario a una fattura emessa e la marca incassata.

        Modellazione semplificata (FISCAL-RULES §11): solo abbinamento 1:1
        movimento<->fattura; incassi parziali/cumulativi non modellati.
        """
        self.tool_calls += 1
        tx = next((t for t in self.transactions if t.id == tx_id), None)
        inv = next((i for i in self.issued if i.numero == numero), None)
        if tx is None or inv is None:
            return {"error": f"movimento {tx_id!r} o fattura {numero!r} non trovati"}
        inv.paid = True
        self.reconciliations.append(Reconciliation(tx_id=tx_id, numero=numero))
        return {"tx_id": tx_id, "numero": numero, "paid": True}

    @staticmethod
    def _amounts(lines: list[InvoiceLine], regime: str) -> tuple[float, float, float, float]:
        """Imponibile, IVA, bollo e totale di un documento, secondo il regime.

        Regole condivise da fatture e note di credito (vedi docs/FISCAL-RULES.md):
        - reverse charge / esente: IVA non esposta (0.0);
        - bollo 2 euro solo sulle operazioni ESENTI > 77,47 euro; NON sul reverse
          charge (principio di alternativita IVA/bollo — Fiscomania, RegimeMinimi);
        - split payment: il cliente PA paga il solo imponibile, l'IVA va all'Erario.
        """
        imponibile = round(sum(ln.quantita * ln.prezzo_unitario for ln in lines), 2)
        if regime in ("reverse_charge", "esente"):
            iva = 0.0
        else:  # ordinario e split_payment hanno la stessa IVA in fattura
            iva = round(
                sum(ln.quantita * ln.prezzo_unitario * ln.aliquota_iva / 100 for ln in lines), 2
            )
        bollo = 2.0 if (regime == "esente" and imponibile > 77.47) else 0.0
        if regime == "split_payment":
            totale = round(imponibile + bollo, 2)
        else:
            totale = round(imponibile + iva + bollo, 2)
        return imponibile, iva, bollo, totale

    def emit_invoice(
        self, client: str, lines: list[InvoiceLine], regime: str = "ordinario"
    ) -> Invoice:
        """Emette una fattura calcolando imponibile, IVA e bollo secondo il regime.

        regime: ordinario | reverse_charge | split_payment | esente
        """
        self.tool_calls += 1
        imponibile, iva, bollo, totale = self._amounts(lines, regime)
        inv = Invoice(client=client, imponibile=imponibile, iva=iva,
                      totale=totale, regime=regime, bollo=bollo)
        inv.sdi_outcome = self._simulate_sdi(client, inv, regime)
        self.issued.append(inv)
        return inv

    def emit_credit_note(
        self, client: str, lines: list[InvoiceLine], regime: str = "ordinario",
        refers_to: str = "",
    ) -> CreditNote:
        """Emette una nota di credito (TD04) a storno totale o parziale.

        Gli importi sono calcolati con le stesse regole della fattura stornata;
        il documento transita dallo SDI (stessi controlli sul destinatario).
        """
        self.tool_calls += 1
        imponibile, iva, _bollo, totale = self._amounts(lines, regime)
        note = CreditNote(client=client, imponibile=imponibile, iva=iva,
                          totale=totale, regime=regime, refers_to=refers_to)
        note.sdi_outcome = self._simulate_sdi(client, None, regime)
        self.credit_notes.append(note)
        return note

    # --- simulatore SDI -------------------------------------------------------

    def _simulate_sdi(self, client_name: str, inv: Invoice | None, regime: str) -> str:
        """Applica i controlli di scarto SDI piu comuni (sottoinsieme didattico)."""
        c = self.clients.get(client_name)
        if c is None:
            return "scarto:00200"  # destinatario/anagrafica non valida
        cd = c.get("codice_destinatario", "")
        if c.get("estero"):
            return "accettata"  # estero: codice convenzionale (es. XXXXXXX)
        if c.get("pa"):
            # PA: codice univoco ufficio a 6 caratteri (IPA). Lo split payment e' una
            # questione di contenuto fattura, non un controllo di scarto SDI: qui lo SDI
            # verifica solo la validita del codice ufficio.
            if len(cd) != 6:
                return "scarto:00312"
            return "accettata"
        # Privati: codice destinatario a 7 caratteri
        if len(cd) != 7:
            return "scarto:00312"
        return "accettata"
