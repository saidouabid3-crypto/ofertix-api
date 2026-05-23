from importers.pccomponentes import import_pccomponentes
from importers.aliexpress import import_aliexpress
from importers.carrefour import import_carrefour
from importers.bosh import import_bosh
from importers.mediamarkt import import_mediamarkt
from importers.amazon import import_amazon


def run_all_importers():
    print("Starting importers...")

    import_pccomponentes()
    import_aliexpress()
    import_carrefour()
    import_bosh()
    import_mediamarkt()

    # دابا نخدمو غير Amazon الحقيقي
    import_amazon()

    print("All importers finished")


if __name__ == "__main__":
    run_all_importers()