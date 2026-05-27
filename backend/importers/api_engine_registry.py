from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ApiConnectorDefinition:
    source: str
    country_code: str
    enabled_by_default: bool
    requires_api_key: bool
    schedule: str = 'every_12h'


CONNECTORS: List[ApiConnectorDefinition] = [
    ApiConnectorDefinition('amazon_es', 'es', False, True),
    ApiConnectorDefinition('aliexpress_global', 'global', False, True),
    ApiConnectorDefinition('jumia_ma', 'ma', False, True),
    ApiConnectorDefinition('amazon_fr', 'fr', False, True),
    ApiConnectorDefinition('amazon_eg', 'eg', False, True),
    ApiConnectorDefinition('carrefour_es', 'es', False, True),
    ApiConnectorDefinition('mediamarkt_es', 'es', False, True),
]


def connector_blueprint() -> list[dict]:
    return [connector.__dict__ for connector in CONNECTORS]
