from core.market_config import SUPPORTED_MARKETS

STORE_CONNECTORS = {
    'es': ['amazon_es', 'miravia_es', 'carrefour_es', 'mediamarkt_es', 'pccomponentes_es'],
    'ma': ['jumia_ma', 'avito_ma', 'marjane_ma', 'electroplanet_ma'],
    'dz': ['ouedkniss_dz', 'local_dz'],
    'fr': ['amazon_fr', 'cdiscount_fr', 'fnac_fr', 'carrefour_fr'],
    'pt': ['worten_pt', 'fnac_pt', 'amazon_es'],
    'it': ['amazon_it', 'mediaworld_it', 'unieuro_it'],
    'de': ['amazon_de', 'mediamarkt_de', 'saturn_de'],
    'uk': ['amazon_uk', 'argos_uk', 'currys_uk'],
    'us': ['amazon_us', 'walmart_us', 'bestbuy_us', 'target_us'],
    'ca': ['amazon_ca', 'walmart_ca', 'bestbuy_ca', 'canadian_tire_ca'],
    'eg': ['amazon_eg', 'jumia_eg', 'noon_eg', 'btech_eg'],
    'sa': ['amazon_sa', 'noon_sa', 'jarir_sa', 'extra_sa'],
    'ae': ['amazon_ae', 'noon_ae', 'sharafdg_ae', 'carrefour_ae'],
    'mx': ['amazon_mx', 'mercadolibre_mx', 'walmart_mx', 'coppel_mx'],
}

def registry():
    return {code: {'market': SUPPORTED_MARKETS[code], 'connectors': STORE_CONNECTORS.get(code, [])} for code in SUPPORTED_MARKETS}
