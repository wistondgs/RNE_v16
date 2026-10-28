"""Integración simbiótica N0-N6 con el organismo vivo."""

from .census import ComponentClass, integration_census, validate_active_census
from .adapters import CanonicalOrganAdapter, canonical_adapter_registry
from .contracts import (
    CONSUMER_RECEIPT_SCHEMA_VERSION,
    SYMBIOSIS_TRACE_SCHEMA_VERSION,
    AuthorityEffect,
    ConsumerReceipt,
    ConsumerVerdictClass,
    OrganTrace,
    SymbiosisIdentity,
    SymbiosisTrace,
    validate_consumer_receipt,
)
from .coordinator import SymbioticNeuralCoordinator

__all__ = [
    "ComponentClass",
    "CanonicalOrganAdapter",
    "CONSUMER_RECEIPT_SCHEMA_VERSION",
    "ConsumerReceipt",
    "ConsumerVerdictClass",
    "OrganTrace",
    "AuthorityEffect",
    "SYMBIOSIS_TRACE_SCHEMA_VERSION",
    "SymbiosisIdentity",
    "SymbiosisTrace",
    "SymbioticNeuralCoordinator",
    "canonical_adapter_registry",
    "integration_census",
    "validate_active_census",
    "validate_consumer_receipt",
]
