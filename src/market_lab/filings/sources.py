"""Politika istochnikov i bezsetevye interfeisy adapterov korporativnyh raskrytii."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from market_lab.filings.schema import FilingSourceKind, ReportEvent

INTERFAX_GATEWAY_DOCS = (  # Oficial'naya Swagger-dokumentaciya avtomatizirovannogo shlyuza.
    "https://gateway.e-disclosure.ru/swagger/ui/index.html"
)
INTERFAX_USAGE_TERMS = (  # Pravila Interfaks-CRKI, kotorye nuzhno proverit' pered bulk I/O.
    "https://esg-disclosure.ru/usloviya-ispolzovaniya-informatsii/"
)
INTERFAX_PUBLIC_PORTAL = "https://www.e-disclosure.ru/"  # Publichnyi portal raskrytiya.


@dataclass(frozen=True, slots=True)
class SourceAccessPolicy:
    """Fiksiruet vozmozhnosti i pravovye ogranicheniya odnogo tipa istochnika."""

    source_kind: FilingSourceKind
    documentation_url: str
    authorized_disclosure_distributor: bool
    automated_interface: bool
    authentication_required: bool
    exact_publication_timestamp_expected: bool
    revision_events_expected: bool
    attachment_download_expected: bool
    bulk_research_approved: bool
    limitations: tuple[str, ...]


SOURCE_ACCESS_POLICIES = {  # Konservativnyi reestr: bulk zapreshchen do dogovora i credentialov.
    FilingSourceKind.INTERFAX_GATEWAY: SourceAccessPolicy(
        source_kind=FilingSourceKind.INTERFAX_GATEWAY,
        documentation_url=INTERFAX_GATEWAY_DOCS,
        authorized_disclosure_distributor=True,
        automated_interface=True,
        authentication_required=True,
        exact_publication_timestamp_expected=True,
        revision_events_expected=True,
        attachment_download_expected=True,
        bulk_research_approved=False,
        limitations=(
            "Nuzhny credentialy i podtverzhdenie dogovornogo prava na bulk-poluchenie.",
            "Adapter obyazan otklonit' sobytie bez tochnogo timestamp i revision metadata.",
            "Tekushchie usloviya ispol'zovaniya nuzhno zafiksirovat' na datu zagruzki.",
        ),
    ),
    FilingSourceKind.INTERFAX_PORTAL: SourceAccessPolicy(
        source_kind=FilingSourceKind.INTERFAX_PORTAL,
        documentation_url=INTERFAX_PUBLIC_PORTAL,
        authorized_disclosure_distributor=True,
        automated_interface=False,
        authentication_required=False,
        exact_publication_timestamp_expected=False,
        revision_events_expected=False,
        attachment_download_expected=True,
        bulk_research_approved=False,
        limitations=(
            "Tol'ko malaya ruchnaya proverka metadata; ne massovyi scraping.",
            "Tablica dokumentov mozhet pokazyvat' tol'ko datu razmeshcheniya bez vremeni.",
            "Istoriya zamены dokumenta na HTML-stranice ne yavlyaetsya polnym event-log.",
        ),
    ),
    FilingSourceKind.ISSUER_IR: SourceAccessPolicy(
        source_kind=FilingSourceKind.ISSUER_IR,
        documentation_url="https://www.sberbank.com/investor-relations",
        authorized_disclosure_distributor=False,
        automated_interface=False,
        authentication_required=False,
        exact_publication_timestamp_expected=False,
        revision_events_expected=False,
        attachment_download_expected=True,
        bulk_research_approved=False,
        limitations=(
            "Usloviya, URL i timestamp nuzhno proverit' otdel'no dlya kazhdogo emitenta.",
            "Tekushchii IR-arhiv ne dokazyvaet istoricheskuyu point-in-time dostupnost'.",
            "PDF bez vremena publikacii nel'zya samostoyatel'no privyazat' k torgovoi sessii.",
        ),
    ),
}


class FilingMetadataSource(Protocol):
    """Zadaet typed adapter, kotoryi mozhno realizovat' tol'ko posle prava dostupa."""

    def list_events(
        self,
        issuer_symbols: Iterable[str],
        start_date: date,
        end_date: date,
    ) -> tuple[ReportEvent, ...]:
        """Vozvrashchaet provider event-log bez chteniya cen ili targetov."""
        ...

    def fetch_artifact(self, event: ReportEvent) -> bytes:
        """Vozvrashchaet original'nye bytes dlya proverki hash i atomic storage."""
        ...


def source_access_policy(source_kind: FilingSourceKind) -> SourceAccessPolicy:
    """Vozvrashchaet zafiksirovannuyu konservativnuyu politiku istochnika."""
    return SOURCE_ACCESS_POLICIES[source_kind]


def require_bulk_authorization(source_kind: FilingSourceKind, contract_confirmed: bool) -> None:
    """Fail-closed zapreshchaet bulk do yavnogo podtverzhdeniya dogovora."""
    policy = source_access_policy(source_kind)
    if not policy.automated_interface:
        raise PermissionError("Istochnik ne imeet odobrennogo avtomatizirovannogo interfeisa")
    if not contract_confirmed or not policy.bulk_research_approved:
        raise PermissionError(
            "Bulk raskrytii ne odobren: nuzhny dogovor, credentialy i audit uslovii"
        )
